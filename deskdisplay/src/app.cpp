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
#include "ui_layout.h"
#include <Arduino.h>
#include <time.h>

namespace
{
app_state::Model model;
uint32_t nextTelemetry = 0;
bool lastDown = false;
uint32_t pressedAt = 0;

int trainingIndexForDay(uint8_t dayOffset)
{
    if (!model.timeValid) return -1;
    const time_t now = time(nullptr);
    struct tm local = {};
    if (!localtime_r(&now, &local)) return -1;
    local.tm_mday += dayOffset;
    local.tm_hour = 12;
    local.tm_min = 0;
    local.tm_sec = 0;
    if (mktime(&local) == static_cast<time_t>(-1)) return -1;
    char iso[11];
    strftime(iso, sizeof(iso), "%Y-%m-%d", &local);
    for (uint8_t index = 0; index < model.trainingTelemetry.count; ++index)
        if (strcmp(model.trainingTelemetry.workouts[index].date, iso) == 0) return index;
    return -1;
}

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
    model.nightMode = hardware::nightMode();
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
    const auto inside = [](int16_t px, int16_t py, int16_t left, int16_t top,
                           int16_t rectWidth) {
        return px >= left && px < left + rectWidth
            && py >= top && py < top + ui_layout::buttonHeight;
    };
    if (model.page == app_state::Page::Home)
    {
        if (inside(x, y, ui_layout::leftButtonX, ui_layout::homeTopButtonY,
                   ui_layout::pairedButtonWidth)) return 1;
        if (inside(x, y, ui_layout::rightButtonX, ui_layout::homeTopButtonY,
                   ui_layout::pairedButtonWidth)) return 2;
        if (inside(x, y, ui_layout::leftButtonX, ui_layout::homeBottomButtonY,
                   ui_layout::pairedButtonWidth)) return 3;
        if (inside(x, y, ui_layout::rightButtonX, ui_layout::homeBottomButtonY,
                   ui_layout::pairedButtonWidth)) return 4;
    }
    else if (model.page == app_state::Page::System)
    {
        if (x >= ui_layout::brightnessSliderX
            && x < ui_layout::brightnessSliderX + ui_layout::brightnessSliderWidth
            && y >= ui_layout::brightnessSliderY
            && y < ui_layout::brightnessSliderY + ui_layout::brightnessSliderHeight)
            return 11;
        if (inside(x, y, ui_layout::leftButtonX, ui_layout::systemButtonY,
                   ui_layout::pairedButtonWidth)) return 6;
        if (inside(x, y, ui_layout::rightButtonX, ui_layout::systemButtonY,
                   ui_layout::pairedButtonWidth)) return 5;
    }
    else if (model.page == app_state::Page::Training)
    {
        for (uint8_t dayOffset = 0; dayOffset < ui_layout::trainingDayCount; ++dayOffset)
        {
            const int16_t top = static_cast<int16_t>(ui_layout::trainingFirstRowY
                                                   + dayOffset * ui_layout::trainingRowStep);
            if (x >= ui_layout::trainingRowX
                && x < ui_layout::trainingRowX + ui_layout::trainingRowWidth
                && y >= top && y < top + ui_layout::trainingRowHeight)
            {
                const int workoutIndex = trainingIndexForDay(dayOffset);
                if (workoutIndex >= 0) return static_cast<uint8_t>(20 + workoutIndex);
                return 0;
            }
        }
        if (inside(x, y, ui_layout::singleButtonX, ui_layout::singleButtonY,
                   ui_layout::singleButtonWidth)) return 5;
    }
    else if (model.page == app_state::Page::TrainingDetail)
    {
        if (inside(x, y, ui_layout::leftButtonX, ui_layout::systemButtonY,
                   ui_layout::pairedButtonWidth)) return 10;
        if (inside(x, y, ui_layout::rightButtonX, ui_layout::systemButtonY,
                   ui_layout::pairedButtonWidth)) return 5;
    }
    else if (inside(x, y, ui_layout::singleButtonX, ui_layout::singleButtonY,
                    ui_layout::singleButtonWidth)) return 5;
    return 0;
}

void action(uint8_t button)
{
    if (button >= 20 && button < 20 + secure_protocol::trainingItemMax)
    {
        model.selectedTraining = static_cast<uint8_t>(button - 20);
        model.page = app_state::Page::TrainingDetail;
        model.pressedButton = 0;
        ui::page(model);
        return;
    }
    switch (button)
    {
    case 1: model.page = app_state::Page::Cluster; model.pressedButton = 0; ui::page(model); break;
    case 2: model.page = app_state::Page::Training; model.pressedButton = 0; ui::page(model); break;
    case 3: model.page = app_state::Page::Calendar; model.pressedButton = 0; ui::page(model); break;
    case 4: model.page = app_state::Page::System; model.pressedButton = 0; ui::page(model); break;
    case 5: model.page = app_state::Page::Home; model.pressedButton = 0; ui::page(model); break;
    case 6:
        model.nightMode = hardware::toggleNightMode();
        ui::page(model);
        break;
    case 10:
        model.page = app_state::Page::Training;
        model.pressedButton = 0;
        ui::page(model);
        break;
    default: break;
    }
}

void updateBrightnessSlider(int16_t x)
{
    const int16_t first = ui_layout::brightnessSliderX;
    const int16_t last = static_cast<int16_t>(first + ui_layout::brightnessSliderWidth - 1);
    if (x < first) x = first;
    if (x > last) x = last;
    const uint8_t percent = static_cast<uint8_t>(hardware::minimumBrightness
        + (x - first) * (hardware::maximumBrightness - hardware::minimumBrightness)
          / (ui_layout::brightnessSliderWidth - 1));
    if (percent == model.brightnessPercent) return;
    model.brightnessPercent = percent;
    hardware::previewBrightness(percent);
    ui::brightness(model);
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
            if (model.pressedButton == 11) updateBrightnessSlider(point.x);
            else if (model.pressedButton) ui::pressed(model);
        }
        else if (model.pressedButton == 11) updateBrightnessSlider(point.x);
    }
    else if (lastDown)
    {
        const uint8_t button = model.pressedButton;
        model.pressedButton = 0;
        if (button)
        {
            if (button == 11)
            {
                hardware::saveBrightness();
                ui::brightness(model);
            }
            else
            {
                // The pressed visual is held until release; actions are click-on-up.
                ui::pressed(model);
                action(button);
            }
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
