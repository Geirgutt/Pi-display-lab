#include "ui.h"
#include "hardware.h"
#include <LovyanGFX.hpp>

namespace
{
constexpr int16_t width = 480;
constexpr int16_t height = 480;
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

void header(const char* title)
{
    display().fillRect(0, 0, width, headerHeight, 0x0841);
    display().setTextColor(text, 0x0841);
    display().setTextSize(3);
    display().drawString("DeskDisplay", 24, 12);
    display().setTextSize(2);
    display().drawString(title, 340, 19);
}
}

void ui::begin(const app_state::Model& model) { page(model); }

void ui::page(const app_state::Model& model)
{
    display().fillScreen(background);
    if (model.page == app_state::Page::Dashboard)
    {
        header("Dashboard");
        display().fillRoundRect(20, 72, 440, 228, 10, card);
        label("Live platform status", 32, 82, 2, muted);
        telemetry(model);
        button(1, "Wi-Fi", 35, 325, model.pressedButton == 1);
        button(2, "System", 255, 325, model.pressedButton == 2);
        button(3, "Backlight", 35, 397, model.pressedButton == 3);
        button(4, "Touch Test", 255, 397, model.pressedButton == 4);
    }
    else if (model.page == app_state::Page::System)
    {
        header("System");
        display().fillRoundRect(20, 72, 440, 270, 10, card);
        label("Diagnostics", 32, 84, 2, muted);
        char line[32];
        snprintf(line, sizeof(line), "%lu bytes", static_cast<unsigned long>(model.diagnostics.internalFree));
        valueRow("Heap free", line, 120);
        snprintf(line, sizeof(line), "%lu bytes", static_cast<unsigned long>(model.diagnostics.internalLargest));
        valueRow("Largest", line, 151);
        snprintf(line, sizeof(line), "%lu bytes", static_cast<unsigned long>(model.diagnostics.psramFree));
        valueRow("PSRAM free", line, 182);
        snprintf(line, sizeof(line), "%llu s", static_cast<unsigned long long>(model.diagnostics.uptimeMs / 1000));
        valueRow("Uptime", line, 213);
        label("Serial `d` still prints the full report.", 32, 285, 1, muted);
        button(5, "Back", 145, 380, model.pressedButton == 5);
    }
    else
    {
        header("Touch Test");
        display().fillRoundRect(20, 72, 440, 245, 10, card);
        label("Primary contact", 32, 84, 2, muted);
        touch(model);
        label("Raw coordinates are shown without calibration changes.", 32, 274, 1, muted);
        button(6, "Back", 145, 380, model.pressedButton == 6);
    }
}

void ui::telemetry(const app_state::Model& model)
{
    char line[40];
    if (model.page == app_state::Page::System)
    {
        snprintf(line, sizeof(line), "%lu bytes", static_cast<unsigned long>(model.diagnostics.internalFree));
        valueRow("Heap free", line, 120);
        snprintf(line, sizeof(line), "%lu bytes", static_cast<unsigned long>(model.diagnostics.internalLargest));
        valueRow("Largest", line, 151);
        snprintf(line, sizeof(line), "%lu bytes", static_cast<unsigned long>(model.diagnostics.psramFree));
        valueRow("PSRAM free", line, 182);
        snprintf(line, sizeof(line), "%llu s", static_cast<unsigned long long>(model.diagnostics.uptimeMs / 1000));
        valueRow("Uptime", line, 213);
        return;
    }
    if (model.wifiConnected)
    {
        snprintf(line, sizeof(line), "CONNECTED  %s", model.ip);
        valueRow("Wi-Fi", line, 116, good);
        snprintf(line, sizeof(line), "%d dBm", static_cast<int>(model.wifiRssi));
        valueRow("RSSI", line, 147, good);
    }
    else
    {
        valueRow("Wi-Fi", model.wifiActive ? "CONNECTING" : "OFF", 116, model.wifiActive ? warning : muted);
        valueRow("IP", "-", 147, muted);
    }
    snprintf(line, sizeof(line), "%lu KB", static_cast<unsigned long>(model.diagnostics.internalFree / 1024));
    valueRow("Heap", line, 178);
    snprintf(line, sizeof(line), "%lu KB", static_cast<unsigned long>(model.diagnostics.psramFree / 1024));
    valueRow("PSRAM", line, 209);
    snprintf(line, sizeof(line), "%llu s", static_cast<unsigned long long>(model.diagnostics.uptimeMs / 1000));
    valueRow("Uptime", line, 240);
}

void ui::touch(const app_state::Model& model)
{
    char line[32];
    display().fillRect(32, 120, 416, 116, card);
    if (model.touchDown)
    {
        snprintf(line, sizeof(line), "raw x=%d y=%d", model.touchX, model.touchY);
        display().setTextColor(text, card);
        display().setTextSize(2);
        display().drawString(line, 42, 130);
        const int16_t markerX = 52 + (model.touchX * 376) / 480;
        const int16_t markerY = 174 + (model.touchY * 48) / 480;
        display().drawRect(52, 174, 376, 48, muted);
        display().fillCircle(markerX, markerY, 7, accent);
    }
    else label("Touch the screen", 128, 164, 2, muted);
}
void ui::pressed(const app_state::Model& model)
{
    if (model.page == app_state::Page::Dashboard)
    {
        button(1, "Wi-Fi", 35, 325, model.pressedButton == 1);
        button(2, "System", 255, 325, model.pressedButton == 2);
        button(3, "Backlight", 35, 397, model.pressedButton == 3);
        button(4, "Touch Test", 255, 397, model.pressedButton == 4);
    }
    else button(model.pressedButton, "Back", 145, 380, model.pressedButton != 0);
}
