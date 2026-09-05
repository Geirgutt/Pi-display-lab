# Foundation milestone — 2026-09-05

## Physical verification update — 2026-09-06

The user tested the current foundation firmware (`3b09aac`; documentation-only
rollback checkpoint `d670515`) and reported these results. These are user-run
physical tests, not tests executed by Codex.

| Area | Status |
|---|---|
| Display output | Physically verified; no obvious instability |
| Backlight | `0` + Enter off / `1` + Enter on physically verified |
| GT911 touch and orientation | Physically verified |
| Touch down/move/up and drag | Physically verified; smooth coordinate updates |
| Default heap/PSRAM stability | Unchanged across repeated diagnostics over several minutes and extensive touch/drag testing |
| Wi-Fi connection via serial credentials | Physically verified |
| Stored credentials | Retained across reboot; no re-entry needed |
| Wi-Fi disabled at startup | Physically verified after reboot |
| Explicit reconnect after reboot (`w`) | Physically verified |
| Display/touch with active Wi-Fi | Physically verified |
| BLE | Intentionally disabled |

No obvious short-term memory leak was observed. This does not establish long-term
stability, automatic AP-outage recovery, or repeated Wi-Fi stop/start behavior.
No hardware configuration or calibration change is justified by these results.
The original display-only baseline remains `b7cf625`.

Approximate raw touch samples with the display upright:

| Position | x | y |
|---|---:|---:|
| Top-left | 38 | 41 |
| Top-right | 446 | 51 |
| Bottom-left | 43 | 470 |
| Bottom-right | 445 | 452 |
| Center | 231 | 238 |

These are manually sampled positions, not measured controller extrema or
calibration targets. Orientation is confirmed; no scaling, offset, inversion or
axis swap is inferred from the samples.

### User-reported runtime measurements

All memory values are bytes, copied from the supplied diagnostics.

| Metric | Default build | Wi-Fi build, before start | First connection | Reboot + stored reconnect |
|---|---:|---:|---:|---:|
| Internal heap free | 362212 | 328804 | 289992 | 290024 |
| Internal heap minimum | 356884 | 323456 | 284444 | 284372 |
| Internal heap largest block | 327668 | 286708 | 278516 | 278516 |
| PSRAM total (reported) | 8386167 | 8386167 | 8385815 | 8385847 |
| PSRAM free | 7924871 | 7924871 | 7909931 | 7910067 |
| PSRAM used | 461296 | 461296 | 475884 | 475780 |

The default readings remained unchanged throughout the reported test. First
connection returned status 3, IP `192.168.2.49`, RSSI approximately -50 to -51 dBm.
After reboot, Wi-Fi remained disabled until `w`; stored reconnect returned status
3, the same IP and RSSI -51 dBm. The IP is a test observation, not firmware config.

Measured differences:

- Wi-Fi build before radio start versus default: 33408 fewer free internal heap
  bytes; identical reported PSRAM readings. This runtime difference is distinct
  from the static build RAM difference below.
- First connection versus Wi-Fi build before start: free internal heap decreased
  by 38812 bytes; free PSRAM by 14940 bytes; reported used PSRAM increased by
  14588 bytes.
- Reboot + stored reconnect versus first connection: free internal heap +32 bytes,
  minimum -72 bytes, largest block unchanged; free PSRAM +136 bytes and reported
  used PSRAM -104 bytes. These samples are effectively consistent, not a trend.

Reported PSRAM total varies slightly between samples (by hundreds of bytes).
The table preserves the diagnostic values exactly; it does not imply physical
PSRAM capacity changed. The cause has not been investigated. Because the reported
total changes, the free-PSRAM delta and used-PSRAM delta are not identical.
CPU load, throughput, numeric memory after Wi-Fi stop and long-term behavior
remain unmeasured. The exact test duration was described as several minutes.

## Evidence and preserved hardware

No previous Codex conversation was available or used. The source baseline is
`b7cf625e5472a5629c75fb0827636ff434c657b9`, the repository's sole commit at start.
All tracked source/configuration files and recent history were inspected before
editing; the working tree was clean. Installed package manifests and relevant
library implementations were read before configuring new hardware support.

The project identifies Guition ESP32-S3-4848S040: 480×480 ST7701-family RGB
display, 16 MiB quad flash and 8 MiB octal PSRAM configuration. The exact physical
PCB revision/suffix is not recorded, and no manufacturer schematic was available
in the repository. Those details have not been independently physically verified.

`src/display.h` remains byte-for-byte identical to the known-good commit.
Every original `platformio.ini` setting is preserved, including RGB-related
memory configuration, partition scheme and upload/monitor settings. No panel
timing, pixel clock, pin, rotation, color depth or initialization command changed.
The original black background, white text, positions, startup delay and backlight
LOW/HIGH behavior are retained. Backlight stays dark until the image is drawn;
it cannot be enabled through the module after failed display initialization.
On/off remains GPIO control; no PWM timer or unverified brightness curve added.

Installed sources used (relative to `.pio/libdeps/guition-4848s040/LovyanGFX`):

- `library.json`: version 1.2.28.
- `src/lgfx/v1/platforms/esp32s3/Panel_RGB.{hpp,cpp}`: existing exact-board
  `Panel_ST7701_guition_esp32_4848S040` command sequence, RGB565 depth and line array.
- `src/lgfx/v1/platforms/esp32s3/Bus_RGB.cpp`: PSRAM framebuffer and internal DMA
  allocation. `use_psram` is marked unimplemented in the header; the active bus
  allocation code is the evidence of PSRAM placement, not that setting alone.
- `src/lgfx/v1/touch/Touch_GT911.{hpp,cpp}` and `Touch.hpp`: configuration,
  address retry, polling and one-contact read support.
- `src/lgfx/v1/panel/Panel_Device.cpp`: touch attachment/calibration behavior.

Arduino sources under `~/.platformio/packages/framework-arduinoespressif32`:
`libraries/WiFi/src/WiFiSTA.cpp`, `WiFiGeneric.cpp`, `cores/esp32/esp32-hal-misc.c`,
`esp32-hal-bt.c`, and `tools/sdk/esp32s3/qio_opi/include/sdkconfig.h` establish
native credential storage/reconnect behavior, allocation lifecycle and BLE support.
Package versions are recorded in [baseline.md](baseline.md). Original unpinned
dependency declarations remain unchanged; use these installed versions for
comparison, and pin tested versions when accepting the hardware milestone.

## Touch evidence and limits

Exact-board implementations inspected online:

- [espcontrol board source](https://github.com/jtenniswood/espcontrol/blob/main/devices/guition-esp32-s3-4848s040/device/device.yaml): GT911, SDA 19, SCL 45; polling with no touch reset/IRQ assignment.
- [LovyanGFX exact-board implementation](https://github.com/lovyan03/LovyanGFX/discussions/722): same controller/pins, I2C port 1 at 400 kHz, reset/IRQ explicitly unassigned.

These are independent exact-board project implementations, not proof of the
unrecorded physical board revision. The second source discusses display problems
and uses different RGB settings; only its touch configuration was used after
cross-checking. Neither source overrides our physically working display setup.

`touch.cpp` uses the installed `lgfx::Touch_GT911` directly, without a new driver
or dependency. Its native init probes 0x14 and 0x5D. Touch init runs after display
success and cannot change the display init result. No controller configuration
rewrite (`setTouchNums`), reset pin, calibration or axis transform is applied.

The smallest initial interface returns a primary contact's **raw** coordinates.
The application prints down/move/up events at a maximum polling cadence of 50 Hz.
This polling is necessary with the selected no-IRQ configuration. The driver
retains its last contact on a transient I2C read failure, so this is not a
bus-health monitor; a stuck touch must be reported during testing. The driver can
also spend up to roughly 24 ms refreshing stale data after a polling gap.
Orientation and smooth primary-contact tracking are now physically verified.
Multi-touch gesture handling and precise screen calibration remain deferred; the
reported manual samples do not establish calibration extrema.

## Structure and Wi-Fi behavior

- `main.cpp`: original test image and simple touch test; setup/loop orchestration.
- `hardware.*`: one display owner, initialization and GPIO backlight control.
  Applications use LovyanGFX directly for drawing; no multi-board abstraction.
- `touch.*`: independent GT911 initialization and primary-contact read.
- `diagnostics.*`: native heap/system measurements, printed at startup and on demand.
- `console.*`: bounded serial test commands; no dynamic command strings.
- `network.*`: optional native Wi-Fi station lifecycle and bounded retries.

The default environment excludes networking code. The `guition-4848s040-wifi`
environment defines `DESKDISPLAY_WIFI=1`, with identical hardware settings.
Even that build does not initialize Wi-Fi at boot or automatically connect using
stored credentials. `startStored()` or `configureAndStart()` explicitly starts it.
These functions accept a connection request; success does not mean DHCP completed.
The native `WiFi.status()`, `WiFi.localIP()` and `WiFi.RSSI()` APIs expose state.

Native Wi-Fi NVS storage owns credentials; no second Preferences store or private
credentials in firmware source. The test input supports WPA passphrases of 8–63
bytes and SSIDs of 1–32 bytes, including spaces. Open networks, enterprise auth,
64-character raw PSKs and tab/newline characters in credentials are outside this
test console's scope. Input is not echoed by firmware; disable terminal local echo
and avoid credential-bearing terminal logs. NVS encryption is not configured.

`service()` checks native connection state at most once per second while enabled,
and retries at 30-second intervals while disconnected, including absent APs and
authentication failure. Unsigned elapsed-time arithmetic handles millis rollover.
Arduino auto-reconnect is disabled to avoid competing policies; the installed
core still performs its built-in single first-failure retry. No custom event
callback, timer, task, AP, scan loop or blocking connection wait is introduced.
Stop cancels retries and calls native Wi-Fi OFF/deinit; failure is reported.
Forget clears only native station configuration then stops the radio.

## Bluetooth integration point

ESP32-S3 supports BLE, not Bluetooth Classic/SPP/A2DP:
[Espressif ESP32-S3 Bluetooth overview](https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32s3/api-guides/bluetooth.html).
The installed Arduino SDK selects Bluedroid/BLE. No BLE library is referenced,
controller started, service advertised or custom Bluetooth wrapper added.

The installed core calls `esp_bt_controller_mem_release(ESP_BT_MODE_BTDM)` when
its weak `btInUse()` returns false. Both built ELFs retain that unused-BT path
and contain no `esp_bt_controller_init` or `BLEDevice::init` definition.
A future BLE-enabled build must retain controller memory at boot through the
framework's BLE linkage before lazy initialization can work. Releasing that memory
is not a reversible runtime enable switch. Measure BLE-enabled-but-idle versus
active operation separately; select a host stack at that milestone rather than
installing an unused dependency now.

## Resource measurements

Clean PlatformIO release builds on the same installed versions:

| Build | Flash bytes | Static RAM bytes | Flash delta vs baseline | RAM delta |
|---|---:|---:|---:|---:|
| Hardware-confirmed baseline | 352925 | 20300 | — | — |
| Display/backlight separation + diagnostics | 353729 | 20300 | +804 | 0 |
| Touch step | 368625 | 20460 | +15700 | +160 |
| Final default | 369145 | 20588 | +16220 | +288 |
| Final optional Wi-Fi | 784241 | 45100 | +431316 | +24800 |

Wi-Fi inclusion costs +415096 flash / +24512 static RAM bytes relative to final
default, even before connecting. PlatformIO's RAM figure is static data/BSS,
not runtime free heap or a complete accounting of internal instruction RAM.
Its flash denominator is the 6553600-byte application partition, not the full
16 MiB chip. Linker dummy/reservation sections must not be summed as real usage.

Permanent buffers/resources:

- Existing 460800-byte RGB565 framebuffer in PSRAM; 1380 bytes of DMA descriptors
  and 1920-byte line-pointer array in internal DMA-capable heap, plus driver and
  allocator overhead. No second framebuffer, sprites or touch marker buffer added.
- Fixed 112-byte console buffer (cleared after commands/30 s inactivity) and
  92-byte GT911 object in static RAM; these are included in the static totals.
- No application tasks added. The existing Arduino task now yields for 20 ms
  between touch reads. Unchanged RGB DMA/VSYNC activity continues while idle,
  including when the backlight is off. Moving-touch serial output has a CPU/UART
  cost; stationary/absent touch produces no repeated application logs.
- Once Wi-Fi starts, the framework creates driver/network resources, including
  Arduino event task (4096-byte stack), event queue (32 pointer entries), IDF
  event loop and TCP/IP task. Installed stack settings include 2048-byte system
  event and 2560-byte TCP/IP stacks. Driver buffers/heap allocations are additional.
  Stopping the radio deinitializes the driver; framework event/TCP-IP infrastructure
  can remain allocated after first use. Do not assume heap returns to boot level.
- No third-party dependencies introduced. Optional Wi-Fi uses framework-bundled
  WiFi 2.0.0. PlatformIO's dependency scanner also lists/builds WiFi in the default
  environment, but ELF inspection confirms its initialization/class methods are
  not linked there. BLE remains unused in both variants.

During implementation, runtime internal heap, PSRAM consumption, CPU load and
network performance were **not measured by Codex**: no device was opened, flashed
or monitored. The subsequent user verification above confirms heap/PSRAM
stability and supplies the numeric readings recorded above. Startup diagnostics
provide snapshots before display init, after display init and after touch init.
`d` provides uptime, internal free/minimum/largest heap, PSRAM total/free/used,
flash size/speed/sketch size, chip revision/cores/frequency, SDK and reset reason.
Minimum heap is the allocator's reported low-water metric, not an instantaneous
measurement. Compare free and largest blocks as well as minimum values.

## Validation and exact next hardware tests

Software verified: clean baseline and final builds; each intermediate meaningful
step built before proceeding. One missing I2C header was corrected before moving
past the touch step. Final clean builds have no compiler warnings/errors.
Source comparison confirms every original PlatformIO setting and all of
`display.h` are unchanged. ELF symbol checks confirm expected Wi-Fi exclusion
and absent BLE initialization. `git diff --check` passes. Codex executed no radio,
persistence, touch, failure-injection or long-running runtime tests; subsequent
user hardware results are recorded at the top of this report.

Original hardware test procedure (retained for regression testing; no upload was
performed by Codex). Display/touch, initial Wi-Fi connection and the reboot/stored
credential portions have passed as reported above; this does not imply every
repetition or exact duration below was performed.

**Smallest next milestone: Wi-Fi lifecycle validation, without firmware changes.**
Test AP outage/recovery and initial AP absence from step 6, then repeated `x`/`w`
stop/start cycles from step 7. Capture `s` and `d` while connected, after stop,
and after reconnect; exercise touch throughout. Compare repeated cycles at the
same lifecycle stage rather than expecting all startup allocations to disappear.
Credential erasure, wrong-password handling and console boundary tests also remain
pending. Record the results before adding the next feature.

Regression procedure:

1. Build/upload **guition-4848s040** using your established hardware workflow.
   Open serial at **115200**, then cold boot. Confirm exactly the original two
   text lines, placement, colors, orientation and stable image. Capture all three
   startup diagnostic snapshots and the touch init success/failure message.
2. Send `0` then Enter: backlight off. Send `1` then Enter: same image restored,
   without panel reinitialization. Repeat five times; watch for startup flashes,
   flicker, image shifts or artifacts. Backlight off is not panel/CPU sleep.
3. With the original text upright, touch top-left, top-right, bottom-right,
   bottom-left and center, slightly inside the glass edge. Record each raw x/y.
   Drag left-to-right and top-to-bottom; report which coordinate increases and
   whether axes are swapped/mirrored. Lift after each touch and confirm `up`.
   Expected screen-space targets would be near (0,0), (479,0), (479,479), (0,479),
   (240,240); raw values are evidence to compare, not a claimed calibration.
4. Leave idle for 10 minutes, send `d` + Enter, drag repeatedly, then send `d`
   again. Report free internal heap, minimum/largest block, PSRAM and any reset.
5. Only after the above passes, build/upload **guition-4848s040-wifi**. Verify
   the same display/touch behavior and capture boot/`d` readings before Wi-Fi.
   Send `s` + Enter: disabled. Send `wifi YOUR SSID<TAB>YOUR PASSWORD` + Enter,
   using an actual tab and your own credentials. After several seconds send `s`:
   expect connected status 3, nonzero IP and RSSI. Send `d` for memory comparison.
6. Cold boot: Wi-Fi must remain disabled. Send `w` + Enter: stored credentials
   should reconnect. Switch the AP off for at least 60 seconds, then on; allow
   30 seconds plus association/DHCP time, checking `s`. Exercise touch throughout.
   Also test initial AP absence and a deliberately wrong password: display and
   console must remain responsive, with no rapid restart/reconnect loop.
7. Send `x` + Enter: stop radio/retries. Wait 60 seconds, check `s` and `d`;
   restart with `w`. Repeat several times to look for steadily falling heap.
   Finally send `forget` + Enter, cold boot, then `w`: expect no stored credentials
   and a disabled radio. Do not include passwords in any logs you share.
8. Paste a line longer than 111 bytes: expect rejection, with the following valid
   `d` command still working. Confirm LF and CRLF submissions work.

Any touch init failure, stuck contact, mismatch in orientation or display
regression in subsequent testing requires physical investigation before accepting
further firmware changes.
If touch fails, verify the actual board revision/schematic rather than trying
arbitrary reset/interrupt pins. Upstream GT911 initialization does not validate a
product ID, so its success message alone is not proof of correct touch behavior.

After lifecycle validation, the smallest implementation milestone is to pin the
already-tested dependency versions for reproducible builds, verifying unchanged
hardware configuration and build sizes. Then consider one small touch-driven
page using existing LovyanGFX. Keep BLE disabled; LVGL, web management and a
telemetry protocol remain separate measured milestones.
