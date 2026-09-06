#include <Arduino.h>
#include "app.h"

void setup()
{
    Serial.begin(115200);
    delay(2000);

    app::begin();
}

void loop()
{
    app::service();
}
