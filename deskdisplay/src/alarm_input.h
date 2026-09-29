#pragma once
#include <stdint.h>

namespace alarm_input
{
struct Editor
{
    uint8_t value = 0, length = 0, maximum = 59;
    bool error = false;

    void begin(uint8_t limit) { value = length = 0; maximum = limit; error = false; }
    bool digit(uint8_t number)
    {
        const uint16_t next = uint16_t(value) * 10 + number;
        if (number > 9 || length >= 2 || next > maximum)
        {
            error = true;
            return false;
        }
        value = static_cast<uint8_t>(next);
        ++length;
        error = false;
        return true;
    }
    void erase() { if (length) { value /= 10; --length; } error = false; }
    void clear() { value = length = 0; error = false; }
    bool valid() const { return length != 0 && value <= maximum && !error; }
};
}
