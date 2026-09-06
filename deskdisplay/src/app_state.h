#pragma once
#include <stdint.h>
#include "diagnostics.h"

namespace app_state
{
enum class Page : uint8_t { Dashboard, System, TouchTest };

struct Model
{
    Page page = Page::Dashboard;
    diagnostics::Snapshot diagnostics{};
    bool wifiActive = false;
    bool wifiConnected = false;
    uint8_t wifiStatus = 0;
    int32_t wifiRssi = 0;
    char ip[16] = "-";
    bool touchDown = false;
    int16_t touchX = -1;
    int16_t touchY = -1;
    uint8_t pressedButton = 0;
    bool backlightOn = true;
};
}
