#include <Arduino.h>
#include "display.h"

LGFX display_instance;

namespace
{
constexpr uint8_t BACKLIGHT_PIN = 38;
}

void setup()
{
    Serial.begin(115200);
    delay(2000);

    Serial.println("=== Pi Display Lab ===");

    // Keep the backlight dark until the framebuffer contains the test image.
    pinMode(BACKLIGHT_PIN, OUTPUT);
    digitalWrite(BACKLIGHT_PIN, LOW);

    Serial.println("Initializing display...");
    if (!display_instance.init())
    {
        Serial.println("Display initialization failed.");
        return;
    }

    display_instance.fillScreen(TFT_BLACK);
    display_instance.setTextColor(TFT_WHITE, TFT_BLACK);
    display_instance.setTextSize(2);
    display_instance.drawString("Pi Display Lab", 40, 190);
    display_instance.drawString("Hallo Milana!", 40, 230);

    digitalWrite(BACKLIGHT_PIN, HIGH);
    Serial.println("Display initialized.");
}

void loop()
{
    Serial.println("--- Status ---");

    Serial.printf(
        "Flash: %u MB\n",
        ESP.getFlashChipSize() / 1024 / 1024
    );

    Serial.printf(
        "PSRAM: %.2f MB\n",
        ESP.getPsramSize() / 1024.0 / 1024.0
    );

    Serial.printf(
        "Ledig PSRAM: %u bytes\n",
        ESP.getFreePsram()
    );

    Serial.println();
    delay(3000);
}
