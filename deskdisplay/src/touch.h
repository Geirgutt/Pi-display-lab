#pragma once
#include <stdint.h>

namespace touch
{
struct Point { int16_t x; int16_t y; };
bool begin();
// One primary contact in controller coordinates. No heap allocation.
// Call at a bounded cadence; false also covers unavailable hardware.
bool read(Point& point);
}
