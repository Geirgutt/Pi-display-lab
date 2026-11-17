#include "ui.h"
#include "hardware.h"
#include "ui_layout.h"
#include <LovyanGFX.hpp>
#include <time.h>

namespace
{
constexpr int16_t width = ui_layout::screenWidth;
constexpr int16_t headerHeight = 58;
constexpr uint16_t homeBackground = TFT_BLACK;
constexpr uint16_t homeButtonOutline = 0x1082;
constexpr uint16_t nightRed = 0xF800;
constexpr uint16_t nightOutline = 0x3000;
constexpr uint16_t nightPressed = 0x6000;
constexpr uint16_t menuOutline = 0x7BEF;
constexpr uint16_t nightMenuOutline = 0xA800;
constexpr uint16_t background = 0x1082;
constexpr uint16_t card = 0x18E3;
constexpr uint16_t accent = 0x05BF;
constexpr uint16_t good = 0x05E8;
constexpr uint16_t warning = 0xFD20;
constexpr uint16_t text = TFT_WHITE;
constexpr uint16_t muted = 0xBDF7;
char lastClockText[6] = {};
char lastDateText[24] = {};
uint16_t lastHomeNodeCount = UINT16_MAX;
uint16_t lastHomeOnlineCount = UINT16_MAX;
bool lastHomeStreamLive = false;
bool lastHomeTimeValid = false;
secure_protocol::TrainingTelemetry lastTraining{};
secure_protocol::CalendarTelemetry lastCalendar{};
bool trainingDrawn = false;
bool calendarDrawn = false;
secure_protocol::SpotifyTelemetry lastSpotify{};
bool spotifyDrawn = false;
bool lastSpotifyConnected = false;
secure_protocol::GarminTelemetry lastGarmin{};
bool garminDrawn = false;
uint8_t lastGarminPage = 255;
uint32_t lastGarminAge = UINT32_MAX;
bool lastGarminConnected = false;
struct HomeSummary
{
    char heading[64] = {};
    char title[96] = {};
    bool pressed = false;
};
HomeSummary lastHomeCalendar{}, lastHomeTraining{}, lastHomeActivity{};
bool lastHomeCalendarVisible = false;
bool isTomorrow(const app_state::Model& model, const char* iso);

LGFX& display() { return hardware::display(); }

void copyDisplayText(const char* source, char* destination, size_t capacity)
{
    if (!capacity) return;
    if (!source) source = "";
    size_t input = 0;
    size_t output = 0;
    while (source[input] && output + 1 < capacity)
    {
        const unsigned char first = static_cast<unsigned char>(source[input]);
        if (first == 0xC3 && source[input + 1])
        {
            const unsigned char second = static_cast<unsigned char>(source[input + 1]);
            const char* replacement = nullptr;
            switch (second)
            {
            case 0x86: replacement = "Ae"; break; // Latin capital AE
            case 0xA6: replacement = "ae"; break; // Latin small ae
            case 0x98: replacement = "O"; break;  // O with stroke
            case 0xB8: replacement = "o"; break;  // o with stroke
            case 0x85: replacement = "A"; break;  // A with ring
            case 0xA5: replacement = "a"; break;  // a with ring
            default: break;
            }
            if (replacement)
            {
                for (size_t index = 0; replacement[index] && output + 1 < capacity; ++index)
                    destination[output++] = replacement[index];
                input += 2;
                continue;
            }
        }
        destination[output++] = source[input++];
    }
    destination[output] = 0;
}

void label(const char* value, int16_t x, int16_t y, uint8_t size = 2, uint16_t color = text)
{
    display().setTextSize(size);
    display().setTextColor(color, background);
    display().drawString(value, x, y);
}

void valueRow(const char* name, const char* value, int16_t y, uint16_t color = text)
{
    display().fillRect(28, y, 424, 27, background);
    label(name, 32, y + 3, 2, muted);
    label(value, 178, y + 3, 2, color);
}

void button(uint8_t id, const char* caption, int16_t x, int16_t y, int16_t buttonWidth,
            bool active, uint16_t idleFill = card, uint16_t outline = muted,
            uint16_t captionColor = text, uint16_t activeFill = accent)
{
    const uint16_t fill = active ? activeFill : idleFill;
    display().fillRoundRect(x, y, buttonWidth, ui_layout::buttonHeight, 8, fill);
    display().drawRoundRect(x, y, buttonWidth, ui_layout::buttonHeight, 8, outline);
    display().setTextColor(captionColor, fill);
    display().setTextSize(2);
    const int16_t textX = x + (buttonWidth - display().textWidth(caption)) / 2;
    display().drawString(caption, textX, y + 11);
    (void)id;
}

void homeButton(uint8_t id, const char* caption, int16_t x, int16_t y,
                const app_state::Model& model)
{
    button(id, caption, x, y, ui_layout::pairedButtonWidth, model.pressedButton == id,
           homeBackground, model.nightMode ? nightMenuOutline : menuOutline,
           model.nightMode ? nightRed : text, model.nightMode ? nightPressed : accent);
}

void homeAlarm(const app_state::Model& model)
{
    char caption[36];
    if (model.alarmEnabled)
        snprintf(caption, sizeof(caption), "Alarm %02u:%02u %s  >",
                 model.alarmHour, model.alarmMinute,
                 model.alarmRepeats ? "DAILY" : "ONCE");
    else snprintf(caption, sizeof(caption), "Alarm OFF  -  tap to set  >");
    button(7, caption, 20, ui_layout::homeAlarmY, 440,
           model.pressedButton == 7, homeBackground,
           model.nightMode ? nightOutline : homeButtonOutline,
           model.nightMode ? nightRed : text,
           model.nightMode ? nightPressed : accent);
}

void homeNavigation(const app_state::Model& model)
{
    button(8, "Menu", ui_layout::homeMenuX, ui_layout::homeMenuY,
           ui_layout::homeMenuWidth, model.pressedButton == 8,
           homeBackground, model.nightMode ? nightOutline : homeButtonOutline,
           model.nightMode ? nightRed : text, model.nightMode ? nightPressed : accent);
}

void menuButtons(const app_state::Model& model)
{
    homeButton(54, "Spotify", ui_layout::leftButtonX, 364, model);
    homeButton(58, "Garmin", ui_layout::rightButtonX, 364, model);
    homeButton(1, "Cluster", ui_layout::leftButtonX, ui_layout::menuFirstRowY, model);
    homeButton(2, "Training", ui_layout::rightButtonX, ui_layout::menuFirstRowY, model);
    homeButton(3, "Calendar", ui_layout::leftButtonX, ui_layout::menuSecondRowY, model);
    homeButton(7, "Alarm", ui_layout::rightButtonX, ui_layout::menuSecondRowY, model);
    homeButton(4, "System", ui_layout::leftButtonX, ui_layout::menuThirdRowY, model);
    homeButton(5, "Clock", ui_layout::rightButtonX, ui_layout::menuThirdRowY, model);
}

void header(const char* title, uint16_t fill, uint16_t foreground);

void alarmSettings(const app_state::Model& model, bool force = true)
{
    if (force)
    {
        header("Alarm", 0x0841, text);
        display().fillRoundRect(12, 68, 456, 340, 10, card);
    }
    label("Reminder - local display time", 28, 84, 2, muted);
    char timeText[6];
    snprintf(timeText, sizeof(timeText), "%02u:%02u", model.alarmHour, model.alarmMinute);
    display().setFont(&fonts::Font0);
    display().setTextColor(text, card);
    display().setTextSize(7);
    display().drawString(timeText, (width - display().textWidth(timeText)) / 2, 124);
    label("HOUR", 98, 194, 2, muted);
    label("MINUTE", 324, 194, 2, muted);
    button(12, "Set hour", 24, ui_layout::alarmAdjustY, 208, model.pressedButton == 12);
    button(14, "Set minute", 248, ui_layout::alarmAdjustY, 208, model.pressedButton == 14);
    button(17, model.alarmRepeats ? "Repeat: Daily" : "Repeat: Once",
           12, ui_layout::alarmOptionsY, 222, model.pressedButton == 17);
    button(18, model.alarmMethod == 0 ? "Style: Full screen" : "Style: Clock only",
           246, ui_layout::alarmOptionsY, 222, model.pressedButton == 18);
    button(16, model.alarmEnabled ? "Enabled - tap to turn OFF"
                                  : "Disabled - tap to turn ON",
           12, ui_layout::alarmToggleY, 456, model.pressedButton == 16);
    label("Flashes for 30 seconds; tap screen to stop", 28, 382, 1, muted);
    button(19, "Test alarm", 12, ui_layout::singleButtonY, 222,
           model.pressedButton == 19);
    button(5, "Clock", 246, ui_layout::singleButtonY, 222,
           model.pressedButton == 5);
}

void alarmNumberKeys(const app_state::Model& model)
{
    for (uint8_t number = 1; number <= 9; ++number)
    {
        char caption[2] = {static_cast<char>('0' + number), 0};
        button(40 + number, caption, 24 + ((number - 1) % 3) * 156,
               200 + ((number - 1) / 3) * 52, 120, model.pressedButton == 40 + number);
    }
    button(51, "Clear", 24, 356, 120, model.pressedButton == 51);
    button(40, "0", 180, 356, 120, model.pressedButton == 40);
    button(50, "Delete", 336, 356, 120, model.pressedButton == 50);
    button(53, "Cancel", 12, ui_layout::singleButtonY, 222, model.pressedButton == 53);
    button(52, "Save", 246, ui_layout::singleButtonY, 222, model.pressedButton == 52);
}

void brightnessSlider(const app_state::Model& model)
{
    display().fillRect(28, 330, 424, 78, card);
    char caption[24];
    snprintf(caption, sizeof(caption), "Brightness  %u%%", model.brightnessPercent);
    display().setTextColor(text, card);
    display().setTextSize(2);
    display().drawString(caption, ui_layout::brightnessSliderX, 338);

    constexpr int16_t trackY = 382;
    constexpr int16_t trackHeight = 8;
    const int16_t travel = ui_layout::brightnessSliderWidth - 1;
    const int16_t knobX = static_cast<int16_t>(ui_layout::brightnessSliderX
        + (model.brightnessPercent - hardware::minimumBrightness) * travel
          / (hardware::maximumBrightness - hardware::minimumBrightness));
    display().fillRoundRect(ui_layout::brightnessSliderX, trackY,
                            ui_layout::brightnessSliderWidth, trackHeight, 4, 0x4208);
    display().fillRoundRect(ui_layout::brightnessSliderX, trackY,
                            knobX - ui_layout::brightnessSliderX + 1, trackHeight, 4, accent);
    display().fillCircle(knobX, trackY + trackHeight / 2, 11, accent);
    display().drawCircle(knobX, trackY + trackHeight / 2, 11, text);
}

void nightModeButton(const app_state::Model& model)
{
    button(6, model.nightMode ? "Night ON" : "Night OFF", ui_layout::leftButtonX,
           ui_layout::systemButtonY, ui_layout::pairedButtonWidth,
           model.pressedButton == 6);
}

void header(const char* title, uint16_t fill = 0x0841, uint16_t foreground = text)
{
    display().fillRect(0, 0, width, headerHeight, fill);
    display().setTextColor(foreground, fill);
    display().setTextSize(2);
    display().setFont(&fonts::Font0);
    display().drawString(title, (width - display().textWidth(title)) / 2, 19);
}

void homeClock(const app_state::Model& model, bool force = false)
{
    const uint16_t primary = model.nightMode ? nightRed : text;
    if (force || strcmp(lastClockText, model.clockText) != 0)
    {
        // Clock digits have a stable width. Drawing with an opaque background
        // replaces the old glyphs without flashing the whole screen every second.
        if (!force && lastHomeTimeValid != model.timeValid)
            display().fillRect(20, 78, 440, 96, homeBackground);
        display().setTextColor(model.timeValid ? primary : muted, homeBackground);
        display().setFont(&fonts::Font0);
        uint8_t clockSize = 11;
        display().setTextSize(clockSize);
        while (clockSize > 1 && display().textWidth(model.clockText) > width - 32)
        {
            display().setTextSize(--clockSize);
        }
        display().drawString(model.clockText,
                             (width - display().textWidth(model.clockText)) / 2, 86);
        display().setFont(&fonts::Font0);
        strncpy(lastClockText, model.clockText, sizeof(lastClockText));
        lastClockText[sizeof(lastClockText) - 1] = 0;
        lastHomeTimeValid = model.timeValid;
    }
    if (force || strcmp(lastDateText, model.dateText) != 0)
    {
        if (!force) display().fillRect(20, 181, 440, 40, homeBackground);
        display().setTextColor(model.timeValid ? primary : muted, homeBackground);
        display().setFont(&fonts::Font0);
        uint8_t dateSize = 4;
        display().setTextSize(dateSize);
        while (dateSize > 2 && display().textWidth(model.dateText) > width - 32)
        {
            display().setTextSize(--dateSize);
        }
        display().drawString(model.dateText,
                             (width - display().textWidth(model.dateText)) / 2, 185);
        display().setFont(&fonts::Font0);
        strncpy(lastDateText, model.dateText, sizeof(lastDateText));
        lastDateText[sizeof(lastDateText) - 1] = 0;
    }

    const bool streamLive = model.nodeLastUpdate != 0
                         && uint32_t(millis() - model.nodeLastUpdate) < 5000;
    if (force || lastHomeNodeCount != model.clusterTelemetry.totalNodes
        || lastHomeOnlineCount != model.clusterTelemetry.onlineNodes
        || lastHomeStreamLive != streamLive)
    {
        char status[48];
        if (!streamLive || model.clusterTelemetry.totalNodes == 0)
            snprintf(status, sizeof(status), "Cluster: waiting for data");
        else snprintf(status, sizeof(status), "Cluster: %u/%u online",
                      static_cast<unsigned>(model.clusterTelemetry.onlineNodes),
                      static_cast<unsigned>(model.clusterTelemetry.totalNodes));
        display().fillRect(ui_layout::homeClusterX, ui_layout::homeClusterY,
                           ui_layout::homeClusterWidth, ui_layout::buttonHeight, homeBackground);
        const uint16_t statusColor = model.nightMode ? nightRed
            : (streamLive && model.clusterTelemetry.onlineNodes
               == model.clusterTelemetry.totalNodes ? muted : warning);
        display().setTextColor(statusColor, homeBackground);
        display().setTextSize(1);
        display().setFont(&fonts::Font0);
        display().drawString(status, ui_layout::homeClusterX + 8, ui_layout::homeClusterY + 16);
        lastHomeNodeCount = model.clusterTelemetry.totalNodes;
        lastHomeOnlineCount = model.clusterTelemetry.onlineNodes;
        lastHomeStreamLive = streamLive;
    }
}

void fitText(char* value, size_t capacity, int16_t pixels)
{
    if (display().textWidth(value) <= pixels) return;
    size_t length = strlen(value);
    while (length && (length + 4 > capacity
           || display().textWidth(value) + display().textWidth("...") > pixels))
    {
        --length;
        while (length && (static_cast<uint8_t>(value[length]) & 0xC0) == 0x80) --length;
        value[length] = 0;
    }
    if (length + 4 <= capacity) strcat(value, "...");
}

void drawHomeSummary(HomeSummary& previous, HomeSummary value, int16_t x, int16_t y, int16_t cardWidth,
                     int16_t cardHeight, const app_state::Model& model, bool force)
{
    if (!force && previous.pressed == value.pressed
        && strcmp(previous.heading, value.heading) == 0
        && strcmp(previous.title, value.title) == 0) return;
    previous = value;
    display().fillRect(x, y, cardWidth, cardHeight, homeBackground);
    display().setFont(&fonts::Font0);
    display().setTextSize(1);
    display().setTextColor(model.nightMode ? nightRed : muted, homeBackground);
    fitText(value.heading, sizeof(value.heading), cardWidth - 16);
    display().drawString(value.heading, x + 8, y + cardHeight / 4 - 6);
    display().setTextSize(2);
    display().setTextColor(model.nightMode ? nightRed : text, homeBackground);
    fitText(value.title, sizeof(value.title), cardWidth - 16);
    display().drawString(value.title, x + 8, y + cardHeight / 2 - 4);
    display().drawRoundRect(x, y, cardWidth, cardHeight, 4,
                           model.nightMode ? (value.pressed ? nightRed : nightOutline)
                                           : (value.pressed ? accent : homeButtonOutline));
}

void homeSummaries(const app_state::Model& model, bool force = false)
{
    const bool calendarVisible = model.calendarTelemetry.available;
    if (force || calendarVisible != lastHomeCalendarVisible)
    {
        display().fillRect(ui_layout::homeSummaryX, ui_layout::homeCalendarY,
                           ui_layout::homeSummaryWidth, ui_layout::homeSummaryHeight, homeBackground);
        lastHomeCalendarVisible = calendarVisible;
        force = true;
    }
    const bool cached = model.nodeLastUpdate != 0
        && uint32_t(millis() - model.nodeLastUpdate) >= 5000;
    HomeSummary calendar{};
    calendar.pressed = model.pressedButton == 3;
    snprintf(calendar.heading, sizeof(calendar.heading), "Calendar");
    const char* calendarFallback = !model.calendarTelemetry.available ? "Not configured"
        : (!model.timeValid ? "Waiting for time" : "No upcoming events");
    copyDisplayText(calendarFallback, calendar.title, sizeof(calendar.title));
    if (model.nextCalendar >= 0)
    {
        const auto& event = model.calendarTelemetry.events[model.nextCalendar];
        const time_t starts = event.startsAt;
        const time_t now = time(nullptr);
        struct tm local = {}, today = {};
        char when[32] = {};
        if (localtime_r(&starts, &local) && localtime_r(&now, &today))
        {
            const bool sameDay = local.tm_year == today.tm_year && local.tm_yday == today.tm_yday;
            if (!event.allDay && starts <= now && event.endsAt > now)
                snprintf(when, sizeof(when), "NOW");
            else strftime(when, sizeof(when), event.allDay
                ? (sameDay ? "TODAY ALL DAY" : "%d.%m ALL DAY")
                : (sameDay ? "TODAY %H:%M" : "%d.%m %H:%M"), &local);
        }
        snprintf(calendar.heading, sizeof(calendar.heading), "Calendar - %s%s",
                 when, cached ? " (cached)" : "");
        copyDisplayText(event.title[0] ? event.title : "Calendar event",
                        calendar.title, sizeof(calendar.title));
    }
    if (calendarVisible)
        drawHomeSummary(lastHomeCalendar, calendar, ui_layout::homeSummaryX, ui_layout::homeCalendarY,
                        ui_layout::homeSummaryWidth, ui_layout::homeSummaryHeight, model, force);

    HomeSummary activity{};
    activity.pressed = model.pressedButton == 66;
    snprintf(activity.heading, sizeof(activity.heading), "Last activity");
    if (model.activities.count)
    {
        const auto& latest = model.activities.items[0];
        snprintf(activity.heading, sizeof(activity.heading), "Last activity - %.2s.%.2s",
                 latest.date + 8, latest.date + 5);
        copyDisplayText(latest.title, activity.title, sizeof(activity.title));
    }
    else copyDisplayText("No activity yet", activity.title, sizeof(activity.title));
    drawHomeSummary(lastHomeActivity, activity, ui_layout::homeSummaryX, ui_layout::homeWorkoutY,
                    ui_layout::homeWorkoutWidth, ui_layout::homeWorkoutHeight, model, force);

    HomeSummary training{};
    training.pressed = model.pressedButton == 2;
    snprintf(training.heading, sizeof(training.heading), "Next 7 days");
    const char* trainingFallback = !model.trainingTelemetry.available ? "Not configured"
        : (!model.timeValid ? "Waiting for time" : "No workouts");
    copyDisplayText(trainingFallback, training.title, sizeof(training.title));
    if (model.nextTraining >= 0)
    {
        const auto& workout = model.trainingTelemetry.workouts[model.nextTraining];
        char when[16];
        const time_t now = time(nullptr);
        struct tm local = {};
        char today[11] = {};
        if (localtime_r(&now, &local)) strftime(today, sizeof(today), "%Y-%m-%d", &local);
        if (strcmp(workout.date, today) == 0) snprintf(when, sizeof(when), "TODAY");
        else if (isTomorrow(model, workout.date)) snprintf(when, sizeof(when), "TOMORROW");
        else snprintf(when, sizeof(when), "%.2s.%.2s", workout.date + 8, workout.date + 5);
        snprintf(training.heading, sizeof(training.heading), "Next 7 days - %s%s",
                 when, cached ? " (cached)" : "");
        copyDisplayText(workout.title[0] ? workout.title : "Workout",
                        training.title, sizeof(training.title));
    }
    drawHomeSummary(lastHomeTraining, training, ui_layout::homeUpcomingX, ui_layout::homeWorkoutY,
                    ui_layout::homeWorkoutWidth, ui_layout::homeWorkoutHeight, model, force);
}

void systemTelemetry(const app_state::Model& model)
{
    char line[40];
    valueRow("Wi-Fi", model.wifiConnected ? "CONNECTED" : (model.wifiActive ? "CONNECTING" : "OFF"),
             110, model.wifiConnected ? good : warning);
    valueRow("IP", model.wifiConnected ? model.ip : "-", 141,
             model.wifiConnected ? text : muted);
    if (model.wifiConnected) snprintf(line, sizeof(line), "%d dBm", static_cast<int>(model.wifiRssi));
    else snprintf(line, sizeof(line), "-");
    valueRow("RSSI", line, 172, model.wifiConnected ? good : muted);
    snprintf(line, sizeof(line), "%lu KB", static_cast<unsigned long>(model.diagnostics.internalFree / 1024));
    valueRow("Heap free", line, 203);
    snprintf(line, sizeof(line), "%lu KB", static_cast<unsigned long>(model.diagnostics.psramFree / 1024));
    valueRow("PSRAM free", line, 234);
    snprintf(line, sizeof(line), "%llu s", static_cast<unsigned long long>(model.diagnostics.uptimeMs / 1000));
    valueRow("ESP uptime", line, 265);
    const bool streamLive = model.nodeLastUpdate != 0
                         && uint32_t(millis() - model.nodeLastUpdate) < 5000;
    valueRow("Cluster TLS", streamLive ? "LIVE" : "WAITING", 296,
             streamLive ? good : warning);
}

void clusterTelemetry(const app_state::Model& model)
{
    if (model.clusterTelemetry.count == 0)
    {
        label("No controller data", 28, 120, 3, muted);
        return;
    }

    char pageLine[32];
    snprintf(pageLine, sizeof(pageLine), "Nodes %u-%u / %u",
             static_cast<unsigned>(model.clusterTelemetry.pageIndex * secure_protocol::clusterNodeMax + 1),
             static_cast<unsigned>(model.clusterTelemetry.pageIndex * secure_protocol::clusterNodeMax
                                  + model.clusterTelemetry.count),
             static_cast<unsigned>(model.clusterTelemetry.totalNodes));
    label(pageLine, 28, 80, 2, muted);
    const bool streamLive = model.nodeLastUpdate != 0
                         && uint32_t(millis() - model.nodeLastUpdate) < 5000;
    for (size_t index = 0; index < model.clusterTelemetry.count; ++index)
    {
        const secure_protocol::ClusterNode& node = model.clusterTelemetry.nodes[index];
        const bool online = streamLive && node.online;
        const int16_t y = static_cast<int16_t>(109 + index * 91);
        const uint16_t fill = online ? card : 0x2945;
        display().fillRoundRect(20, y, 440, 82, 6, fill);
        display().setTextColor(text, fill);
        display().setTextSize(2);
        char nodeName[secure_protocol::clusterNameMax * 2 + 2];
        copyDisplayText(node.name[0] ? node.name : "node", nodeName, sizeof(nodeName));
        display().drawString(nodeName, 30, y + 8);
        display().setTextColor(online ? good : warning, fill);
        const char* status = online ? "ONLINE" : "OFFLINE";
        display().drawString(status, 450 - display().textWidth(status), y + 8);

        char cpu[16];
        char ram[16];
        char temperature[16];
        if (!online)
        {
            snprintf(cpu, sizeof(cpu), "CPU N/A");
            snprintf(ram, sizeof(ram), "RAM N/A");
            snprintf(temperature, sizeof(temperature), "T N/A");
        }
        else
        {
            snprintf(cpu, sizeof(cpu), "CPU %u.%u%%", node.cpuTenths / 10, node.cpuTenths % 10);
            snprintf(ram, sizeof(ram), "RAM %u.%u%%", node.ramTenths / 10, node.ramTenths % 10);
        }
        if (online && node.temperatureTenths == secure_protocol::temperatureUnavailable)
            snprintf(temperature, sizeof(temperature), "T N/A");
        else if (online)
            snprintf(temperature, sizeof(temperature), "T %d.%dC",
                     node.temperatureTenths / 10, abs(node.temperatureTenths % 10));
        display().setTextColor(online ? text : muted, fill);
        display().setTextSize(2);
        display().drawString(cpu, 30, y + 48);
        display().drawString(ram, 174, y + 48);
        display().drawString(temperature, 450 - display().textWidth(temperature), y + 48);
    }
}

void shortDate(const char* iso, char* output, size_t capacity)
{
    if (iso && strlen(iso) == 10)
        snprintf(output, capacity, "%.2s.%.2s", iso + 8, iso + 5);
    else snprintf(output, capacity, "--.--");
}

bool isTomorrow(const app_state::Model& model, const char* iso)
{
    if (!model.timeValid || !iso || strlen(iso) != 10) return false;
    const time_t now = time(nullptr);
    struct tm local = {};
    if (!localtime_r(&now, &local)) return false;
    local.tm_mday += 1;
    local.tm_hour = 12;
    local.tm_min = 0;
    local.tm_sec = 0;
    if (mktime(&local) == static_cast<time_t>(-1)) return false;
    char tomorrow[11];
    strftime(tomorrow, sizeof(tomorrow), "%Y-%m-%d", &local);
    return strcmp(iso, tomorrow) == 0;
}

void workoutDay(const app_state::Model& model, const secure_protocol::TrainingWorkout& workout,
                char* output, size_t capacity)
{
    if (workout.today) snprintf(output, capacity, "TODAY");
    else if (isTomorrow(model, workout.date)) snprintf(output, capacity, "TOMORROW");
    else shortDate(workout.date, output, capacity);
}

bool weekDate(const app_state::Model& model, uint8_t offset, char* iso, size_t isoCapacity,
              char* caption, size_t captionCapacity)
{
    if (!model.timeValid) return false;
    const time_t now = time(nullptr);
    struct tm local = {};
    if (!localtime_r(&now, &local)) return false;
    local.tm_mday += offset;
    local.tm_hour = 12;
    local.tm_min = 0;
    local.tm_sec = 0;
    if (mktime(&local) == static_cast<time_t>(-1)) return false;
    strftime(iso, isoCapacity, "%Y-%m-%d", &local);
    if (offset == 0) snprintf(caption, captionCapacity, "TODAY");
    else if (offset == 1) snprintf(caption, captionCapacity, "TOMORROW");
    else
    {
        static const char* days[] = {"SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"};
        snprintf(caption, captionCapacity, "%s %02d.%02d", days[local.tm_wday],
                 local.tm_mday, local.tm_mon + 1);
    }
    return true;
}

int trainingForDate(const secure_protocol::TrainingTelemetry& state, const char* iso)
{
    for (size_t index = 0; index < state.count; ++index)
        if (strcmp(state.workouts[index].date, iso) == 0) return static_cast<int>(index);
    return -1;
}

void clippedText(const char* value, int16_t x, int16_t y, int16_t maxWidth)
{
    char clipped[64];
    copyDisplayText(value, clipped, sizeof(clipped));
    size_t length = strlen(clipped);
    while (length > 3 && display().textWidth(clipped) > maxWidth)
    {
        clipped[--length] = 0;
        if (length > 3)
        {
            clipped[length - 1] = '.';
            clipped[length - 2] = '.';
            clipped[length - 3] = '.';
        }
    }
    display().drawString(clipped, x, y);
}

void wrappedText(const char* value, int16_t x, int16_t y, int16_t maxWidth,
                 uint8_t size, uint16_t color, uint16_t fill, uint8_t maxLines)
{
    if (!value || !value[0] || maxLines == 0) return;
    char copy[secure_protocol::trainingDescriptionMax + 1];
    copyDisplayText(value, copy, sizeof(copy));
    char line[secure_protocol::trainingDescriptionMax + 1] = {};
    char* save = nullptr;
    char* word = strtok_r(copy, " ", &save);
    uint8_t lineNumber = 0;
    display().setTextColor(color, fill);
    display().setTextSize(size);
    while (word && lineNumber < maxLines)
    {
        char candidate[sizeof(line)];
        snprintf(candidate, sizeof(candidate), "%s%s%s", line, line[0] ? " " : "", word);
        if (line[0] && display().textWidth(candidate) > maxWidth)
        {
            display().drawString(line, x, y + lineNumber * (size * 9));
            ++lineNumber;
            strncpy(line, word, sizeof(line) - 1);
            line[sizeof(line) - 1] = 0;
        }
        else
        {
            strncpy(line, candidate, sizeof(line) - 1);
            line[sizeof(line) - 1] = 0;
        }
        word = strtok_r(nullptr, " ", &save);
    }
    if (line[0] && lineNumber < maxLines)
        display().drawString(line, x, y + lineNumber * (size * 9));
}

void trainingTelemetry(const app_state::Model& model, bool force = false)
{
    const secure_protocol::TrainingTelemetry& state = model.trainingTelemetry;
    if (!force && trainingDrawn && memcmp(&lastTraining, &state, sizeof(state)) == 0) return;
    lastTraining = state;
    trainingDrawn = true;
    display().fillRoundRect(12, 68, 456, 340, 10, card);
    label("NEXT 7 DAYS", 28, 80, 1, muted);
    if (!state.available)
    {
        label("Not configured", 28, 132, 3, warning);
        label("Configure Garmin on the controller", 28, 180, 2, muted);
        return;
    }

    if (!model.timeValid)
    {
        label("Waiting for date and time", 28, 132, 2, muted);
        return;
    }
    for (uint8_t dayOffset = 0; dayOffset < ui_layout::trainingDayCount; ++dayOffset)
    {
        char iso[11] = {};
        char day[16] = {};
        if (!weekDate(model, dayOffset, iso, sizeof(iso), day, sizeof(day))) continue;
        const int workoutIndex = trainingForDate(state, iso);
        const bool hasWorkout = workoutIndex >= 0;
        const bool pressed = hasWorkout && model.pressedButton == 20 + workoutIndex;
        const int16_t y = static_cast<int16_t>(ui_layout::trainingFirstRowY
                                             + dayOffset * ui_layout::trainingRowStep);
        const uint16_t fill = pressed ? accent : (dayOffset == 0 ? 0x2945 : 0x2104);
        display().fillRoundRect(ui_layout::trainingRowX, y, ui_layout::trainingRowWidth,
                                ui_layout::trainingRowHeight, 6, fill);
        display().setTextColor(pressed ? text : (dayOffset == 0 ? good : accent), fill);
        display().setTextSize(2);
        display().drawString(day, 28, y + 10);
        if (!hasWorkout)
        {
            display().setTextColor(muted, fill);
            display().drawString("Rest / no workout", 166, y + 10);
            continue;
        }

        const secure_protocol::TrainingWorkout& workout = state.workouts[workoutIndex];
        char type[secure_protocol::trainingTypeMax * 2 + 2];
        copyDisplayText(workout.activityType[0] ? workout.activityType : "Workout",
                        type, sizeof(type));
        display().setTextColor(text, fill);
        display().setTextSize(2);
        clippedText(workout.title[0] ? workout.title : "Workout", 166, y + 2, 270);
        char details[48];
        if (workout.distanceTenths && workout.durationMinutes)
            snprintf(details, sizeof(details), "%s  %u min  %u.%u km", type,
                     workout.durationMinutes, workout.distanceTenths / 10,
                     workout.distanceTenths % 10);
        else if (workout.durationMinutes)
            snprintf(details, sizeof(details), "%s  %u min", type, workout.durationMinutes);
        else snprintf(details, sizeof(details), "%s  Scheduled", type);
        display().setTextColor(muted, fill);
        display().setTextSize(1);
        clippedText(details, 166, y + 23, 260);
        display().drawString(">", 444 - display().textWidth(">"), y + 23);
    }
}

void trainingDetail(const app_state::Model& model)
{
    display().fillRoundRect(12, 68, 456, 340, 10, card);
    if (model.selectedTraining >= model.trainingTelemetry.count)
    {
        label("Workout unavailable", 28, 120, 3, warning);
        return;
    }
    const secure_protocol::TrainingWorkout& workout =
        model.trainingTelemetry.workouts[model.selectedTraining];
    char day[12];
    workoutDay(model, workout, day, sizeof(day));
    display().setTextColor(workout.today ? good : accent, card);
    display().setTextSize(2);
    display().drawString(day, 28, 82);
    char type[secure_protocol::trainingTypeMax * 2 + 2];
    copyDisplayText(workout.activityType[0] ? workout.activityType : "Workout",
                    type, sizeof(type));
    display().setTextColor(text, card);
    display().drawString(type, 452 - display().textWidth(type), 82);
    wrappedText(workout.title[0] ? workout.title : "Workout", 28, 116, 424, 3, text, card, 2);

    char details[40];
    if (workout.distanceTenths)
        snprintf(details, sizeof(details), "%u min   %u.%u km", workout.durationMinutes,
                 workout.distanceTenths / 10, workout.distanceTenths % 10);
    else if (workout.durationMinutes)
        snprintf(details, sizeof(details), "%u minutes", workout.durationMinutes);
    else snprintf(details, sizeof(details), "Scheduled workout");
    label(details, 28, 178, 2, muted);
    if (workout.description[0])
    {
        display().drawFastHLine(28, 210, 424, muted);
        label("WORKOUT DETAILS", 28, 226, 1, muted);
        wrappedText(workout.description, 28, 248, 424, 2, text, card, 7);
    }
}

void calendarTelemetry(const app_state::Model& model, bool force = false)
{
    const secure_protocol::CalendarTelemetry& state = model.calendarTelemetry;
    if (!force && calendarDrawn && memcmp(&lastCalendar, &state, sizeof(state)) == 0) return;
    lastCalendar = state;
    calendarDrawn = true;
    display().fillRoundRect(20, 72, 440, 288, 10, card);
    label("Upcoming", 32, 84, 1, muted);
    if (!state.available)
    {
        label("Not configured", 32, 128, 2, warning);
        label("Add an ICS calendar on controller", 32, 166, 1, muted);
        return;
    }
    if (state.count == 0)
    {
        label("No upcoming events", 32, 128, 2, muted);
        return;
    }
    for (size_t index = 0; index < state.count; ++index)
    {
        const secure_protocol::CalendarEvent& event = state.events[index];
        const int16_t y = static_cast<int16_t>(104 + index * 78);
        display().fillRoundRect(28, y, 424, 68, 6, 0x2104);
        char when[24] = "--.-- --:--";
        const time_t starts = static_cast<time_t>(event.startsAt);
        struct tm local = {};
        if (event.startsAt && localtime_r(&starts, &local))
            strftime(when, sizeof(when), event.allDay ? "%d.%m ALL DAY" : "%d.%m %H:%M", &local);
        display().setTextColor(accent, 0x2104);
        display().setTextSize(1);
        display().drawString(when, 38, y + 8);
        display().setTextColor(text, 0x2104);
        display().setTextSize(2);
        char title[secure_protocol::calendarTitleMax * 2 + 2];
        copyDisplayText(event.title[0] ? event.title : "Calendar event", title, sizeof(title));
        display().drawString(title, 38, y + 25);
        if (event.location[0])
        {
            display().setTextColor(muted, 0x2104);
            display().setTextSize(1);
            char location[secure_protocol::calendarLocationMax * 2 + 2];
            copyDisplayText(event.location, location, sizeof(location));
            display().drawString(location, 38, y + 50);
        }
    }
}
}

namespace
{
void garminButtons(const app_state::Model& model)
{
    button(59, "<", 12, 426, 52, model.pressedButton == 59);
    button(60, ">", 72, 426, 52, model.pressedButton == 60);
    button(61, "History", 132, 426, 112, model.pressedButton == 61);
    button(2, "Workouts", 252, 426, 120, model.pressedButton == 2);
    button(5, "Home", 380, 426, 88, model.pressedButton == 5);
}

void activityHistory(const app_state::Model& model, bool force = false)
{
    static uint32_t lastRevision = UINT32_MAX;
    if (!force && lastRevision == model.activityRevision) return;
    lastRevision = model.activityRevision;
    display().fillRect(0, 58, width, 422, background);
    const uint8_t offset = model.activityOffset();
    const uint8_t count = model.activities.count;
    if (!count) label("No completed activities yet", 24, 96);
    for (uint8_t row = 0; row < app_state::activityPageSize && offset + row < count; ++row)
    {
        const auto& activity = model.activities.items[offset + row];
        const int16_t y = ui_layout::activityFirstRowY + row * ui_layout::activityRowStep;
        const uint16_t fill = model.pressedButton == 70 + row ? accent : card;
        display().fillRoundRect(20, y, 440, ui_layout::activityRowHeight, 8, fill);
        display().setTextColor(text, fill);
        display().setTextSize(2);
        clippedText(activity.title, 32, y + 7, 384);
        display().drawString(">", 432, y + 17);
        display().setTextColor(muted, fill);
        display().setTextSize(1);
        clippedText(activity.date, 32, y + 34, 110);
        if (strcmp(activity.kind, "-")) clippedText(activity.kind, 152, y + 34, 260);
    }
    if (offset) button(63, "<", 12, 426, 80, model.pressedButton == 63);
    if (!offset && count > app_state::activityPageSize)
        button(64, ">", 104, 426, 80, model.pressedButton == 64);
    button(62, "Garmin", 196, 426, 152, model.pressedButton == 62);
    button(5, "Home", 360, 426, 108, model.pressedButton == 5);
}

void activityDetail(const app_state::Model& model)
{
    const auto& activity = model.selectedActivity;
    if (!activity.title[0])
    {
        label("No completed activities yet", 24, 96);
        return;
    }
    static const char* labels[] = {"Distance", "Time", "Pace", "Avg HR", "Aerobic TE", "Load"};
    static const char* units[] = {"km", "min", "min/km", "bpm", "", ""};
    display().setTextColor(text, background);
    display().setTextSize(2);
    clippedText(activity.title, 16, 72, 448);
    label(activity.date, 16, 104, 1, muted);
    if (strcmp(activity.kind, "-")) clippedText(activity.kind, 136, 104, 320);
    for (size_t index = 0; index < secure_protocol::activityMetricCount; ++index)
    {
        const int16_t x = 12 + (index % 2) * 234;
        const int16_t y = 126 + (index / 2) * 92;
        display().fillRoundRect(x, y, 222, 82, 8, card);
        display().setTextColor(muted, card);
        display().setTextSize(1);
        display().drawString(labels[index], x + 12, y + 9);
        display().setTextColor(text, card);
        display().setTextSize(2);
        clippedText(activity.values[index], x + 12, y + 28, 198);
        display().setTextColor(muted, card);
        display().setTextSize(1);
        display().drawString(units[index], x + 12, y + 58);
    }
}

void activityDetailButtons(const app_state::Model& model)
{
    if (model.activityFromHome) button(61, "History", 12, 426, 108, model.pressedButton == 61);
    else button(65, "Back", 12, 426, 108, model.pressedButton == 65);
    if (model.selectedActivity.title[0])
    {
        button(67, model.activityView == app_state::ActivityView::Charts ? "Summary" : "Charts",
               128, 426, 108, model.pressedButton == 67);
        button(76, model.activityView == app_state::ActivityView::Laps ? "Summary" : "Laps",
               244, 426, 108, model.pressedButton == 76);
    }
    button(5, "Home", 360, 426, 108, model.pressedButton == 5);
}

void lapNavigation(const app_state::Model& model)
{
    if (model.lapOffset) button(68, "<", 12, 376, 72, model.pressedButton == 68);
    if (model.lapOffset + app_state::lapsPageSize < model.selectedActivity.lapCount)
        button(69, ">", 396, 376, 72, model.pressedButton == 69);
}

void lapTime(uint64_t seconds, char* value, size_t capacity)
{
    if (seconds >= 3600)
        snprintf(value, capacity, "%llu:%02llu:%02llu", static_cast<unsigned long long>(seconds / 3600),
                 static_cast<unsigned long long>(seconds / 60 % 60),
                 static_cast<unsigned long long>(seconds % 60));
    else
        snprintf(value, capacity, "%llu:%02llu", static_cast<unsigned long long>(seconds / 60),
                 static_cast<unsigned long long>(seconds % 60));
}

void activityLaps(const app_state::Model& model)
{
    const auto& activity = model.selectedActivity;
    if (!activity.lapCount)
    {
        label("No laps available yet", 24, 106);
        return;
    }
    static const int16_t columns[] = {24, 66, 169, 266, 382, 458};
    static const char* headings[] = {"#", "Time", "Dist km", "Pace min/km", "HR bpm"};
    for (size_t i = 0; i < 5; ++i) label(headings[i], columns[i], 102, 1, muted);
    for (uint8_t index = model.lapOffset;
         index < activity.lapCount && index < model.lapOffset + app_state::lapsPageSize; ++index)
    {
        const int16_t y = 124 + (index - model.lapOffset) * 40;
        const auto& lap = activity.laps[index];
        char cells[5][20] = {{}, "--", "--", "--", "--"};
        snprintf(cells[0], sizeof(cells[0]), "%u", index + 1);
        if (lap.seconds) lapTime(lap.seconds, cells[1], sizeof(cells[1]));
        if (lap.metres) snprintf(cells[2], sizeof(cells[2]), "%.2f", lap.metres / 1000.0);
        if (lap.seconds && lap.metres)
            lapTime((uint64_t(lap.seconds) * 1000 + lap.metres / 2) / lap.metres,
                    cells[3], sizeof(cells[3]));
        if (lap.heartRate) snprintf(cells[4], sizeof(cells[4]), "%u", lap.heartRate);
        display().fillRoundRect(12, y, 456, 34, 5, card);
        display().setTextColor(text, card);
        display().setTextSize(2);
        for (size_t i = 0; i < 5; ++i)
            clippedText(cells[i], columns[i], y + 8, columns[i + 1] - columns[i] - 5);
    }
    char position[48];
    const unsigned pageEnd = model.lapOffset + app_state::lapsPageSize;
    const unsigned end = pageEnd < activity.lapCount ? pageEnd : activity.lapCount;
    snprintf(position, sizeof(position), "Laps %u-%u of %u", model.lapOffset + 1, end, activity.lapTotal);
    label(position, 161, 392, 1, muted);
    lapNavigation(model);
}

bool chartBounds(const int16_t* samples, size_t count, int16_t& low, int16_t& high)
{
    low = INT16_MAX;
    high = INT16_MIN;
    for (size_t i = 0; i < count; ++i)
    {
        if (samples[i] == INT16_MIN) continue;
        if (samples[i] < low) low = samples[i];
        if (samples[i] > high) high = samples[i];
    }
    return high != INT16_MIN;
}

void drawChart(const int16_t* samples, size_t count, int16_t low, int16_t high,
               int16_t x, int16_t y, int16_t plotWidth, int16_t plotHeight, bool lowerIsHigher = false)
{
    bool previous = false;
    int16_t px = 0, py = 0;
    for (size_t i = 0; i < count; ++i)
    {
        if (samples[i] == INT16_MIN) { previous = false; continue; }
        const int16_t nx = x + static_cast<int16_t>(i * plotWidth / (count - 1));
        const int32_t fromTop = lowerIsHigher ? samples[i] - low : high - samples[i];
        const int16_t ny = y + (high == low ? plotHeight / 2 : fromTop * plotHeight / (high - low));
        if (previous) display().drawLine(px, py, nx, ny, accent);
        display().fillCircle(nx, ny, 1, accent);
        px = nx; py = ny; previous = true;
    }
}

void garminSparkline(const int16_t* history, int16_t x, int16_t y)
{
    int16_t low, high;
    if (chartBounds(history, secure_protocol::garminHistoryMax, low, high))
        drawChart(history, secure_protocol::garminHistoryMax, low, high, x, y, 180, 14);
}

void activityCharts(const app_state::Model& model)
{
    const auto& activity = model.selectedActivity;
    if (!activity.chartsAvailable)
    {
        label("No chart data available yet", 24, 106);
        return;
    }
    static const char* captions[] = {"Heart rate (bpm)", "Pace (min/km)", "Elevation (m)"};
    for (size_t series = 0; series < secure_protocol::activityChartCount; ++series)
    {
        const int16_t y = 68 + series * 110;
        label(captions[series], 24, y, 2);
        int16_t low, high;
        const auto& samples = activity.charts[series];
        if (!chartBounds(samples, secure_protocol::activityChartSamples, low, high))
        {
            label("No measurements", 24, y + 42, 1, muted);
            continue;
        }
        char range[48];
        const bool pace = series == 1;
        if (pace) snprintf(range, sizeof(range), "%d:%02d - %d:%02d", low / 60, low % 60,
                           high / 60, high % 60);
        else snprintf(range, sizeof(range), "%d - %d", low, high);
        label(range, 322, y + 6, 1, muted);
        display().drawFastHLine(24, y + 96, 432, muted);
        drawChart(samples, secure_protocol::activityChartSamples, low, high, 24, y + 30, 431, 60, pace);
    }
    label("Start", 24, 392, 1, muted);
    label("Finish", 420, 392, 1, muted);
}

void garminMetricDetail(const app_state::Model& model)
{
    const auto& metric = model.selectedGarminMetric;
    char current[48];
    snprintf(current, sizeof(current), "%s %s", metric.value, metric.unit);
    label(current, 24, 70, 3);
    int16_t low, high;
    if (!metric.scale || !chartBounds(metric.history, secure_protocol::garminHistoryMax, low, high))
    {
        label("No measurement history", 24, 130, 2, muted);
        return;
    }
    label("Last 7 days", 24, 110, 1, muted);
    display().drawFastHLine(24, 214, 432, muted);
    drawChart(metric.history, secure_protocol::garminHistoryMax, low, high, 24, 130, 431, 77);
    label("Recent measurements", 24, 229, 1, muted);
    int16_t y = 251;
    for (int day = secure_protocol::garminHistoryMax - 1; day >= 0; --day)
    {
        if (metric.history[day] == INT16_MIN) continue;
        char when[24] = {};
        if (model.garminMetricHistoryEnd > secure_protocol::garminHistoryMax)
        {
            const time_t timestamp = (static_cast<int64_t>(model.garminMetricHistoryEnd)
                - (secure_protocol::garminHistoryMax - 1 - day)) * 86400;
            struct tm utc = {};
            if (gmtime_r(&timestamp, &utc)) strftime(when, sizeof(when), "%d.%m", &utc);
        }
        else snprintf(when, sizeof(when), "%u days ago",
                      static_cast<unsigned>(secure_protocol::garminHistoryMax - 1 - day));
        const int64_t tenths = static_cast<int64_t>(metric.history[day]) * metric.scale;
        char value[40];
        snprintf(value, sizeof(value), metric.scale == 1 && tenths % 10 ? "%.1f %s" : "%.0f %s",
                 tenths / 10.0, metric.unit);
        label(when, 24, y, 1, muted);
        label(value, 132, y - 3, 2);
        y += 23;
    }
}

void garminMetricButtons(const app_state::Model& model)
{
    button(62, "Back", 12, 426, 180, model.pressedButton == 62);
    button(5, "Home", 288, 426, 180, model.pressedButton == 5);
}

void garminTelemetry(const app_state::Model& model, bool force = false)
{
    const auto& state = model.garminTelemetry;
    const uint8_t page = state.count ? model.selectedGarmin % state.count : 0;
    const time_t now = time(nullptr);
    const uint32_t age = model.timeValid && state.updatedAt && now >= state.updatedAt
        ? static_cast<uint32_t>(now - state.updatedAt) / 60 : UINT32_MAX;
    if (!force && garminDrawn && page == lastGarminPage && age == lastGarminAge
        && lastGarminConnected == model.garminConnected
        && memcmp(&lastGarmin, &state, sizeof(state)) == 0) return;
    garminDrawn = true; lastGarminPage = page; lastGarminAge = age;
    lastGarminConnected = model.garminConnected; lastGarmin = state;
    display().fillRect(0, 58, width, 360, background);
    const char* statuses[] = {"Configure Garmin on the Pi", "Synced", "Cached data - sync delayed",
        "Renew Garmin key on the Pi", "Garmin unavailable"};
    char status[72];
    if (!model.garminConnected) snprintf(status, sizeof(status), "Controller disconnected - cached data");
    else if (state.status == 1 && age != UINT32_MAX)
        snprintf(status, sizeof(status), "Synced %lu min ago - charts: last 7 days", (unsigned long)age);
    else snprintf(status, sizeof(status), "%s", statuses[state.status <= 4 ? state.status : 4]);
    label(status, 16, 68, 1, state.status == 1 ? muted : warning);
    if (!state.count)
    {
        label("No Garmin measurements yet", 28, 150, 2, muted);
        label("Configure Garmin in the terminal menu.", 28, 190, 1, muted);
        label("Upcoming workouts use the calendar feed.", 28, 214, 1, muted);
        return;
    }
    const auto& group = state.groups[page];
    char heading[48];
    snprintf(heading, sizeof(heading), "%s  %u/%u", group.title, page + 1, state.count);
    label(heading, 16, 92, 2);
    for (uint8_t index = 0; index < group.count; ++index)
    {
        const auto& metric = group.metrics[index];
        const int16_t x = ui_layout::garminMetricX(index);
        const int16_t y = ui_layout::garminMetricY(index);
        display().fillRoundRect(x, y, ui_layout::garminMetricWidth, ui_layout::garminMetricHeight, 8, card);
        display().setTextColor(muted, card); display().setTextSize(1);
        display().drawString(metric.label, x + 12, y + 8);
        display().drawString(">", x + ui_layout::garminMetricWidth - 16, y + 8);
        display().setTextColor(text, card);
        display().setTextSize(strlen(metric.value) > 10 ? 2 : 3);
        display().drawString(metric.value[0] ? metric.value : "--", x + 12, y + 23);
        display().setTextSize(1); display().setTextColor(muted, card);
        display().drawString(metric.unit, x + 12, y + 50);
        garminSparkline(metric.history, x + 14, y + 67);
    }
}

void spotifyLine(const char* value, int16_t y, uint16_t color = text)
{
    char line[200];
    copyDisplayText(value, line, sizeof(line));
    display().setTextSize(2);
    size_t length = strlen(line);
    while (length && display().textWidth(line) > 428) line[--length] = 0;
    label(line, 26, y, 2, color);
}

void spotifyProgress(uint32_t elapsed, uint32_t duration)
{
    char progress[32];
    snprintf(progress, sizeof(progress), "%lu:%02lu / %lu:%02lu",
             static_cast<unsigned long>(elapsed / 60), static_cast<unsigned long>(elapsed % 60),
             static_cast<unsigned long>(duration / 60), static_cast<unsigned long>(duration % 60));
    label(progress, 26, 274, 2, muted);
}

void spotifyTelemetry(const app_state::Model& model, bool force = false)
{
    const auto& state = model.spotifyTelemetry;
    const bool hasPlayback = model.spotifyConnected && (state.status == 1 || state.status == 2);
    const bool showProgress = hasPlayback && state.durationMs > 0;
    const uint32_t elapsed = state.progressMs / 1000;
    const uint32_t duration = state.durationMs / 1000;
    if (!force && spotifyDrawn && lastSpotifyConnected == model.spotifyConnected)
    {
        const uint32_t previousElapsed = lastSpotify.progressMs / 1000;
        lastSpotify.progressMs = state.progressMs;
        if (memcmp(&lastSpotify, &state, sizeof(state)) == 0)
        {
            if (showProgress && elapsed != previousElapsed)
            {
                display().fillRect(26, 274, 428, 20, background);
                spotifyProgress(elapsed, duration);
            }
            return;
        }
    }
    spotifyDrawn = true;
    lastSpotify = state;
    lastSpotifyConnected = model.spotifyConnected;
    display().fillRect(12, 68, 456, 340, background);
    const char* statuses[] = {"Not connected to Spotify", "Playing", "Paused",
        "Start Spotify on a device", "Reconnect Spotify on the Pi",
        "Spotify access denied", "Spotify request limit; waiting", "Spotify unavailable"};
    spotifyLine(model.spotifyConnected ? (state.capabilities & 8 ? "Updating playback..."
                                      : statuses[state.status <= 7 ? state.status : 7])
                                      : "Controller disconnected", 88, good);
    if (hasPlayback)
    {
        spotifyLine(state.title[0] ? state.title : "Track info unavailable", 144);
        spotifyLine(state.artist, 184, muted);
        spotifyLine(state.device, 230, muted);
        if (showProgress) spotifyProgress(elapsed, duration);
    }
    else if (model.spotifyConnected && (state.status == 0 || state.status == 4))
    {
        label("Run configure-spotify.py on the Pi", 26, 160, 2, muted);
        label("Approve access in your browser", 26, 200, 2, muted);
    }
    const uint8_t flags = model.spotifyConnected && !(state.capabilities & 8) ? state.capabilities : 0;
    button(55, "Previous", 20, 324, 132, model.pressedButton == 55,
           card, flags & 4 ? good : muted, flags & 4 ? text : muted);
    button(56, state.status == 1 ? "Pause" : "Play", 174, 324, 132, model.pressedButton == 56,
           card, flags & 1 ? good : muted, flags & 1 ? text : muted);
    button(57, "Next", 328, 324, 132, model.pressedButton == 57,
           card, flags & 2 ? good : muted, flags & 2 ? text : muted);
}
}

void ui::begin(const app_state::Model& model) { page(model); }

void ui::showSystemUpdate()
{
    display().fillScreen(TFT_BLACK);
    display().setFont(&fonts::Font0);
    display().setTextColor(TFT_WHITE, TFT_BLACK);

    const char* title = "SYSTEM UPDATE";
    display().setTextSize(3);
    display().drawString(title, (width - display().textWidth(title)) / 2, 168);

    const char* message = "Updating firmware...";
    display().setTextSize(2);
    display().drawString(message, (width - display().textWidth(message)) / 2, 222);

    const char* warning = "Do not power off";
    display().setTextSize(2);
    display().drawString(warning, (width - display().textWidth(warning)) / 2, 268);
}

void ui::alarmFlash(bool lit, const app_state::Model& model)
{
    const uint16_t alarmColor = model.nightMode ? nightRed : text;
    if (model.alarmMethod == 1)
    {
        display().fillRect(20, 78, 440, 96, homeBackground);
        if (!lit) return;
        display().setFont(&fonts::Font0);
        display().setTextColor(alarmColor, homeBackground);
        display().setTextSize(11);
        display().drawString(model.clockText,
                             (width - display().textWidth(model.clockText)) / 2, 86);
        return;
    }
    const uint16_t fill = lit ? alarmColor : TFT_BLACK;
    display().fillScreen(fill);
    if (!lit) return;
    display().setFont(&fonts::Font0);
    display().setTextColor(TFT_BLACK, fill);
    display().setTextSize(4);
    const char* message = "STOP PLAYING";
    display().drawString(message, (width - display().textWidth(message)) / 2, 178);
    display().setTextSize(3);
    display().drawString(model.clockText, (width - display().textWidth(model.clockText)) / 2, 242);
}

void ui::page(const app_state::Model& model)
{
    display().fillScreen((model.page == app_state::Page::Home || model.page == app_state::Page::Menu)
                        ? homeBackground : background);
    if (model.page == app_state::Page::Garmin)
    {
        header("Garmin");
        garminTelemetry(model, true);
        garminButtons(model);
    }
    else if (model.page == app_state::Page::ActivityHistory)
    {
        header("Activity history");
        activityHistory(model, true);
    }
    else if (model.page == app_state::Page::ActivityDetail)
    {
        header(model.activityView == app_state::ActivityView::Laps ? "Laps / intervals" : "Activity");
        if (model.activityView == app_state::ActivityView::Laps) activityLaps(model);
        else if (model.activityView == app_state::ActivityView::Charts) activityCharts(model);
        else activityDetail(model);
        activityDetailButtons(model);
    }
    else if (model.page == app_state::Page::GarminMetricDetail)
    {
        header(model.selectedGarminMetric.label);
        garminMetricDetail(model);
        garminMetricButtons(model);
    }
    else if (model.page == app_state::Page::Spotify)
    {
        header("Spotify");
        spotifyTelemetry(model, true);
        button(5, "Home", ui_layout::singleButtonX, ui_layout::singleButtonY,
               ui_layout::singleButtonWidth, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::Home)
    {
        homeClock(model, true);
        homeAlarm(model);
        homeSummaries(model, true);
        homeNavigation(model);
    }
    else if (model.page == app_state::Page::Menu)
    {
        header("Menu", homeBackground, model.nightMode ? nightRed : text);
        display().setTextSize(1);
        display().setTextColor(model.nightMode ? nightRed : muted, homeBackground);
        display().drawString("Choose a page", 200, 80);
        display().drawString("Swipe down for clock", 180, 414);
        menuButtons(model);
    }
    else if (model.page == app_state::Page::AlarmNumber)
    {
        header(model.alarmEditingHour ? "Set hour" : "Set minute");
        label(model.alarmEditingHour ? "Enter hour (0-23)" : "Enter minute (0-59)",
              100, 80, 2, muted);
        ui::alarmInput(model);
    }
    else if (model.page == app_state::Page::System)
    {
        header("System");
        display().fillRoundRect(12, 68, 456, 340, 10, card);
        label("ESP32 and connection diagnostics", 32, 84, 1, muted);
        systemTelemetry(model);
        brightnessSlider(model);
        nightModeButton(model);
        button(5, "Home", ui_layout::rightButtonX, ui_layout::systemButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::Alarm)
    {
        alarmSettings(model);
    }
    else if (model.page == app_state::Page::Cluster)
    {
        header("Cluster");
        display().fillRoundRect(12, 68, 456, 340, 10, card);
        clusterTelemetry(model);
        button(5, "Home", ui_layout::singleButtonX, ui_layout::singleButtonY,
               ui_layout::singleButtonWidth, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::Training)
    {
        header("Training");
        trainingTelemetry(model, true);
        button(5, "Home", ui_layout::singleButtonX, ui_layout::singleButtonY,
               ui_layout::singleButtonWidth, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::TrainingDetail)
    {
        header("Workout");
        trainingDetail(model);
        button(10, "Back", ui_layout::leftButtonX, ui_layout::systemButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 10);
        button(5, "Home", ui_layout::rightButtonX, ui_layout::systemButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::Calendar)
    {
        header("Calendar");
        calendarTelemetry(model, true);
        button(5, "Home", ui_layout::singleButtonX, ui_layout::singleButtonY,
               ui_layout::singleButtonWidth, model.pressedButton == 5);
    }
}

void ui::telemetry(const app_state::Model& model)
{
    if (model.page == app_state::Page::Garmin) { garminTelemetry(model); return; }
    if (model.page == app_state::Page::ActivityHistory) { activityHistory(model); return; }
    if (model.page == app_state::Page::Spotify) { spotifyTelemetry(model); return; }
    if (model.page == app_state::Page::System)
    {
        systemTelemetry(model);
        return;
    }
    if (model.page == app_state::Page::Cluster)
    {
        clusterTelemetry(model);
        return;
    }
    if (model.page == app_state::Page::Home)
    {
        homeClock(model);
        homeSummaries(model);
        return;
    }
    if (model.page == app_state::Page::Training)
    {
        trainingTelemetry(model);
        return;
    }
    if (model.page == app_state::Page::Calendar)
    {
        calendarTelemetry(model);
        return;
    }
}
void ui::pressed(const app_state::Model& model)
{
    if (model.page == app_state::Page::Garmin)
    {
        garminButtons(model);
    }
    else if (model.page == app_state::Page::ActivityHistory) activityHistory(model, true);
    else if (model.page == app_state::Page::ActivityDetail)
    {
        activityDetailButtons(model);
        if (model.activityView == app_state::ActivityView::Laps) lapNavigation(model);
    }
    else if (model.page == app_state::Page::GarminMetricDetail) garminMetricButtons(model);
    else if (model.page == app_state::Page::Spotify)
    {
        spotifyTelemetry(model, true);
        button(5, "Home", ui_layout::singleButtonX, ui_layout::singleButtonY,
               ui_layout::singleButtonWidth, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::Home)
    {
        homeAlarm(model);
        homeSummaries(model);
        homeNavigation(model);
    }
    else if (model.page == app_state::Page::Menu)
    {
        menuButtons(model);
    }
    else if (model.page == app_state::Page::System)
    {
        brightnessSlider(model);
        nightModeButton(model);
        button(5, "Home", ui_layout::rightButtonX, ui_layout::systemButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::Alarm)
    {
        alarmSettings(model, false);
    }
    else if (model.page == app_state::Page::AlarmNumber) alarmNumberKeys(model);
    else if (model.page == app_state::Page::Training)
    {
        trainingTelemetry(model, true);
        button(5, "Home", ui_layout::singleButtonX, ui_layout::singleButtonY,
               ui_layout::singleButtonWidth, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::TrainingDetail)
    {
        button(10, "Back", ui_layout::leftButtonX, ui_layout::systemButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 10);
        button(5, "Home", ui_layout::rightButtonX, ui_layout::systemButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 5);
    }
    else button(5, "Home", ui_layout::singleButtonX, ui_layout::singleButtonY,
                ui_layout::singleButtonWidth, model.pressedButton == 5);
}

void ui::brightness(const app_state::Model& model)
{
    brightnessSlider(model);
}

void ui::alarmInput(const app_state::Model& model)
{
    char digits[3] = "__";
    if (model.alarmInput.length == 1) digits[0] = '0' + model.alarmInput.value;
    else if (model.alarmInput.length == 2)
    {
        digits[0] = '0' + model.alarmInput.value / 10;
        digits[1] = '0' + model.alarmInput.value % 10;
    }
    display().fillRect(164, 108, 152, 60, card);
    display().setFont(&fonts::Font0);
    display().setTextSize(7);
    display().setTextColor(text, card);
    display().drawString(digits, (width - display().textWidth(digits)) / 2, 110);
    display().fillRect(12, 172, 456, 20, background);
    if (model.alarmInput.error)
        label(model.alarmEditingHour ? "Enter 0-23; delete or clear to correct"
                                    : "Enter 0-59; delete or clear to correct", 28, 176, 1, warning);
    alarmNumberKeys(model);
}
