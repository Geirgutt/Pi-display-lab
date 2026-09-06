#pragma once
#ifndef DESKDISPLAY_BLE
#define DESKDISPLAY_BLE 0
#endif

#if DESKDISPLAY_BLE
namespace ble_test
{
// Arduino loop task only; GAP callback merely posts completion results.
void start();
void stop();
void service();
void printStatus();
}
#endif
