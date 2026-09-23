#pragma once

#include "display.h"

// One board, one display. Application drawing uses LovyanGFX directly.
namespace hardware
{
constexpr uint8_t minimumBrightness = 25;
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
void setBacklight(bool on);
}
