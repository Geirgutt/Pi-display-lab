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
#include <openssl/evp.h>
#include <openssl/ssl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>

static volatile sig_atomic_t running = 1;
static unsigned char psk[32];
static int replay_once = 0;
static int malformed_once = 0;
static char state_host[16] = {0};
static char state_path[128] = {0};
static uint16_t state_port = 0;
static char ota_file_path[4096] = {0};

#define OTA_OFFER_TYPE 0x80
#define OTA_CHUNK_TYPE 0x81
#define OTA_COMPLETE_TYPE 0x82
#define OTA_ACK_TYPE 0x90
#define OTA_READY 1
#define OTA_CHUNK_ACCEPTED 2
#define OTA_COMPLETE 3
#define OTA_FAILED 0x80
#define OTA_CHUNK_SIZE 96

#define CLUSTER_NODE_MAX_PER_FRAME 3
#define CLUSTER_STATE_MAX_NODES 128
#define CLUSTER_NAME_MAX 16
#define CLUSTER_NODE_SIZE (1 + CLUSTER_NAME_MAX + 2 + 2 + 2 + 4 + 1)
#define CLUSTER_PAYLOAD_SIZE (4 + CLUSTER_NODE_MAX_PER_FRAME * CLUSTER_NODE_SIZE)
#define CLUSTER_FRAME_SIZE (14 + CLUSTER_PAYLOAD_SIZE)

struct cluster_node {
    char name[CLUSTER_NAME_MAX + 1];
    uint16_t cpu_tenths;
    int16_t temperature_tenths;
    uint16_t ram_tenths;
    uint32_t uptime_seconds;
    uint8_t online;
};

struct cluster_state {
    size_t count;
    struct cluster_node nodes[CLUSTER_STATE_MAX_NODES];
};

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

static int parse_unsigned(const char* text, unsigned long maximum, unsigned long* result)
{
    char* end = NULL;
    const unsigned long value = strtoul(text, &end, 10);
    if (!text[0] || !end || *end || value > maximum) return 0;
    *result = value;
    return 1;
}

static int parse_signed(const char* text, long minimum, long maximum, long* result)
{
    char* end = NULL;
    const long value = strtol(text, &end, 10);
    if (!text[0] || !end || *end || value < minimum || value > maximum) return 0;
    *result = value;
    return 1;
}

static int send_socket_all(int fd, const char* data, size_t length)
{
    size_t sent = 0;
    while (sent < length)
    {
        const ssize_t amount = send(fd, data + sent, length - sent, 0);
        if (amount <= 0) return 0;
        sent += (size_t)amount;
    }
    return 1;
}

static int fetch_controller_state(struct cluster_state* result)
{
    if (!state_host[0] || !state_path[0] || !result) return 0;
    const int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return 0;
    struct sockaddr_in endpoint = {0};
    endpoint.sin_family = AF_INET;
    endpoint.sin_port = htons(state_port);
    if (inet_pton(AF_INET, state_host, &endpoint.sin_addr) != 1 ||
        connect(fd, (struct sockaddr*)&endpoint, sizeof(endpoint)) != 0)
    {
        close(fd);
        return 0;
    }

    char request[256];
    const int request_length = snprintf(request, sizeof(request),
                                        "GET %s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n\r\n",
                                        state_path, state_host);
    if (request_length <= 0 || (size_t)request_length >= sizeof(request) ||
        !send_socket_all(fd, request, (size_t)request_length))
    {
        close(fd);
        return 0;
    }

    static char response[16384];
    memset(response, 0, sizeof(response));
    size_t length = 0;
    while (length + 1 < sizeof(response))
    {
        const ssize_t amount = recv(fd, response + length, sizeof(response) - length - 1, 0);
        if (amount < 0) { close(fd); return 0; }
        if (amount == 0) break;
        length += (size_t)amount;
    }
    close(fd);
    response[length] = 0;
    if (strncmp(response, "HTTP/1.0 200", 12) != 0 && strncmp(response, "HTTP/1.1 200", 12) != 0)
        return 0;
    char* body = strstr(response, "\r\n\r\n");
    if (!body) return 0;
    body += 4;
    if (strncmp(body, "DSCLUSTER/1\n", 12) != 0 && strncmp(body, "DSCLUSTER/1\r\n", 13) != 0)
        return 0;
    char* save = NULL;
    char* line = strtok_r(body, "\r\n", &save);
    if (!line || strcmp(line, "DSCLUSTER/1") != 0) return 0;
    memset(result, 0, sizeof(*result));
    while ((line = strtok_r(NULL, "\r\n", &save)) != NULL)
    {
        if (result->count >= CLUSTER_STATE_MAX_NODES) return 0;
        char* fields[7] = {0};
        size_t field_count = 0;
        char* field_save = NULL;
        char* field = strtok_r(line, "\t", &field_save);
        while (field && field_count < 7)
        {
            fields[field_count++] = field;
            field = strtok_r(NULL, "\t", &field_save);
        }
        if (field_count != 7 || strcmp(fields[0], "node") != 0 ||
            !fields[1][0] || strlen(fields[1]) > CLUSTER_NAME_MAX)
            return 0;
        unsigned long cpu = 0, ram = 0, uptime = 0, online = 0;
        long temperature = 0;
        if (!parse_unsigned(fields[2], 1000, &cpu) ||
            !parse_signed(fields[3], -32768, 32767, &temperature) ||
            !parse_unsigned(fields[4], 1000, &ram) ||
            !parse_unsigned(fields[5], 0xFFFFFFFFUL, &uptime) ||
            !parse_unsigned(fields[6], 1, &online))
            return 0;
        struct cluster_node* node = &result->nodes[result->count++];
        strncpy(node->name, fields[1], CLUSTER_NAME_MAX);
        node->name[CLUSTER_NAME_MAX] = 0;
        node->cpu_tenths = (uint16_t)cpu;
        node->temperature_tenths = (int16_t)temperature;
        node->ram_tenths = (uint16_t)ram;
        node->uptime_seconds = (uint32_t)uptime;
        node->online = (uint8_t)online;
    }
    return 1;
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

static int read_all(SSL* ssl, unsigned char* data, size_t length)
{
    size_t received = 0;
    while (received < length)
    {
        const int result = SSL_read(ssl, data + received, (int)(length - received));
        if (result <= 0) return 0;
        received += (size_t)result;
    }
    return 1;
}

static int read_frame(SSL* ssl, unsigned char* frame, size_t capacity, size_t* length)
{
    if (capacity < 14 || !read_all(ssl, frame, 14)) return 0;
    if (frame[0] != 'D' || frame[1] != 'S' || frame[2] != 1) return 0;
    const size_t payload_length = (size_t)frame[4] | ((size_t)frame[5] << 8);
    if (payload_length > capacity - 14) return 0;
    if (!read_all(ssl, frame + 14, payload_length)) return 0;
    *length = 14 + payload_length;
    return 1;
}

static int wait_ota_ack(SSL* ssl, unsigned char expected_status, uint32_t expected_offset)
{
    unsigned char frame[128] = {0};
    size_t length = 0;
    if (!read_frame(ssl, frame, sizeof(frame), &length) || frame[3] != OTA_ACK_TYPE
        || length != 19 || frame[14] != expected_status)
        return 0;
    const uint32_t offset = (uint32_t)frame[15] | ((uint32_t)frame[16] << 8)
                          | ((uint32_t)frame[17] << 16) | ((uint32_t)frame[18] << 24);
    return offset == expected_offset;
}

static int ota_digest(const char* path, uint32_t* size, unsigned char digest[32])
{
    FILE* file = fopen(path, "rb");
    if (!file) return 0;
    EVP_MD_CTX* context = EVP_MD_CTX_new();
    if (!context || EVP_DigestInit_ex(context, EVP_sha256(), NULL) != 1)
    {
        EVP_MD_CTX_free(context);
        fclose(file);
        return 0;
    }
    unsigned char buffer[4096];
    uint64_t total = 0;
    size_t amount;
    while ((amount = fread(buffer, 1, sizeof(buffer), file)) > 0)
    {
        total += amount;
        if (total > UINT32_MAX || EVP_DigestUpdate(context, buffer, amount) != 1)
        {
            EVP_MD_CTX_free(context);
            fclose(file);
            return 0;
        }
    }
    unsigned int digest_length = 0;
    const int ok = !ferror(file) && total > 0
                && EVP_DigestFinal_ex(context, digest, &digest_length) == 1
                && digest_length == 32;
    EVP_MD_CTX_free(context);
    fclose(file);
    if (!ok) return 0;
    *size = (uint32_t)total;
    return 1;
}

static int send_ota_header(SSL* ssl, unsigned char type, uint64_t sequence,
                           const unsigned char* payload, size_t payload_length)
{
    unsigned char frame[128] = {0};
    if (payload_length > sizeof(frame) - 14) return 0;
    frame[0] = 'D'; frame[1] = 'S'; frame[2] = 1; frame[3] = type;
    frame[4] = (unsigned char)payload_length;
    frame[5] = (unsigned char)(payload_length >> 8);
    for (unsigned index = 0; index < 8; ++index)
        frame[6 + index] = (unsigned char)(sequence >> (index * 8));
    if (payload_length) memcpy(frame + 14, payload, payload_length);
    return send_all(ssl, frame, 14 + payload_length);
}

static int perform_ota(SSL* ssl)
{
    uint32_t image_size = 0;
    unsigned char digest[32] = {0};
    if (!ota_digest(ota_file_path, &image_size, digest))
    {
        fprintf(stderr, "OTA image could not be read or hashed: %s\n", ota_file_path);
        return 0;
    }
    unsigned char offer[36] = {0};
    offer[0] = (unsigned char)image_size;
    offer[1] = (unsigned char)(image_size >> 8);
    offer[2] = (unsigned char)(image_size >> 16);
    offer[3] = (unsigned char)(image_size >> 24);
    memcpy(offer + 4, digest, sizeof(digest));
    if (!send_ota_header(ssl, OTA_OFFER_TYPE, 1, offer, sizeof(offer))
        || !wait_ota_ack(ssl, OTA_READY, 0))
        return 0;

    FILE* file = fopen(ota_file_path, "rb");
    if (!file) return 0;
    unsigned char buffer[OTA_CHUNK_SIZE];
    unsigned char chunk[OTA_CHUNK_SIZE + 6];
    uint32_t offset = 0;
    uint64_t sequence = 2;
    int ok = 1;
    while (offset < image_size)
    {
        const size_t amount = fread(buffer, 1, sizeof(buffer), file);
        if (amount == 0) { ok = 0; break; }
        chunk[0] = (unsigned char)offset;
        chunk[1] = (unsigned char)(offset >> 8);
        chunk[2] = (unsigned char)(offset >> 16);
        chunk[3] = (unsigned char)(offset >> 24);
        chunk[4] = (unsigned char)amount;
        chunk[5] = (unsigned char)(amount >> 8);
        memcpy(chunk + 6, buffer, amount);
        if (!send_ota_header(ssl, OTA_CHUNK_TYPE, sequence++, chunk, amount + 6)
            || !wait_ota_ack(ssl, OTA_CHUNK_ACCEPTED, offset + (uint32_t)amount))
        { ok = 0; break; }
        offset += (uint32_t)amount;
    }
    fclose(file);
    if (ok)
        ok = send_ota_header(ssl, OTA_COMPLETE_TYPE, sequence++, NULL, 0)
          && wait_ota_ack(ssl, OTA_COMPLETE, offset);
    if (ok)
    {
        unlink(ota_file_path);
        printf("OTA image delivered successfully (%u bytes).\n", image_size);
    }
    else fprintf(stderr, "OTA transfer failed; image retained for retry.\n");
    return ok;
}

static size_t make_local_frame(unsigned char* frame, uint64_t sequence, int invalid)
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

static size_t make_cluster_frame(unsigned char* frame, uint64_t sequence, int invalid)
{
    static struct cluster_state latest = {0};
    static int state_available = 0;
    static size_t page_index = 0;
    struct cluster_state current = {0};
    if (fetch_controller_state(&current))
    {
        latest = current;
        state_available = 1;
    }
    else if (state_available)
    {
        current = latest;
        for (size_t index = 0; index < current.count; ++index) current.nodes[index].online = 0;
        latest = current;
    }
    else current.count = 0;

    frame[0] = invalid ? 'X' : 'D';
    frame[1] = 'S';
    frame[2] = 1;
    frame[3] = 2;
    put16(frame + 4, CLUSTER_PAYLOAD_SIZE);
    put64(frame + 6, sequence);
    unsigned char* payload = frame + 14;
    const size_t page_count = current.count == 0
                            ? 1 : (current.count + CLUSTER_NODE_MAX_PER_FRAME - 1) / CLUSTER_NODE_MAX_PER_FRAME;
    if (page_index >= page_count) page_index = 0;
    const size_t first = page_index * CLUSTER_NODE_MAX_PER_FRAME;
    const size_t page_nodes = current.count > first
                            ? (current.count - first > CLUSTER_NODE_MAX_PER_FRAME
                               ? CLUSTER_NODE_MAX_PER_FRAME : current.count - first)
                            : 0;
    payload[0] = (unsigned char)page_index;
    payload[1] = (unsigned char)page_count;
    put16(payload + 2, (uint16_t)current.count);
    payload[4] = (unsigned char)page_nodes;
    memset(payload + 5, 0, CLUSTER_NODE_MAX_PER_FRAME * CLUSTER_NODE_SIZE);
    for (size_t index = 0; index < page_nodes; ++index)
    {
        const struct cluster_node* node = &current.nodes[first + index];
        unsigned char* encoded = payload + 5 + index * CLUSTER_NODE_SIZE;
        const size_t name_length = strlen(node->name) > CLUSTER_NAME_MAX ? CLUSTER_NAME_MAX : strlen(node->name);
        encoded[0] = (unsigned char)name_length;
        memcpy(encoded + 1, node->name, name_length);
        put16(encoded + 1 + CLUSTER_NAME_MAX, node->cpu_tenths);
        put16(encoded + 1 + CLUSTER_NAME_MAX + 2, (uint16_t)node->temperature_tenths);
        put16(encoded + 1 + CLUSTER_NAME_MAX + 4, node->ram_tenths);
        put32(encoded + 1 + CLUSTER_NAME_MAX + 6, node->uptime_seconds);
        encoded[1 + CLUSTER_NAME_MAX + 10] = node->online;
    }
    page_index = (page_index + 1) % page_count;
    return CLUSTER_FRAME_SIZE;
}

static size_t make_frame(unsigned char* frame, uint64_t sequence, int invalid)
{
    return state_path[0] ? make_cluster_frame(frame, sequence, invalid)
                         : make_local_frame(frame, sequence, invalid);
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
        else if (!strcmp(argv[i], "--state-host") && i + 1 < argc)
        {
            strncpy(state_host, argv[++i], sizeof(state_host) - 1);
            state_host[sizeof(state_host) - 1] = 0;
        }
        else if (!strcmp(argv[i], "--state-port") && i + 1 < argc) state_port = (uint16_t)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--state-path") && i + 1 < argc)
        {
            strncpy(state_path, argv[++i], sizeof(state_path) - 1);
            state_path[sizeof(state_path) - 1] = 0;
        }
        else if (!strcmp(argv[i], "--ota-file") && i + 1 < argc)
        {
            strncpy(ota_file_path, argv[++i], sizeof(ota_file_path) - 1);
            ota_file_path[sizeof(ota_file_path) - 1] = 0;
        }
        else if (!strcmp(argv[i], "--replay-once")) replay_once = 1;
        else if (!strcmp(argv[i], "--malformed-once")) malformed_once = 1;
        else { fprintf(stderr, "usage: %s --psk-file FILE [--listen IPv4] [--port N] [--state-host IPv4 --state-port N --state-path PATH] [--ota-file FILE] [--replay-once] [--malformed-once]\n", argv[0]); return 2; }
    }
    if (!psk_path || !load_psk(psk_path)) { fprintf(stderr, "PSK file must contain 64 hexadecimal characters.\n"); return 2; }
    if ((state_host[0] || state_port || state_path[0]) && (!state_host[0] || !state_port || !state_path[0]))
    {
        fprintf(stderr, "state-host, state-port and state-path must be supplied together.\n");
        return 2;
    }
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
        const struct timeval ota_timeout = {.tv_sec = 30, .tv_usec = 0};
        setsockopt(socket_fd, SOL_SOCKET, SO_RCVTIMEO, &ota_timeout, sizeof(ota_timeout));
        SSL* ssl = SSL_new(context);
        SSL_set_fd(ssl, socket_fd);
        if (SSL_accept(ssl) != 1)
        {
            fprintf(stderr, "TLS authentication/handshake failed.\n");
            ERR_print_errors_fp(stderr);
            SSL_free(ssl); close(socket_fd); continue;
        }
        printf("TLS session established: %s\n", SSL_get_cipher(ssl));
        if (ota_file_path[0] && access(ota_file_path, R_OK) == 0)
        {
            perform_ota(ssl);
            SSL_shutdown(ssl);
            SSL_free(ssl); close(socket_fd);
            printf("TLS session closed after OTA attempt; waiting for reconnect.\n");
            continue;
        }
        uint64_t sequence = 1;
        int replay_sent = 0, malformed_sent = 0;
        while (running)
        {
            unsigned char frame[128];
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
