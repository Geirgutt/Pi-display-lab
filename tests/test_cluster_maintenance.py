"""Focused orchestration tests for cluster maintenance (no real nodes)."""

import json
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cluster_install
import cluster_maintenance

PROJECT_DIR = Path(__file__).resolve().parent.parent
REAL_TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory


def project_temp_directory(*, prefix):
    return REAL_TEMPORARY_DIRECTORY(prefix=prefix, dir=PROJECT_DIR)


def controller_settings(workers=("one.example", "two.example")):
    return SimpleNamespace(
        ssh_user="labuser",
        ssh_identity_file="/keys/lab",
        worker_hosts=workers,
    )


class ClusterMaintenanceTests(unittest.TestCase):
    def test_unknown_worker_is_rejected_before_credentials_or_commands(self):
        with patch.object(cluster_maintenance, "validate_controller_config", return_value=controller_settings()), \
                patch.object(cluster_maintenance, "collect_passwords") as collect, \
                patch.object(cluster_maintenance.subprocess, "run") as run:
            result = cluster_maintenance.main(["--worker", "missing.example"])

        self.assertEqual(result, 1)
        collect.assert_not_called()
        run.assert_not_called()

    def test_empty_worker_selection_is_rejected_before_credentials_or_commands(self):
        with patch.object(cluster_maintenance, "validate_controller_config", return_value=controller_settings(())), \
                patch.object(cluster_maintenance, "collect_passwords") as collect, \
                patch.object(cluster_maintenance.subprocess, "run") as run:
            result = cluster_maintenance.main([])

        self.assertEqual(result, 1)
        collect.assert_not_called()
        run.assert_not_called()

    def test_sudo_failure_prevents_ansible_playbook(self):
        with patch.object(cluster_maintenance, "collect_passwords", side_effect=RuntimeError("sudo rejected")), \
                patch.object(cluster_maintenance.shutil, "which", return_value="ansible-playbook"), \
                patch.object(cluster_maintenance.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "sudo rejected"):
                cluster_maintenance.run_maintenance(controller_settings(), ["one.example"], False)

        run.assert_not_called()

    def test_invalid_parallel_values_are_rejected_before_credentials(self):
        for parallel in (0, -1, 101):
            with self.subTest(parallel=parallel), \
                    patch.object(cluster_maintenance, "collect_passwords") as collect:
                with self.assertRaisesRegex(RuntimeError, "parallel"):
                    cluster_maintenance.run_maintenance(
                        controller_settings(), ["one.example"], False, parallel=parallel,
                    )
                collect.assert_not_called()

    def test_cli_rejects_parallel_outside_one_to_one_hundred(self):
        for parallel in ("0", "-1", "101"):
            with self.subTest(parallel=parallel), \
                    patch.object(cluster_maintenance, "validate_controller_config") as validate:
                with self.assertRaises(SystemExit):
                    cluster_maintenance.main(["--parallel", parallel])
                validate.assert_not_called()

    def test_ansible_nonzero_status_is_returned(self):
        completed = subprocess.CompletedProcess(["ansible-playbook"], 17)
        with patch.object(cluster_maintenance.os, "chmod"), \
                patch.object(cluster_maintenance.tempfile, "TemporaryDirectory", side_effect=project_temp_directory), \
                patch.object(cluster_maintenance, "collect_passwords", return_value={"one.example": ""}), \
                patch.object(cluster_maintenance, "PasswordBroker", return_value=nullcontext(SimpleNamespace(path="/private/sudo.sock"))), \
                patch.object(cluster_maintenance.shutil, "which", return_value="ansible-playbook"), \
                patch.object(cluster_maintenance.subprocess, "run", return_value=completed):
            result = cluster_maintenance.run_maintenance(controller_settings(), ["one.example"], False)

        self.assertEqual(result, 17)

    def test_default_main_runs_all_workers_without_upgrade(self):
        settings = controller_settings(("one.example", "two.example"))
        with patch.object(cluster_maintenance, "validate_controller_config", return_value=settings) as validate, \
                patch.object(cluster_maintenance, "run_maintenance", return_value=0) as maintain, \
                patch("builtins.input", return_value="") as prompt, \
                patch("sys.argv", ["cluster-maintenance"]):
            result = cluster_maintenance.main()

        self.assertEqual(result, 0)
        validate.assert_called_once_with(PROJECT_DIR / "config.local.json")
        maintain.assert_called_once_with(settings, ["one.example", "two.example"], False, 3)
        prompt.assert_called_once()

    def test_prompt_accepts_yes_for_upgrade(self):
        settings = controller_settings()
        with patch.object(cluster_maintenance, "validate_controller_config", return_value=settings), \
                patch.object(cluster_maintenance, "run_maintenance", return_value=0) as maintain, \
                patch("builtins.input", return_value="yes") as prompt:
            result = cluster_maintenance.main([])

        self.assertEqual(result, 0)
        maintain.assert_called_once_with(settings, ["one.example", "two.example"], True, 3)
        prompt.assert_called_once()

    def test_prompt_retries_invalid_answer_then_accepts_no(self):
        settings = controller_settings()
        with patch.object(cluster_maintenance, "validate_controller_config", return_value=settings), \
                patch.object(cluster_maintenance, "run_maintenance", return_value=0) as maintain, \
                patch("builtins.input", side_effect=["perhaps", "no"]) as prompt:
            result = cluster_maintenance.main([])

        self.assertEqual(result, 0)
        maintain.assert_called_once_with(settings, ["one.example", "two.example"], False, 3)
        self.assertEqual(prompt.call_count, 2)

    def test_update_only_skips_upgrade_prompt(self):
        settings = controller_settings()
        with patch.object(cluster_maintenance, "validate_controller_config", return_value=settings), \
                patch.object(cluster_maintenance, "run_maintenance", return_value=0) as maintain, \
                patch("builtins.input") as prompt:
            result = cluster_maintenance.main(["--update-only"])

        self.assertEqual(result, 0)
        maintain.assert_called_once_with(settings, ["one.example", "two.example"], False, 3)
        prompt.assert_not_called()

    def test_prompt_eof_aborts_without_running_maintenance(self):
        settings = controller_settings()
        with patch.object(cluster_maintenance, "validate_controller_config", return_value=settings), \
                patch.object(cluster_maintenance, "run_maintenance") as maintain, \
                patch("builtins.input", side_effect=EOFError):
            result = cluster_maintenance.main([])

        self.assertEqual(result, 130)
        maintain.assert_not_called()

    def test_repeated_worker_options_select_requested_workers_and_upgrade(self):
        settings = controller_settings(("one.example", "two.example", "three.example"))
        with patch.object(cluster_maintenance, "validate_controller_config", return_value=settings), \
                patch.object(cluster_maintenance, "run_maintenance", return_value=0) as maintain, \
                patch("builtins.input") as prompt:
            result = cluster_maintenance.main([
                "--upgrade", "--parallel", "2", "--worker", "two.example",
                "--worker", "one.example", "--worker", "three.example",
            ])

        self.assertEqual(result, 0)
        maintain.assert_called_once_with(settings, ["one.example", "two.example", "three.example"], True, 2)
        prompt.assert_not_called()

    def test_password_is_absent_from_command_and_generated_files(self):
        secret = "sensitive-sudo-token-7f2a"
        file_contents = []
        command_seen = []
        subprocess_kwargs = []

        def run(command, **kwargs):
            command_seen.extend(command)
            subprocess_kwargs.append(kwargs)
            inventory = Path(command[command.index("-i") + 1])
            vars_file = Path(next(value[1:] for value in command if value.startswith("@")))
            file_contents.extend((inventory.read_text(encoding="utf-8"), vars_file.read_text(encoding="utf-8")))
            return subprocess.CompletedProcess(command, 0)

        with patch.object(cluster_maintenance.os, "chmod"), \
                patch.object(cluster_maintenance.tempfile, "TemporaryDirectory", side_effect=project_temp_directory), \
                patch.object(cluster_maintenance, "collect_passwords", return_value={"one.example": secret}) as collect, \
                patch.object(cluster_maintenance, "PasswordBroker", return_value=nullcontext(SimpleNamespace(path="/private/sudo.sock"))), \
                patch.object(cluster_maintenance.shutil, "which", return_value="ansible-playbook"), \
                patch.object(cluster_maintenance.subprocess, "run", side_effect=run):
            result = cluster_maintenance.run_maintenance(
                controller_settings(), ["one.example"], True, parallel=2,
            )

        self.assertEqual(result, 0)
        self.assertTrue(command_seen)
        self.assertNotIn(secret, " ".join(map(str, command_seen)))
        self.assertTrue(file_contents, "expected private inventory and vars files to be created")
        self.assertNotIn(secret, "\n".join(file_contents))
        inventory_contents, variables_contents = file_contents
        self.assertEqual(inventory_contents, "[cluster_workers]\none.example\n")
        self.assertNotIn("two.example", inventory_contents)
        self.assertTrue(json.loads(variables_contents)["maintenance_upgrade"])
        self.assertEqual(json.loads(variables_contents)["maintenance_parallel"], 2)
        self.assertEqual(command_seen[command_seen.index("--forks") + 1], "1")
        collect.assert_called_once_with("labuser", ["one.example"], identity_file="/keys/lab")
        self.assertIs(subprocess_kwargs[0]["stdin"], subprocess.DEVNULL)
        environment = subprocess_kwargs[0]["env"]
        self.assertEqual(environment["ANSIBLE_STDOUT_CALLBACK"], "pi_maintenance")
        self.assertEqual(json.loads(environment["PI_DISPLAY_MAINTENANCE_WORKERS"]), ["one.example"])
        self.assertEqual(environment["PI_DISPLAY_MAINTENANCE_UPGRADE"], "1")

    def test_shared_sudo_password_is_prompted_once_and_brokered_to_each_worker(self):
        secret = "shared-sudo-token"
        broker_passwords = []
        commands = []
        inventories = []
        variables = []

        def run(command, **kwargs):
            commands.append(command)
            inventory = Path(command[command.index("-i") + 1])
            inventories.append(inventory.read_text(encoding="utf-8"))
            vars_file = Path(next(value[1:] for value in command if value.startswith("@")))
            variables.append(json.loads(vars_file.read_text(encoding="utf-8")))
            return subprocess.CompletedProcess(command, 0)

        def broker(path, passwords):
            broker_passwords.append(passwords.copy())
            return nullcontext(SimpleNamespace(path=path))

        def check_sudo(user, host, password=None, **kwargs):
            return password == secret

        with patch.object(cluster_maintenance.os, "chmod"), \
                patch.object(cluster_maintenance.tempfile, "TemporaryDirectory", side_effect=project_temp_directory), \
                patch.object(cluster_install, "check_sudo", side_effect=check_sudo), \
                patch.object(cluster_install, "read_password", return_value=secret) as read_password, \
                patch("builtins.input", return_value="j") as confirm_shared, \
                patch.object(cluster_maintenance, "PasswordBroker", side_effect=broker), \
                patch.object(cluster_maintenance.shutil, "which", return_value="ansible-playbook"), \
                patch.object(cluster_maintenance.subprocess, "run", side_effect=run):
            result = cluster_maintenance.run_maintenance(
                controller_settings(), ["one.example", "two.example"], False,
            )

        self.assertEqual(result, 0)
        read_password.assert_called_once()
        confirm_shared.assert_called_once()
        self.assertEqual(broker_passwords, [{"one.example": secret, "two.example": secret}])
        self.assertEqual(len(commands), 1)
        self.assertEqual(inventories, ["[cluster_workers]\none.example\ntwo.example\n"])
        self.assertEqual(commands[0][0], "ansible-playbook")
        self.assertIn("ansible/maintain-workers.yml", commands[0])
        self.assertEqual(commands[0][commands[0].index("--forks") + 1], "2")
        self.assertEqual(variables[0]["maintenance_parallel"], 3)


if __name__ == "__main__":
    unittest.main()
