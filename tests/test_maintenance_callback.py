"""Exercise the maintenance callback without SSH, apt or a running Ansible."""

import importlib.util
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml

PROJECT_DIR = Path(__file__).resolve().parent.parent


def load_callback():
    # The real CallbackBase is not available on Windows. Stub only that import;
    # all callback routing and terminal rendering below use production code.
    class CallbackBase:
        def __init__(self):
            self._display = Mock()

    callback_api = types.ModuleType("ansible.plugins.callback")
    callback_api.CallbackBase = CallbackBase
    modules = {name: types.ModuleType(name) for name in ("ansible", "ansible.plugins")}
    modules["ansible.plugins.callback"] = callback_api
    spec = importlib.util.spec_from_file_location(
        "maintenance_callback_under_test", PROJECT_DIR / "ansible/callback_plugins/pi_maintenance.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class MaintenanceCallbackTests(unittest.TestCase):
    def setUp(self):
        self.module = load_callback()
        self.stream = io.StringIO()
        with patch.dict(os.environ, {
            "PI_DISPLAY_MAINTENANCE_WORKERS": json.dumps(["pi-one", "pi-two"]),
            "PI_DISPLAY_MAINTENANCE_UPGRADE": "1",
        }), patch("sys.stdout", self.stream):
            self.callback = self.module.CallbackModule()

    @staticmethod
    def result(register, data, no_log=False, host="pi-one"):
        return SimpleNamespace(
            _host=SimpleNamespace(get_name=lambda: host),
            _task=SimpleNamespace(register=register, no_log=no_log, get_name=lambda: "Pakkeoppgradering"),
            _result=data,
        )

    def test_playbook_results_produce_exact_changes_remaining_and_reboot_summary(self):
        plays = yaml.safe_load((PROJECT_DIR / "ansible/maintain-workers.yml").read_text(encoding="utf-8"))
        # ansible-core 2.21 serializes classic `register: name` as a mapping
        # from the variable name to `_task.POLYMORPHIC_RESULT_EXPRESSION`.
        task_registers = [
            {task["register"]: "_task.polymorphic_result"}
            for task in plays[1]["tasks"]
        ]
        results = [
            {"changed": True},
            {"stdout": "installed\topenssl\t1.0\n"},
            {"stdout": "Listing... Done\nopenssl/stable 1.1 arm64 [upgradable from: 1.0]\n"},
            {"changed": True, "stdout": "verbose apt output should not be dumped"},
            {"stdout": "installed\topenssl\t1.1\ninstalled\tnew-lib\t2.0\n"},
            {"stdout": "Listing... Done\n"},
            {"stat": {"exists": True}},
        ]
        self.assertEqual(len(task_registers), len(results))
        for register, data in zip(task_registers, results):
            result = self.result(register, data)
            self.callback.v2_playbook_on_task_start(result._task, False)
            self.callback.v2_runner_on_start(result._host, result._task)
            self.callback.v2_runner_on_ok(result)
        self.callback.v2_playbook_on_stats(None)
        text = self.stream.getvalue()
        self.assertIn("openssl 1.0 → 1.1", text)
        self.assertIn("new-lib 2.0 (ny installasjon)", text)
        self.assertIn("0 oppgraderinger gjenstår", text)
        self.assertIn("omstart kreves", text)
        self.assertIn("1 fullført, 0 feilet, 1 ufullstendig", text)
        self.assertNotIn("verbose apt output", text)

    def test_legacy_string_register_and_unrelated_projection_are_safe(self):
        task = SimpleNamespace(register="maintenance_reboot", get_name=lambda: "Reboot status")
        self.assertEqual(self.module.CallbackModule._stage_for_task(task), "reboot")

        projection = SimpleNamespace(register={"other_result": "_task.polymorphic_result"})
        self.assertIsNone(self.module.CallbackModule._stage_for_task(projection))

        stage_projection = SimpleNamespace(register={
            "other_result": "_task.polymorphic_result",
            "maintenance_reboot": "_task.polymorphic_result",
        })
        self.assertEqual(self.module.CallbackModule._stage_for_task(stage_projection), "reboot")

    def test_secret_task_failure_is_hidden_and_does_not_complete_the_node(self):
        result = self.result({"maintenance_upgrade_result": "_task.polymorphic_result"}, {
            "msg": "sensitive-password", "stdout": "sensitive-output", "stderr": "sensitive-stderr",
        }, no_log=True)
        self.callback.v2_runner_on_failed(result)
        self.callback.v2_playbook_on_stats(None)
        text = self.stream.getvalue()
        self.assertNotIn("sensitive", text)
        self.assertIn("Detaljer er skjult", text)
        self.assertIn("0 fullført, 1 feilet, 1 ufullstendig", text)

    def test_connection_failure_keeps_diagnostics_and_pending_nodes(self):
        self.callback.v2_runner_on_unreachable(self.result(None, {"msg": "SSH: Connection refused"}))
        self.callback.v2_playbook_on_stats(None)
        self.assertIn("SSH: Connection refused", self.stream.getvalue())
        self.assertIn("pi-two: ufullstendig", self.stream.getvalue())

    def test_hidden_package_snapshots_are_reported_as_unknown(self):
        for register in ("maintenance_before", "maintenance_after", "maintenance_remaining"):
            self.callback.v2_runner_on_ok(self.result(register, {"_ansible_no_log": True, "stdout": "secret"}))
        self.callback.v2_playbook_on_stats(None)
        text = self.stream.getvalue()
        self.assertNotIn("secret", text)
        self.assertIn("ukjent nye pakker; ukjent oppgradert; ukjent oppgraderinger gjenstår", text)


if __name__ == "__main__":
    unittest.main()
