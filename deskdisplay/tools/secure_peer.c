/*
 * Minimal Linux/Raspberry Pi peer for the optional DeskDisplay secure build.
 * It is a TLS 1.2 PSK server. The PSK file must contain exactly 64 hex
 * characters and should be mode 0600. No credentials belong in the repository.
 *
 * Build:
 *   cc -O2 -Wall -Wextra -Isrc -o tools/secure_peer tools/secure_peer.c \
 *      -lssl -lcrypto
 */
#define _POSIX_C_SOURCE 200809L

#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <openssl/err.h>
#include <openssl/ssl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static volatile sig_atomic_t running = 1;
static unsigned char psk[32];
static int replay_once = 0;
static int malformed_once = 0;

static void stop_handler(int signal_number)
{
    (void)signal_number;
    running = 0;
}

static int hex_value(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int load_psk(const char* path)
{
    FILE* file = fopen(path, "r");
    if (!file) return 0;
    char text[96] = {0};
    size_t length = fread(text, 1, sizeof(text) - 1, file);
    fclose(file);
    size_t compact = 0;
    for (size_t i = 0; i < length; ++i)
        if (text[i] != ' ' && text[i] != '\t' && text[i] != '\r' && text[i] != '\n')
            text[compact++] = text[i];
    if (compact != 64) return 0;
    for (size_t i = 0; i < 32; ++i)
    {
        const int high = hex_value(text[i * 2]);
        const int low = hex_value(text[i * 2 + 1]);
        if (high < 0 || low < 0) return 0;
        psk[i] = (unsigned char)((high << 4) | low);
    }
    return 1;
}

static unsigned int psk_callback(SSL* ssl, const char* identity,
                                 unsigned char* output, unsigned int max_length)
{
    (void)ssl;
    if (!identity || strcmp(identity, "DeskDisplay-peer") != 0 || max_length < sizeof(psk)) return 0;
    memcpy(output, psk, sizeof(psk));
    return sizeof(psk);
}

static void put16(unsigned char* p, uint16_t value)
{
    p[0] = (unsigned char)value;
    p[1] = (unsigned char)(value >> 8);
}

static void put32(unsigned char* p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = (unsigned char)(value >> (i * 8));
}

static void put64(unsigned char* p, uint64_t value)
{
    for (unsigned i = 0; i < 8; ++i) p[i] = (unsigned char)(value >> (i * 8));
}

static int read_cpu(uint64_t* total, uint64_t* idle)
{
    FILE* file = fopen("/proc/stat", "r");
    if (!file) return 0;
    unsigned long long user = 0, nice = 0, system = 0, idle_value = 0;
    unsigned long long iowait = 0, irq = 0, softirq = 0, steal = 0;
    const int ok = fscanf(file, "cpu %llu %llu %llu %llu %llu %llu %llu %llu",
                          &user, &nice, &system, &idle_value, &iowait,
                          &irq, &softirq, &steal) >= 4;
    fclose(file);
    if (!ok) return 0;
    *idle = idle_value + iowait;
    *total = user + nice + system + idle_value + iowait + irq + softirq + steal;
    return 1;
}

static uint16_t read_ram_tenths(void)
{
    FILE* file = fopen("/proc/meminfo", "r");
    if (!file) return 0;
    unsigned long total = 0, available = 0;
    char name[32];
    unsigned long value;
    while (fscanf(file, "%31s %lu kB", name, &value) == 2)
    {
        if (!strcmp(name, "MemTotal:")) total = value;
        else if (!strcmp(name, "MemAvailable:")) available = value;
    }
    fclose(file);
    if (!total || available > total) return 0;
    return (uint16_t)(((total - available) * 1000u) / total);
}

static int read_millidegrees(const char* path, int16_t* result)
{
    FILE* file = fopen(path, "r");
    if (!file) return 0;
    long millidegrees = 0;
    const int ok = fscanf(file, "%ld", &millidegrees) == 1;
    fclose(file);
    if (!ok || millidegrees < -100000 || millidegrees > 200000) return 0;
    *result = (int16_t)(millidegrees / 100);
    return 1;
}

static int read_text(const char* path, char* result, size_t capacity)
{
    FILE* file = fopen(path, "r");
    if (!file) return 0;
    const int ok = fgets(result, (int)capacity, file) != NULL;
    fclose(file);
    if (!ok) return 0;
    result[strcspn(result, "\r\n")] = 0;
    return result[0] != 0;
}

static int is_cpu_thermal_type(const char* type)
{
    return !strcmp(type, "cpu-thermal") || !strcmp(type, "cpu_thermal")
        || !strcmp(type, "bcm2835_thermal") || !strcmp(type, "x86_pkg_temp")
        || !strcmp(type, "soc-thermal") || !strcmp(type, "soc_thermal");
}

static int is_cpu_hwmon(const char* name)
{
    return !strcmp(name, "coretemp") || !strcmp(name, "k10temp")
        || !strcmp(name, "zenpower") || !strcmp(name, "cpu_thermal")
        || !strcmp(name, "cpu-thermal") || !strcmp(name, "bcm2835_thermal");
}

static int16_t read_temperature_tenths(void)
{
    DIR* thermal = opendir("/sys/class/thermal");
    if (thermal)
    {
        struct dirent* entry = NULL;
        while ((entry = readdir(thermal)) != NULL)
        {
            if (strncmp(entry->d_name, "thermal_zone", 12) != 0) continue;
            char typePath[512], tempPath[512], type[64];
            snprintf(typePath, sizeof(typePath), "/sys/class/thermal/%s/type", entry->d_name);
            if (!read_text(typePath, type, sizeof(type)) || !is_cpu_thermal_type(type)) continue;
            snprintf(tempPath, sizeof(tempPath), "/sys/class/thermal/%s/temp", entry->d_name);
            int16_t value = 0;
            if (read_millidegrees(tempPath, &value)) { closedir(thermal); return value; }
        }
        closedir(thermal);
    }

    DIR* hwmon = opendir("/sys/class/hwmon");
    if (hwmon)
    {
        struct dirent* entry = NULL;
        while ((entry = readdir(hwmon)) != NULL)
        {
            if (strncmp(entry->d_name, "hwmon", 5) != 0) continue;
            char namePath[512], name[64];
            snprintf(namePath, sizeof(namePath), "/sys/class/hwmon/%s/name", entry->d_name);
            if (!read_text(namePath, name, sizeof(name)) || !is_cpu_hwmon(name)) continue;
            for (unsigned sensor = 1; sensor <= 16; ++sensor)
            {
                char tempPath[512];
                snprintf(tempPath, sizeof(tempPath), "/sys/class/hwmon/%s/temp%u_input", entry->d_name, sensor);
                int16_t value = 0;
                if (read_millidegrees(tempPath, &value)) { closedir(hwmon); return value; }
            }
        }
        closedir(hwmon);
    }
    return INT16_MIN;
}

static int send_all(SSL* ssl, const unsigned char* data, size_t length)
{
    size_t sent = 0;
    while (sent < length)
    {
        const int result = SSL_write(ssl, data + sent, (int)(length - sent));
        if (result <= 0) return 0;
        sent += (size_t)result;
    }
    return 1;
}

static size_t make_frame(unsigned char* frame, uint64_t sequence, int invalid)
{
    static char hostname[33] = {0};
    static int hostname_ready = 0;
    if (!hostname_ready)
    {
        if (gethostname(hostname, sizeof(hostname) - 1) != 0) strcpy(hostname, "linux-peer");
        hostname[sizeof(hostname) - 1] = 0;
        hostname_ready = 1;
    }
    uint64_t total = 0, idle = 0;
    static uint64_t previous_total = 0, previous_idle = 0;
    uint16_t cpu = 0;
    if (read_cpu(&total, &idle) && previous_total && total > previous_total)
    {
        const uint64_t delta_total = total - previous_total;
        const uint64_t delta_idle = idle >= previous_idle ? idle - previous_idle : 0;
        cpu = (uint16_t)(((delta_total > delta_idle ? delta_total - delta_idle : 0) * 1000u) / delta_total);
    }
    previous_total = total;
    previous_idle = idle;
    const size_t name_length = strlen(hostname) > 32 ? 32 : strlen(hostname);
    frame[0] = invalid ? 'X' : 'D';
    frame[1] = 'S';
    frame[2] = 1;
    frame[3] = 1;
    put16(frame + 4, 44);
    put64(frame + 6, sequence);
    unsigned char* payload = frame + 14;
    payload[0] = (unsigned char)name_length;
    memset(payload + 1, 0, 32);
    memcpy(payload + 1, hostname, name_length);
    put16(payload + 33, cpu);
    put16(payload + 35, (uint16_t)read_temperature_tenths());
    put16(payload + 37, read_ram_tenths());
    struct {
        double uptime;
    } up = {0};
    FILE* uptime = fopen("/proc/uptime", "r");
    if (uptime) { fscanf(uptime, "%lf", &up.uptime); fclose(uptime); }
    put32(payload + 39, (uint32_t)(up.uptime < 0 ? 0 : up.uptime));
    payload[43] = 1;
    return 58;
}

static int make_listener(const char* address, uint16_t port)
{
    const int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in endpoint = {0};
    endpoint.sin_family = AF_INET;
    endpoint.sin_port = htons(port);
    if (inet_pton(AF_INET, address, &endpoint.sin_addr) != 1 ||
        bind(fd, (struct sockaddr*)&endpoint, sizeof(endpoint)) != 0 || listen(fd, 1) != 0)
    {
        close(fd);
        return -1;
    }
    return fd;
}

int main(int argc, char** argv)
{
    const char* listen_address = "0.0.0.0";
    const char* psk_path = NULL;
    uint16_t port = 4567;
    for (int i = 1; i < argc; ++i)
    {
        if (!strcmp(argv[i], "--listen") && i + 1 < argc) listen_address = argv[++i];
        else if (!strcmp(argv[i], "--port") && i + 1 < argc) port = (uint16_t)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--psk-file") && i + 1 < argc) psk_path = argv[++i];
        else if (!strcmp(argv[i], "--replay-once")) replay_once = 1;
        else if (!strcmp(argv[i], "--malformed-once")) malformed_once = 1;
        else { fprintf(stderr, "usage: %s --psk-file FILE [--listen IPv4] [--port N] [--replay-once] [--malformed-once]\n", argv[0]); return 2; }
    }
    if (!psk_path || !load_psk(psk_path)) { fprintf(stderr, "PSK file must contain 64 hexadecimal characters.\n"); return 2; }
    signal(SIGINT, stop_handler);
    signal(SIGTERM, stop_handler);
    SSL_library_init();
    SSL_load_error_strings();
    OpenSSL_add_ssl_algorithms();
    SSL_CTX* context = SSL_CTX_new(TLS_server_method());
    if (!context || SSL_CTX_set_min_proto_version(context, TLS1_2_VERSION) != 1 ||
        SSL_CTX_set_max_proto_version(context, TLS1_2_VERSION) != 1 ||
        SSL_CTX_set_cipher_list(context, "ECDHE-PSK-AES128-CBC-SHA256") != 1)
    { ERR_print_errors_fp(stderr); return 1; }
    SSL_CTX_set_psk_server_callback(context, psk_callback);
    const int listener = make_listener(listen_address, port);
    if (listener < 0) { perror("listen"); SSL_CTX_free(context); return 1; }
    printf("DeskDisplay secure peer listening on %s:%u\n", listen_address, port);
    while (running)
    {
        const int socket_fd = accept(listener, NULL, NULL);
        if (socket_fd < 0) { if (errno == EINTR) continue; perror("accept"); break; }
        SSL* ssl = SSL_new(context);
        SSL_set_fd(ssl, socket_fd);
        if (SSL_accept(ssl) != 1)
        {
            fprintf(stderr, "TLS authentication/handshake failed.\n");
            ERR_print_errors_fp(stderr);
            SSL_free(ssl); close(socket_fd); continue;
        }
        printf("TLS session established: %s\n", SSL_get_cipher(ssl));
        uint64_t sequence = 1;
        int replay_sent = 0, malformed_sent = 0;
        while (running)
        {
            unsigned char frame[58];
            const uint64_t wire_sequence = sequence;
            const size_t length = make_frame(frame, wire_sequence, malformed_sent == 0 && malformed_once);
            if (!send_all(ssl, frame, length)) break;
            if (malformed_once && !malformed_sent) malformed_sent = 1;
            else if (replay_once && !replay_sent) replay_sent = 1;
            else ++sequence;
            sleep(1);
        }
        SSL_shutdown(ssl);
        SSL_free(ssl); close(socket_fd);
        printf("TLS session closed; waiting for reconnect.\n");
    }
    close(listener);
    SSL_CTX_free(context);
    EVP_cleanup();
    return 0;
}
