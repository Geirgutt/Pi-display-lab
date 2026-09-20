#include "ui.h"
#include "hardware.h"
#include <LovyanGFX.hpp>

namespace
{
constexpr int16_t width = 480;
constexpr int16_t headerHeight = 58;
constexpr int16_t buttonHeight = 54;
constexpr uint16_t background = 0x1082;
constexpr uint16_t card = 0x18E3;
constexpr uint16_t accent = 0x05BF;
constexpr uint16_t good = 0x05E8;
constexpr uint16_t warning = 0xFD20;
constexpr uint16_t text = TFT_WHITE;
constexpr uint16_t muted = 0xBDF7;

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

void button(uint8_t id, const char* caption, int16_t x, int16_t y, bool active)
{
    const uint16_t fill = active ? accent : card;
    display().fillRoundRect(x, y, 190, buttonHeight, 8, fill);
    display().drawRoundRect(x, y, 190, buttonHeight, 8, muted);
    display().setTextColor(text, fill);
    display().setTextSize(2);
    const int16_t textX = x + (190 - display().textWidth(caption)) / 2;
    display().drawString(caption, textX, y + 17);
    (void)id;
}

void brightnessButton(const app_state::Model& model)
{
    char caption[20];
    snprintf(caption, sizeof(caption), "Bright %u%%", model.brightnessPercent);
    button(6, caption, 35, 390, model.pressedButton == 6);
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

void homeClock(const app_state::Model& model)
{
    display().fillRoundRect(20, 72, 440, 204, 10, card);
    display().fillRect(28, 88, 424, 138, card);
    display().setTextColor(model.timeValid ? text : muted, card);
    display().setTextSize(7);
    display().drawString(model.clockText,
                         (width - display().textWidth(model.clockText)) / 2, 96);
    display().setTextSize(2);
    display().drawString(model.dateText,
                         (width - display().textWidth(model.dateText)) / 2, 190);

    char status[48];
    if (model.clusterTelemetry.totalNodes > 0)
        snprintf(status, sizeof(status), "Cluster: %u nodes",
                 static_cast<unsigned>(model.clusterTelemetry.totalNodes));
    else snprintf(status, sizeof(status), "Cluster: waiting for data");
    display().fillRect(28, 234, 424, 28, card);
    display().setTextColor(model.clusterTelemetry.totalNodes > 0 ? good : warning, card);
    display().setTextSize(1);
    display().drawString(status, (width - display().textWidth(status)) / 2, 242);
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
        label("No controller data", 32, 120, 2, muted);
        return;
    }

    char pageLine[32];
    snprintf(pageLine, sizeof(pageLine), "Nodes %u-%u / %u",
             static_cast<unsigned>(model.clusterTelemetry.pageIndex * secure_protocol::clusterNodeMax + 1),
             static_cast<unsigned>(model.clusterTelemetry.pageIndex * secure_protocol::clusterNodeMax
                                  + model.clusterTelemetry.count),
             static_cast<unsigned>(model.clusterTelemetry.totalNodes));
    label(pageLine, 32, 83, 1, muted);
    for (size_t index = 0; index < model.clusterTelemetry.count; ++index)
    {
        const secure_protocol::ClusterNode& node = model.clusterTelemetry.nodes[index];
        const int16_t y = static_cast<int16_t>(101 + index * 77);
        const uint16_t fill = node.online ? card : 0x2945;
        display().fillRoundRect(28, y, 424, 66, 6, fill);
        display().setTextColor(text, fill);
        display().setTextSize(2);
        display().drawString(node.name[0] ? node.name : "node", 38, y + 8);
        display().setTextColor(node.online ? good : warning, fill);
        display().drawString(node.online ? "ONLINE" : "OFFLINE", 330, y + 8);

        char line[64];
        if (node.temperatureTenths == secure_protocol::temperatureUnavailable)
        {
            snprintf(line, sizeof(line), "CPU %u.%u%%   RAM %u.%u%%   T N/A",
                     node.cpuTenths / 10, node.cpuTenths % 10,
                     node.ramTenths / 10, node.ramTenths % 10);
        }
        else
        {
            snprintf(line, sizeof(line), "CPU %u.%u%%   RAM %u.%u%%   T %d.%dC",
                     node.cpuTenths / 10, node.cpuTenths % 10,
                     node.ramTenths / 10, node.ramTenths % 10,
                     node.temperatureTenths / 10, abs(node.temperatureTenths % 10));
        }
        display().setTextColor(node.online ? text : muted, fill);
        display().setTextSize(1);
        display().drawString(line, 38, y + 39);
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
        homeClock(model);
        button(1, "Cluster", 35, 300, model.pressedButton == 1);
        button(2, "Training", 255, 300, model.pressedButton == 2);
        button(3, "Calendar", 35, 374, model.pressedButton == 3);
        button(4, "System", 255, 374, model.pressedButton == 4);
    }
    else if (model.page == app_state::Page::System)
    {
        header("System");
        display().fillRoundRect(20, 72, 440, 292, 10, card);
        label("ESP32 and connection diagnostics", 32, 84, 1, muted);
        systemTelemetry(model);
        brightnessButton(model);
        button(5, "Home", 255, 390, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::Cluster)
    {
        header("Cluster");
        display().fillRoundRect(20, 72, 440, 270, 10, card);
        clusterTelemetry(model);
        button(5, "Home", 145, 400, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::Training)
    {
        header("Training");
        display().fillRoundRect(20, 72, 440, 270, 10, card);
        label("Server-side training state", 32, 84, 2, muted);
        valueRow("Status", "PLACEHOLDER", 120, warning);
        valueRow("Source", "WEB PROVIDER", 151, muted);
        label("Live training data will arrive with", 32, 204, 1, muted);
        label("a future compact DeskDisplay transport.", 32, 220, 1, muted);
        label("No Garmin login or scraping runs here.", 32, 252, 1, muted);
        button(5, "Home", 145, 400, model.pressedButton == 5);
    }
    else if (model.page == app_state::Page::Calendar)
    {
        header("Calendar");
        display().fillRoundRect(20, 72, 440, 288, 10, card);
        label("Upcoming events", 32, 84, 2, muted);
        valueRow("Status", "PLACEHOLDER", 120, warning);
        valueRow("Source", "NOT CONNECTED", 151, muted);
        label("Calendar data will be supplied by", 32, 204, 1, muted);
        label("the controller, not stored here.", 32, 220, 1, muted);
        button(5, "Home", 145, 400, model.pressedButton == 5);
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
}
void ui::pressed(const app_state::Model& model)
{
    if (model.page == app_state::Page::Home)
    {
        button(1, "Cluster", 35, 300, model.pressedButton == 1);
        button(2, "Training", 255, 300, model.pressedButton == 2);
        button(3, "Calendar", 35, 374, model.pressedButton == 3);
        button(4, "System", 255, 374, model.pressedButton == 4);
    }
    else if (model.page == app_state::Page::System)
    {
        brightnessButton(model);
        button(5, "Home", 255, 390, model.pressedButton == 5);
    }
    else button(5, "Home", 145, 400, model.pressedButton == 5);
}

void ui::brightness(const app_state::Model& model)
{
    brightnessButton(model);
}
