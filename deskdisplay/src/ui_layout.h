#pragma once

#include <stdint.h>

namespace ui_layout
{
constexpr int16_t screenWidth = 480;

constexpr int16_t buttonHeight = 42;
constexpr int16_t pairedButtonWidth = 180;
constexpr int16_t leftButtonX = 12;
constexpr int16_t rightButtonX = 288;
constexpr int16_t homeSummaryX = 20;
constexpr int16_t homeSummaryWidth = 440;
constexpr int16_t homeWorkoutY = 244;
constexpr int16_t homeWorkoutWidth = 214;
constexpr int16_t homeWorkoutHeight = 68;
constexpr int16_t homeUpcomingX = 246;
constexpr int16_t homeCalendarY = 326;
constexpr int16_t homeSummaryHeight = 48;
constexpr bool inHomeSummary(int16_t x, int16_t y, int16_t left, int16_t top,
                             int16_t width, int16_t height)
{
    return x >= left && x < left + width && y >= top && y < top + height;
}
constexpr int16_t homeClusterX = 20;
constexpr int16_t homeClusterY = 432;
constexpr int16_t homeClusterWidth = 300;
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
constexpr int16_t activityFirstRowY = 84;
constexpr int16_t activityRowStep = 64;
constexpr int16_t activityRowHeight = 56;
constexpr int16_t garminMetricWidth = 222;
constexpr int16_t garminMetricHeight = 88;
constexpr int16_t garminMetricX(uint8_t index) { return 12 + (index % 2) * 234; }
constexpr int16_t garminMetricY(uint8_t index) { return 122 + (index / 2) * 96; }
}
