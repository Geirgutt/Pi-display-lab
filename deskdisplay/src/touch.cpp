#include "touch.h"
#include <LovyanGFX.hpp>
#include <driver/i2c.h>

namespace
{
lgfx::Touch_GT911 controller;
bool ready = false;
}

bool touch::begin()
{
    // Exact-board references and installed-driver behavior: docs/foundation.md.
    // No reset or interrupt pin is assigned by those board examples.
    auto cfg = controller.config();
    cfg.pin_sda = 19;
    cfg.pin_scl = 45;
    cfg.pin_int = -1;
    cfg.pin_rst = -1;
    cfg.i2c_port = I2C_NUM_1;
    cfg.freq = 400000;
    cfg.bus_shared = false;
    // Keep the driver's default address and its 0x14/0x5D detection.
    // Read raw coordinates until physical alignment is confirmed; no guessed
    // calibration, axis inversion or change to the working display rotation.
    controller.config(cfg);
    ready = controller.init();
    return ready;
}

bool touch::read(Point& point)
{
    if (!ready) return false;
    lgfx::touch_point_t raw;
    if (!controller.getTouchRaw(&raw, 1)) return false;
    point = {raw.x, raw.y};
    return true;
}
