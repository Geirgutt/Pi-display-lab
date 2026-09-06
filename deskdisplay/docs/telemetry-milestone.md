# First Linux/Raspberry Pi telemetry page

This milestone adds the first application feature on top of the physically
verified TLS foundation: one Linux/Raspberry Pi peer can send real local
telemetry and the DeskDisplay can show it on a `Cluster` page. The existing
display, GT911 touch, backlight, Wi-Fi, BLE and TLS code paths were preserved.
The initial telemetry path and the follow-up hostname, counter and
temperature-source corrections are now physically verified. No device was
flashed by this documentation/build follow-up.

## Physical verification — initial telemetry run

The secure Wi-Fi build was flashed and tested with Fedora as the peer. Display,
touch, navigation, backlight, Wi-Fi, TLS setup, continuous telemetry, sequence
numbers, offline behavior, automatic reconnect and UI coexistence all worked.
The Cluster page showed the hostname, status, CPU, temperature field, RAM and
uptime. No visible progressive memory leak was observed.

During the active session the measured values were approximately:

| State | Internal heap free | Minimum heap | Largest block | PSRAM used | Sketch |
|---|---:|---:|---:|---:|---:|
| Secure telemetry active | 248808–248844 | 239212–239460 | 233460 | 476004 | 946400 |
| Peer unavailable | 284144 | — | — | — | — |
| After reconnect | 248816 | — | 233460 | — | — |

The observed `accepted=62`, increasing sequences, reconnect and stable
post-reconnect heap confirm the architecture path:

```text
TLS -> validated telemetry frame -> app_state -> Cluster UI
```

The run also exposed two follow-up issues: the hostname redraw left one stale
glyph when the new string was shorter, and Fedora's `thermal_zone0` (`acpitz`)
was incorrectly presented as a CPU temperature. The correction clears the
bounded hostname region and accepts only identified CPU/SoC thermal sources.

## Physical verification — final telemetry retest

The corrected secure build was retested on the real device with Fedora. The
Cluster hostname displayed exactly `fedora` without a stale trailing glyph.
TLS telemetry, Wi-Fi, UI, touch, disconnect detection, automatic reconnect and
temperature handling all remained functional. Stopping `secure_peer` produced
the expected retry attempts; restarting it restored TLS and telemetry
automatically.

During stable active telemetry the measured runtime values were approximately:

| Internal heap free | Minimum heap | Largest block | PSRAM used |
|---:|---:|---:|---:|
| 248800 bytes | 239184 bytes | 233460 bytes | 476004 bytes |

No progressive memory loss was observed. The previous constant `25.0 C` was an
unhelpful Fedora ACPI thermal-zone value. The sender now reports a recognized
CPU/package source when available; the observed real value varied roughly from
57 to 69 C. Hosts without a trustworthy source report `N/A` instead of a
fabricated number.

## Scope

The existing outbound TLS 1.2 ECDHE-PSK connection is reused unchanged. The
existing fixed 58-byte, version-1 telemetry frame (type 1) now carries data
collected by `tools/secure_peer.c`:

- bounded hostname (up to 32 bytes)
- CPU utilization in tenths of a percent from `/proc/stat`
- CPU temperature in tenths of a degree from common `/sys` thermal paths
- RAM utilization in tenths of a percent from `/proc/meminfo`
- uptime seconds from `/proc/uptime`
- an online flag set by the sender

The sender emits one frame per second, requires no root privileges and has no
control actions. Temperature is reported as unavailable (`INT16_MIN` on the
wire, displayed as `N/A`) when no identified CPU/SoC source exists. Raspberry
Pi `cpu-thermal`, `bcm2835_thermal` and equivalent SoC names are accepted;
generic Linux accepts explicitly named CPU sensors such as `x86_pkg_temp`,
`coretemp`, `k10temp` and `zenpower`. Generic zones such as Fedora `acpitz`
are deliberately rejected. No protocol or cryptographic change was made.

On the ESP32, only a frame that has passed the existing TLS, framing, message
type, bounds and strictly increasing sequence checks is copied into the fixed
application model. The UI never parses network bytes. `nodeOnline` requires a
recent valid frame (less than five seconds old) and its online flag; when the
sender stops, the last values remain visible while status changes to OFFLINE.

## UI

The System page keeps its existing centered Back button and adds a small
`Cluster` button. The new page is intentionally direct LovyanGFX drawing:

```text
 DeskDisplay                              Cluster
 ┌──────────────────────────────────────────────┐
 │ <linux-hostname>                              │
 │ Status     ONLINE                             │
 │ CPU        23.4 %                             │
 │ Temp       49.0 C                             │
 │ RAM        41.2 %                             │
 │ Uptime     2d 04h 12m                         │
 └──────────────────────────────────────────────┘
                     [ Back ]
```

The existing 20 ms application loop still handles touch and services. Node
state is sampled and the visible page is updated at most once per second. A
page transition redraws the page; normal telemetry updates redraw only the
changed value rows. No new FreeRTOS task, timer, heap allocation, PSRAM buffer,
library or dependency was introduced.

## Build/resource comparison

These are clean release sizes from the installed PlatformIO packages. The
comparison is with the immediately preceding physically verified UI/TLS
foundation.

| Environment | Before flash | After flash | Flash delta | Before static RAM | After static RAM | RAM delta |
|---|---:|---:|---:|---:|---:|---:|
| Default | 373209 | 374293 | +1084 | 20676 | 20812 | +136 |
| Wi-Fi | 788533 | 789685 | +1152 | 45172 | 45316 | +144 |
| BLE | 960165 | 961337 | +1172 | 46180 | 46324 | +144 |
| Wi-Fi + BLE | 1328785 | 1329993 | +1208 | 66068 | 66212 | +144 |
| Secure Wi-Fi | 944969 | 946405 | +1436 | 47896 | 47968 | +72 |

The new persistent application state is one fixed telemetry record, a last
update timestamp, an accepted-frame counter and one status flag. The TLS
record/session allocations remain the same as the verified secure build and
are created only when the secure connection is started. The sender uses only
libc/POSIX file reads and the already-required OpenSSL `libssl`/`libcrypto`;
there is no `psutil` dependency, service installation or extra daemon.

The final physical run measured the values above during stable one-second
telemetry, after sender stop and after automatic reconnect. The application-side
state remains fixed; no new PSRAM buffer or task is expected.

## Software build

Build every affected firmware variant without uploading:

```sh
/home/geir/.platformio/penv/bin/pio run -t clean \
  -e guition-4848s040 \
  -e guition-4848s040-wifi \
  -e guition-4848s040-ble \
  -e guition-4848s040-wifi-ble \
  -e guition-4848s040-secure
/home/geir/.platformio/penv/bin/pio run \
  -e guition-4848s040 \
  -e guition-4848s040-wifi \
  -e guition-4848s040-ble \
  -e guition-4848s040-wifi-ble \
  -e guition-4848s040-secure
cc -O2 -Wall -Wextra -Isrc -o /tmp/deskdisplay-secure-peer \
  tools/secure_peer.c -lssl -lcrypto
```

The secure UI test uses `guition-4848s040-secure`; it includes Wi-Fi and the
existing secure console commands. The firmware is deliberately not uploaded by
this milestone.

When you are ready to flash it on the established hardware setup, use:

```sh
/home/geir/.platformio/penv/bin/pio run -e guition-4848s040-secure
/home/geir/.platformio/penv/bin/pio run -e guition-4848s040-secure -t upload
/home/geir/.platformio/penv/bin/pio device monitor -e guition-4848s040-secure
```

## Physical test procedure

1. Flash `guition-4848s040-secure` using the established local hardware
   workflow. Confirm the already verified display, orientation, backlight,
   touch, System page and Touch Test first.
2. On Fedora, create a restricted PSK file outside the repository and compile
   the sender:

   ```sh
   install -d -m 700 ~/.config/deskdisplay
   umask 077
   openssl rand -hex 32 > ~/.config/deskdisplay/peer.psk
   chmod 600 ~/.config/deskdisplay/peer.psk
   /tmp/deskdisplay-secure-peer --psk-file ~/.config/deskdisplay/peer.psk
   ```

   On the ESP32 serial console, enter the same key, the Fedora/Raspberry Pi
   address and the existing peer port, then start the radios and secure channel:

   ```text
   secure key <contents of ~/.config/deskdisplay/peer.psk>
   secure peer <sender-ip> 4567
   w
   secure start
   secure status
   ```

   `secure status` should show `key=1 peer=1`; the peer should print a TLS
   session-established line and the ESP32 should print accepted telemetry with
   increasing sequence values. Transport failures while the peer is stopped
   should increment `transport-fail`, while `auth-fail` is reserved for a
   failed TLS setup/handshake reported by mbedTLS.
3. From Dashboard, tap **System**, then **Cluster**. Verify the real hostname,
   changing CPU/RAM values, a trustworthy CPU/SoC temperature or `N/A`, and
   increasing uptime. Verify that the page remains responsive during TLS
   reconnects and that a shorter hostname leaves no stale character behind.
4. Stop the sender with `Ctrl-C`. Within approximately five seconds the Cluster
   page must show `OFFLINE` while retaining the last valid values. Restart the
   sender; the ESP32 must reconnect automatically and return to `ONLINE`.
5. Run the same compiled sender on one Raspberry Pi (copy the binary or compile
   there with the same command), using the Pi's restricted PSK file and the
   device's configured peer address. Repeat the page and offline/recovery tests.
6. Use serial `d` before secure start, during stable telemetry, after sender
   stop, and after reconnect. Record free/minimum/largest internal heap and
   PSRAM. Use `secure status` to record accepted, auth-fail, transport-fail,
   replay, malformed, unauthorized and reconnect counters. No progressive loss
   should appear.

Do not add credentials to the repository or serial logs. Do not test by adding
plaintext telemetry, a second listener, control commands or a web service.

## Intentionally deferred

This is one node only. Multi-node storage, discovery, configuration UI, web
server, telemetry history, control/RPC commands, Home Assistant, MQTT, OTA,
LVGL and service installation remain separate milestones.
