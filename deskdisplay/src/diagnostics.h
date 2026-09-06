#pragma once
#include <Arduino.h>

namespace diagnostics
{
struct Snapshot
{
    uint32_t internalFree;
    uint32_t internalMinimum;
    uint32_t internalLargest;
    uint32_t psramTotal;
    uint32_t psramFree;
    uint64_t uptimeMs;
};

void snapshot(Snapshot& value);
void print(Print& out);
}
