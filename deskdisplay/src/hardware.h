#pragma once

#include "display.h"

// One board, one display. Application drawing uses LovyanGFX directly.
namespace hardware
{
LGFX& display();
bool beginDisplay(); // Backlight remains off until application draws its image.
void setBacklight(bool on);
}
