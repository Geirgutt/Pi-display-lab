#include <Arduino.h>
#include <Preferences.h>
#include "hardware.h"

namespace
{
LGFX displayInstance;
constexpr uint8_t backlightPin = 38; // Preserved from baseline main.cpp.
// Keep the Arduino core's previously working 1 kHz PWM. Very low frequencies
// can fail LEDC timer setup at 8-bit resolution on the ESP32-S3's 40 MHz clock.
constexpr uint32_t backlightFrequency = 1000;
bool displayReady = false;
uint8_t currentBrightness = 100;
bool currentNightMode = false;
constexpr char preferenceNamespace[] = "dd-ui";
constexpr char brightnessKey[] = "brightness";
constexpr char nightModeKey[] = "night";

bool supportedBrightness(uint8_t value)
{
    return value >= hardware::minimumBrightness && value <= hardware::maximumBrightness;
}

uint8_t clampBrightness(uint8_t value)
{
    if (value < hardware::minimumBrightness) return hardware::minimumBrightness;
    if (value > hardware::maximumBrightness) return hardware::maximumBrightness;
    return value;
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
        currentNightMode = preferences.getBool(nightModeKey, false);
        preferences.end();
    }
    pinMode(backlightPin, OUTPUT);
    digitalWrite(backlightPin, LOW);
    displayReady = displayInstance.init();
    analogWriteFrequency(backlightFrequency);
    setBrightness(currentBrightness);
    return displayReady;
}

void setBrightness(uint8_t percent)
{
    const uint8_t next = clampBrightness(percent);
    const bool changed = next != currentBrightness;
    currentBrightness = next;
    applyBrightness(currentBrightness);
    if (changed) saveBrightness();
}

void previewBrightness(uint8_t percent)
{
    currentBrightness = clampBrightness(percent);
    applyBrightness(currentBrightness);
}

void saveBrightness()
{
    if (supportedBrightness(currentBrightness))
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

bool nightMode() { return currentNightMode; }

bool toggleNightMode()
{
    currentNightMode = !currentNightMode;
    Preferences preferences;
    if (preferences.begin(preferenceNamespace, false))
    {
        preferences.putBool(nightModeKey, currentNightMode);
        preferences.end();
    }
    return currentNightMode;
}

void setBacklight(bool on)
{
    applyBrightness(on ? currentBrightness : 0);
}
}
