#pragma once
#include <stdint.h>

#ifndef DESKDISPLAY_WIFI
#define DESKDISPLAY_WIFI 0
#endif

#if DESKDISPLAY_WIFI
#include <WiFi.h>

namespace network
{
struct Info
{
    bool active;
    bool connected;
    uint8_t status;
    int32_t rssi;
    char ip[16];
};

// Call from the Arduino loop task only. No credentials retained by this module.
bool startStored();
bool configureAndStart(const char* ssid, const char* password);
bool stop();
bool forget(); // Clears native station credentials, then stops the radio.
void service();
bool enabled();
// Native WiFi.status(), WiFi.localIP(), WiFi.RSSI() remain the application API.
void printStatus(Print& out);
void info(Info& value);
}
#else
namespace network
{
struct Info { bool active = false; bool connected = false; uint8_t status = 0; int32_t rssi = 0; char ip[16] = "-"; };
inline void info(Info& value) { value = Info{}; }
}
#endif
