#pragma once
#include <stdint.h>
#include "diagnostics.h"
#include "secure_protocol.h"

namespace app_state
{
enum class Page : uint8_t { Home, Cluster, Training, TrainingDetail, Calendar, System };

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
    uint8_t brightnessPercent = 100;
    bool nightMode = false;
    bool timeValid = false;
    char clockText[6] = "--:--";
    char dateText[24] = "--.--.----";
    secure_protocol::Telemetry nodeTelemetry{};
    secure_protocol::ClusterTelemetry clusterTelemetry{};
    secure_protocol::TrainingTelemetry trainingTelemetry{};
    secure_protocol::CalendarTelemetry calendarTelemetry{};
    uint32_t nodeLastUpdate = 0;
    uint32_t nodeAccepted = 0;
    bool nodeOnline = false;
};
}
