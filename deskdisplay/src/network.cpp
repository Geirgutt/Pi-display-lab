#include "network.h"
#if DESKDISPLAY_WIFI
#include <esp_wifi.h>

namespace
{
bool active = false;
uint32_t lastCheck = 0;
uint32_t lastAttempt = 0;
constexpr uint32_t retryMs = 30000;

bool prepare()
{
    // Use the framework's NVS station config; no duplicate credential store.
    WiFi.persistent(true);
    // This core retries only selected reasons automatically. One bounded retry
    // policy also handles absent APs/bad credentials without an event callback.
    WiFi.setAutoReconnect(false);
    return WiFi.mode(WIFI_STA);
}

bool connectConfigured()
{
    wifi_config_t cfg = {};
    const bool configured = esp_wifi_get_config(WIFI_IF_STA, &cfg) == ESP_OK
                         && cfg.sta.ssid[0] != 0;
    // Do not leave a second password copy on our stack.
    volatile uint8_t* p = reinterpret_cast<volatile uint8_t*>(&cfg);
    for (size_t i = 0; i < sizeof(cfg); ++i) p[i] = 0;
    if (!configured) { network::stop(); return false; }
    active = true;
    lastCheck = lastAttempt = millis();
    // A synchronous start error is retried by service(); never wait for DHCP.
    WiFi.begin();
    return true;
}
}

bool network::startStored()
{
    if (active) return true;
    if (!prepare()) { stop(); return false; }
    return connectConfigured();
}

bool network::configureAndStart(const char* ssid, const char* password)
{
    if (!ssid || !password) return false;
    const size_t ssidLen = strlen(ssid), passLen = strlen(password);
    if (ssidLen == 0 || ssidLen > 32 || passLen < 8 || passLen > 63) return false;
    if (!stop()) return false;
    if (!prepare()) { stop(); return false; }
    // Let Arduino validate/copy/store the configuration, without connecting yet.
    if (WiFi.begin(ssid, password, 0, nullptr, false) == WL_CONNECT_FAILED)
    {
        stop();
        return false;
    }
    return connectConfigured();
}

bool network::stop()
{
    active = false; // Prevent retries even if driver shutdown reports an error.
    return WiFi.mode(WIFI_OFF);
}

bool network::forget()
{
    if (!prepare()) { stop(); return false; }
    wifi_config_t empty = {};
    const bool erased = esp_wifi_set_config(WIFI_IF_STA, &empty) == ESP_OK;
    const bool stopped = stop();
    return erased && stopped;
}

void network::service()
{
    if (!active) return;
    const uint32_t now = millis();
    if (uint32_t(now - lastCheck) < 1000) return;
    lastCheck = now;
    if (WiFi.status() == WL_CONNECTED) { lastAttempt = now; return; }
    if (uint32_t(now - lastAttempt) < retryMs) return;
    lastAttempt = now;
    WiFi.reconnect();
}

bool network::enabled() { return active; }

void network::printStatus(Print& out)
{
    if (!active) { out.println("Wi-Fi disabled."); return; }
    out.printf("Wi-Fi status=%d (wl_status_t)", static_cast<int>(WiFi.status()));
    if (WiFi.status() == WL_CONNECTED)
    {
        const IPAddress ip = WiFi.localIP();
        out.printf(" IP=%u.%u.%u.%u RSSI=%d dBm", ip[0], ip[1], ip[2], ip[3], WiFi.RSSI());
    }
    out.println();
}
#endif
