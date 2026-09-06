#pragma once

#include <Arduino.h>
#include "secure_protocol.h"

namespace secure_transport
{
struct Counters
{
    uint32_t accepted = 0;
    uint32_t authFailures = 0;
    uint32_t replayDrops = 0;
    uint32_t malformed = 0;
    uint32_t unauthorized = 0;
    uint32_t reconnects = 0;
};

void begin();
void service();
bool start();
void stop();
bool setKeyHex(const char* hex);
bool setPeer(const char* address, uint16_t port);
bool enabled();
bool connected();
void printStatus(Print& out);
const secure_protocol::Telemetry& lastTelemetry();
const Counters& counters();
}
