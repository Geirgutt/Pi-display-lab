#pragma once
#include "app_state.h"

namespace ui
{
void begin(const app_state::Model& model);
void page(const app_state::Model& model);
void telemetry(const app_state::Model& model);
void touch(const app_state::Model& model);
void pressed(const app_state::Model& model);
void brightness(const app_state::Model& model);
}
