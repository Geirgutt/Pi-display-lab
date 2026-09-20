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
constexpr uint8_t clusterTelemetryType = 2;
constexpr uint8_t trainingTelemetryType = 3;
constexpr uint8_t calendarTelemetryType = 4;
constexpr uint8_t controlTypeBase = 0x80;
constexpr uint8_t otaOfferType = 0x80;
constexpr uint8_t otaChunkType = 0x81;
constexpr uint8_t otaCompleteType = 0x82;
constexpr uint8_t otaAckType = 0x90;
constexpr uint8_t otaReady = 1;
constexpr uint8_t otaChunkAccepted = 2;
constexpr uint8_t otaComplete = 3;
constexpr uint8_t otaFailed = 0x80;
constexpr size_t hostnameMax = 32;
constexpr size_t clusterNodeMax = 3;
constexpr size_t clusterNameMax = 16;
constexpr size_t trainingItemMax = 3;
constexpr size_t trainingTitleMax = 36;
constexpr size_t trainingTypeMax = 14;
constexpr size_t trainingDescriptionMax = 240;
constexpr size_t calendarEventMax = 3;
constexpr size_t calendarTitleMax = 40;
constexpr size_t calendarLocationMax = 24;
constexpr size_t payloadSize = 1 + hostnameMax + 2 + 2 + 2 + 4 + 1;
constexpr size_t headerSize = 2 + 1 + 1 + 2 + 8;
constexpr size_t frameSize = headerSize + payloadSize;
constexpr size_t clusterNodeSize = 1 + clusterNameMax + 2 + 2 + 2 + 4 + 1;
// page index + page count + total node count (uint16) + nodes on this page.
constexpr size_t clusterMetadataSize = 5;
constexpr size_t clusterPayloadSize = clusterMetadataSize + clusterNodeMax * clusterNodeSize;
constexpr size_t clusterFrameSize = headerSize + clusterPayloadSize;
constexpr size_t trainingWorkoutSize = 11 + trainingTitleMax + 1 + trainingTypeMax + 1
                                     + trainingDescriptionMax + 1 + 2 + 2 + 1;
constexpr size_t trainingActivitySize = 1 + 11 + trainingTypeMax + 1 + 2 + 4 + 2 + 2;
constexpr size_t trainingPayloadSize = 3 + trainingItemMax * trainingWorkoutSize + trainingActivitySize;
constexpr size_t trainingFrameSize = headerSize + trainingPayloadSize;
constexpr size_t calendarEventSize = 4 + 4 + 1 + calendarTitleMax + 1 + calendarLocationMax + 1;
constexpr size_t calendarPayloadSize = 3 + calendarEventMax * calendarEventSize;
constexpr size_t calendarFrameSize = headerSize + calendarPayloadSize;
constexpr size_t otaDigestSize = 32;
// Legacy firmware accepted 96-byte chunks in a 128-byte receive buffer. New
// firmware accepts 4 KiB chunks while remaining able to receive legacy chunks.
constexpr size_t otaChunkDataSize = 4096;
constexpr size_t otaOfferPayloadSize = 4 + otaDigestSize;
constexpr size_t otaChunkHeaderSize = 4 + 2;
constexpr size_t otaOfferFrameSize = headerSize + otaOfferPayloadSize;
constexpr size_t otaChunkFrameSize = headerSize + otaChunkHeaderSize + otaChunkDataSize;
constexpr size_t otaCompleteFrameSize = headerSize;
constexpr size_t otaAckPayloadSize = 1 + 4;
constexpr size_t otaAckFrameSize = headerSize + otaAckPayloadSize;
constexpr size_t maxFrameSize = otaChunkFrameSize > clusterFrameSize
                              ? otaChunkFrameSize : clusterFrameSize;
static_assert(clusterFrameSize <= maxFrameSize, "Cluster frame exceeds receive buffer");
static_assert(trainingFrameSize <= maxFrameSize, "Training frame exceeds receive buffer");
static_assert(calendarFrameSize <= maxFrameSize, "Calendar frame exceeds receive buffer");
static_assert(otaChunkFrameSize <= maxFrameSize, "OTA frame exceeds receive buffer");
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

struct ClusterNode
{
    char name[clusterNameMax + 1] = {};
    uint16_t cpuTenths = 0;
    int16_t temperatureTenths = temperatureUnavailable;
    uint16_t ramTenths = 0;
    uint32_t uptimeSeconds = 0;
    bool online = false;
};

struct ClusterTelemetry
{
    uint8_t count = 0;
    uint8_t pageIndex = 0;
    uint8_t pageCount = 1;
    uint16_t totalNodes = 0;
    ClusterNode nodes[clusterNodeMax]{};
};

enum class DataSource : uint8_t { None = 0, Garmin = 1, Calendar = 2, Local = 3, Mock = 4 };

struct TrainingWorkout
{
    char date[11] = {};
    char title[trainingTitleMax + 1] = {};
    char activityType[trainingTypeMax + 1] = {};
    char description[trainingDescriptionMax + 1] = {};
    uint16_t durationMinutes = 0;
    uint16_t distanceTenths = 0;
    bool today = false;
};

struct TrainingActivity
{
    bool present = false;
    char date[11] = {};
    char activityType[trainingTypeMax + 1] = {};
    uint16_t distanceTenths = 0;
    uint32_t durationSeconds = 0;
    uint16_t paceHundredths = 0;
    uint16_t averageHr = 0;
};

struct TrainingTelemetry
{
    bool available = false;
    DataSource source = DataSource::None;
    uint8_t count = 0;
    TrainingWorkout workouts[trainingItemMax]{};
    TrainingActivity lastActivity{};
};

struct CalendarEvent
{
    uint32_t startsAt = 0;
    uint32_t endsAt = 0;
    bool allDay = false;
    char title[calendarTitleMax + 1] = {};
    char location[calendarLocationMax + 1] = {};
};

struct CalendarTelemetry
{
    bool available = false;
    DataSource source = DataSource::None;
    uint8_t count = 0;
    CalendarEvent events[calendarEventMax]{};
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

inline size_t encodeClusterTelemetry(uint8_t* frame, size_t capacity, uint64_t sequence,
                                     const ClusterTelemetry& value)
{
    if (!frame || capacity < clusterFrameSize || value.count > clusterNodeMax) return 0;
    frame[0] = magic0;
    frame[1] = magic1;
    frame[2] = version;
    frame[3] = clusterTelemetryType;
    put16(frame + 4, clusterPayloadSize);
    put64(frame + 6, sequence);

    uint8_t* payload = frame + headerSize;
    payload[0] = value.pageIndex;
    payload[1] = value.pageCount;
    put16(payload + 2, value.totalNodes);
    payload[4] = value.count;
    memset(payload + clusterMetadataSize, 0, clusterNodeMax * clusterNodeSize);
    for (size_t index = 0; index < value.count; ++index)
    {
        const ClusterNode& node = value.nodes[index];
        uint8_t* encoded = payload + clusterMetadataSize + index * clusterNodeSize;
        const size_t nameLength = strnlen(node.name, clusterNameMax);
        encoded[0] = static_cast<uint8_t>(nameLength);
        memcpy(encoded + 1, node.name, nameLength);
        put16(encoded + 1 + clusterNameMax, node.cpuTenths);
        put16(encoded + 1 + clusterNameMax + 2, static_cast<uint16_t>(node.temperatureTenths));
        put16(encoded + 1 + clusterNameMax + 4, node.ramTenths);
        put32(encoded + 1 + clusterNameMax + 6, node.uptimeSeconds);
        encoded[1 + clusterNameMax + 10] = node.online ? 1 : 0;
    }
    return clusterFrameSize;
}

inline bool decodeClusterTelemetry(const uint8_t* frame, size_t length, uint64_t& sequence,
                                   ClusterTelemetry& value)
{
    if (!frame || length != clusterFrameSize || frame[0] != magic0 || frame[1] != magic1
        || frame[2] != version || frame[3] != clusterTelemetryType
        || get16(frame + 4) != clusterPayloadSize) return false;
    const uint8_t* payload = frame + headerSize;
    if (payload[0] >= payload[1] || payload[1] == 0 || payload[4] > clusterNodeMax)
        return false;
    const uint16_t totalNodes = get16(payload + 2);
    if (totalNodes == 0 && (payload[0] != 0 || payload[1] != 1 || payload[4] != 0))
        return false;
    sequence = get64(frame + 6);
    memset(&value, 0, sizeof(value));
    value.pageIndex = payload[0];
    value.pageCount = payload[1];
    value.totalNodes = totalNodes;
    value.count = payload[4];
    for (size_t index = 0; index < value.count; ++index)
    {
        const uint8_t* encoded = payload + clusterMetadataSize + index * clusterNodeSize;
        const size_t nameLength = encoded[0];
        if (nameLength > clusterNameMax || encoded[1 + clusterNameMax + 10] > 1) return false;
        ClusterNode& node = value.nodes[index];
        memcpy(node.name, encoded + 1, nameLength);
        node.name[nameLength] = 0;
        node.cpuTenths = get16(encoded + 1 + clusterNameMax);
        node.temperatureTenths = static_cast<int16_t>(get16(encoded + 1 + clusterNameMax + 2));
        node.ramTenths = get16(encoded + 1 + clusterNameMax + 4);
        node.uptimeSeconds = get32(encoded + 1 + clusterNameMax + 6);
        node.online = encoded[1 + clusterNameMax + 10] != 0;
    }
    return true;
}

inline bool decodeTrainingTelemetry(const uint8_t* frame, size_t length, uint64_t& sequence,
                                    TrainingTelemetry& value)
{
    if (!frame || length != trainingFrameSize || frame[0] != magic0 || frame[1] != magic1
        || frame[2] != version || frame[3] != trainingTelemetryType
        || get16(frame + 4) != trainingPayloadSize) return false;
    const uint8_t* payload = frame + headerSize;
    if (payload[0] > 1 || payload[2] > trainingItemMax) return false;
    sequence = get64(frame + 6);
    memset(&value, 0, sizeof(value));
    value.available = payload[0] != 0;
    value.source = static_cast<DataSource>(payload[1]);
    value.count = payload[2];
    const uint8_t* encoded = payload + 3;
    for (size_t index = 0; index < trainingItemMax; ++index, encoded += trainingWorkoutSize)
    {
        constexpr size_t typeOffset = 12 + trainingTitleMax;
        constexpr size_t descriptionOffset = typeOffset + trainingTypeMax + 1;
        constexpr size_t durationOffset = descriptionOffset + trainingDescriptionMax + 1;
        if (encoded[10] != 0 || encoded[11 + trainingTitleMax] != 0
            || encoded[typeOffset + trainingTypeMax] != 0
            || encoded[descriptionOffset + trainingDescriptionMax] != 0
            || encoded[trainingWorkoutSize - 1] > 1) return false;
        if (index >= value.count) continue;
        TrainingWorkout& item = value.workouts[index];
        memcpy(item.date, encoded, 11);
        memcpy(item.title, encoded + 11, trainingTitleMax + 1);
        memcpy(item.activityType, encoded + typeOffset, trainingTypeMax + 1);
        memcpy(item.description, encoded + descriptionOffset, trainingDescriptionMax + 1);
        item.durationMinutes = get16(encoded + durationOffset);
        item.distanceTenths = get16(encoded + durationOffset + 2);
        item.today = encoded[trainingWorkoutSize - 1] != 0;
    }
    const uint8_t* activity = payload + 3 + trainingItemMax * trainingWorkoutSize;
    if (activity[0] > 1 || activity[11] != 0 || activity[12 + trainingTypeMax] != 0)
        return false;
    value.lastActivity.present = activity[0] != 0;
    memcpy(value.lastActivity.date, activity + 1, 11);
    memcpy(value.lastActivity.activityType, activity + 12, trainingTypeMax + 1);
    value.lastActivity.distanceTenths = get16(activity + 13 + trainingTypeMax);
    value.lastActivity.durationSeconds = get32(activity + 15 + trainingTypeMax);
    value.lastActivity.paceHundredths = get16(activity + 19 + trainingTypeMax);
    value.lastActivity.averageHr = get16(activity + 21 + trainingTypeMax);
    return true;
}

inline bool decodeCalendarTelemetry(const uint8_t* frame, size_t length, uint64_t& sequence,
                                    CalendarTelemetry& value)
{
    if (!frame || length != calendarFrameSize || frame[0] != magic0 || frame[1] != magic1
        || frame[2] != version || frame[3] != calendarTelemetryType
        || get16(frame + 4) != calendarPayloadSize) return false;
    const uint8_t* payload = frame + headerSize;
    if (payload[0] > 1 || payload[2] > calendarEventMax) return false;
    sequence = get64(frame + 6);
    memset(&value, 0, sizeof(value));
    value.available = payload[0] != 0;
    value.source = static_cast<DataSource>(payload[1]);
    value.count = payload[2];
    const uint8_t* encoded = payload + 3;
    for (size_t index = 0; index < calendarEventMax; ++index, encoded += calendarEventSize)
    {
        if (encoded[8] > 1 || encoded[9 + calendarTitleMax] != 0
            || encoded[10 + calendarTitleMax + calendarLocationMax] != 0) return false;
        if (index >= value.count) continue;
        CalendarEvent& event = value.events[index];
        event.startsAt = get32(encoded);
        event.endsAt = get32(encoded + 4);
        event.allDay = encoded[8] != 0;
        memcpy(event.title, encoded + 9, calendarTitleMax + 1);
        memcpy(event.location, encoded + 10 + calendarTitleMax, calendarLocationMax + 1);
    }
    return true;
}
}
