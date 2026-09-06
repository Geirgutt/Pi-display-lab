#include "console.h"
#include "diagnostics.h"
#include "hardware.h"
#include "network.h"
#include "ble_test.h"
#include "secure_transport.h"

namespace
{
// Fixed, bounded command buffer. No String allocations or read timeouts.
char line[112];
size_t length = 0;
bool overflow = false;
uint32_t lastByte = 0;

void clear()
{
    volatile char* p = line;
    for (size_t i = 0; i < sizeof(line); ++i) p[i] = 0;
    length = 0;
    overflow = false;
}

void execute()
{
    if (!strcmp(line, "d")) diagnostics::print(Serial);
    else if (!strcmp(line, "0")) hardware::setBacklight(false);
    else if (!strcmp(line, "1")) hardware::setBacklight(true);
    else if (!strcmp(line, "?")) console::help();
#if DESKDISPLAY_BLE
    else if (!strcmp(line, "ble start")) ble_test::start();
    else if (!strcmp(line, "ble stop")) ble_test::stop();
    else if (!strcmp(line, "ble status")) ble_test::printStatus();
#endif
#if DESKDISPLAY_WIFI
    else if (!strcmp(line, "w")) Serial.println(network::startStored() ? "Wi-Fi requested; use s for status." : "Wi-Fi start failed or no stored credentials.");
    else if (!strcmp(line, "s")) network::printStatus(Serial);
    else if (!strcmp(line, "x")) Serial.println(network::stop() ? "Wi-Fi stopped." : "Wi-Fi stop failed.");
    else if (!strcmp(line, "forget")) Serial.println(network::forget() ? "Station credentials erased; Wi-Fi stopped." : "Erase/stop failed.");
    else if (!strncmp(line, "wifi ", 5))
    {
        char* separator = strchr(line + 5, '\t');
        if (!separator) { Serial.println("Expected wifi SSID<TAB>PASSWORD"); return; }
        *separator = 0;
        Serial.println(network::configureAndStart(line + 5, separator + 1)
            ? "Credentials configured; connection requested. Use s for status."
            : "Configuration failed (SSID 1-32 bytes, WPA password 8-63 bytes).");
    }
#endif
#if DESKDISPLAY_SECURE && DESKDISPLAY_WIFI
    else if (!strcmp(line, "secure start")) Serial.println(secure_transport::start() ? "Secure transport requested." : "Secure start failed; configure key and peer first.");
    else if (!strcmp(line, "secure stop")) { secure_transport::stop(); Serial.println("Secure transport stopped."); }
    else if (!strcmp(line, "secure status")) secure_transport::printStatus(Serial);
    else if (!strncmp(line, "secure key ", 11)) Serial.println(secure_transport::setKeyHex(line + 11) ? "Secure PSK stored." : "Invalid PSK; expected exactly 64 hexadecimal characters.");
    else if (!strncmp(line, "secure peer ", 12))
    {
        char* separator = strchr(line + 12, ' ');
        if (!separator) { Serial.println("Expected secure peer IPv4 PORT"); return; }
        *separator = 0;
        const long port = strtol(separator + 1, nullptr, 10);
        Serial.println(port > 0 && port <= 65535 && secure_transport::setPeer(line + 12, static_cast<uint16_t>(port))
            ? "Secure peer stored." : "Invalid secure peer.");
    }
#endif
    else if (length) Serial.println("Unknown command; use ?");
}
}

void console::help()
{
    Serial.println("Commands (Enter to submit): d=diagnostics, 0/1=backlight off/on, ?=help");
#if DESKDISPLAY_WIFI
    Serial.println("Wi-Fi: w=start stored, s=status/IP/RSSI, x=stop, forget=erase station credentials");
    Serial.println("Set credentials: wifi SSID<TAB>PASSWORD (literal tab, no quotes; not echoed)");
#else
#if DESKDISPLAY_BLE
    Serial.println("Wi-Fi excluded from this build.");
#else
    Serial.println("Wi-Fi excluded from this build; BLE unused.");
#endif
#endif
#if DESKDISPLAY_BLE
    Serial.println("BLE: ble start, ble stop, ble status (inactive at boot; d=resources)");
#endif
#if DESKDISPLAY_SECURE && DESKDISPLAY_WIFI
    Serial.println("Secure: secure key <64 hex>, secure peer IPv4 PORT, secure start, secure stop, secure status");
#endif
}

void console::service()
{
    // Expire incomplete commands; never execute a truncated credential line.
    if ((length || overflow) && uint32_t(millis() - lastByte) >= 30000) clear();
    for (unsigned budget = 0; budget < 32 && Serial.available(); ++budget)
    {
        const char c = Serial.read();
        lastByte = millis();
        if (c == '\r' || c == '\n')
        {
            if (overflow) Serial.println("Command rejected: too long or invalid byte.");
            else execute();
            clear();
        }
        else if (!overflow)
        {
            if (c == '\0' || length == sizeof(line) - 1) overflow = true;
            else { line[length++] = c; line[length] = 0; }
        }
    }
}
