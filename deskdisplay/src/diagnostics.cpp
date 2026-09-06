#include "diagnostics.h"
#include <esp_heap_caps.h>
#include <esp_system.h>
#include <esp_timer.h>

void diagnostics::print(Print& out)
{
    Snapshot value;
    snapshot(value);
    out.printf("Uptime: %llu ms; reset reason: %d (esp_reset_reason_t)\n",
               static_cast<unsigned long long>(value.uptimeMs),
               static_cast<int>(esp_reset_reason()));
    out.printf("CPU: %s rev %u, %u cores, %u MHz; SDK: %s\n",
               ESP.getChipModel(), ESP.getChipRevision(), ESP.getChipCores(),
               ESP.getCpuFreqMHz(), ESP.getSdkVersion());
    out.printf("Internal heap: free=%u minimum=%u largest=%u bytes\n",
               value.internalFree, value.internalMinimum, value.internalLargest);
    out.printf("PSRAM: total=%u free=%u used=%u bytes\n",
               value.psramTotal, value.psramFree, value.psramTotal - value.psramFree);
    out.printf("Flash: %u bytes, %u Hz; sketch=%u bytes\n",
               ESP.getFlashChipSize(), ESP.getFlashChipSpeed(), ESP.getSketchSize());
}

void diagnostics::snapshot(Snapshot& value)
{
    constexpr uint32_t caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT;
    value.internalFree = heap_caps_get_free_size(caps);
    value.internalMinimum = heap_caps_get_minimum_free_size(caps);
    value.internalLargest = heap_caps_get_largest_free_block(caps);
    value.psramTotal = ESP.getPsramSize();
    value.psramFree = ESP.getFreePsram();
    value.uptimeMs = static_cast<uint64_t>(esp_timer_get_time() / 1000);
}
