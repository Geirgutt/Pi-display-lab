#pragma once

#include "display.h"

// One board, one display. Application drawing uses LovyanGFX directly.
namespace hardware
{
constexpr uint8_t minimumBrightness = 20;
constexpr uint8_t maximumBrightness = 100;
LGFX& display();
bool beginDisplay(); // Backlight remains off until application draws its image.
void setBrightness(uint8_t percent);
void previewBrightness(uint8_t percent);
void saveBrightness();
uint8_t brightness();
uint8_t cycleBrightness();
bool nightMode();
bool toggleNightMode();
bool alarmEnabled();
uint8_t alarmHour();
uint8_t alarmMinute();
void setAlarm(bool enabled, uint8_t hour, uint8_t minute);
uint32_t lastAlarmDate();
void markAlarmFired(uint32_t date);
void setBacklight(bool on);
}
