# DeskDisplay

Small firmware foundation for the Guition ESP32-S3-4848S040.
The original physically verified display baseline is commit `b7cf625`.
On 2026-09-06, the user confirmed the foundation at `3b09aac`: display,
backlight, GT911 touch, orientation, drag/release, and short-test heap/PSRAM
stability. Subsequent tests verified Wi-Fi connection, stored credentials,
explicit reconnect after reboot, and display/touch operation with active Wi-Fi.
AP-outage recovery and repeated stop/start testing remain pending. BLE is
intentionally disabled. See the measured results in the foundation report.

Build the default display/touch/diagnostics firmware:

```sh
pio run -e guition-4848s040
```

Optional Wi-Fi build (radio remains off until requested over serial):

```sh
pio run -e guition-4848s040-wifi
```

See [foundation and hardware tests](docs/foundation.md) and the
[pre-change resource baseline](docs/baseline.md). No web server, LVGL, OTA,
dashboard engine, telemetry protocol or BLE service is included.

Optional advertising-only [BLE and Wi-Fi + BLE test builds](docs/ble-test.md)
have been physically tested: BLE discovery and repeated start/stop, plus basic
Wi-Fi coexistence including BLE-first startup. Normal default/Wi-Fi builds keep
BLE inactive and exclude the test implementation. See the
[Wi-Fi shutdown investigation](docs/wifi-shutdown-investigation.md) for the late
timer log and retained first-use memory findings.
