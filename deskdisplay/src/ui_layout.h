#pragma once

#include <stdint.h>

namespace ui_layout
{
constexpr int16_t screenWidth = 480;

constexpr int16_t buttonHeight = 42;
constexpr int16_t pairedButtonWidth = 180;
constexpr int16_t leftButtonX = 12;
constexpr int16_t rightButtonX = 288;
constexpr int16_t homeCalendarY = 326;
constexpr int16_t homeTrainingY = 380;
constexpr int16_t homeTrainingTop(bool calendarVisible)
{
    return calendarVisible ? homeTrainingY : homeCalendarY;
}
constexpr int16_t homeSummaryHeight = 48;
constexpr int16_t homeMenuX = 360;
constexpr int16_t homeMenuY = 432;
constexpr int16_t homeMenuWidth = 100;
constexpr int16_t menuFirstRowY = 124;
constexpr int16_t menuSecondRowY = 204;
constexpr int16_t menuThirdRowY = 284;
constexpr int16_t homeAlarmY = 18;
constexpr int16_t alarmAdjustY = 224;
constexpr int16_t alarmOptionsY = 278;
constexpr int16_t alarmToggleY = 322;
constexpr int16_t systemButtonY = 426;
constexpr int16_t brightnessSliderX = 48;
constexpr int16_t brightnessSliderY = 342;
constexpr int16_t brightnessSliderWidth = 384;
constexpr int16_t brightnessSliderHeight = 64;
constexpr int16_t brightnessSliderHitPadding = 12;

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
