#include <Arduino.h>
#include "hardware.h"

namespace
{
LGFX displayInstance;
constexpr uint8_t backlightPin = 38; // Preserved from baseline main.cpp.
bool displayReady = false;
uint8_t currentBrightness = 100;
}

namespace hardware
{
LGFX& display() { return displayInstance; }

bool beginDisplay()
{
    pinMode(backlightPin, OUTPUT);
    digitalWrite(backlightPin, LOW);
    displayReady = displayInstance.init();
    setBrightness(currentBrightness);
    return displayReady;
}

void setBrightness(uint8_t percent)
{
    currentBrightness = percent > 100 ? 100 : percent;
    if (!displayReady) return;
    const uint8_t duty = static_cast<uint8_t>((static_cast<uint16_t>(currentBrightness) * 255u) / 100u);
    analogWrite(backlightPin, duty);
}

uint8_t brightness() { return currentBrightness; }

uint8_t cycleBrightness()
{
    constexpr uint8_t levels[] = {100, 75, 50, 25, 10};
    for (size_t index = 0; index < sizeof(levels); ++index)
    {
        if (currentBrightness == levels[index])
        {
            const uint8_t next = levels[(index + 1) % (sizeof(levels) / sizeof(levels[0]))];
            setBrightness(next);
            return next;
        }
    }
    setBrightness(levels[0]);
    return levels[0];
}

void setBacklight(bool on)
{
    setBrightness(on ? 100 : 0);
}
}
