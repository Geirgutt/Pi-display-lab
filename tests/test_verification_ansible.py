"""Read-only verification must not need writable Ansible staging on a worker."""

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = shutil.which("ansible-playbook")


def production_play():
    return yaml.safe_load((ROOT / "ansible/verify-workers.yml").read_text(encoding="utf-8"))[0]


class VerificationCommandTests(unittest.TestCase):
    def test_raw_paths_strip_line_endings_and_quote_whole_arguments(self):
        play = production_play()
        home = "/home/worker's home"
        context = {"worker_home": SimpleNamespace(stdout=home + "\r\n"),
                   "item": "cluster-worker.service"}
        environment = Environment(undefined=StrictUndefined)
        environment.filters["quote"] = shlex.quote
        remote = [task for task in play["pre_tasks"] + play["tasks"] if "ansible.builtin.raw" in task]
        commands = [shlex.split(environment.from_string(task["ansible.builtin.raw"]).render(context))
                    for task in remote]
        self.assertEqual(commands[1], ["git", "-C", home + "/Pi-display-lab", "rev-parse", "HEAD"])
        self.assertEqual(commands[2], ["systemctl", "is-active", "cluster-worker.service"])
        self.assertEqual(commands[3], [home + "/Pi-display-lab/.venv/bin/python", "-B",
                                     home + "/Pi-display-lab/scripts/verify-worker.py",
                                     home + "/Pi-display-lab/config.local.json"])

    def test_revision_comparison_accepts_raw_crlf_but_rejects_other_commit(self):
        assertion = next(task["ansible.builtin.assert"]["that"][0]
                         for task in production_play()["tasks"] if "ansible.builtin.assert" in task)
        evaluate = Environment(undefined=StrictUndefined).compile_expression(assertion)
        self.assertTrue(evaluate(worker_revision=SimpleNamespace(stdout="abc123\r\n"), project_version="abc123"))
        self.assertFalse(evaluate(worker_revision=SimpleNamespace(stdout="other\r\n"), project_version="abc123"))


@unittest.skipUnless(ANSIBLE and os.name == "posix", "Requires Ansible on Linux")
class WorkerVerificationAnsibleTests(unittest.TestCase):
    def run_verification(self, *, wrong_revision=False, inactive=False):
        with tempfile.TemporaryDirectory(prefix="verify-worker-") as directory:
            root = Path(directory)
            home = root / "worker's home"
            project = home / "Pi-display-lab"
            (project / ".venv/bin").mkdir(parents=True)
            (project / "scripts").mkdir()
            (project / ".venv/bin/python").symlink_to(sys.executable)
            (project / "config.local.json").write_text("{}")
            (project / "scripts/verify-worker.py").write_text(
                "import pathlib, sys\nassert sys.dont_write_bytecode\n"
                "assert pathlib.Path(sys.argv[1]).is_file()\nprint('TLS_IDENTITY_VERIFIED')\n")
            tools = root / "tools"
            tools.mkdir()
            (tools / "git").write_text(
                '#!/bin/sh\n[ "$1" = "-C" ] && [ "$2" = "$TEST_WORKER_PROJECT" ] || exit 2\n'
                'printf "%s\\n" "$TEST_WORKER_REVISION"\n')
            (tools / "systemctl").write_text(
                '#!/bin/sh\n[ "$1" = "is-active" ] || exit 2\n'
                '[ "$2" != "$TEST_INACTIVE_SERVICE" ]\n')
            for executable in tools.iterdir():
                executable.chmod(0o700)
            play = production_play()
            play["vars"] = {"project_version": "a" * 40,
                            "ansible_remote_tmp": "/proc/pi-display-unwritable"}
            playbook = root / "verify.yml"
            playbook.write_text(yaml.safe_dump([play]))
            inventory = root / "inventory.ini"
            inventory.write_text("[cluster_workers]\nlocalhost ansible_connection=local\n")
            environment = dict(os.environ, HOME=str(home), PATH=str(tools) + os.pathsep + os.environ["PATH"],
                               ANSIBLE_LOCAL_TEMP=str(root / "controller-tmp"),
                               ANSIBLE_NOCOLOR="1", ANSIBLE_STDOUT_CALLBACK="default",
                               TEST_WORKER_PROJECT=str(project),
                               TEST_WORKER_REVISION=("b" if wrong_revision else "a") * 40,
                               TEST_INACTIVE_SERVICE="cluster-worker.service" if inactive else "")
            result = subprocess.run([ANSIBLE, "-i", str(inventory), str(playbook)], cwd=root,
                                    env=environment, capture_output=True, text=True, timeout=50)
            self.assertFalse((home / ".ansible/tmp").exists())
            return result.returncode, result.stdout + result.stderr

    def test_checks_succeed_with_unwritable_remote_tmp(self):
        code, output = self.run_verification()
        self.assertEqual(code, 0, output)
        self.assertIn("failed=0", output)
        self.assertIn("changed=0", output)

    def test_wrong_revision_is_still_rejected(self):
        code, output = self.run_verification(wrong_revision=True)
        self.assertNotEqual(code, 0, output)
        self.assertIn("eksakte Git-revisjon", output)

    def test_inactive_worker_service_is_still_rejected(self):
        code, output = self.run_verification(inactive=True)
        self.assertNotEqual(code, 0, output)
        self.assertIn("cluster-worker.service", output)
