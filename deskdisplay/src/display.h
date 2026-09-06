#pragma once

#define LGFX_USE_V1

#include <LovyanGFX.hpp>
#include <lgfx/v1/platforms/esp32s3/Panel_RGB.hpp>
#include <lgfx/v1/platforms/esp32s3/Bus_RGB.hpp>

class LGFX : public lgfx::LGFX_Device
{
public:
    lgfx::Bus_RGB _bus_instance;
    lgfx::Panel_ST7701_guition_esp32_4848S040 _panel_instance;

    LGFX()
    {
        // RGB-bussen
        auto bus_cfg = _bus_instance.config();

        bus_cfg.panel = &_panel_instance;

        // Blå: 5 bit
        bus_cfg.pin_d0 = GPIO_NUM_4;
        bus_cfg.pin_d1 = GPIO_NUM_5;
        bus_cfg.pin_d2 = GPIO_NUM_6;
        bus_cfg.pin_d3 = GPIO_NUM_7;
        bus_cfg.pin_d4 = GPIO_NUM_15;

        // Grønn: 6 bit
        bus_cfg.pin_d5  = GPIO_NUM_8;
        bus_cfg.pin_d6  = GPIO_NUM_20;
        bus_cfg.pin_d7  = GPIO_NUM_3;
        bus_cfg.pin_d8  = GPIO_NUM_46;
        bus_cfg.pin_d9  = GPIO_NUM_9;
        bus_cfg.pin_d10 = GPIO_NUM_10;

        // Rød: 5 bit
        bus_cfg.pin_d11 = GPIO_NUM_11;
        bus_cfg.pin_d12 = GPIO_NUM_12;
        bus_cfg.pin_d13 = GPIO_NUM_13;
        bus_cfg.pin_d14 = GPIO_NUM_14;
        bus_cfg.pin_d15 = GPIO_NUM_0;

        // RGB styresignaler
        bus_cfg.pin_henable = GPIO_NUM_18;
        bus_cfg.pin_vsync   = GPIO_NUM_17;
        bus_cfg.pin_hsync   = GPIO_NUM_16;
        bus_cfg.pin_pclk    = GPIO_NUM_21;

        // Timing
        bus_cfg.freq_write = 16000000;

        bus_cfg.hsync_polarity    = 0;
        bus_cfg.hsync_front_porch = 10;
        bus_cfg.hsync_pulse_width = 8;
        bus_cfg.hsync_back_porch  = 50;

        bus_cfg.vsync_polarity    = 0;
        bus_cfg.vsync_front_porch = 10;
        bus_cfg.vsync_pulse_width = 8;
        bus_cfg.vsync_back_porch  = 20;

        bus_cfg.pclk_active_neg = 1;
        bus_cfg.pclk_idle_high  = 0;
        bus_cfg.de_idle_high    = 0;

        _bus_instance.config(bus_cfg);
        _panel_instance.setBus(&_bus_instance);

        // Panelstørrelse
        auto panel_cfg = _panel_instance.config();

        panel_cfg.memory_width  = 480;
        panel_cfg.memory_height = 480;
        panel_cfg.panel_width   = 480;
        panel_cfg.panel_height  = 480;

        _panel_instance.config(panel_cfg);

        // ST7701S initialiseres via 3-wire SPI
        auto detail_cfg = _panel_instance.config_detail();

        detail_cfg.pin_cs   = GPIO_NUM_39;
        detail_cfg.pin_sclk = GPIO_NUM_48;
        detail_cfg.pin_mosi = GPIO_NUM_47;

        // Legg framebuffer i PSRAM
        detail_cfg.use_psram = 2;

        _panel_instance.config_detail(detail_cfg);

        setPanel(&_panel_instance);
    }
};
