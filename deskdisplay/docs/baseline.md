# Hardware-confirmed baseline

Before edits on 2026-09-05: clean working tree at
`b7cf625e5472a5629c75fb0827636ff434c657b9` (sole commit,
“Working Guition display baseline”). User confirmed build/flash/display operation.
No device access was performed during this work.

Clean release build: `pio run -t clean`, then `pio run`.
Flash: **352925 bytes / 6553600 application partition bytes**.
Static RAM: **20300 bytes / 327680 bytes**.
Runtime internal heap and PSRAM: not measured (requires hardware).

Installed packages: espressif32 7.1.0; framework-arduinoespressif32
3.20017.241212+sha.dcc1105b (Arduino 2.0.17); LovyanGFX 1.2.28;
Xtensa ESP32-S3 GCC 8.4.0+2021r2-patch5; esptool 4.11.0.
No compiler warnings were observed in the baseline build.

`src/display.h` and all hardware settings in `platformio.ini` are authoritative.
Installed LovyanGFX `src/lgfx/v1/platforms/esp32s3/Bus_RGB.cpp` allocates
one framebuffer in PSRAM and DMA descriptors in internal DMA-capable heap.
At the existing 480×480 RGB565 configuration the framebuffer is 460800 bytes;
115 descriptors × 12 bytes = 1380 bytes. `Panel_RGB.cpp` also allocates
a 480-entry line-pointer array: 1920 internal DMA-capable bytes.
These figures exclude allocator/driver overhead.
Continuous RGB DMA/VSYNC activity exists even for a static image.

Repository inspection included every tracked file, ignored editor configuration,
directory inventory and the backup binary inventory. Backup flash images were
left untouched and not decoded for credentials; they are not source code.
