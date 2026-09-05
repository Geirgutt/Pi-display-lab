#pragma once

#ifndef DESKDISPLAY_WIFI
#define DESKDISPLAY_WIFI 0
#endif

#if DESKDISPLAY_WIFI
#include <WiFi.h>

namespace network
{
// Call from the Arduino loop task only. No credentials retained by this module.
bool startStored();
bool configureAndStart(const char* ssid, const char* password);
bool stop();
bool forget(); // Clears native station credentials, then stops the radio.
void service();
bool enabled();
// Native WiFi.status(), WiFi.localIP(), WiFi.RSSI() remain the application API.
void printStatus(Print& out);
}
#endif
