#pragma once
#include <stdint.h>

namespace alarm_schedule
{
// Editing the schedule or explicitly enabling it starts a new alarm.
// Visual style changes must not retrigger an already-fired daily alarm.
inline bool shouldRearm(bool wasEnabled, uint8_t oldHour, uint8_t oldMinute,
                        bool oldRepeats, bool enabled, uint8_t hour,
                        uint8_t minute, bool repeats)
{
    return (!wasEnabled && enabled) || oldHour != hour || oldMinute != minute
        || oldRepeats != repeats;
}
}
