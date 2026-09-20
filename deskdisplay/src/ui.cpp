#include "ui.h"
#include "hardware.h"
#include "ui_layout.h"
#include <LovyanGFX.hpp>
#include <time.h>

namespace
{
constexpr int16_t width = ui_layout::screenWidth;
constexpr int16_t headerHeight = 58;
constexpr uint16_t background = 0x1082;
constexpr uint16_t card = 0x18E3;
constexpr uint16_t accent = 0x05BF;
constexpr uint16_t good = 0x05E8;
constexpr uint16_t warning = 0xFD20;
constexpr uint16_t text = TFT_WHITE;
constexpr uint16_t muted = 0xBDF7;
char lastClockText[6] = {};
char lastDateText[16] = {};
uint16_t lastHomeNodeCount = UINT16_MAX;
bool lastHomeTimeValid = false;
secure_protocol::TrainingTelemetry lastTraining{};
secure_protocol::CalendarTelemetry lastCalendar{};
bool trainingDrawn = false;
bool calendarDrawn = false;

LGFX& display() { return hardware::display(); }

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
            bool active)
{
    const uint16_t fill = active ? accent : card;
    display().fillRoundRect(x, y, buttonWidth, ui_layout::buttonHeight, 8, fill);
    display().drawRoundRect(x, y, buttonWidth, ui_layout::buttonHeight, 8, muted);
    display().setTextColor(text, fill);
    display().setTextSize(2);
    const int16_t textX = x + (buttonWidth - display().textWidth(caption)) / 2;
    display().drawString(caption, textX, y + 11);
    (void)id;
}

void brightnessButton(const app_state::Model& model)
{
    char caption[20];
    snprintf(caption, sizeof(caption), "Bright %u%%", model.brightnessPercent);
    button(6, caption, ui_layout::leftButtonX, ui_layout::systemButtonY,
           ui_layout::pairedButtonWidth, model.pressedButton == 6);
}

void header(const char* title)
{
    display().fillRect(0, 0, width, headerHeight, 0x0841);
    display().setTextColor(text, 0x0841);
    display().setTextSize(3);
    display().drawString("DeskDisplay", 24, 12);
    display().setTextSize(2);
    display().drawString(title, width - 24 - display().textWidth(title), 19);
}

void homeClock(const app_state::Model& model, bool force = false)
{
    if (force || strcmp(lastClockText, model.clockText) != 0)
    {
        // Clock digits have a stable width. Drawing with an opaque background
        // replaces the old glyphs without flashing the whole card every second.
        if (!force && lastHomeTimeValid != model.timeValid)
            display().fillRect(20, 78, 440, 96, card);
        display().setTextColor(model.timeValid ? text : muted, card);
        display().setTextSize(10);
        display().drawString(model.clockText,
                             (width - display().textWidth(model.clockText)) / 2, 86);
        strncpy(lastClockText, model.clockText, sizeof(lastClockText));
        lastClockText[sizeof(lastClockText) - 1] = 0;
        lastHomeTimeValid = model.timeValid;
    }
    if (force || strcmp(lastDateText, model.dateText) != 0)
    {
        if (!force) display().fillRect(20, 181, 440, 40, card);
        display().setTextColor(model.timeValid ? text : muted, card);
        display().setTextSize(4);
        display().drawString(model.dateText,
                             (width - display().textWidth(model.dateText)) / 2, 185);
        strncpy(lastDateText, model.dateText, sizeof(lastDateText));
        lastDateText[sizeof(lastDateText) - 1] = 0;
    }

    if (force || lastHomeNodeCount != model.clusterTelemetry.totalNodes)
    {
        char status[48];
        if (model.clusterTelemetry.totalNodes > 0)
            snprintf(status, sizeof(status), "Cluster: %u nodes",
                     static_cast<unsigned>(model.clusterTelemetry.totalNodes));
        else snprintf(status, sizeof(status), "Cluster: waiting for data");
        display().fillRect(20, 245, 440, 42, card);
        display().setTextColor(model.clusterTelemetry.totalNodes > 0 ? good : warning, card);
        display().setTextSize(model.clusterTelemetry.totalNodes > 0 ? 3 : 2);
        display().drawString(status, (width - display().textWidth(status)) / 2,
                             model.clusterTelemetry.totalNodes > 0 ? 250 : 255);
        lastHomeNodeCount = model.clusterTelemetry.totalNodes;
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
    for (size_t index = 0; index < model.clusterTelemetry.count; ++index)
    {
        const secure_protocol::ClusterNode& node = model.clusterTelemetry.nodes[index];
        const int16_t y = static_cast<int16_t>(109 + index * 91);
        const uint16_t fill = node.online ? card : 0x2945;
        display().fillRoundRect(20, y, 440, 82, 6, fill);
        display().setTextColor(text, fill);
        display().setTextSize(2);
        display().drawString(node.name[0] ? node.name : "node", 30, y + 8);
        display().setTextColor(node.online ? good : warning, fill);
        const char* status = node.online ? "ONLINE" : "OFFLINE";
        display().drawString(status, 450 - display().textWidth(status), y + 8);

        char cpu[16];
        char ram[16];
        char temperature[16];
        snprintf(cpu, sizeof(cpu), "CPU %u.%u%%", node.cpuTenths / 10, node.cpuTenths % 10);
        snprintf(ram, sizeof(ram), "RAM %u.%u%%", node.ramTenths / 10, node.ramTenths % 10);
        if (node.temperatureTenths == secure_protocol::temperatureUnavailable)
            snprintf(temperature, sizeof(temperature), "T N/A");
        else
            snprintf(temperature, sizeof(temperature), "T %d.%dC",
                     node.temperatureTenths / 10, abs(node.temperatureTenths % 10));
        display().setTextColor(node.online ? text : muted, fill);
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

void wrappedText(const char* value, int16_t x, int16_t y, int16_t maxWidth,
                 uint8_t size, uint16_t color, uint16_t fill, uint8_t maxLines)
{
    if (!value || !value[0] || maxLines == 0) return;
    char copy[secure_protocol::trainingDescriptionMax + 1];
    strncpy(copy, value, sizeof(copy) - 1);
    copy[sizeof(copy) - 1] = 0;
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
    label("Garmin training", 28, 80, 2, muted);
    if (!state.available)
    {
        label("Not configured", 28, 132, 3, warning);
        label("Configure Garmin on the controller", 28, 180, 2, muted);
        return;
    }

    if (state.count == 0)
        label("No scheduled workouts", 28, 132, 3, muted);
    for (size_t index = 0; index < state.count && index < 3; ++index)
    {
        const secure_protocol::TrainingWorkout& workout = state.workouts[index];
        const int16_t y = static_cast<int16_t>(ui_layout::trainingFirstRowY
                                             + index * ui_layout::trainingRowStep);
        const bool pressed = model.pressedButton == 7 + index;
        const uint16_t fill = pressed ? accent : 0x2104;
        display().fillRoundRect(ui_layout::trainingRowX, y, ui_layout::trainingRowWidth,
                                ui_layout::trainingRowHeight, 6, fill);
        char day[12];
        workoutDay(model, workout, day, sizeof(day));
        display().setTextColor(pressed ? text : (workout.today ? good : accent), fill);
        display().setTextSize(2);
        display().drawString(day, 28, y + 8);
        const char* type = workout.activityType[0] ? workout.activityType : "Workout";
        display().setTextColor(text, fill);
        display().drawString(type, 452 - display().textWidth(type), y + 8);
        display().drawString(workout.title[0] ? workout.title : "Workout", 28, y + 34);
        char details[32];
        if (workout.distanceTenths)
            snprintf(details, sizeof(details), "%u min  %u.%u km", workout.durationMinutes,
                     workout.distanceTenths / 10, workout.distanceTenths % 10);
        else if (workout.durationMinutes)
            snprintf(details, sizeof(details), "%u min", workout.durationMinutes);
        else snprintf(details, sizeof(details), "Scheduled");
        display().setTextColor(muted, fill);
        display().setTextSize(2);
        display().drawString(details, 28, y + 59);
        display().drawString(">", 444 - display().textWidth(">"), y + 59);
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
    const char* type = workout.activityType[0] ? workout.activityType : "Workout";
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
        display().drawString(event.title[0] ? event.title : "Calendar event", 38, y + 25);
        if (event.location[0])
        {
            display().setTextColor(muted, 0x2104);
            display().setTextSize(1);
            display().drawString(event.location, 38, y + 50);
        }
    }
}
}

void ui::begin(const app_state::Model& model) { page(model); }

void ui::page(const app_state::Model& model)
{
    display().fillScreen(background);
    if (model.page == app_state::Page::Home)
    {
        header("Home");
        display().fillRoundRect(12, 68, 456, 272, 10, card);
        homeClock(model, true);
        button(1, "Cluster", ui_layout::leftButtonX, ui_layout::homeTopButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 1);
        button(2, "Training", ui_layout::rightButtonX, ui_layout::homeTopButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 2);
        button(3, "Calendar", ui_layout::leftButtonX, ui_layout::homeBottomButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 3);
        button(4, "System", ui_layout::rightButtonX, ui_layout::homeBottomButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 4);
    }
    else if (model.page == app_state::Page::System)
    {
        header("System");
        display().fillRoundRect(12, 68, 456, 340, 10, card);
        label("ESP32 and connection diagnostics", 32, 84, 1, muted);
        systemTelemetry(model);
        brightnessButton(model);
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
        button(1, "Cluster", ui_layout::leftButtonX, ui_layout::homeTopButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 1);
        button(2, "Training", ui_layout::rightButtonX, ui_layout::homeTopButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 2);
        button(3, "Calendar", ui_layout::leftButtonX, ui_layout::homeBottomButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 3);
        button(4, "System", ui_layout::rightButtonX, ui_layout::homeBottomButtonY,
               ui_layout::pairedButtonWidth, model.pressedButton == 4);
    }
    else if (model.page == app_state::Page::System)
    {
        brightnessButton(model);
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
    brightnessButton(model);
}
