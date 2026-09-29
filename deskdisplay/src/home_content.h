#pragma once
#include "secure_protocol.h"

namespace home_content
{
inline int8_t nextWorkout(const secure_protocol::TrainingTelemetry& data, const char* today)
{
    if (!data.available || !today || strlen(today) != 10) return -1;
    int8_t selected = -1;
    for (uint8_t i = 0; i < data.count && i < secure_protocol::trainingItemMax; ++i)
    {
        const auto& workout = data.workouts[i];
        if (strlen(workout.date) != 10 || strcmp(workout.date, today) < 0) continue;
        if (selected < 0 || strcmp(workout.date, data.workouts[selected].date) < 0)
            selected = static_cast<int8_t>(i);
    }
    return selected;
}

inline int8_t nextEvent(const secure_protocol::CalendarTelemetry& data, uint32_t now)
{
    if (!data.available || !now) return -1;
    int8_t selected = -1;
    for (uint8_t i = 0; i < data.count && i < secure_protocol::calendarEventMax; ++i)
    {
        const auto& event = data.events[i];
        if (!event.startsAt || (event.startsAt <= now && event.endsAt <= now)) continue;
        if (selected < 0 || event.startsAt < data.events[selected].startsAt)
            selected = static_cast<int8_t>(i);
    }
    return selected;
}
}
