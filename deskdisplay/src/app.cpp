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
#include <time.h>

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
    model.brightnessPercent = hardware::brightness();
    const time_t now = time(nullptr);
    struct tm localTime = {};
    model.timeValid = now >= 1700000000 && localtime_r(&now, &localTime) != nullptr;
    if (model.timeValid)
    {
        strftime(model.clockText, sizeof(model.clockText), "%H:%M", &localTime);
        strftime(model.dateText, sizeof(model.dateText), "%d.%m.%Y", &localTime);
    }
    else
    {
        strncpy(model.clockText, "--:--", sizeof(model.clockText));
        strncpy(model.dateText, "Venter pa tid", sizeof(model.dateText));
    }
    strncpy(model.ip, wifi.ip, sizeof(model.ip));
    model.ip[sizeof(model.ip) - 1] = 0;
    const secure_transport::Counters& secureStats = secure_transport::counters();
    if (secureStats.accepted != model.nodeAccepted)
    {
        model.nodeTelemetry = secure_transport::lastTelemetry();
        model.clusterTelemetry = secure_transport::lastClusterTelemetry();
        model.trainingTelemetry = secure_transport::lastTrainingTelemetry();
        model.calendarTelemetry = secure_transport::lastCalendarTelemetry();
        model.nodeAccepted = secureStats.accepted;
    }
    model.nodeLastUpdate = secure_transport::lastTelemetryAt();
    model.nodeOnline = model.nodeLastUpdate != 0
                    && uint32_t(millis() - model.nodeLastUpdate) < 5000
                    && model.nodeTelemetry.online;
}

uint8_t hit(int16_t x, int16_t y)
{
    if (model.page == app_state::Page::Home)
    {
        if (y >= 300 && y < 354) return x < 240 ? 1 : 2;
        if (y >= 374 && y < 428) return x < 240 ? 3 : 4;
    }
    else if (model.page == app_state::Page::System && y >= 390 && y < 444)
        return x < 240 ? 6 : 5;
    else if (model.page != app_state::Page::Home
             && y >= 400 && y < 454 && x >= 145 && x < 335)
        return 5;
    return 0;
}

void action(uint8_t button)
{
    switch (button)
    {
    case 1: model.page = app_state::Page::Cluster; model.pressedButton = 0; ui::page(model); break;
    case 2: model.page = app_state::Page::Training; model.pressedButton = 0; ui::page(model); break;
    case 3: model.page = app_state::Page::Calendar; model.pressedButton = 0; ui::page(model); break;
    case 4: model.page = app_state::Page::System; model.pressedButton = 0; ui::page(model); break;
    case 5: model.page = app_state::Page::Home; model.pressedButton = 0; ui::page(model); break;
    case 6:
        model.brightnessPercent = hardware::cycleBrightness();
        ui::brightness(model);
        break;
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
#if DESKDISPLAY_WIFI
    configTzTime("CET-1CEST,M3.5.0,M10.5.0/3", "pool.ntp.org", "time.nist.gov");
    Serial.println(network::startStored()
        ? "Wi-Fi autostart requested."
        : "Wi-Fi not started; no stored credentials.");
#endif
#if DESKDISPLAY_SECURE && DESKDISPLAY_WIFI
    Serial.println(secure_transport::start()
        ? "Secure transport autostart requested."
        : "Secure transport not started; configure key and peer first.");
#endif
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
        ui::telemetry(model);
    }
    delay(20);
}
