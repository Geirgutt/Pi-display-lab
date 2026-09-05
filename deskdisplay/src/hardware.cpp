#include <Arduino.h>
#include "hardware.h"

namespace
{
LGFX displayInstance;
constexpr uint8_t backlightPin = 38; // Preserved from baseline main.cpp.
bool displayReady = false;
}

namespace hardware
{
LGFX& display() { return displayInstance; }

bool beginDisplay()
{
    pinMode(backlightPin, OUTPUT);
    digitalWrite(backlightPin, LOW);
    displayReady = displayInstance.init();
    return displayReady;
}

void setBacklight(bool on)
{
    digitalWrite(backlightPin, on && displayReady ? HIGH : LOW);
}
}
