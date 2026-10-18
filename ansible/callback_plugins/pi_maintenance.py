"""Readable progress and package reports for maintain-workers.sh only."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from ansible.plugins.callback import CallbackBase

# Ansible loads this plugin by file path, independently of the controller's
# application environment. The renderer is pure Python and needs no extra pip deps.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from maintenance_output import MaintenanceOutput  # noqa: E402

DOCUMENTATION = r'''
name: pi_maintenance
type: stdout
short_description: Show worker maintenance progress and package version changes
description:
  - Enabled only by the worker maintenance launcher.
  - Reports completed stages, elapsed waiting time and measured package changes.
'''

STAGES = {
    "maintenance_refresh": "refresh",
    "maintenance_before": "before",
    "maintenance_available": "available",
    "maintenance_upgrade_result": "upgrade",
    "maintenance_after": "after",
    "maintenance_remaining": "remaining",
    "maintenance_reboot": "reboot",
}


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "stdout"
    CALLBACK_NAME = "pi_maintenance"

    def __init__(self):
        super().__init__()
        self.output = MaintenanceOutput(
            json.loads(os.environ.get("PI_DISPLAY_MAINTENANCE_WORKERS", "[]")),
            os.environ.get("PI_DISPLAY_MAINTENANCE_UPGRADE") == "1",
        )
        self._display.display("Fremdriftslinjene viser fullførte trinn og noder. Ventetid vises mens apt jobber.")

    def v2_playbook_on_play_start(self, play):
        self._display.display(f"\n{play.get_name()}")

    def v2_playbook_on_task_start(self, task, is_conditional):
        if self._stage_for_task(task) is None:
            self._display.display(f"  {task.get_name()}")

    def v2_runner_on_start(self, host, task):
        stage = self._stage_for_task(task)
        if stage:
            self.output.start(host.get_name(), stage)

    def v2_runner_on_ok(self, result):
        stage = self._stage_for_task(result._task)
        if stage:
            self.output.result(result._host.get_name(), stage, self._public_result(result))
        else:
            self._display.display(f"  OK: {result._host.get_name()}")

    def v2_runner_on_skipped(self, result):
        stage = self._stage_for_task(result._task)
        if stage:
            self.output.result(result._host.get_name(), stage, {}, skipped=True)

    @staticmethod
    def _stage_for_task(task):
        """Resolve a maintenance stage across Ansible's string and projection forms."""
        register = getattr(task, "register", None)
        if isinstance(register, str):
            return STAGES.get(register)
        if isinstance(register, Mapping):
            stages = {
                STAGES[key]
                for key in register
                if isinstance(key, str) and key in STAGES
            }
            if len(stages) == 1:
                return stages.pop()
        return None

    def _public_result(self, result):
        data = result._result
        if data.get("_ansible_no_log") or getattr(result._task, "no_log", False):
            return {"msg": "Detaljer er skjult for denne oppgaven."}
        return data

    def _failure(self, result):
        data = self._public_result(result)
        message = str(data.get("msg") or "Oppgaven feilet.")
        for key in ("stderr", "stdout"):
            if data.get(key):
                message += "\n" + str(data[key])
        self.output.fail(result._host.get_name(), f"{result._task.get_name()}: {message}")

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._failure(result)

    def v2_runner_on_unreachable(self, result):
        self._failure(result)

    def v2_playbook_on_stats(self, stats):
        self.output.finish()
