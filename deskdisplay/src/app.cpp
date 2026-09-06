#include "app.h"
#include "app_state.h"
#include "console.h"
#include "diagnostics.h"
#include "hardware.h"
#include "network.h"
#include "touch.h"
#include "ui.h"
#include "ble_test.h"
#include "secure_transport.h"
#include <Arduino.h>

namespace
{
app_state::Model model;
uint32_t nextTelemetry = 0;
bool lastDown = false;
uint32_t pressedAt = 0;

void refreshState()
{
    diagnostics::snapshot(model.diagnostics);
    network::Info wifi;
    network::info(wifi);
    model.wifiActive = wifi.active;
    model.wifiConnected = wifi.connected;
    model.wifiStatus = wifi.status;
    model.wifiRssi = wifi.rssi;
    strncpy(model.ip, wifi.ip, sizeof(model.ip));
    model.ip[sizeof(model.ip) - 1] = 0;
}

uint8_t hit(int16_t x, int16_t y)
{
    if (model.page == app_state::Page::Dashboard)
    {
        if (y >= 325 && y < 379) return x < 240 ? 1 : 2;
        if (y >= 397 && y < 451) return x < 240 ? 3 : 4;
    }
    else if (y >= 380 && y < 434 && x >= 145 && x < 335) return model.page == app_state::Page::System ? 5 : 6;
    return 0;
}

void action(uint8_t button)
{
    switch (button)
    {
    case 1:
#if DESKDISPLAY_WIFI
        if (model.wifiActive) network::stop();
        else network::startStored();
#endif
        refreshState();
        ui::telemetry(model);
        break;
    case 2: model.page = app_state::Page::System; model.pressedButton = 0; ui::page(model); break;
    case 3: model.backlightOn = !model.backlightOn; hardware::setBacklight(model.backlightOn); break;
    case 4: model.page = app_state::Page::TouchTest; model.pressedButton = 0; ui::page(model); break;
    case 5:
    case 6: model.page = app_state::Page::Dashboard; model.pressedButton = 0; ui::page(model); break;
    default: break;
    }
}

void processTouch()
{
    touch::Point point;
    const bool down = touch::read(point);
    model.touchDown = down;
    if (down)
    {
        model.touchX = point.x;
        model.touchY = point.y;
        if (!lastDown)
        {
            model.pressedButton = hit(point.x, point.y);
            pressedAt = millis();
            if (model.pressedButton) ui::pressed(model);
        }
        else if (model.page == app_state::Page::TouchTest)
        {
            ui::touch(model);
        }
    }
    else if (lastDown)
    {
        const uint8_t button = model.pressedButton;
        model.pressedButton = 0;
        if (button)
        {
            // The pressed visual is held until release; actions are click-on-up.
            ui::pressed(model);
            action(button);
        }
        else if (model.page == app_state::Page::TouchTest) ui::touch(model);
    }
    lastDown = down;
    (void)pressedAt;
}
}

bool app::begin()
{
    Serial.println("=== DeskDisplay ===");
    console::help();
    diagnostics::print(Serial);
    Serial.println("Initializing display...");
    if (!hardware::beginDisplay())
    {
        Serial.println("Display initialization failed.");
        return false;
    }
    auto& display = hardware::display();
    display.fillScreen(TFT_BLACK);
    hardware::setBacklight(true);
    Serial.println("Display initialized.");
    Serial.println(touch::begin() ? "Touch initialized (raw coordinates)." : "Touch initialization failed; display remains available.");
    secure_transport::begin();
    refreshState();
    ui::begin(model);
    nextTelemetry = millis() + 1000;
    diagnostics::print(Serial);
    return true;
}

void app::service()
{
    processTouch();
    console::service();
#if DESKDISPLAY_BLE
    ble_test::service();
#endif
#if DESKDISPLAY_WIFI
    network::service();
#endif
#if DESKDISPLAY_SECURE && DESKDISPLAY_WIFI
    secure_transport::service();
#endif
    const uint32_t now = millis();
    if (static_cast<int32_t>(now - nextTelemetry) >= 0)
    {
        nextTelemetry = now + 1000;
        refreshState();
        if (model.page == app_state::Page::Dashboard || model.page == app_state::Page::System) ui::telemetry(model);
    }
    delay(20);
}
