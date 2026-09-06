# Optional BLE physical test — 2026-09-06

Status: user physically verified BLE discovery/start/stop, five stable BLE-only
cycles, and basic Wi-Fi + BLE coexistence including BLE-first startup. Codex has
not uploaded or committed this BLE milestone. See the
[shutdown investigation and measured results](wifi-shutdown-investigation.md).
Verified foundation before this work: `d86ced5`, documenting unchanged firmware
from `3b09aac`. Display, backlight, touch, initial Wi-Fi connection and stored
reconnect evidence remains in [foundation.md](foundation.md).

## Implementation and inspected source

The installed framework is Arduino-ESP32 2.0.17
(`3.20017.241212+sha.dcc1105b`), espressif32 7.1.0, LovyanGFX 1.2.28.
Inspected actual installed files under `~/.platformio/packages/framework-arduinoespressif32`:

- `libraries/BLE/src/BLEDevice.{h,cpp}` and `BLEAdvertising.h`: native Arduino
  wrapper lifecycle, error handling and GATT dependencies.
- `cores/esp32/esp32-hal-bt.c` and `esp32-hal-misc.c`: S3 startup memory hook.
- `tools/sdk/esp32s3/include/bt/host/bluedroid/api/include/api/esp_gap_ble_api.h`
  and `esp_bt_main.h`: GAP event and host APIs.
- `tools/sdk/esp32s3/include/bt/include/esp32c3/include/esp_bt.h`: the controller
  header actually bundled for this S3 SDK; defaults/status/lifecycle APIs.
- `tools/sdk/esp32s3/qio_opi/include/sdkconfig.h` and
  `tools/sdk/esp32s3/include/esp_system/include/esp_task.h`: stack configuration.

`ble_test.*` uses the bundled ESP-IDF Bluedroid/GAP APIs directly. This is the
framework-native BLE stack, with no third-party dependency, custom radio driver,
GATT server/client, service, characteristic, pairing setup or application protocol.
The C++ BLEDevice wrapper initializes GATT callbacks and includes client/server
machinery; direct GAP allows an advertising-only test with checked return values.
No alternative lightweight BLE host was installed in project libdeps.

Controller initialization uses the installed SDK defaults and `ESP_BT_MODE_BLE`.
The raw advertisement is 16 bytes: BLE discoverability flags and the complete
name **DeskDisplay**. It is non-connectable, with a nominal 500 ms interval on all
advertising channels. The name is in the primary advertisement; no scan response
or local GATT name service is needed. Classic Bluetooth is not enabled.

The Arduino loop owns lifecycle state. A native GAP callback posts a tagged
completion/status through one atomic integer; it performs no serial output or
display access. `service()` consumes completions without an additional task or
timer. Advertising configuration/start/stop has a five-second completion timeout.
Native stack init/deinit calls execute synchronously on explicit commands and can
briefly delay touch servicing; there is no application busy-wait for discovery.

`ble stop` normally waits for advertising-stop completion, then disables and
deinitializes host and controller. It does not irreversibly release controller
memory, allowing an explicit restart to be tested. Partial initialization errors
can be cleaned up with `ble stop`. Stop errors/timeouts attempt stack shutdown;
native shutdown failures leave an error state instead of claiming success.
Repeated start while active and stop while off are harmless status queries.
During an operation, another start is ignored and stop asks for a retry after
completion. Stack reinitialization and memory recovery still require hardware tests.

The BLE-only strong `btInUse()` hook returns true to explicitly retain controller
memory before setup. **Correction to earlier foundation notes:** disassembly shows
the installed S3 core's weak hook also returns true in the normal builds; it does
not release controller memory there. Neither normal build initializes BLE.
The existing normal-build behavior is unchanged. See the native
[controller lifecycle and irreversible memory-release documentation](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32s3/api-reference/bluetooth/controller_vhci.html).

## Build measurements

Before edits, the default and Wi-Fi builds were rebuilt and matched their recorded
baseline. After implementation, all four variants passed without compiler warnings.

| Environment suffix | Flash bytes | Static RAM bytes | Flash delta | RAM delta | Compared with |
|---|---:|---:|---:|---:|---|
| default (`guition-4848s040`) | 369145 | 20588 | 0 | 0 | pre-BLE default |
| `-wifi` | 784241 | 45100 | 0 | 0 | pre-BLE Wi-Fi |
| `-ble` | 956021 | 46108 | +586876 | +25520 | default |
| `-wifi-ble` | 1324549 | 65980 | +540308 | +20880 | Wi-Fi |

These are PlatformIO flash/static data-BSS measurements, not total runtime internal
memory. The compiled host/controller bring significant code and static costs even
before radio startup. No extra framebuffer or application task was added.
Application storage is a 16-byte advertisement, small parameter/state objects,
one atomic completion slot and constant messages. Stack-owned buffers are separate.

Native resources expected after startup from installed configuration:

- BLE controller task: default stack 4096 bytes (3584 + 512).
- Bluedroid BTC task: configured stack 3072 bytes.
- Bluedroid BTU task: configured stack 4352 bytes.
- Host/controller queues, timers, synchronization and protocol buffers; exact
  allocations and auxiliary task behavior must be measured on the device.
- No application scan service, connections, GATT service or periodic BLE polling
  task. GAP events are handled by the native stack; the loop checks a completion
  slot only during an operation. Radio advertising continues autonomously.

Stop calls the native disable/deinit APIs to tear down stack tasks/resources.
Static/reserved memory is retained; do not assume free heap returns exactly to
pre-start levels or to the smaller normal build. `ble status` includes the total
system task count (not a list of BLE task names). Compare it before, during and
after BLE; Wi-Fi in the combined build also creates tasks/resources.

The original measurement worksheet is retained below. Numeric combined-build
results and BLE-only stability observations are now recorded in the linked
investigation; blank phases still need exact readings:

| Phase (record separately for BLE-only and combined) | Internal free/minimum/largest | PSRAM total/free/used | System tasks |
|---|---|---|---|
| Boot, radios inactive | pending | pending | pending |
| Wi-Fi connected, BLE inactive (combined only) | pending | pending | pending |
| BLE advertising | pending | pending | pending |
| BLE off after deinit | pending | pending | pending |
| After repeated start/stop cycles | pending | pending | pending |

Use `d` for memory and `ble status` for task/state readings at each phase. Record
PSRAM totals exactly as reported, since the existing diagnostics showed small
total variations in prior tests. Minimum heap is a historical low-water mark and
is not expected to recover after stop. Record free and largest blocks too.

## Physical test procedure

Codex did not open serial or flash the device. Commands below are for the user.

1. Build and upload BLE-only using your established workflow:

   ```sh
   pio run -e guition-4848s040-ble -t upload
   pio device monitor -e guition-4848s040-ble
   ```

2. At 115200 baud, send **each command followed by Enter**:

   ```text
   ble status
   d
   ```

   Expect `state=off; controller=0 host=0`, plus task count. Display, touch,
   orientation, drag/release and `0`/`1` backlight commands should behave as before.
   A fresh BLE scan should receive no DeskDisplay advertisement from this device.

3. Send `ble start`. Wait for
   `BLE advertising: DeskDisplay (non-connectable). Use d for resources.`
   Then send `ble status` and `d`. Expect state `advertising`, controller=2,
   host=2. Save heap/PSRAM and task readings.

4. Use a phone/PC **BLE advertisement scanner**, with filters disabled, and find
   `DeskDisplay`. Ordinary OS pairing settings may hide non-connectable devices.
   Confirm fresh advertisement timestamps/RSSI; cached names alone are not proof.
   Do not try to pair/connect: this test intentionally accepts no connections.
   Drag on the display while scanning and check for artifacts/stuck touch.

5. Send `ble stop`. Wait for
   `BLE off; host/controller deinitialized. Use d for resources.`
   Send `ble status` and `d` immediately and again after 10 seconds. Expect off,
   controller=0, host=0 and no fresh received advertisements. Clear scanner history
   or restart scanning to avoid mistaking a cached entry for ongoing advertising.

6. Repeat steps 3–5 five times, allowing completion before each next command.
   Compare free heap/largest blocks, PSRAM and tasks at equivalent phases. Confirm
   discovery returns after each start and stops after each stop. A repeated
   `ble start` while advertising and `ble stop` while off should simply show status.
   Reboot and confirm BLE remains off. Keep any error messages for investigation.

7. Build/upload the combined variant:

   ```sh
   pio run -e guition-4848s040-wifi-ble -t upload
   pio device monitor -e guition-4848s040-wifi-ble
   ```

   Confirm `s` says Wi-Fi disabled and `ble status` says off. Save `d` and task
   count. Send `w` to use stored Wi-Fi credentials (or the existing serial
   credential command if necessary). After `s` reports connected/IP/RSSI, record
   `d`/`ble status` before BLE starts. Never include passwords in shared logs.

8. Start BLE and repeat discovery, touch/drag and resource tests while Wi-Fi stays
   connected. Check `s` throughout. Stop BLE: Wi-Fi should stay connected. Restart
   BLE, then use `x` to stop Wi-Fi: BLE should continue advertising. Use `w` again
   while BLE advertises and confirm Wi-Fi reconnects. Test the reverse startup
   order after reboot (BLE first, Wi-Fi second) and capture both sets of readings.
   This verifies basic coexistence, not throughput or heavy simultaneous traffic.

9. Stop both radios, verify their states and repeat memory readings after 10 s.
   Compare repeated same-state samples rather than expecting Wi-Fi's persistent
   infrastructure to vanish. Report any resets, freezes or steadily falling heap.

Normal default and Wi-Fi builds expose no `ble` commands and still exclude this
test implementation. All their original PlatformIO settings, display/touch/Wi-Fi
implementation and diagnostics are unchanged. ELF checks confirm controller init
only in BLE variants, Wi-Fi init only in Wi-Fi variants, and no Arduino BLEDevice
wrapper linkage. The BLE hooks are compile-time guarded and confined to
`ble_test.*`, three console commands, one loop service call and two environments.

The linked investigation records the supplied hardware results and their short-test
limits. Long-term stability and heavy simultaneous radio traffic remain unverified.
No CPU/load optimization or SDK buffer tuning was attempted for this milestone.
