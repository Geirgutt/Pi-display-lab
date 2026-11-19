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
#include "home_content.h"
#include "navigation_gesture.h"
#include <Arduino.h>
#include <time.h>

namespace
{
app_state::Model model;
uint32_t nextTelemetry = 0;
bool lastDown = false;
navigation_gesture::Tracker gesture;
app_state::Page touchPage = app_state::Page::Home;
bool touchCancelled = false;
uint32_t pressedActivityRevision = 0;
char pressedSpotifyTrack[secure_protocol::spotifyTrackIdSize + 1] = {};
bool activityDetailNeedsRedraw = false;
bool alarmActive = false;
bool alarmLit = false;
uint32_t alarmStartedAt = 0;
uint32_t lastAlarmBlinkAt = 0;
app_state::Page alarmReturnPage = app_state::Page::Home;

void stopAlarm()
{
    alarmActive = false;
    alarmLit = false;
    model.pressedButton = 0;
    model.page = alarmReturnPage;
    ui::page(model);
}

void startAlarm()
{
    alarmReturnPage = model.page;
    model.page = app_state::Page::Home;
    model.pressedButton = 0;
    touchCancelled = true;
    alarmActive = true;
    alarmLit = true;
    alarmStartedAt = millis();
    lastAlarmBlinkAt = alarmStartedAt;
    if (model.alarmMethod == 1) ui::page(model);
    ui::alarmFlash(true, model);
}

void checkAlarm()
{
    if (!model.alarmEnabled || !model.timeValid || alarmActive) return;
    const time_t now = time(nullptr);
    struct tm local = {};
    if (!localtime_r(&now, &local)) return;
    const uint32_t date = static_cast<uint32_t>((local.tm_year + 1900) * 10000
        + (local.tm_mon + 1) * 100 + local.tm_mday);
    if (local.tm_hour != model.alarmHour || local.tm_min != model.alarmMinute
        || date == hardware::lastAlarmDate()) return;
    hardware::markAlarmFired(date, !model.alarmRepeats);
    model.alarmEnabled = hardware::alarmEnabled();
    startAlarm();
}

void serviceAlarm(uint32_t now)
{
    if (!alarmActive) return;
    if (uint32_t(now - alarmStartedAt) >= 30000)
    {
        stopAlarm();
        return;
    }
    if (uint32_t(now - lastAlarmBlinkAt) >= 500)
    {
        lastAlarmBlinkAt = now;
        alarmLit = !alarmLit;
        ui::alarmFlash(alarmLit, model);
    }
}

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
    model.alarmEnabled = hardware::alarmEnabled();
    model.alarmHour = hardware::alarmHour();
    model.alarmMinute = hardware::alarmMinute();
    model.alarmRepeats = hardware::alarmRepeats();
    model.alarmMethod = hardware::alarmMethod();
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
        strncpy(model.dateText, "Waiting for time", sizeof(model.dateText) - 1);
        model.dateText[sizeof(model.dateText) - 1] = 0;
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
        model.spotifyTelemetry = secure_transport::lastSpotifyTelemetry();
        model.garminTelemetry = secure_transport::lastGarminTelemetry();
        const auto& activities = secure_transport::lastActivityTelemetry();
        if (memcmp(&model.activities, &activities, sizeof(activities)) != 0)
        {
            model.activities = activities;
            if (activities.count <= app_state::activityPageSize) model.activityPage = 0;
            ++model.activityRevision;
            if (model.page == app_state::Page::ActivityDetail)
            {
                auto& selected = model.selectedActivity;
                for (uint8_t i = 0; i < activities.count; ++i)
                {
                    const auto& candidate = activities.items[i];
                    const bool sameDescription = strcmp(selected.date, candidate.date) == 0
                        && strcmp(selected.title, candidate.title) == 0
                        && strcmp(selected.kind, candidate.kind) == 0
                        && memcmp(selected.values, candidate.values, sizeof(selected.values)) == 0;
                    const bool sameActivity = selected.id && candidate.id
                        ? selected.id == candidate.id : sameDescription;
                    if (sameActivity || (!selected.title[0] && model.activityFromHome && i == 0))
                    {
                        activityDetailNeedsRedraw = memcmp(&selected, &candidate, sizeof(selected)) != 0;
                        const bool mapChanged = selected.id != candidate.id
                            || (selected.routeCount < 2 && candidate.routeCount >= 2);
                        selected = candidate;
                        if (mapChanged && model.activityView == app_state::ActivityView::Map && selected.routeCount >= 2)
                            secure_transport::requestActivityMap(selected.id);
                        if (model.lapOffset >= selected.lapCount) model.lapOffset = 0;
                        break;
                    }
                }
            }
        }
        model.nodeAccepted = secureStats.accepted;
    }
    model.nodeLastUpdate = secure_transport::lastTelemetryAt();
    model.spotifyConnected = secure_transport::connected() && model.nodeLastUpdate != 0
                          && uint32_t(millis() - model.nodeLastUpdate) < 5000;
    model.garminConnected = model.spotifyConnected;
    model.nodeOnline = model.nodeLastUpdate != 0
                    && uint32_t(millis() - model.nodeLastUpdate) < 5000
                    && model.nodeTelemetry.online;
    char today[11] = {};
    if (model.timeValid) strftime(today, sizeof(today), "%Y-%m-%d", &localTime);
    model.nextTraining = home_content::nextWorkout(model.trainingTelemetry, today);
    model.nextCalendar = home_content::nextEvent(model.calendarTelemetry,
        model.timeValid ? static_cast<uint32_t>(now) : 0);
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
        if (x >= 20 && x < 460 && y >= ui_layout::homeAlarmY
            && y < ui_layout::homeAlarmY + ui_layout::buttonHeight) return 7;
        if (inside(x, y, ui_layout::homeClusterX, ui_layout::homeClusterY,
                   ui_layout::homeClusterWidth)) return 1;
        if (ui_layout::inHomeSummary(x, y, ui_layout::homeSummaryX, ui_layout::homeWorkoutY,
                                     ui_layout::homeWorkoutWidth, ui_layout::homeWorkoutHeight)) return 66;
        if (ui_layout::inHomeSummary(x, y, ui_layout::homeUpcomingX, ui_layout::homeWorkoutY,
                                     ui_layout::homeWorkoutWidth, ui_layout::homeWorkoutHeight)) return 2;
        if (model.calendarTelemetry.available && ui_layout::inHomeSummary(x, y, ui_layout::homeSummaryX,
                ui_layout::homeCalendarY, ui_layout::homeSummaryWidth, ui_layout::homeSummaryHeight)) return 3;
        if (inside(x, y, ui_layout::homeMenuX, ui_layout::homeMenuY,
                   ui_layout::homeMenuWidth)) return 8;
    }
    else if (model.page == app_state::Page::Menu)
    {
        if (inside(x, y, ui_layout::leftButtonX, 364, ui_layout::pairedButtonWidth)) return 54;
        if (inside(x, y, ui_layout::rightButtonX, 364, ui_layout::pairedButtonWidth)) return 58;
        if (inside(x, y, ui_layout::leftButtonX, ui_layout::menuFirstRowY,
                   ui_layout::pairedButtonWidth)) return 1;
        if (inside(x, y, ui_layout::rightButtonX, ui_layout::menuFirstRowY,
                   ui_layout::pairedButtonWidth)) return 2;
        if (inside(x, y, ui_layout::leftButtonX, ui_layout::menuSecondRowY,
                   ui_layout::pairedButtonWidth)) return 3;
        if (inside(x, y, ui_layout::rightButtonX, ui_layout::menuSecondRowY,
                   ui_layout::pairedButtonWidth)) return 7;
        if (inside(x, y, ui_layout::leftButtonX, ui_layout::menuThirdRowY,
                   ui_layout::pairedButtonWidth)) return 4;
        if (inside(x, y, ui_layout::rightButtonX, ui_layout::menuThirdRowY,
                   ui_layout::pairedButtonWidth)) return 5;
    }
    else if (model.page == app_state::Page::Garmin)
    {
        for (uint8_t i = 0; i < secure_protocol::garminMetricMax && model.garminCard(i); ++i)
        {
            const int16_t left = ui_layout::garminMetricX(i);
            const int16_t top = ui_layout::garminMetricY(i);
            if (x >= left && x < left + ui_layout::garminMetricWidth
                && y >= top && y < top + ui_layout::garminMetricHeight) return 80 + i;
        }
        if (inside(x, y, 12, 426, 52)) return 59;
        if (inside(x, y, 72, 426, 52)) return 60;
        if (inside(x, y, 132, 426, 112)) return 61;
        if (inside(x, y, 252, 426, 120)) return 2;
        if (inside(x, y, 380, 426, 88)) return 5;
    }
    else if (model.page == app_state::Page::ActivityHistory)
    {
        for (uint8_t row = 0; row < app_state::activityPageSize; ++row)
        {
            const int16_t top = ui_layout::activityFirstRowY + row * ui_layout::activityRowStep;
            if (model.activityOffset() + row < model.activities.count
                && x >= 20 && x < 460 && y >= top && y < top + ui_layout::activityRowHeight)
                return 70 + row;
        }
        if (model.activityOffset() && inside(x, y, 12, 426, 80)) return 63;
        if (!model.activityOffset() && model.activities.count > app_state::activityPageSize
            && inside(x, y, 104, 426, 80)) return 64;
        if (inside(x, y, 196, 426, 152)) return 62;
        if (inside(x, y, 360, 426, 108)) return 5;
    }
    else if (model.page == app_state::Page::ActivityDetail)
    {
        if (inside(x, y, 12, 426, 94)) return model.activityFromHome ? 61 : 65;
        if (model.selectedActivity.title[0] && inside(x, y, 110, 426, 92)) return 67;
        if (model.selectedActivity.title[0] && inside(x, y, 206, 426, 82)) return 76;
        if (model.selectedActivity.title[0] && inside(x, y, 292, 426, 82)) return 77;
        if (inside(x, y, 378, 426, 90)) return 5;
        if (model.activityView == app_state::ActivityView::Charts && model.selectedActivity.extraChartsAvailable
            && inside(x, y, 370, 376, 98)) return 78;
        if (model.activityView == app_state::ActivityView::Laps)
        {
            if (model.lapOffset && inside(x, y, 12, 376, 72)) return 68;
            if (model.lapOffset + app_state::lapsPageSize < model.selectedActivity.lapCount
                && inside(x, y, 396, 376, 72)) return 69;
        }
    }
    else if (model.page == app_state::Page::GarminMetricDetail)
    {
        if (inside(x, y, 12, 426, 180)) return 62;
        if (inside(x, y, 288, 426, 180)) return 5;
    }
    else if (model.page == app_state::Page::Spotify)
    {
        if (inside(x, y, ui_layout::singleButtonX, ui_layout::singleButtonY,
                   ui_layout::singleButtonWidth)) return 5;
        if (!model.spotifyConnected || (model.spotifyTelemetry.capabilities & 8)) return 0;
        const uint8_t flags = model.spotifyTelemetry.capabilities;
        if ((flags & 4) && inside(x, y, 20, 324, 100)) return 55;
        if ((flags & 1) && inside(x, y, 132, 324, 100)) return 56;
        if ((flags & 2) && inside(x, y, 244, 324, 100)) return 57;
        if ((model.spotifyTelemetry.library == 1 || model.spotifyTelemetry.library == 5)
            && inside(x, y, 356, 324, 104)) return 79;
    }
    else if (model.page == app_state::Page::System)
    {
        if (x >= ui_layout::brightnessSliderX - ui_layout::brightnessSliderHitPadding
            && x < ui_layout::brightnessSliderX + ui_layout::brightnessSliderWidth
                            + ui_layout::brightnessSliderHitPadding
            && y >= ui_layout::brightnessSliderY
            && y < ui_layout::brightnessSliderY + ui_layout::brightnessSliderHeight)
            return 11;
        if (inside(x, y, ui_layout::leftButtonX, ui_layout::systemButtonY,
                   ui_layout::pairedButtonWidth)) return 6;
        if (inside(x, y, ui_layout::rightButtonX, ui_layout::systemButtonY,
                   ui_layout::pairedButtonWidth)) return 5;
    }
    else if (model.page == app_state::Page::Alarm)
    {
        if (y >= 110 && y < 190)
        {
            if (x >= 72 && x < 232) return 12;
            if (x >= 248 && x < 408) return 14;
        }
        if (y >= ui_layout::alarmAdjustY
            && y < ui_layout::alarmAdjustY + ui_layout::buttonHeight)
        {
            if (x >= 24 && x < 232) return 12;
            if (x >= 248 && x < 456) return 14;
        }
        if (x >= 12 && x < 468 && y >= ui_layout::alarmToggleY
            && y < ui_layout::alarmToggleY + ui_layout::buttonHeight) return 16;
        if (y >= ui_layout::alarmOptionsY
            && y < ui_layout::alarmOptionsY + ui_layout::buttonHeight)
        {
            if (x >= 12 && x < 240) return 17;
            if (x >= 240 && x < 468) return 18;
        }
        if (inside(x, y, 12, ui_layout::singleButtonY, 222)) return 19;
        if (inside(x, y, 246, ui_layout::singleButtonY, 222)) return 5;
    }
    else if (model.page == app_state::Page::AlarmNumber)
    {
        for (uint8_t row = 0; row < 4; ++row)
            for (uint8_t column = 0; column < 3; ++column)
                if (inside(x, y, 24 + column * 156, 200 + row * 52, 120))
                    return row < 3 ? static_cast<uint8_t>(41 + row * 3 + column)
                        : (column == 0 ? 51 : column == 1 ? 40 : 50);
        if (inside(x, y, 12, ui_layout::singleButtonY, 222)) return 53;
        if (inside(x, y, 246, ui_layout::singleButtonY, 222)) return 52;
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
    if (model.page == app_state::Page::Garmin && button >= 80
        && button < 80 + secure_protocol::garminMetricMax)
    {
        const auto& state = model.garminTelemetry;
        const auto* metric = model.garminCard(button - 80);
        if (!metric) return;
        model.selectedGarminMetric = *metric;
        model.garminMetricHistoryEnd = state.historyEnd;
        model.page = app_state::Page::GarminMetricDetail;
        ui::page(model);
        return;
    }
    if (model.page == app_state::Page::ActivityHistory && button >= 70
        && button < 70 + app_state::activityPageSize)
    {
        const uint8_t index = model.activityOffset() + button - 70;
        if (index >= model.activities.count || pressedActivityRevision != model.activityRevision) return;
        model.selectedActivity = model.activities.items[index];
        model.activityFromHome = false;
        model.activityView = app_state::ActivityView::Summary;
        model.extraActivityCharts = false;
        model.lapOffset = 0;
        model.page = app_state::Page::ActivityDetail;
        ui::page(model);
        return;
    }
    if (model.page == app_state::Page::Garmin && (button == 59 || button == 60))
    {
        const uint8_t count = model.garminPageCount();
        if (count) model.selectedGarmin = static_cast<uint8_t>(
            (model.selectedGarmin + (button == 59 ? count - 1 : 1)) % count);
        model.pressedButton = 0;
        ui::page(model);
        return;
    }
    if (model.page == app_state::Page::Spotify && ((button >= 55 && button <= 57) || button == 79))
    {
        const uint8_t command = button == 79 ? 5 : button == 55 ? 4 : button == 57 ? 3
                              : model.spotifyTelemetry.status == 1 ? 2 : 1;
        secure_transport::spotifyCommand(command, button == 79 ? pressedSpotifyTrack : nullptr);
        model.pressedButton = 0;
        ui::pressed(model);
        return;
    }
    if (model.page == app_state::Page::AlarmNumber)
    {
        model.pressedButton = 0;
        if (button >= 40 && button <= 49) model.alarmInput.digit(button - 40);
        else if (button == 50) model.alarmInput.erase();
        else if (button == 51) model.alarmInput.clear();
        else if (button == 53) { model.page = app_state::Page::Alarm; ui::page(model); return; }
        else if (button == 52)
        {
            if (!model.alarmInput.valid()) { model.alarmInput.error = true; ui::alarmInput(model); return; }
            if (model.alarmEditingHour) model.alarmHour = model.alarmInput.value;
            else model.alarmMinute = model.alarmInput.value;
            hardware::setAlarm(model.alarmEnabled, model.alarmHour, model.alarmMinute,
                               model.alarmRepeats, model.alarmMethod);
            model.page = app_state::Page::Alarm;
            ui::page(model);
            return;
        }
        ui::alarmInput(model);
        return;
    }
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
    case 61: model.activityPage = 0; model.page = app_state::Page::ActivityHistory; ui::page(model); break;
    case 62: model.page = app_state::Page::Garmin; ui::page(model); break;
    case 63: model.activityPage = 0; ui::page(model); break;
    case 64: model.activityPage = 1; ui::page(model); break;
    case 65: model.page = app_state::Page::ActivityHistory; ui::page(model); break;
    case 67:
        model.activityView = model.activityView == app_state::ActivityView::Charts
            ? app_state::ActivityView::Summary : app_state::ActivityView::Charts;
        ui::page(model);
        break;
    case 68: model.lapOffset -= app_state::lapsPageSize; ui::page(model); break;
    case 69: model.lapOffset += app_state::lapsPageSize; ui::page(model); break;
    case 76:
        model.activityView = model.activityView == app_state::ActivityView::Laps
            ? app_state::ActivityView::Summary : app_state::ActivityView::Laps;
        ui::page(model);
        break;
    case 77:
        model.activityView = model.activityView == app_state::ActivityView::Map
            ? app_state::ActivityView::Summary : app_state::ActivityView::Map;
        if (model.activityView == app_state::ActivityView::Map && model.selectedActivity.routeCount >= 2)
            secure_transport::requestActivityMap(model.selectedActivity.id);
        ui::page(model);
        break;
    case 78: model.extraActivityCharts = !model.extraActivityCharts; ui::page(model); break;
    case 58: model.page = app_state::Page::Garmin; model.pressedButton = 0; ui::page(model); break;
    case 54: model.page = app_state::Page::Spotify; model.pressedButton = 0; ui::page(model); break;
    case 1: model.page = app_state::Page::Cluster; model.pressedButton = 0; ui::page(model); break;
    case 2: model.page = app_state::Page::Training; model.pressedButton = 0; ui::page(model); break;
    case 3: model.page = app_state::Page::Calendar; model.pressedButton = 0; ui::page(model); break;
    case 4: model.page = app_state::Page::System; model.pressedButton = 0; ui::page(model); break;
    case 5: model.page = app_state::Page::Home; model.pressedButton = 0; ui::page(model); break;
    case 6:
        model.nightMode = hardware::toggleNightMode();
        ui::page(model);
        break;
    case 7: model.page = app_state::Page::Alarm; model.pressedButton = 0; ui::page(model); break;
    case 8: model.page = app_state::Page::Menu; model.pressedButton = 0; ui::page(model); break;
    case 66:
        model.selectedActivity = model.activities.count ? model.activities.items[0] : secure_protocol::Activity{};
        model.activityFromHome = true;
        model.activityView = app_state::ActivityView::Summary;
        model.extraActivityCharts = false;
        model.lapOffset = 0;
        model.page = app_state::Page::ActivityDetail;
        ui::page(model);
        break;
    case 12:
    case 14:
        model.alarmEditingHour = button == 12;
        model.alarmInput.begin(model.alarmEditingHour ? 23 : 59);
        model.page = app_state::Page::AlarmNumber;
        model.pressedButton = 0;
        ui::page(model);
        break;
    case 16: model.alarmEnabled = !model.alarmEnabled; break;
    case 17: model.alarmRepeats = !model.alarmRepeats; break;
    case 18: model.alarmMethod = static_cast<uint8_t>((model.alarmMethod + 1) % 2); break;
    case 19:
        // A preview never consumes ONCE or alters the persisted schedule.
        startAlarm();
        break;
    case 10:
        model.page = app_state::Page::Training;
        model.pressedButton = 0;
        ui::page(model);
        break;
    default: break;
    }
    if (button >= 16 && button <= 18)
    {
        hardware::setAlarm(model.alarmEnabled, model.alarmHour, model.alarmMinute,
                           model.alarmRepeats, model.alarmMethod);
        model.pressedButton = 0;
        ui::pressed(model);
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
    if (alarmActive)
    {
        if (down && !lastDown) stopAlarm();
        touchCancelled = true;
        lastDown = down;
        return;
    }
    if (down)
    {
        model.touchX = point.x;
        model.touchY = point.y;
        if (!lastDown)
        {
            gesture.begin(point.x, point.y, millis());
            touchPage = model.page;
            touchCancelled = false;
            model.pressedButton = hit(point.x, point.y);
            if (model.pressedButton == 79)
                memcpy(pressedSpotifyTrack, model.spotifyTelemetry.trackId, sizeof(pressedSpotifyTrack));
            pressedActivityRevision = model.activityRevision;
            if (model.pressedButton == 11) updateBrightnessSlider(point.x);
            else if (model.pressedButton) ui::pressed(model);
        }
        else
        {
            gesture.move(point.x, point.y);
            if (model.pressedButton == 11) updateBrightnessSlider(point.x);
        }
    }
    else if (lastDown)
    {
        const uint8_t button = model.pressedButton;
        model.pressedButton = 0;
        if (touchCancelled) touchCancelled = false;
        else if (touchPage == model.page && (touchPage == app_state::Page::Home
            || touchPage == app_state::Page::Menu || touchPage == app_state::Page::AlarmNumber))
        {
            const auto result = gesture.finish(millis());
            if (touchPage == app_state::Page::Home && gesture.originY() >= 78
                && result == navigation_gesture::Result::Up) action(8);
            else if (touchPage == app_state::Page::Menu
                     && result == navigation_gesture::Result::Down) action(5);
            else
            {
                ui::pressed(model);
                if (result == navigation_gesture::Result::Tap && button
                    && hit(gesture.x(), gesture.y()) == button) action(button);
            }
        }
        else if (touchPage == model.page && button)
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
    if (!secure_transport::displaySuppressed())
    {
        processTouch();
        console::service();
    }
#if DESKDISPLAY_BLE
    if (!secure_transport::displaySuppressed()) ble_test::service();
#endif
#if DESKDISPLAY_WIFI
    network::service();
#endif
#if DESKDISPLAY_SECURE && DESKDISPLAY_WIFI
    secure_transport::service();
#endif
    if (secure_transport::takeDisplayRestoreRequest()) ui::page(model);
    if (secure_transport::displaySuppressed())
    {
        if (alarmActive) model.page = alarmReturnPage;
        alarmActive = false;
        return;
    }
    const uint32_t now = millis();
    if (static_cast<int32_t>(now - nextTelemetry) >= 0)
    {
        nextTelemetry = now + 1000;
        refreshState();
        checkAlarm();
        if (!alarmActive)
        {
            const bool mapNeedsRedraw = model.page == app_state::Page::ActivityDetail
                && model.activityView == app_state::ActivityView::Map && !model.pressedButton
                && secure_transport::takeActivityMapUpdate(model.selectedActivity.id);
            if ((activityDetailNeedsRedraw || mapNeedsRedraw) && model.page == app_state::Page::ActivityDetail)
                ui::page(model);
            else ui::telemetry(model);
        }
        activityDetailNeedsRedraw = false;
    }
    // checkAlarm() may have started the alarm after the telemetry timestamp.
    // Use a fresh time so unsigned elapsed arithmetic cannot underflow.
    serviceAlarm(millis());
    delay(20);
}
