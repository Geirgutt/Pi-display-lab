#include "diagnostics.h"
#include <esp_heap_caps.h>
#include <esp_system.h>
#include <esp_timer.h>

void diagnostics::print(Print& out)
{
    constexpr uint32_t caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
    out.printf("Uptime: %llu ms; reset reason: %d (esp_reset_reason_t)\n",
               static_cast<unsigned long long>(esp_timer_get_time() / 1000),
               static_cast<int>(esp_reset_reason()));
    out.printf("CPU: %s rev %u, %u cores, %u MHz; SDK: %s\n",
               ESP.getChipModel(), ESP.getChipRevision(), ESP.getChipCores(),
               ESP.getCpuFreqMHz(), ESP.getSdkVersion());
    out.printf("Internal heap: free=%u minimum=%u largest=%u bytes\n",
               heap_caps_get_free_size(caps), heap_caps_get_minimum_free_size(caps),
               heap_caps_get_largest_free_block(caps));
    out.printf("PSRAM: total=%u free=%u used=%u bytes\n",
               ESP.getPsramSize(), ESP.getFreePsram(),
               ESP.getPsramSize() - ESP.getFreePsram());
    out.printf("Flash: %u bytes, %u Hz; sketch=%u bytes\n",
               ESP.getFlashChipSize(), ESP.getFlashChipSpeed(), ESP.getSketchSize());
}
