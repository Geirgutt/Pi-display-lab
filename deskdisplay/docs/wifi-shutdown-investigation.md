# Wi-Fi shutdown investigation — 2026-09-06

## Conclusion

No firmware correction is warranted by the reported test. Preserve the current
`network::stop()` sequence and verified display/touch/BLE behavior. The message
`wifi:timeout when WiFi un-init, type=4` comes from a Wi-Fi probe timer callback
finding the driver no longer initialized. It is not a public shutdown call
waiting too long. In the reported sequence, evidence supports a harmless late
timer callback after successful shutdown, rather than a failed radio shutdown.

This investigation changed documentation only. No firmware, installed library,
hardware configuration, flash/upload or commit was changed/performed. No rebuild
was necessary for these documentation changes; existing BLE milestone build
measurements remain applicable.

## Exact emitter in the installed SDK

Inspected Arduino-ESP32 2.0.17 package
`3.20017.241212+sha.dcc1105b`, its ESP32-S3 IDF headers (version **4.4.7**),
`libraries/WiFi/src/WiFiGeneric.cpp`, current `src/network.cpp`/`console.cpp`,
and the actual SDK static libraries used by the build.

The private Wi-Fi implementation is shipped as a binary archive; its C source is
not present in the installed framework. Therefore the exact message/branch was
traced using the installed Xtensa objdump's section data and relocatable
disassembly, rather than treating another SDK version or a forum report as proof.

Archive relative to the installed framework:
`tools/sdk/esp32s3/lib/libnet80211.a`

SHA-256:
`6aae206c85e9009a24cd1f28ce535e2a2d578d9687fe2dc77d4697d45ebc8d0f`

Binary findings:

- Member `ieee80211_timer.o`, section `.rodata_wlog_error.24`, contains the
  exact format string `timeout when WiFi un-init, type=%d`.
- `ieee80211_timer_process` calls `wifi_api_lock()`, then
  `wifi_get_init_state()`. At offset `0x73`, the comparison against state value
  3 branches to normal timer processing. Otherwise it unlocks, logs that exact
  message, and returns literal `0x3001`, matching installed
  `ESP_ERR_WIFI_NOT_INIT`. There is no timed-wait loop in this error branch.
- In `wl_cnx.o`, `.text.mgd_probe_send_timeout` passes `a11 = 4` to
  `ieee80211_timer_process` (instruction at offset `0x9`). The callee logs this
  second argument as the timer type. Thus **type 4 is the probe-send timer**;
  it is not an Arduino Wi-Fi event number or a public shutdown return code.

Readable reconstruction of the relevant logic, **not original C source**:

```text
probe-send timer callback -> timer_process(..., type=4, ...)
timer_process:
    acquire Wi-Fi API lock
    if internal init state != 3:
        unlock
        log "timeout when WiFi un-init, type=%d"
        return ESP_ERR_WIFI_NOT_INIT
    otherwise allocate/post timer work
```

The phrase "timeout" here denotes timer expiry. The driver explicitly rejects
that timer work when no longer initialized. The original private source and
runtime trace are unavailable, so the exact reason this callback remained
pending, its scheduling delay, and whether BLE changes its frequency are not
established. Do not label it a proven BLE coexistence defect or suppress all Wi-Fi
errors on the strength of this single message.

Reproduce the binary inspection with the installed
`xtensa-esp32s3-elf-objdump -s` (string sections) and `-dr` (code plus symbol
relocations) on the archive above. This avoids relying on stripped final ELF
symbols for private static functions.

## Shutdown sequence and return value

The current call chain is:

```text
network::stop()
  active = false                  // cancels application reconnect policy
  WiFi.mode(WIFI_OFF)
    espWiFiStop()
      esp_wifi_stop()
      wifiLowLevelDeinit()
        esp_wifi_deinit()
```

Installed `WiFiGeneric.cpp`: mode selection near line 1249, stop near line 728,
deinit near line 705. Each native failure on the connected-to-OFF path propagates
false. The console prints `Wi-Fi stopped.` only when `network::stop()` returns
true. With the reported connected starting state, that is evidence that both
stop and deinit returned success; the later log is a separate timer path.

Installed `esp_wifi.h` documents stopping station operation and deinitializing
driver resources/task. Matching upstream
[IDF 4.4.7 wifi_init.c](https://github.com/espressif/esp-idf/blob/v4.4.7/components/esp_wifi/src/wifi_init.c)
also checks that Wi-Fi is stopped before driver deinit and propagates errors.
The Arduino stop sequence is appropriate. Adding a separate disconnect, arbitrary
delay, repeated direct deinit, manual framework task deletion or an SDK upgrade
has no demonstrated benefit for this observation.

Limit: the later `s` output `Wi-Fi disabled.` alone means our application retry
flag is false, not independent driver-state verification. It must not override a
future `Wi-Fi stop failed.` message. Here the successful stop result, one fewer
task, reclaimed heap/PSRAM and BLE continuing to advertise agree with shutdown.

## Retained first-use memory

Installed `WiFiGeneric.cpp` shows allocations beyond the Wi-Fi driver:

- `tcpipInit()` is guarded by a persistent initialization flag.
- `_start_network_event_task()` creates Arduino event group, 32-pointer queue,
  4096-byte-stack `arduino_events` task and IDF default event loop/handlers.
- `wifiLowLevelInit()` creates **both** default station and AP esp-netif objects
  when absent, even though this application enables only station mode. This does
  not mean a SoftAP radio is started.
- `wifiLowLevelDeinit()` calls only `esp_wifi_deinit()`; it does not delete the
  Arduino event machinery, default event loop, esp-netif objects or TCP/IP stack.

Matching [IDF 4.4.7 esp_netif_lwip.c](https://github.com/espressif/esp-idf/blob/v4.4.7/components/esp_netif/lwip/esp_netif_lwip.c#L314)
initializes TCP/IP and synchronization objects once. `esp_netif_deinit()` explicitly
returns `ESP_ERR_NOT_SUPPORTED` once lwIP is initialized; stack-wide deinit is not
supported there. Installed default stack sizes also include system event
2048 + 512 = 2560 bytes and TCP/IP 2560 + 512 = 3072 bytes. Together with the
Arduino event stack this is 9728 bytes of stack allocation, before task control
blocks, queues, network interfaces, locks and other one-time allocations.

Consequently a one-time retained heap cost is expected. The observed plateau
around 277.8 KB versus about 294.2 KB before first radio use is consistent with
this architecture. It is **not** an exactly derived 16 KB allocation, and no heap
trace has attributed every retained byte. Repeated cycles without continued loss
support bounded initialization overhead rather than a progressive leak. Do not
manually dismantle framework-owned network objects to recover this memory.

## Physical results supplied by the user

BLE-only: initialization, advertising, stop/deinit and five start/stop cycles
passed; tasks cleaned up, PSRAM unchanged, no visible progressive heap loss.
The reported difference after five cycles was approximately 244 bytes; full
per-cycle numeric readings were not supplied.

Combined build, BLE started first:

| Phase | Internal free | Minimum | Largest block | PSRAM used | Tasks |
|---|---:|---:|---:|---:|---:|
| BLE advertising, before Wi-Fi | 219876 | 195728 | 208884 | 461296 | 13 |
| Wi-Fi connected + BLE advertising | 198040 | 192388 | 188404 | 475780 | 14 |
| Wi-Fi stopped, BLE advertising | 219596 | not supplied | not supplied | 461296 | 13 |
| Both stopped/deinitialized | 277556 | 192388 | 188404 | 461296 | 9 |

Wi-Fi reported status 3, IP `192.168.2.49`, RSSI -58 dBm. BLE remained advertising
with host/controller 2/2 through Wi-Fi startup and shutdown; after BLE stop both
were 0. Both radios functioned simultaneously.

Within this sequence, Wi-Fi start reduced free internal heap by 21836 bytes and
increased used PSRAM by 14484 bytes. Wi-Fi stop recovered 21556 internal bytes
and all that PSRAM; the pre-/post-Wi-Fi BLE-active samples differ by 280 bytes.
BLE stop then recovered 57960 internal bytes and reduced task count by four.
These are snapshot differences, not an allocator trace or a claim that all
allocations belong exclusively to one stack.

The final minimum remains a historical low-water value. Largest free block need
not return to its prior value when total free heap recovers; allocation layout
and persistent objects affect it. Neither metric alone proves a leak.

## Recommended confirmation on the same firmware

No corrected firmware or mandatory reflash is needed. For extra confidence in the
specific timer event, use the already-tested combined build and keep a timestamped
serial log, with no credentials included:

1. Cold boot. Send `ble status`, `s`, `d` (Enter after each).
2. Send `ble start`; wait for advertising completion. Capture `ble status`, `d`.
3. Send `w`; wait for `s` status 3. Capture `s`, `ble status`, `d`.
4. Send `x`; retain the success/failure message and any later timer log. Capture
   `s`, `ble status`, `d` after 1 s and again after 10 s. Confirm fresh BLE
   advertisements and working touch/display.
5. Wait 60 s: Wi-Fi should not restart on its own. Send `w`; verify connection
   succeeds with BLE still active. Repeat steps 3–5 five times and compare the
   same post-stop phase for heap, PSRAM and tasks. A finite late type-4 message
   without other symptoms fits this finding; continuing logs/tasks/heap loss,
   failed restart or `Wi-Fi stop failed.` would warrant further investigation.
6. Send `ble stop`; wait for completion, then record `ble status`, `d` after 10 s.
   Compare against the post-first-use both-off plateau, not the fresh-boot heap.

This does not claim long-term stability, AP-outage recovery or heavy traffic
performance. No new diagnostic code, delay or workaround was added.
