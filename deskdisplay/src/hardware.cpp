#include <Arduino.h>
#include <Preferences.h>
#include "hardware.h"

namespace
{
LGFX displayInstance;
constexpr uint8_t backlightPin = 38; // Preserved from baseline main.cpp.
bool displayReady = false;
uint8_t currentBrightness = 100;
constexpr char preferenceNamespace[] = "dd-ui";
constexpr char brightnessKey[] = "brightness";

bool supportedBrightness(uint8_t value)
{
    return value == 25 || value == 50 || value == 75 || value == 100;
}

void applyBrightness(uint8_t percent)
{
    if (!displayReady) return;
    const uint8_t duty = static_cast<uint8_t>((static_cast<uint16_t>(percent) * 255u) / 100u);
    analogWrite(backlightPin, duty);
}
}

namespace hardware
{
LGFX& display() { return displayInstance; }

bool beginDisplay()
{
    Preferences preferences;
    if (preferences.begin(preferenceNamespace, true))
    {
        const uint8_t saved = preferences.getUChar(brightnessKey, currentBrightness);
        if (supportedBrightness(saved)) currentBrightness = saved;
        preferences.end();
    }
    pinMode(backlightPin, OUTPUT);
    digitalWrite(backlightPin, LOW);
    displayReady = displayInstance.init();
    setBrightness(currentBrightness);
    return displayReady;
}

void setBrightness(uint8_t percent)
{
    const uint8_t next = percent > 100 ? 100 : percent;
    const bool changed = next != currentBrightness;
    currentBrightness = next;
    applyBrightness(currentBrightness);
    if (changed && supportedBrightness(currentBrightness))
    {
        Preferences preferences;
        if (preferences.begin(preferenceNamespace, false))
        {
            preferences.putUChar(brightnessKey, currentBrightness);
            preferences.end();
        }
    }
}

uint8_t brightness() { return currentBrightness; }

uint8_t cycleBrightness()
{
    constexpr uint8_t levels[] = {100, 75, 50, 25};
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
    applyBrightness(on ? currentBrightness : 0);
}
}
