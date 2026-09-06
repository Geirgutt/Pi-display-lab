"""Exercise complete wizard decisions with installation and network calls replaced."""

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from setup_cluster import DetectedValues, build_controller_config, run_wizard, setup_firewall


class WizardFlowTests(unittest.TestCase):
    def run_add(self, outdated=False, approve_update=True, install_result=0, remove=False, heartbeat=True):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            config_path = root / "config.local.json"
            original = build_controller_config("controller.example", "labuser", ["one.example", "two.example"])
            original["node_heartbeat_auth"] = heartbeat
            config_path.write_text(json.dumps(original), encoding="utf-8")
            detected = DetectedValues("labuser", "controller", "192.0.2.1", root, "main", "a" * 7, ())
            stack.enter_context(patch("setup_cluster.os", SimpleNamespace(name="posix", geteuid=lambda: 1000, chmod=os.chmod)))
            stack.enter_context(patch("setup_cluster.sys.platform", "linux"))
            stack.enter_context(patch("setup_cluster.detect_values", return_value=detected))
            stack.enter_context(patch("setup_cluster.run_text", side_effect=lambda command, *args: "" if "status" in command else "a" * 40))
            stack.enter_context(patch("setup_cluster.inspect_worker", side_effect=lambda user, host, identity: {
                "hostname": host.split('.')[0], "machine_id": "b" * 32,
                "revision": "b" * 40 if outdated and host == "one.example" else "a" * 40,
            }))
            prepare = stack.enter_context(patch("setup_cluster.prepare_workers", return_value={"three.example": "test-private"}))
            stack.enter_context(patch("setup_cluster.prepare_removal", return_value={"two.example": "test-remove"}))
            stop = stack.enter_context(patch("setup_cluster.stop_removed_workers", return_value=True))
            stack.enter_context(patch("setup_cluster._preflight", return_value={h: h for h in ["one.example", "two.example", "three.example"]}))
            stack.enter_context(patch("setup_cluster.inspect_pki", return_value=SimpleNamespace(ca_exists=False, ca_is_valid=False, server_exists=False)))
            stack.enter_context(patch("setup_cluster.detect_port_listener", return_value=None))
            stack.enter_context(patch("setup_cluster.old_prototype_files", return_value=()))
            stack.enter_context(patch("setup_cluster.setup_firewall"))
            stack.enter_context(patch("setup_cluster.PasswordBroker", side_effect=lambda path, values: nullcontext(SimpleNamespace(path=path))))
            run = stack.enter_context(patch("setup_cluster.subprocess.run", return_value=subprocess.CompletedProcess([], install_result)))
            stack.enter_context(patch("builtins.print"))
            answers = ["6", "2", "j"] if remove else ["3", "1", "three.example"]
            if outdated:
                answers += ["j" if approve_update else "n"]
            answers += ["j"]
            responses = iter(answers)
            code = run_wizard(root, lambda _: next(responses))
            if remove and install_result == 0:
                stop.assert_called_once()
                self.assertEqual(stop.call_args.args[0]["worker_hosts"], ["one.example"])
                self.assertEqual(stop.call_args.args[1], {"two.example": "test-remove"})
            else:
                stop.assert_not_called()
            return code, json.loads(config_path.read_text()), prepare.call_args, run.call_args, original

    def test_two_existing_workers_plus_one_installs_only_the_new_worker(self):
        code, config, prepare, run, original = self.run_add()
        self.assertEqual(code, 0)
        self.assertEqual(config["worker_hosts"], ["one.example", "two.example", "three.example"])
        self.assertEqual(config["cluster"], original["cluster"])
        self.assertEqual(prepare.args[1], ["three.example"])
        command = run.args[0]
        self.assertEqual(command[command.index("--limit-worker") + 1], "three.example")
        self.assertEqual(command.count("--limit-worker"), 1)
        self.assertIn("--sudo-socket", command)
        self.assertNotIn("test-private", " ".join(command))

    def test_outdated_existing_worker_is_included_only_after_approval(self):
        code, _, prepare, run, _ = self.run_add(outdated=True)
        self.assertEqual(code, 0)
        self.assertEqual(prepare.args[1], ["one.example", "three.example"])
        self.assertEqual(run.args[0].count("--limit-worker"), 2)
        code, config, prepare, run, original = self.run_add(outdated=True, approve_update=False)
        self.assertEqual(code, 0)
        self.assertEqual(config, original)
        self.assertIsNone(prepare)
        self.assertIsNone(run)

    def test_failed_install_preserves_complete_config_for_retry(self):
        code, config, _, _, _ = self.run_add(install_result=2)
        self.assertEqual(code, 2)
        self.assertEqual(config["worker_hosts"], ["one.example", "two.example", "three.example"])

    def test_membership_changes_preserve_heartbeat_settings_on_untouched_workers(self):
        for remove in (True, False):
            code, config, _, _, _ = self.run_add(remove=remove, heartbeat=False)
            self.assertEqual(code, 0)
            self.assertIs(config["node_heartbeat_auth"], False)

    def test_removal_preserves_other_nodes_and_stops_only_after_controller_success(self):
        code, config, prepare, run, _ = self.run_add(remove=True)
        self.assertEqual(code, 0)
        self.assertEqual(config["worker_hosts"], ["one.example"])
        self.assertEqual(prepare.args[1], [])
        self.assertIn("--controller-only", run.args[0])
        self.assertNotIn("--limit-worker", run.args[0])
        self.assertEqual(self.run_add(remove=True, install_result=2)[0], 2)

    @patch("setup_cluster.subprocess.run")
    @patch("setup_cluster.run_text", side_effect=["running", "public\n  interfaces: eth0"])
    @patch("setup_cluster.shutil.which", return_value="/usr/bin/firewall-cmd")
    def test_firewalld_changes_require_explicit_approval(self, which, text, run):
        answers = iter(["public", "n"])
        setup_firewall({"app_port": 5000, "coordinator_port": 5001}, lambda _: next(answers))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
