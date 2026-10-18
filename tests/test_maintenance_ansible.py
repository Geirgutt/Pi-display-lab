"""Run the real callback on local synthetic jobs; never run apt or sudo."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PROJECT_DIR = Path(__file__).resolve().parent.parent
ANSIBLE = shutil.which("ansible-playbook")
WORKERS = ["pi-one", "pi-two", "pi-three", "pi-four"]


@unittest.skipUnless(ANSIBLE and os.name != "nt", "Requires Ansible on Linux")
class MaintenanceAnsibleTests(unittest.TestCase):
    def run_local_maintenance(self, fail_worker=None):
        original = yaml.safe_load((PROJECT_DIR / "ansible/maintain-workers.yml").read_text(encoding="utf-8"))[1]
        outputs = {
            "maintenance_refresh": "",
            "maintenance_before": "installed\tdemo-package\t1.0\n",
            "maintenance_available": "Listing...\ndemo-package/stable 2.0 arm64 [upgradable from: 1.0]\n",
            "maintenance_upgrade_result": "",
            "maintenance_after": "installed\tdemo-package\t2.0\n",
            "maintenance_remaining": "Listing...\n",
        }
        tasks = []
        for task in original["tasks"]:
            register = task["register"]
            synthetic = {"name": task["name"], "register": register}
            if register == "maintenance_reboot":
                synthetic["ansible.builtin.stat"] = {"path": "/does-not-exist-pi-maintenance-test"}
            else:
                synthetic["ansible.builtin.command"] = {
                    "argv": [sys.executable, "-c", f"print({outputs[register]!r})"],
                }
                synthetic["changed_when"] = False
                if fail_worker and register == "maintenance_upgrade_result":
                    synthetic["failed_when"] = f"inventory_hostname == '{fail_worker}'"
            tasks.append(synthetic)
        play = {
            "name": "Synthetic maintenance without package changes",
            "hosts": "cluster_workers", "gather_facts": False,
            "serial": original["serial"], "any_errors_fatal": original["any_errors_fatal"],
            "vars": {"maintenance_parallel": 3}, "tasks": tasks,
        }
        environment = dict(os.environ, ANSIBLE_STDOUT_CALLBACK="pi_maintenance",
                           ANSIBLE_CALLBACK_PLUGINS=str(PROJECT_DIR / "ansible/callback_plugins"),
                           PI_DISPLAY_MAINTENANCE_WORKERS=json.dumps(WORKERS),
                           PI_DISPLAY_MAINTENANCE_UPGRADE="1", ANSIBLE_NOCOLOR="1")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory.ini"
            inventory.write_text("[cluster_workers]\n" + "\n".join(WORKERS) +
                                 "\n[cluster_workers:vars]\nansible_connection=local\n" +
                                 f"ansible_python_interpreter={sys.executable}\n", encoding="utf-8")
            playbook = root / "play.yml"
            playbook.write_text(yaml.safe_dump([play]), encoding="utf-8")
            return subprocess.run(
                [ANSIBLE, "-i", str(inventory), str(playbook), "--forks", "3"],
                env=environment, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90,
            )

    def test_real_registered_tasks_report_all_nodes_without_callback_warnings(self):
        result = self.run_local_maintenance()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Callback dispatch", result.stderr)
        self.assertIn("4 fullført, 0 feilet, 0 ufullstendig", result.stdout)
        for worker in WORKERS:
            self.assertIn(f"{worker}: ferdig; 0 nye pakker; 1 oppgradert", result.stdout)
        self.assertIn("demo-package 1.0 → 2.0", result.stdout)

    def test_failure_in_first_batch_prevents_next_batch(self):
        result = self.run_local_maintenance(fail_worker="pi-two")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Callback dispatch", result.stderr)
        self.assertIn("pi-two: feilet", result.stdout)
        self.assertIn("pi-four: ufullstendig", result.stdout)
        self.assertNotIn("pi-four: oppdaterer pakkelister", result.stdout)


if __name__ == "__main__":
    unittest.main()
