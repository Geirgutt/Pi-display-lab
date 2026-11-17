#pragma once
#include <stdint.h>
#include "diagnostics.h"
#include "secure_protocol.h"
#include "alarm_input.h"

namespace app_state
{
enum class Page : uint8_t { Home, Cluster, Training, TrainingDetail, Calendar, System, Alarm, Menu, AlarmNumber, Spotify, Garmin, ActivityHistory, ActivityDetail, GarminMetricDetail };
enum class ActivityView : uint8_t { Summary, Charts, Laps, Map };

constexpr uint8_t activityPageSize = 5;
constexpr uint8_t lapsPageSize = 6;

struct Model
{
    Page page = Page::Home;
    diagnostics::Snapshot diagnostics{};
    bool wifiActive = false;
    bool wifiConnected = false;
    uint8_t wifiStatus = 0;
    int32_t wifiRssi = 0;
    char ip[16] = "-";
    bool touchDown = false;
    int16_t touchX = -1;
    int16_t touchY = -1;
    uint8_t pressedButton = 0;
    uint8_t selectedTraining = 0;
    uint8_t selectedGarmin = 0;
    int8_t nextTraining = -1;
    int8_t nextCalendar = -1;
    uint8_t brightnessPercent = 100;
    bool nightMode = false;
    bool alarmEnabled = false;
    uint8_t alarmHour = 23;
    uint8_t alarmMinute = 0;
    bool alarmRepeats = true;
    uint8_t alarmMethod = 0;
    bool alarmEditingHour = true;
    alarm_input::Editor alarmInput{};
    bool timeValid = false;
    char clockText[6] = "--:--";
    char dateText[24] = "--.--.----";
    secure_protocol::Telemetry nodeTelemetry{};
    secure_protocol::ClusterTelemetry clusterTelemetry{};
    secure_protocol::TrainingTelemetry trainingTelemetry{};
    secure_protocol::CalendarTelemetry calendarTelemetry{};
    secure_protocol::SpotifyTelemetry spotifyTelemetry{};
    secure_protocol::GarminTelemetry garminTelemetry{};
    secure_protocol::ActivityTelemetry activities{};
    secure_protocol::Activity selectedActivity{};
    bool activityFromHome = false;
    ActivityView activityView = ActivityView::Summary;
    bool extraActivityCharts = false;
    uint8_t lapOffset = 0;
    secure_protocol::GarminMetric selectedGarminMetric{};
    uint32_t garminMetricHistoryEnd = 0;
    uint32_t activityRevision = 0;
    uint8_t activityPage = 0;
    uint8_t activityOffset() const
    {
        return activityPage && activities.count > activityPageSize ? activityPageSize : 0;
    }
    uint8_t garminPageCount() const
    {
        uint8_t cards = 0;
        for (uint8_t i = 0; i < garminTelemetry.count; ++i)
            cards += garminTelemetry.groups[i].count;
        return (cards + secure_protocol::garminMetricMax - 1) / secure_protocol::garminMetricMax;
    }
    uint8_t garminPage() const
    {
        const uint8_t pages = garminPageCount();
        return pages ? selectedGarmin % pages : 0;
    }
    const secure_protocol::GarminMetric* garminCard(uint8_t slot, const char** groupTitle = nullptr) const
    {
        uint8_t index = garminPage() * secure_protocol::garminMetricMax + slot;
        for (uint8_t i = 0; i < garminTelemetry.count; ++i)
        {
            const auto& group = garminTelemetry.groups[i];
            if (index < group.count)
            {
                if (groupTitle) *groupTitle = group.title;
                return &group.metrics[index];
            }
            index -= group.count;
        }
        return nullptr;
    }
    bool spotifyConnected = false;
    bool garminConnected = false;
    uint32_t nodeLastUpdate = 0;
    uint32_t nodeAccepted = 0;
    bool nodeOnline = false;
};
}
