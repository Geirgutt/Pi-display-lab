#pragma once
#include <stdint.h>

namespace navigation_gesture
{
enum class Result : uint8_t { Cancel, Tap, Up, Down };

// One finger, evaluated on release. A drag cannot also activate a button.
class Tracker
{
public:
    void begin(int16_t x, int16_t y, uint32_t now)
    {
        startX = lastX = x;
        startY = lastY = y;
        startedAt = now;
        travel = 0;
    }

    void move(int16_t x, int16_t y)
    {
        lastX = x;
        lastY = y;
        const int32_t dx = absolute(int32_t(x) - startX);
        const int32_t dy = absolute(int32_t(y) - startY);
        if (dx > travel) travel = dx;
        if (dy > travel) travel = dy;
    }

    Result finish(uint32_t now) const
    {
        if (travel <= 18) return Result::Tap;
        if (uint32_t(now - startedAt) > 1500) return Result::Cancel;
        const int32_t dx = absolute(int32_t(lastX) - startX);
        const int32_t dy = int32_t(lastY) - startY;
        if (dx > 45 || absolute(dy) < 75) return Result::Cancel;
        return dy < 0 ? Result::Up : Result::Down;
    }

    int16_t originY() const { return startY; }
    int16_t x() const { return lastX; }
    int16_t y() const { return lastY; }

private:
    static int32_t absolute(int32_t value) { return value < 0 ? -value : value; }
    int16_t startX = 0, startY = 0, lastX = 0, lastY = 0;
    int32_t travel = 0;
    uint32_t startedAt = 0;
};
}
