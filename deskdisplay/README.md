# DeskDisplay

Small firmware foundation for the Guition ESP32-S3-4848S040.
The physically verified display baseline is commit `b7cf625`.
The current foundation changes still require hardware testing.

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
