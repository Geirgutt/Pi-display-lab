#pragma once

#include <stdint.h>
#include <stddef.h>
#include <string.h>

// The TLS session carries this deliberately small, fixed-size application
// frame. It is not a second cryptographic layer: TLS authenticates and encrypts
// the frame, while these fields provide versioning, message authorization and
// an application sequence check.
namespace secure_protocol
{
constexpr uint8_t magic0 = 'D';
constexpr uint8_t magic1 = 'S';
constexpr uint8_t version = 1;
constexpr uint8_t telemetryType = 1;
constexpr uint8_t controlTypeBase = 0x80;
constexpr size_t hostnameMax = 32;
constexpr size_t payloadSize = 1 + hostnameMax + 2 + 2 + 2 + 4 + 1;
constexpr size_t headerSize = 2 + 1 + 1 + 2 + 8;
constexpr size_t frameSize = headerSize + payloadSize;
constexpr size_t maxFrameSize = 128;
constexpr int16_t temperatureUnavailable = INT16_MIN;

struct Telemetry
{
    char hostname[hostnameMax + 1] = {};
    uint16_t cpuTenths = 0;
    int16_t temperatureTenths = 0;
    uint16_t ramTenths = 0;
    uint32_t uptimeSeconds = 0;
    bool online = false;
};

inline void put16(uint8_t* p, uint16_t value)
{
    p[0] = static_cast<uint8_t>(value);
    p[1] = static_cast<uint8_t>(value >> 8);
}

inline uint16_t get16(const uint8_t* p)
{
    return static_cast<uint16_t>(p[0]) | static_cast<uint16_t>(p[1]) << 8;
}

inline void put32(uint8_t* p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = static_cast<uint8_t>(value >> (i * 8));
}

inline uint32_t get32(const uint8_t* p)
{
    uint32_t value = 0;
    for (unsigned i = 0; i < 4; ++i) value |= static_cast<uint32_t>(p[i]) << (i * 8);
    return value;
}

inline void put64(uint8_t* p, uint64_t value)
{
    for (unsigned i = 0; i < 8; ++i) p[i] = static_cast<uint8_t>(value >> (i * 8));
}

inline uint64_t get64(const uint8_t* p)
{
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= static_cast<uint64_t>(p[i]) << (i * 8);
    return value;
}

inline size_t encodeTelemetry(uint8_t* frame, size_t capacity, uint64_t sequence, const Telemetry& value)
{
    if (!frame || capacity < frameSize) return 0;
    frame[0] = magic0;
    frame[1] = magic1;
    frame[2] = version;
    frame[3] = telemetryType;
    put16(frame + 4, payloadSize);
    put64(frame + 6, sequence);

    uint8_t* payload = frame + headerSize;
    const size_t hostnameLength = strnlen(value.hostname, hostnameMax);
    payload[0] = static_cast<uint8_t>(hostnameLength);
    memset(payload + 1, 0, hostnameMax);
    memcpy(payload + 1, value.hostname, hostnameLength);
    put16(payload + 1 + hostnameMax, value.cpuTenths);
    put16(payload + 1 + hostnameMax + 2, static_cast<uint16_t>(value.temperatureTenths));
    put16(payload + 1 + hostnameMax + 4, value.ramTenths);
    put32(payload + 1 + hostnameMax + 6, value.uptimeSeconds);
    payload[1 + hostnameMax + 10] = value.online ? 1 : 0;
    return frameSize;
}

inline bool decodeTelemetry(const uint8_t* frame, size_t length, uint64_t& sequence, Telemetry& value)
{
    if (!frame || length != frameSize || frame[0] != magic0 || frame[1] != magic1
        || frame[2] != version || frame[3] != telemetryType
        || get16(frame + 4) != payloadSize) return false;
    sequence = get64(frame + 6);
    const uint8_t* payload = frame + headerSize;
    const size_t hostnameLength = payload[0];
    if (hostnameLength > hostnameMax || payload[1 + hostnameMax + 10] > 1) return false;
    memset(&value, 0, sizeof(value));
    memcpy(value.hostname, payload + 1, hostnameLength);
    value.hostname[hostnameLength] = 0;
    value.cpuTenths = get16(payload + 1 + hostnameMax);
    value.temperatureTenths = static_cast<int16_t>(get16(payload + 1 + hostnameMax + 2));
    value.ramTenths = get16(payload + 1 + hostnameMax + 4);
    value.uptimeSeconds = get32(payload + 1 + hostnameMax + 6);
    value.online = payload[1 + hostnameMax + 10] != 0;
    return true;
}
}
