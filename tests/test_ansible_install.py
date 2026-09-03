"""Optional local Ansible integration tests; no SSH, sudo or real nodes involved."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cluster_install import PasswordBroker

PROJECT_DIR = Path(__file__).resolve().parent.parent
ANSIBLE = shutil.which("ansible-playbook")


@unittest.skipUnless(ANSIBLE and os.name != "nt", "Requires Ansible on Linux")
class AnsibleInstallTests(unittest.TestCase):
    def run_play(self, play, passwords):
        import yaml

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory.ini"
            inventory.write_text(
                "[cluster_workers]\n"
                "one.example ansible_connection=local\n"
                "two.example ansible_connection=local\n", encoding="utf-8",
            )
            marker = root / "must-not-exist"
            play.setdefault("vars", {})["test_marker"] = str(marker)
            playbook = root / "play.yml"
            playbook.write_text(yaml.safe_dump([play]), encoding="utf-8")
            environment = dict(os.environ, ANSIBLE_LOOKUP_PLUGINS=str(PROJECT_DIR / "ansible/lookup_plugins"))
            with PasswordBroker(root / "sudo.sock", passwords) as broker:
                result = subprocess.run(
                    [ANSIBLE, "-i", str(inventory), str(playbook), "--forks", "2",
                     "--extra-vars", json.dumps({"worker_sudo_socket": str(broker.path)})],
                    stdin=subprocess.DEVNULL, env=environment, text=True, capture_output=True, timeout=60,
                )
            return result, marker.exists()

    def production_play_settings(self):
        import yaml

        play = yaml.safe_load((PROJECT_DIR / "ansible/install-workers.yml").read_text(encoding="utf-8"))[0]
        return {key: play[key] for key in ("hosts", "strategy", "any_errors_fatal", "vars")}

    def test_socket_passwords_are_literal_and_resolve_per_host(self):
        passwords = {"one.example": 'test-{{ lookup("env", "HOME") }}: \\ " æ', "two.example": ""}
        play = self.production_play_settings()
        play["gather_facts"] = False
        play["vars"]["expected"] = {host: hashlib.sha256(value.encode()).hexdigest() for host, value in passwords.items()}
        play["tasks"] = [{
            "name": "Check literal per-host password via local socket",
            "ansible.builtin.assert": {"that": ["ansible_become_password | hash('sha256') == expected[inventory_hostname]"]},
            "no_log": True,
        }]
        result, _ = self.run_play(play, passwords)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(passwords["one.example"], result.stdout + result.stderr)

    def test_one_preflight_failure_prevents_tasks_on_every_host(self):
        play = self.production_play_settings()
        play["gather_facts"] = False
        play["pre_tasks"] = [{
            "ansible.builtin.assert": {"that": ["inventory_hostname != 'one.example'"]},
        }]
        play["tasks"] = [{"ansible.builtin.file": {"path": "{{ test_marker }}", "state": "touch"}}]
        result, marker_exists = self.run_play(play, {"one.example": "", "two.example": ""})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Assertion failed", result.stdout)
        self.assertFalse(marker_exists, result.stdout + result.stderr)

    def test_production_worker_playbook_syntax(self):
        result = subprocess.run(
            [ANSIBLE, "--syntax-check", "-i", "localhost,", str(PROJECT_DIR / "ansible/install-workers.yml")],
            text=True, capture_output=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
