#pragma once

#include <stdint.h>

namespace ui_layout
{
constexpr int16_t screenWidth = 480;

constexpr int16_t buttonHeight = 42;
constexpr int16_t pairedButtonWidth = 180;
constexpr int16_t leftButtonX = 12;
constexpr int16_t rightButtonX = 288;
constexpr int16_t homeTopButtonY = 360;
constexpr int16_t homeBottomButtonY = 420;
constexpr int16_t systemButtonY = 426;
constexpr int16_t brightnessSliderX = 32;
constexpr int16_t brightnessSliderY = 342;
constexpr int16_t brightnessSliderWidth = 416;
constexpr int16_t brightnessSliderHeight = 64;

constexpr int16_t singleButtonWidth = 140;
constexpr int16_t singleButtonX = 170;
constexpr int16_t singleButtonY = 426;

constexpr int16_t trainingRowX = 20;
constexpr int16_t trainingRowWidth = 440;
constexpr int16_t trainingFirstRowY = 104;
constexpr int16_t trainingRowStep = 43;
constexpr int16_t trainingRowHeight = 39;
constexpr uint8_t trainingDayCount = 7;
}
