#include "ble_test.h"
#if DESKDISPLAY_BLE
#include <Arduino.h>
#include <atomic>
#include <esp_bt.h>
#include <esp_bt_main.h>
#include <esp_gap_ble_api.h>

// Explicitly retain controller memory before setup, independent of weak core
// defaults. The installed S3 default also returns true. Optional BLE builds only;
// this hook starts nothing and does not change the normal builds' behavior.
extern "C" bool btInUse() { return true; }

namespace
{
enum class State { off, configuring, starting, advertising, stopping, error };
State state = State::off;
// One GAP operation in flight. No queue allocation or printing in the callback.
std::atomic<int> completion{-1};
uint32_t requestedAt = 0;

// Flags: general discoverable, BR/EDR unsupported; complete local name.
uint8_t advertisement[] = {2, 0x01, 0x06, 12, 0x09,
    'D', 'e', 's', 'k', 'D', 'i', 's', 'p', 'l', 'a', 'y'};

bool check(esp_err_t result, const char* operation)
{
    if (result == ESP_OK) return true;
    Serial.printf("BLE %s failed: %s (0x%x); use ble stop\n",
                  operation, esp_err_to_name(result), static_cast<unsigned>(result));
    state = State::error;
    return false;
}

void gapEvent(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t* param)
{
    switch (event)
    {
    case ESP_GAP_BLE_ADV_DATA_RAW_SET_COMPLETE_EVT:
        completion.store((static_cast<int>(State::configuring) << 8) | param->adv_data_raw_cmpl.status); break;
    case ESP_GAP_BLE_ADV_START_COMPLETE_EVT:
        completion.store((static_cast<int>(State::starting) << 8) | param->adv_start_cmpl.status); break;
    case ESP_GAP_BLE_ADV_STOP_COMPLETE_EVT:
        completion.store((static_cast<int>(State::stopping) << 8) | param->adv_stop_cmpl.status); break;
    default: break;
    }
}

void pending(State next)
{
    completion.store(-1);
    requestedAt = millis();
    state = next;
}

void shutdown()
{
    // Also handles partially successful initialization. Never irreversibly
    // release BT memory: a subsequent explicit start must remain possible.
    if (esp_bluedroid_get_status() == ESP_BLUEDROID_STATUS_ENABLED &&
        !check(esp_bluedroid_disable(), "host disable")) return;
    if (esp_bluedroid_get_status() == ESP_BLUEDROID_STATUS_INITIALIZED &&
        !check(esp_bluedroid_deinit(), "host deinit")) return;
    if (esp_bt_controller_get_status() == ESP_BT_CONTROLLER_STATUS_ENABLED &&
        !check(esp_bt_controller_disable(), "controller disable")) return;
    if (esp_bt_controller_get_status() == ESP_BT_CONTROLLER_STATUS_INITED &&
        !check(esp_bt_controller_deinit(), "controller deinit")) return;
    completion.store(-1);
    state = State::off;
    Serial.println("BLE off; host/controller deinitialized. Use d for resources.");
}
}

void ble_test::start()
{
    if (state != State::off) { printStatus(); return; }
    // Arduino has already initialized NVS. Keep framework controller defaults.
    esp_bt_controller_config_t cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    if (!check(esp_bt_controller_init(&cfg), "controller init") ||
        !check(esp_bt_controller_enable(ESP_BT_MODE_BLE), "controller enable") ||
        !check(esp_bluedroid_init(), "host init") ||
        !check(esp_bluedroid_enable(), "host enable") ||
        !check(esp_ble_gap_register_callback(gapEvent), "GAP callback")) return;
    pending(State::configuring);
    if (!check(esp_ble_gap_config_adv_data_raw(advertisement, sizeof(advertisement)),
               "advertisement data")) return;
    Serial.println("BLE start requested; use ble status for completion.");
}

void ble_test::stop()
{
    if (state == State::off) { printStatus(); return; }
    if (state == State::configuring || state == State::starting || state == State::stopping)
    {
        Serial.println("BLE operation pending; retry ble stop after completion.");
        return;
    }
    if (state == State::error && esp_bluedroid_get_status() != ESP_BLUEDROID_STATUS_ENABLED)
    {
        // Recovery disables the host/controller even when GAP completion failed.
        shutdown();
        return;
    }
    pending(State::stopping);
    if (!check(esp_ble_gap_stop_advertising(), "advertising stop")) shutdown();
}

void ble_test::service()
{
    if (state != State::configuring && state != State::starting && state != State::stopping) return;
    const int result = completion.exchange(-1);
    if (result < 0)
    {
        if (uint32_t(millis() - requestedAt) >= 5000)
        {
            if (state == State::stopping)
            {
                Serial.println("BLE stop completion timeout; attempting stack shutdown.");
                shutdown();
                return;
            }
            state = State::error;
            Serial.println("BLE GAP completion timeout; use ble stop to clean up.");
        }
        return;
    }
    // Ignore a late event belonging to a different operation.
    if ((result >> 8) != static_cast<int>(state)) return;
    const int status = result & 0xff;
    if (status != ESP_BT_STATUS_SUCCESS)
    {
        if (state == State::stopping)
        {
            Serial.printf("BLE advertising stop status=%d; attempting stack shutdown.\n", status);
            shutdown();
            return;
        }
        state = State::error;
        Serial.printf("BLE GAP failed: status=%d; use ble stop\n", status);
        return;
    }
    if (state == State::configuring)
    {
        static esp_ble_adv_params_t params = {};
        params.adv_int_min = 0x320; // 500 ms, in BLE-defined 0.625 ms units.
        params.adv_int_max = 0x320;
        params.adv_type = ADV_TYPE_NONCONN_IND;
        params.own_addr_type = BLE_ADDR_TYPE_PUBLIC;
        params.channel_map = ADV_CHNL_ALL;
        params.adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY;
        pending(State::starting);
        check(esp_ble_gap_start_advertising(&params), "advertising start");
    }
    else if (state == State::starting)
    {
        state = State::advertising;
        Serial.println("BLE advertising: DeskDisplay (non-connectable). Use d for resources.");
    }
    else shutdown();
}

void ble_test::printStatus()
{
    static const char* const names[] = {"off", "configuring", "starting", "advertising", "stopping", "error"};
    Serial.printf("BLE state=%s; controller=%d host=%d; system tasks=%u\n", names[static_cast<unsigned>(state)],
                  static_cast<int>(esp_bt_controller_get_status()),
                  static_cast<int>(esp_bluedroid_get_status()),
                  static_cast<unsigned>(uxTaskGetNumberOfTasks()));
}
#endif
