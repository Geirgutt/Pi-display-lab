#include "secure_transport.h"
#include "network.h"

#ifndef DESKDISPLAY_SECURE
#define DESKDISPLAY_SECURE 0
#endif

#if DESKDISPLAY_SECURE && DESKDISPLAY_WIFI

#include <WiFiClientSecure.h>
#include <Preferences.h>
#include <IPAddress.h>
#include <esp_system.h>

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
uint64_t lastSequence = 0;
uint8_t frame[secure_protocol::maxFrameSize] = {};
size_t frameLength = 0;
secure_protocol::Telemetry latest;
secure_transport::Counters stats;

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

bool processFrame()
{
    if (frameLength < secure_protocol::frameSize) return true;
    if (frameLength > secure_protocol::frameSize)
    {
        ++stats.malformed;
        closeSession(true);
        return false;
    }
    if (frame[3] >= secure_protocol::controlTypeBase)
    {
        ++stats.unauthorized;
        closeSession(true);
        return false;
    }
    uint64_t sequence = 0;
    secure_protocol::Telemetry value;
    if (!secure_protocol::decodeTelemetry(frame, frameLength, sequence, value))
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
    latest = value;
    ++stats.accepted;
    Serial.printf("Secure telemetry seq=%llu host=%s cpu=%.1f%% temp=%.1fC ram=%.1f%% up=%us online=%u\n",
                  static_cast<unsigned long long>(sequence), latest.hostname,
                  latest.cpuTenths / 10.0f, latest.temperatureTenths / 10.0f,
                  latest.ramTenths / 10.0f, latest.uptimeSeconds, latest.online ? 1 : 0);
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
        if (frameLength == secure_protocol::frameSize && !processFrame()) return;
        const size_t room = secure_protocol::frameSize - frameLength;
        if (room == 0)
        {
            ++stats.malformed;
            closeSession(true);
            return;
        }
        const int amount = client.read(frame + frameLength, room);
        if (amount < 0)
        {
            ++stats.authFailures;
            closeSession(true);
            return;
        }
        if (amount == 0) break;
        frameLength += static_cast<size_t>(amount);
        lastRx = millis();
        if (!processFrame()) return;
    }
    if (frameLength == secure_protocol::frameSize && !processFrame()) return;
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
        ++stats.authFailures;
        nextConnect = millis() + reconnectMs;
        Serial.println("Secure TLS connection failed; retrying.");
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
const secure_transport::Counters& secure_transport::counters() { return stats; }

void secure_transport::printStatus(Print& out)
{
    out.printf("Secure: %s, key=%u peer=%u, peer=%s:%u, accepted=%lu auth-fail=%lu replay=%lu malformed=%lu unauthorized=%lu reconnects=%lu\n",
               connected() ? "connected" : (requested ? "waiting" : "off"),
               keyAvailable ? 1 : 0, peerAddress[0] ? 1 : 0,
               peerAddress[0] ? peerAddress : "-", peerPort,
               static_cast<unsigned long>(stats.accepted), static_cast<unsigned long>(stats.authFailures),
               static_cast<unsigned long>(stats.replayDrops), static_cast<unsigned long>(stats.malformed),
               static_cast<unsigned long>(stats.unauthorized),
               static_cast<unsigned long>(stats.reconnects));
    if (stats.accepted)
    {
        out.printf("Last telemetry: host=%s cpu=%.1f%% temp=%.1fC ram=%.1f%% up=%us online=%u\n",
                   latest.hostname, latest.cpuTenths / 10.0f, latest.temperatureTenths / 10.0f,
                   latest.ramTenths / 10.0f, latest.uptimeSeconds, latest.online ? 1 : 0);
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
const secure_transport::Counters& secure_transport::counters()
{
    static secure_transport::Counters value;
    return value;
}

#endif
