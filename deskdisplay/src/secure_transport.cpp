#include "secure_transport.h"
#include "network.h"

#ifndef DESKDISPLAY_SECURE
#define DESKDISPLAY_SECURE 0
#endif

#if DESKDISPLAY_SECURE && DESKDISPLAY_WIFI

#include <WiFiClientSecure.h>
#include <Preferences.h>
#include <IPAddress.h>
#include <Update.h>
#include <esp_system.h>
#include <mbedtls/net_sockets.h>
#include <mbedtls/sha256.h>

namespace
{
constexpr char identity[] = "DeskDisplay-peer";
constexpr char preferenceNamespace[] = "dd-secure";
constexpr uint16_t defaultPort = 4567;
constexpr uint32_t reconnectMs = 5000;
constexpr uint32_t offlineMs = 5000;

WiFiClientSecure client;
Preferences preferences;
uint8_t psk[32] = {};
char pskHex[65] = {};
char peerAddress[16] = {};
uint16_t peerPort = defaultPort;
bool keyAvailable = false;
bool requested = false;
bool sessionActive = false;
uint32_t nextConnect = 0;
uint32_t lastRx = 0;
uint32_t lastValidTelemetry = 0;
uint64_t lastSequence = 0;
uint64_t txSequence = 1;
uint8_t frame[secure_protocol::maxFrameSize] = {};
size_t frameLength = 0;
secure_protocol::Telemetry latest;
secure_protocol::ClusterTelemetry latestCluster;
secure_transport::Counters stats;
bool otaActive = false;
uint32_t otaSize = 0;
uint32_t otaOffset = 0;
uint8_t otaDigest[secure_protocol::otaDigestSize] = {};
mbedtls_sha256_context otaHash;
bool otaHashInitialized = false;
uint32_t otaRebootAt = 0;

int hexValue(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool decodeKey(const char* hex, uint8_t* output)
{
    if (!hex || !output || strlen(hex) != 64) return false;
    for (size_t i = 0; i < 32; ++i)
    {
        const int high = hexValue(hex[i * 2]);
        const int low = hexValue(hex[i * 2 + 1]);
        if (high < 0 || low < 0) return false;
        output[i] = static_cast<uint8_t>((high << 4) | low);
    }
    return true;
}

void clearFrame()
{
    volatile uint8_t* p = frame;
    for (size_t i = 0; i < sizeof(frame); ++i) p[i] = 0;
    frameLength = 0;
}

void closeSession(bool countReconnect)
{
    if (sessionActive || client.connected()) client.stop();
    sessionActive = false;
    lastSequence = 0;
    clearFrame();
    if (countReconnect) ++stats.reconnects;
}

void resetOta()
{
    if (otaActive) Update.abort();
    otaActive = false;
    otaSize = 0;
    otaOffset = 0;
    memset(otaDigest, 0, sizeof(otaDigest));
    if (otaHashInitialized)
    {
        mbedtls_sha256_free(&otaHash);
        otaHashInitialized = false;
    }
}

bool sendOtaAck(uint8_t status, uint32_t offset)
{
    uint8_t response[secure_protocol::otaAckFrameSize] = {};
    response[0] = secure_protocol::magic0;
    response[1] = secure_protocol::magic1;
    response[2] = secure_protocol::version;
    response[3] = secure_protocol::otaAckType;
    secure_protocol::put16(response + 4, secure_protocol::otaAckPayloadSize);
    secure_protocol::put64(response + 6, txSequence++);
    response[secure_protocol::headerSize] = status;
    secure_protocol::put32(response + secure_protocol::headerSize + 1, offset);
    return client.write(response, sizeof(response)) == sizeof(response);
}

bool startOta(const uint8_t* payload, size_t length)
{
    if (!payload || length != secure_protocol::otaOfferPayloadSize) return false;
    resetOta();
    otaSize = secure_protocol::get32(payload);
    if (otaSize == 0) return false;
    memcpy(otaDigest, payload + 4, sizeof(otaDigest));
    if (!Update.begin(otaSize, U_FLASH)) return false;
    mbedtls_sha256_init(&otaHash);
    if (mbedtls_sha256_starts_ret(&otaHash, 0) != 0)
    {
        Update.abort();
        mbedtls_sha256_free(&otaHash);
        return false;
    }
    otaHashInitialized = true;
    otaActive = true;
    otaOffset = 0;
    return true;
}

bool finishOta()
{
    if (!otaActive || otaOffset != otaSize) return false;
    uint8_t actual[secure_protocol::otaDigestSize] = {};
    const bool hashOk = otaHashInitialized
                     && mbedtls_sha256_finish_ret(&otaHash, actual) == 0
                     && memcmp(actual, otaDigest, sizeof(actual)) == 0;
    if (otaHashInitialized)
    {
        mbedtls_sha256_free(&otaHash);
        otaHashInitialized = false;
    }
    if (!hashOk || !Update.end(false))
    {
        Update.abort();
        otaActive = false;
        return false;
    }
    otaActive = false;
    otaRebootAt = millis() + 1000;
    return true;
}

void loadConfiguration()
{
    preferences.begin(preferenceNamespace, true);
    const size_t keyLength = preferences.getBytesLength("psk");
    if (keyLength == sizeof(psk))
    {
        keyAvailable = preferences.getBytes("psk", psk, sizeof(psk)) == sizeof(psk);
        if (keyAvailable)
        {
            for (size_t i = 0; i < sizeof(psk); ++i)
            {
                snprintf(pskHex + i * 2, 3, "%02x", psk[i]);
            }
        }
    }
    const String savedAddress = preferences.getString("peer", "");
    if (savedAddress.length() > 0 && savedAddress.length() < sizeof(peerAddress))
        savedAddress.toCharArray(peerAddress, sizeof(peerAddress));
    peerPort = preferences.getUShort("port", defaultPort);
    preferences.end();
}

bool isTransportError(int errorCode)
{
    switch (errorCode)
    {
    case 0:
    case -1:
    case MBEDTLS_ERR_NET_SOCKET_FAILED:
    case MBEDTLS_ERR_NET_CONNECT_FAILED:
    case MBEDTLS_ERR_NET_RECV_FAILED:
    case MBEDTLS_ERR_NET_SEND_FAILED:
    case MBEDTLS_ERR_NET_CONN_RESET:
    case MBEDTLS_ERR_NET_UNKNOWN_HOST:
    case MBEDTLS_ERR_NET_POLL_FAILED:
    case MBEDTLS_ERR_NET_INVALID_CONTEXT:
    case MBEDTLS_ERR_NET_BAD_INPUT_DATA:
        return true;
    default:
        return false;
    }
}

void formatTemperature(int16_t temperatureTenths, char* output, size_t capacity)
{
    if (temperatureTenths == secure_protocol::temperatureUnavailable)
        snprintf(output, capacity, "N/A");
    else
        snprintf(output, capacity, "%.1fC", temperatureTenths / 10.0f);
}

size_t expectedFrameSize()
{
    if (frameLength < secure_protocol::headerSize) return secure_protocol::headerSize;
    const uint16_t payloadLength = secure_protocol::get16(frame + 4);
    switch (frame[3])
    {
    case secure_protocol::otaOfferType:
        return payloadLength == secure_protocol::otaOfferPayloadSize
             ? secure_protocol::otaOfferFrameSize : 0;
    case secure_protocol::otaChunkType:
        return payloadLength >= secure_protocol::otaChunkHeaderSize
            && payloadLength <= secure_protocol::otaChunkHeaderSize + secure_protocol::otaChunkDataSize
             ? secure_protocol::headerSize + payloadLength : 0;
    case secure_protocol::otaCompleteType:
        return payloadLength == 0 ? secure_protocol::otaCompleteFrameSize : 0;
    default:
        return frame[3] == secure_protocol::clusterTelemetryType
             ? secure_protocol::clusterFrameSize : secure_protocol::frameSize;
    }
}

bool processOtaFrame()
{
    const uint8_t type = frame[3];
    const uint8_t* payload = frame + secure_protocol::headerSize;
    const size_t payloadLength = secure_protocol::get16(frame + 4);
    if (type == secure_protocol::otaOfferType)
    {
        const bool ready = startOta(payload, payloadLength);
        if (!sendOtaAck(ready ? secure_protocol::otaReady : secure_protocol::otaFailed, 0)) return false;
        if (!ready) closeSession(true);
        return ready;
    }
    if (type == secure_protocol::otaChunkType)
    {
        const uint32_t offset = secure_protocol::get32(payload);
        const uint16_t length = secure_protocol::get16(payload + 4);
        if (!otaActive || length != payloadLength - secure_protocol::otaChunkHeaderSize
            || offset != otaOffset || length == 0
            || Update.write(const_cast<uint8_t*>(payload + secure_protocol::otaChunkHeaderSize), length) != length
            || mbedtls_sha256_update_ret(&otaHash, payload + secure_protocol::otaChunkHeaderSize, length) != 0)
        {
            sendOtaAck(secure_protocol::otaFailed, otaOffset);
            resetOta();
            closeSession(true);
            return false;
        }
        otaOffset += length;
        return sendOtaAck(secure_protocol::otaChunkAccepted, otaOffset);
    }
    if (type == secure_protocol::otaCompleteType)
    {
        const bool complete = finishOta();
        if (!sendOtaAck(complete ? secure_protocol::otaComplete : secure_protocol::otaFailed, otaOffset)) return false;
        if (!complete) closeSession(true);
        return complete;
    }
    return false;
}

bool processFrame()
{
    if (frameLength < secure_protocol::headerSize) return true;
    const size_t expected = expectedFrameSize();
    if (expected == 0)
    {
        ++stats.malformed;
        closeSession(true);
        return false;
    }
    if (frameLength < expected) return true;
    if (frameLength > expected)
    {
        ++stats.malformed;
        closeSession(true);
        return false;
    }
    if (frame[3] >= secure_protocol::controlTypeBase)
    {
        const bool handled = frame[3] == secure_protocol::otaOfferType
                          || frame[3] == secure_protocol::otaChunkType
                          || frame[3] == secure_protocol::otaCompleteType;
        if (!handled) ++stats.unauthorized;
        return handled && processOtaFrame();
    }
    uint64_t sequence = 0;
    secure_protocol::Telemetry value;
    secure_protocol::ClusterTelemetry clusterValue;
    const bool isCluster = frame[3] == secure_protocol::clusterTelemetryType;
    const bool decoded = isCluster
                       ? secure_protocol::decodeClusterTelemetry(frame, frameLength, sequence, clusterValue)
                       : secure_protocol::decodeTelemetry(frame, frameLength, sequence, value);
    if (!decoded)
    {
        ++stats.malformed;
        closeSession(true);
        return false;
    }
    if (sequence == 0 || sequence <= lastSequence)
    {
        ++stats.replayDrops;
        clearFrame();
        return true;
    }
    lastSequence = sequence;
    if (isCluster) latestCluster = clusterValue;
    else latest = value;
    lastValidTelemetry = millis();
    ++stats.accepted;
    if (isCluster)
    {
        Serial.printf("Secure cluster seq=%llu nodes=%u\n",
                      static_cast<unsigned long long>(sequence), latestCluster.count);
    }
    else
    {
        char temperature[16];
        formatTemperature(latest.temperatureTenths, temperature, sizeof(temperature));
        Serial.printf("Secure telemetry seq=%llu host=%s cpu=%.1f%% temp=%s ram=%.1f%% up=%us online=%u\n",
                      static_cast<unsigned long long>(sequence), latest.hostname,
                      latest.cpuTenths / 10.0f, temperature,
                      latest.ramTenths / 10.0f, latest.uptimeSeconds, latest.online ? 1 : 0);
    }
    clearFrame();
    return true;
}

void serviceSession()
{
    if (!client.connected())
    {
        closeSession(true);
        return;
    }
    while (client.available())
    {
        size_t expected = expectedFrameSize();
        if (expected == 0)
        {
            ++stats.malformed;
            closeSession(true);
            return;
        }
        if (frameLength >= expected)
        {
            if (!processFrame()) return;
            continue;
        }
        const size_t room = expected - frameLength;
        if (room == 0)
        {
            ++stats.malformed;
            closeSession(true);
            return;
        }
        const int amount = client.read(frame + frameLength, room);
        if (amount < 0)
        {
            ++stats.transportFailures;
            closeSession(true);
            return;
        }
        if (amount == 0) break;
        frameLength += static_cast<size_t>(amount);
        lastRx = millis();
        if (!processFrame()) return;
    }
    if (frameLength >= secure_protocol::headerSize && !processFrame()) return;
    if (uint32_t(millis() - lastRx) >= offlineMs)
    {
        if (frameLength != 0) ++stats.malformed;
        Serial.println("Secure peer timed out; closing session.");
        closeSession(true);
    }
}
}

void secure_transport::begin()
{
    loadConfiguration();
    client.setTimeout(50);
    Serial.printf("Secure transport: %s, peer=%s:%u\n",
                  keyAvailable && peerAddress[0] ? "configured" : "not configured",
                  peerAddress[0] ? peerAddress : "-", peerPort);
}

void secure_transport::service()
{
    if (otaRebootAt != 0 && static_cast<int32_t>(millis() - otaRebootAt) >= 0)
        ESP.restart();
    if (!requested || !keyAvailable || !peerAddress[0]) return;
    network::Info wifi;
    network::info(wifi);
    if (!wifi.connected)
    {
        if (sessionActive) closeSession(true);
        return;
    }
    if (sessionActive)
    {
        serviceSession();
        return;
    }
    if (static_cast<int32_t>(millis() - nextConnect) < 0) return;

    IPAddress address;
    if (!address.fromString(peerAddress))
    {
        ++stats.malformed;
        requested = false;
        return;
    }
    client.setPreSharedKey(identity, pskHex);
    Serial.printf("Secure TLS connection to %s:%u...\n", peerAddress, peerPort);
    if (!client.connect(address, peerPort))
    {
        char errorText[64] = {};
        const int errorCode = client.lastError(errorText, sizeof(errorText));
        // The wrapper returns -1 for socket setup/connect/timeout failures and
        // can return the mbedTLS network errors below. Other negative values
        // are TLS setup/handshake failures.
        if (isTransportError(errorCode)) ++stats.transportFailures;
        else ++stats.authFailures;
        nextConnect = millis() + reconnectMs;
        Serial.printf("Secure TLS connection failed (%d%s%s); retrying.\n",
                      errorCode, errorText[0] ? ": " : "", errorText);
        return;
    }
    sessionActive = true;
    lastRx = millis();
    lastSequence = 0;
    clearFrame();
    Serial.println("Secure TLS session established.");
}

bool secure_transport::start()
{
    if (!keyAvailable || !peerAddress[0]) return false;
    requested = true;
    nextConnect = 0;
    return true;
}

void secure_transport::stop()
{
    requested = false;
    closeSession(false);
}

bool secure_transport::setKeyHex(const char* hex)
{
    uint8_t decoded[sizeof(psk)] = {};
    if (!decodeKey(hex, decoded)) return false;
    Preferences store;
    if (!store.begin(preferenceNamespace, false)) return false;
    const size_t written = store.putBytes("psk", decoded, sizeof(decoded));
    store.end();
    if (written != sizeof(decoded)) return false;
    memcpy(psk, decoded, sizeof(psk));
    strncpy(pskHex, hex, sizeof(pskHex) - 1);
    pskHex[sizeof(pskHex) - 1] = 0;
    keyAvailable = true;
    closeSession(false);
    return true;
}

bool secure_transport::setPeer(const char* address, uint16_t port)
{
    IPAddress parsed;
    if (!address || !parsed.fromString(address) || port == 0) return false;
    Preferences store;
    if (!store.begin(preferenceNamespace, false)) return false;
    const bool ok = store.putString("peer", address) > 0 && store.putUShort("port", port) == sizeof(uint16_t);
    store.end();
    if (!ok) return false;
    strncpy(peerAddress, address, sizeof(peerAddress) - 1);
    peerAddress[sizeof(peerAddress) - 1] = 0;
    peerPort = port;
    closeSession(false);
    return true;
}

bool secure_transport::enabled() { return requested; }
bool secure_transport::connected() { return sessionActive && client.connected(); }
const secure_protocol::Telemetry& secure_transport::lastTelemetry() { return latest; }
const secure_protocol::ClusterTelemetry& secure_transport::lastClusterTelemetry() { return latestCluster; }
uint32_t secure_transport::lastTelemetryAt() { return lastValidTelemetry; }
const secure_transport::Counters& secure_transport::counters() { return stats; }

void secure_transport::printStatus(Print& out)
{
    out.printf("Secure: %s, key=%u peer=%u, peer=%s:%u, accepted=%lu auth-fail=%lu transport-fail=%lu replay=%lu malformed=%lu unauthorized=%lu reconnects=%lu\n",
               connected() ? "connected" : (requested ? "waiting" : "off"),
               keyAvailable ? 1 : 0, peerAddress[0] ? 1 : 0,
               peerAddress[0] ? peerAddress : "-", peerPort,
               static_cast<unsigned long>(stats.accepted), static_cast<unsigned long>(stats.authFailures),
               static_cast<unsigned long>(stats.transportFailures),
               static_cast<unsigned long>(stats.replayDrops), static_cast<unsigned long>(stats.malformed),
               static_cast<unsigned long>(stats.unauthorized),
               static_cast<unsigned long>(stats.reconnects));
    if (stats.accepted)
    {
        if (latestCluster.count > 0)
        {
            out.printf("Last cluster: nodes=%u", latestCluster.count);
            for (size_t index = 0; index < latestCluster.count; ++index)
                out.printf(" %s=%u", latestCluster.nodes[index].name,
                           latestCluster.nodes[index].online ? 1 : 0);
            out.println();
        }
        else
        {
            char temperature[16];
            formatTemperature(latest.temperatureTenths, temperature, sizeof(temperature));
            out.printf("Last telemetry: host=%s cpu=%.1f%% temp=%s ram=%.1f%% up=%us online=%u\n",
                       latest.hostname, latest.cpuTenths / 10.0f, temperature,
                       latest.ramTenths / 10.0f, latest.uptimeSeconds, latest.online ? 1 : 0);
        }
    }
}

#else

void secure_transport::begin() {}
void secure_transport::service() {}
bool secure_transport::start() { return false; }
void secure_transport::stop() {}
bool secure_transport::setKeyHex(const char*) { return false; }
bool secure_transport::setPeer(const char*, uint16_t) { return false; }
bool secure_transport::enabled() { return false; }
bool secure_transport::connected() { return false; }
void secure_transport::printStatus(Print& out) { out.println("Secure transport excluded from this build."); }
const secure_protocol::Telemetry& secure_transport::lastTelemetry()
{
    static secure_protocol::Telemetry value;
    return value;
}
const secure_protocol::ClusterTelemetry& secure_transport::lastClusterTelemetry()
{
    static secure_protocol::ClusterTelemetry value;
    return value;
}
uint32_t secure_transport::lastTelemetryAt() { return 0; }
const secure_transport::Counters& secure_transport::counters()
{
    static secure_transport::Counters value;
    return value;
}

#endif
