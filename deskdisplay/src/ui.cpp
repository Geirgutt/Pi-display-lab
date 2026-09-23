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
           homeBackground, model.nightMode ? nightOutline : homeButtonOutline,
           model.nightMode ? nightRed : text, model.nightMode ? nightPressed : accent);
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
        display().fillRect(20, 272, 440, 42, homeBackground);
        const uint16_t statusColor = model.nightMode ? nightRed
            : (streamLive && model.clusterTelemetry.onlineNodes
               == model.clusterTelemetry.totalNodes ? good : warning);
        display().setTextColor(statusColor, homeBackground);
        display().setTextSize(streamLive && model.clusterTelemetry.totalNodes > 0 ? 3 : 2);
        display().setFont(&fonts::Font0);
        display().drawString(status, (width - display().textWidth(status)) / 2,
                             streamLive && model.clusterTelemetry.totalNodes > 0 ? 278 : 283);
        lastHomeNodeCount = model.clusterTelemetry.totalNodes;
        lastHomeOnlineCount = model.clusterTelemetry.onlineNodes;
        lastHomeStreamLive = streamLive;
    }
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
    display().drawFastHLine(28, 210, 424, muted);
    label("WORKOUT DETAILS", 28, 226, 1, muted);
    if (workout.description[0])
        wrappedText(workout.description, 28, 248, 424, 2, text, card, 7);
    else
    {
        label("Garmin did not include the workout", 28, 254, 2, muted);
        label("steps in the published calendar.", 28, 280, 2, muted);
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

void ui::page(const app_state::Model& model)
{
    display().fillScreen(model.page == app_state::Page::Home ? homeBackground : background);
    if (model.page == app_state::Page::Home)
    {
        homeClock(model, true);
        homeButton(1, "Cluster", ui_layout::leftButtonX, ui_layout::homeTopButtonY, model);
        homeButton(2, "Training", ui_layout::rightButtonX, ui_layout::homeTopButtonY, model);
        homeButton(3, "Calendar", ui_layout::leftButtonX, ui_layout::homeBottomButtonY, model);
        homeButton(4, "System", ui_layout::rightButtonX, ui_layout::homeBottomButtonY, model);
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
    if (model.page == app_state::Page::Home)
    {
        homeButton(1, "Cluster", ui_layout::leftButtonX, ui_layout::homeTopButtonY, model);
        homeButton(2, "Training", ui_layout::rightButtonX, ui_layout::homeTopButtonY, model);
        homeButton(3, "Calendar", ui_layout::leftButtonX, ui_layout::homeBottomButtonY, model);
        homeButton(4, "System", ui_layout::rightButtonX, ui_layout::homeBottomButtonY, model);
    }
    else if (model.page == app_state::Page::System)
    {
        brightnessSlider(model);
        nightModeButton(model);
        button(5, "Home", ui_layout::rightButtonX, ui_layout::systemButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 5);
    }
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
