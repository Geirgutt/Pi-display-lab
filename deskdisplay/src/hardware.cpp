#include <Arduino.h>
#include <Preferences.h>
#include "hardware.h"

namespace
{
LGFX displayInstance;
constexpr uint8_t backlightPin = 38; // Preserved from baseline main.cpp.
// Keep the baseline 1 kHz PWM; higher test frequencies made this backlight
// cut out through much of its dimming range. Set before the first analogWrite().
constexpr uint32_t backlightFrequency = 1000;
bool displayReady = false;
uint8_t currentBrightness = 100;
bool currentNightMode = false;
bool currentAlarmEnabled = false;
uint8_t currentAlarmHour = 23;
uint8_t currentAlarmMinute = 0;
bool currentAlarmRepeats = true;
uint8_t currentAlarmMethod = 0;
uint32_t currentLastAlarmDate = 0;
constexpr char preferenceNamespace[] = "dd-ui";
constexpr char brightnessKey[] = "brightness";
constexpr char nightModeKey[] = "night";
constexpr char alarmEnabledKey[] = "alarmOn";
constexpr char alarmHourKey[] = "alarmHr";
constexpr char alarmMinuteKey[] = "alarmMin";
constexpr char alarmRepeatKey[] = "alarmRpt";
constexpr char alarmMethodKey[] = "alarmMode";
constexpr char lastAlarmDateKey[] = "alarmDate";

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
        currentAlarmEnabled = preferences.getBool(alarmEnabledKey, false);
        const uint8_t savedHour = preferences.getUChar(alarmHourKey, 23);
        const uint8_t savedMinute = preferences.getUChar(alarmMinuteKey, 0);
        currentAlarmHour = savedHour < 24 ? savedHour : 23;
        currentAlarmMinute = savedMinute < 60 ? savedMinute : 0;
        currentAlarmRepeats = preferences.getBool(alarmRepeatKey, true);
        const uint8_t savedMethod = preferences.getUChar(alarmMethodKey, 0);
        currentAlarmMethod = savedMethod <= 1 ? savedMethod : 0;
        currentLastAlarmDate = preferences.getUInt(lastAlarmDateKey, 0);
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

bool alarmEnabled() { return currentAlarmEnabled; }
uint8_t alarmHour() { return currentAlarmHour; }
uint8_t alarmMinute() { return currentAlarmMinute; }
bool alarmRepeats() { return currentAlarmRepeats; }
uint8_t alarmMethod() { return currentAlarmMethod; }

void setAlarm(bool enabled, uint8_t hour, uint8_t minute, bool repeats, uint8_t method)
{
    if (hour >= 24 || minute >= 60 || method > 1) return;
    currentAlarmEnabled = enabled;
    currentAlarmHour = hour;
    currentAlarmMinute = minute;
    currentAlarmRepeats = repeats;
    currentAlarmMethod = method;
    Preferences preferences;
    if (preferences.begin(preferenceNamespace, false))
    {
        preferences.putBool(alarmEnabledKey, enabled);
        preferences.putUChar(alarmHourKey, hour);
        preferences.putUChar(alarmMinuteKey, minute);
        preferences.putBool(alarmRepeatKey, repeats);
        preferences.putUChar(alarmMethodKey, method);
        preferences.end();
    }
}

uint32_t lastAlarmDate() { return currentLastAlarmDate; }

void markAlarmFired(uint32_t date, bool disableAfterFire)
{
    currentLastAlarmDate = date;
    if (disableAfterFire) currentAlarmEnabled = false;
    Preferences preferences;
    if (preferences.begin(preferenceNamespace, false))
    {
        preferences.putUInt(lastAlarmDateKey, date);
        if (disableAfterFire) preferences.putBool(alarmEnabledKey, false);
        preferences.end();
    }
}

void setBacklight(bool on)
{
    applyBrightness(on ? currentBrightness : 0);
}
}
