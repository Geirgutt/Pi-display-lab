# First application UI milestone

This milestone adds the first touch dashboard while preserving the verified
display, backlight, GT911, Wi-Fi and BLE foundation. No hardware settings,
network behavior, calibration or radio stack was changed. The implementation
was physically tested on the real device; no device was flashed by this session
and no commit was made for this work.

## Physical verification — 2026-09-06

The LovyanGFX-only UI was verified in the default, Wi-Fi and Wi-Fi+BLE builds.
The display remained stable and correctly oriented, with no visible flicker or
tearing. System, Back, Touch Test and Backlight controls worked. Touch corners,
center, drag and release behaved correctly. The UI remained responsive while
Wi-Fi connected/disconnected and while BLE advertised.

Default UI build, after approximately 596862 ms uptime:

| Measurement | Result |
|---|---:|
| Internal heap free | 361472 bytes |
| Minimum internal heap | 356144 bytes |
| Largest internal block | 327668 bytes |
| PSRAM total/free/used | 8386167 / 7924871 / 461296 bytes |
| Sketch size reported at runtime | 373520 bytes |

The same values were observed after a fresh reboot. No visible heap or PSRAM
leak was observed during the test interval.

Wi-Fi UI build:

| State | Heap free | Minimum | Largest | PSRAM used |
|---|---:|---:|---:|---:|
| Before Wi-Fi | 328080 | 322732 | 286708 | 461296 |
| Connected, status 3, RSSI about -62 dBm | 289908 | 284264 | 278516 | 475780 |
| After Wi-Fi stop | 311704 | — | — | 461296 |
| Started again | 289772 | 284104 | 278516 | 475780 |

The dashboard, System page and Touch Test stayed usable during both connection
cycles. No new instability was observed.

Wi-Fi+BLE+UI build:

| State | Heap free | Minimum | Largest | PSRAM used |
|---|---:|---:|---:|---:|
| After display/touch init | 294096 | 288968 | 258036 | 461296 |
| Wi-Fi active | 255788 | 250128 | 245748 | 475780 |
| Wi-Fi + BLE advertising | 197944 | 195512 | 184308 | 475884 |
| BLE stopped, Wi-Fi active | 255788 | — | — | 475884 |
| Wi-Fi stopped | 277716 | — | — | 461296 |

During coexistence BLE reported advertising with controller 2, host 2 and 14
system tasks. Wi-Fi reported status 3, IP `192.168.2.49` and RSSI about
`-60 dBm`. BLE and Wi-Fi stop behavior matched the previously investigated
stable first-use retention. No progressive leak was observed.

These results mark the first UI milestone as physically verified. The existing
hardware and network configuration is deliberately unchanged.

## Design choice

The UI uses LovyanGFX directly. The current screen needs a few text rows, four
buttons, two navigation pages and simple pressed feedback. LVGL would add a
second retained object tree, input integration, draw buffers and a scheduler for
functionality this screen does not need. Direct LovyanGFX keeps ownership obvious
and makes redraw boundaries explicit. LVGL can be measured later when real widget
layout, scrolling or multiple complex pages justify it.

## Structure

- `app_state.h`: one fixed-size model containing page, telemetry and touch state.
- `app.cpp`: non-blocking application loop, touch hit testing, page/button actions,
  and one-second telemetry scheduling.
- `ui.cpp/.h`: LovyanGFX drawing only; no radio calls or touch-controller setup.
- Existing `hardware.*`, `touch.*`, `network.*`, `diagnostics.*` and `console.*`
  remain the platform services. `diagnostics::snapshot()` exposes the existing
  measurements to the model without duplicating heap/PSRAM logic.

No heap allocation, task, timer, library or dependency was introduced. The loop
still yields through the existing 20 ms delay (50 Hz input service). Telemetry is
sampled and updated once per second. Dashboard/system changes redraw only the
small value rows; page changes redraw that page; touch-test coordinates redraw
only its test panel. A button redraws only the button group for pressed feedback.

## Screen layout

The dashboard has a dark header (“DeskDisplay / Dashboard”), a compact live-status
card showing Wi-Fi state/IP/RSSI, internal heap, PSRAM free and uptime, then four
large touch targets:

```text
 DeskDisplay                         Dashboard
 ┌──────────────────────────────────────────┐
 │ Live platform status                     │
 │ Wi-Fi       CONNECTED 192.168.2.49       │
 │ RSSI        -58 dBm                       │
 │ Heap        280 KB                        │
 │ PSRAM       7,900 KB                      │
 │ Uptime      123 s                         │
 └──────────────────────────────────────────┘
 [ Wi-Fi ]          [ System ]
 [ Backlight ]      [ Touch Test ]
```

The System page shows heap free/largest block, PSRAM free and uptime with a Back
button. Touch Test shows raw primary-contact coordinates and a small mapped marker;
it does not alter the verified touch calibration/orientation.

Wi-Fi button behavior is build-aware: in the Wi-Fi builds it starts stored Wi-Fi
when off/connecting and stops it when active; the default build leaves the
existing radio-free behavior intact. Backlight toggles the existing GPIO output.
Touch actions run on release after the pressed state has been shown.

## Build and resource measurement

Clean release builds before UI (commit `f02eace`) and after UI, using the same
installed packages:

| Environment | Before flash | After flash | Delta | Before static RAM | After static RAM | Delta |
|---|---:|---:|---:|---:|---:|---:|
| default | 369145 | 373157 | +4012 | 20588 | 20676 | +88 |
| Wi-Fi | 784241 | 788533 | +4292 | 45100 | 45172 | +72 |
| BLE | 956021 | 960165 | +4144 | 46108 | 46180 | +72 |
| Wi-Fi + BLE | 1324549 | 1328785 | +4236 | 65980 | 66068 | +88 |

The flash figure uses PlatformIO’s 6,553,600-byte application-partition limit;
static RAM is the linker data/BSS figure. The final clean build of all four
environments completed successfully with no compiler warnings or errors. The UI
adds only the fixed model, text buffers and coordinates; the existing 480×480
PSRAM framebuffer remains the dominant application buffer.

## Test procedure

Do not include credentials in shared logs.

1. Build and flash the default environment using the established hardware
   workflow. Confirm the screen is stable, upright and free of flicker/tearing.
2. Tap System, then Back. Confirm page changes and that heap/PSRAM/uptime values
   update without visible full-screen redraw artifacts.
3. Tap Touch Test. Touch the four corners and center, then drag. Confirm raw
   values match the previously verified orientation and the marker follows without
   leaving trails. Tap Back.
4. Tap Backlight twice. Confirm the existing backlight turns off/on and the
   dashboard image remains intact.
5. Send `d` over serial. Confirm the existing full diagnostics report still works.
   Watch the dashboard for at least ten minutes and perform repeated touch/drag;
   record free/minimum/largest internal heap and PSRAM before and after.
6. Build the Wi-Fi UI environment and flash it. Confirm it boots with Wi-Fi off,
   then tap Wi-Fi. While it says CONNECTING, use Touch Test and System; the loop
   should remain responsive. When connected, verify status, IP and RSSI change on
   the dashboard. Tap Wi-Fi again and verify the existing stop behavior.
7. Repeat the stored-credential start path after reboot if desired. Confirm the
   known Wi-Fi shutdown timeout behavior, if it appears, is unchanged and that
   display/touch remain responsive.
8. For BLE variants, repeat the already verified BLE advertising/start/stop test
   with the dashboard visible. The UI does not alter BLE commands; `ble status`
   and `d` must continue to work.

The procedure above is retained for regression testing. The current hardware
test passed without a display, touch, radio, responsiveness or memory regression.

## Next milestone

The proposed next milestone is one external Linux/Raspberry Pi telemetry page.
Before implementation, compare a small UDP datagram, an HTTP endpoint and a TCP
stream. The current recommendation is a versioned, bounded UDP packet sent at
about 1 Hz, parsed in the existing loop without a new task. A compact line such
as `DD1|host=pi4|cpu=23.4|temp=47.2|ram=38.1|up=123456|online=1` avoids a JSON
library and keeps the ESP32 side small. Include a sequence number or sender
uptime, reject oversized/malformed packets, and mark the host offline after a
short missed-packet timeout while retaining the last values for display.

The Linux sender can be a small Python program using `psutil` and the standard
library UDP socket. HTTP would be easier to inspect manually but requires an
ESP32 server, request parsing and more idle resources. TCP adds connection state
without helping this one-way, periodic data flow. The UDP design should be
measured in the next milestone; a reasonable initial estimate is a few KB of
flash, less than 1 KB of fixed application buffer/state, no additional task and
little CPU work at 1 Hz, while the already-running Wi-Fi stack remains the
largest radio cost. No telemetry code is included yet.
