#include <Arduino.h>
#include "hardware.h"
#include "diagnostics.h"
#include "touch.h"
#include "console.h"
#include "network.h"
#include "ble_test.h"

void setup()
{
    Serial.begin(115200);
    delay(2000);

    Serial.println("=== Pi Display Lab ===");
    console::help();
    diagnostics::print(Serial);

    // Keep the backlight dark until the framebuffer contains the test image.
    Serial.println("Initializing display...");
    if (!hardware::beginDisplay())
    {
        Serial.println("Display initialization failed.");
        return;
    }

    auto& display_instance = hardware::display();
    display_instance.fillScreen(TFT_BLACK);
    display_instance.setTextColor(TFT_WHITE, TFT_BLACK);
    display_instance.setTextSize(2);
    display_instance.drawString("Pi Display Lab", 40, 190);
    display_instance.drawString("Hallo Milana!", 40, 230);

    hardware::setBacklight(true);
    Serial.println("Display initialized.");
    diagnostics::print(Serial);
    Serial.println(touch::begin() ? "Touch initialized (raw coordinates)." : "Touch initialization failed; display remains available.");
    diagnostics::print(Serial);
}

void loop()
{
    static bool pressed = false;
    static touch::Point previous = {-1, -1};
    touch::Point point;
    const bool down = touch::read(point);
    if (down && (!pressed || point.x != previous.x || point.y != previous.y))
    {
        Serial.printf("Touch %s raw x=%d y=%d\n", pressed ? "move" : "down", point.x, point.y);
        previous = point;
    }
    if (!down && pressed) Serial.println("Touch up");
    pressed = down;

    console::service();
#if DESKDISPLAY_BLE
    ble_test::service();
#endif
#if DESKDISPLAY_WIFI
    network::service();
#endif
    // Board references expose no IRQ. 50 Hz polling, yielding the Arduino task;
    // no extra task, framebuffer redraw, or periodic diagnostics output.
    delay(20);
}
