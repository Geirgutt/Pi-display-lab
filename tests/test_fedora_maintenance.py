"""Fedora command selection and reboot hints without changing any packages."""

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("fedora_reboot", ROOT / "scripts/fedora-reboot-status.py")
reboot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reboot)


class FedoraMaintenanceTests(unittest.TestCase):
    def test_dnf4_and_dnf5_use_the_correct_reboot_command(self):
        for dnf5 in (None, "/usr/bin/dnf5"):
            for code in (0, 1):
                with self.subTest(dnf5=dnf5, code=code), \
                        patch.object(reboot.shutil, "which", side_effect=lambda name: dnf5 if name == "dnf5" else "/usr/bin/dnf"), \
                        patch.object(reboot.subprocess, "run", side_effect=[
                            subprocess.CompletedProcess([], 0, "help", ""),
                            subprocess.CompletedProcess([], code, "hint", ""),
                        ]) as run:
                    self.assertEqual(reboot.reboot_status(), {"reboot_required": code == 1})
                    expected = [dnf5 or "/usr/bin/dnf", "needs-restarting"] + ([] if dnf5 else ["-r"])
                    self.assertEqual(run.call_args.args[0], expected)

    def test_missing_plugin_is_unknown_rather_than_reboot_required(self):
        with patch.object(reboot.shutil, "which", return_value="/usr/bin/dnf5"), \
                patch.object(reboot.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "Unknown command")) as run:
            self.assertIsNone(reboot.reboot_status()["reboot_required"])
            self.assertEqual(run.call_count, 1)

    def test_errors_are_unknown(self):
        for result in (subprocess.CompletedProcess([], 2, "", "error"),
                       subprocess.CompletedProcess([], 1, "", "failed to read process")):
            with patch.object(reboot.shutil, "which", return_value="dnf5"), \
                    patch.object(reboot.subprocess, "run", side_effect=[subprocess.CompletedProcess([], 0, "", ""), result]):
                self.assertIsNone(reboot.reboot_status()["reboot_required"])

    def test_update_only_skips_upgrade_and_after_queries_on_both_platforms(self):
        for platform in ("debian", "fedora"):
            tasks = yaml.safe_load((ROOT / f"ansible/maintenance-{platform}.yml").read_text(encoding="utf-8"))
            self.assertEqual(len(tasks), 7)
            guarded = {task["register"] for task in tasks if "when" in task}
            self.assertEqual(guarded, {"maintenance_upgrade_result", "maintenance_after", "maintenance_remaining"})
            for task in tasks:
                if "when" in task:
                    self.assertEqual(task["when"], "maintenance_upgrade | default(false) | bool")


if __name__ == "__main__":
    unittest.main()
