"""Credential collection and installation ordering without touching real nodes."""

import getpass
import json
import os
import socket
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from cluster_install import PasswordBroker, check_sudo, collect_passwords, install, read_password, select_workers


class WorkerPasswordTests(unittest.TestCase):
    @patch("cluster_install.read_password")
    @patch("cluster_install.check_sudo")
    def test_approved_login_passwords_can_be_reused_for_sudo(self, check, prompt):
        check.side_effect = lambda user, host, value=None: value == "test-login"
        result = collect_passwords("labuser", ["one.example", "two.example"],
                                   initial_passwords={"one.example": "test-login", "two.example": "test-login"})
        self.assertEqual(result, {"one.example": "test-login", "two.example": "test-login"})
        prompt.assert_not_called()

    @patch("cluster_install.read_password", return_value="test-shared")
    @patch("builtins.input", return_value="")
    @patch("cluster_install.check_sudo")
    def test_shared_password_is_asked_once_and_passwordless_worker_is_skipped(self, check, answer, password):
        check.side_effect = lambda user, host, value=None: host == "free.example" or value == "test-shared"
        result = collect_passwords("labuser", ["one.example", "free.example", "two.example"])
        self.assertEqual(result, {"free.example": "", "one.example": "test-shared", "two.example": "test-shared"})
        password.assert_called_once()
        answer.assert_called_once()
        self.assertNotIn(call("labuser", "free.example", "test-shared"), check.call_args_list)

    @patch("cluster_install.read_password", side_effect=["test-shared", "test-other"])
    @patch("builtins.input", return_value="j")
    @patch("cluster_install.check_sudo")
    def test_only_worker_rejecting_shared_password_needs_another_prompt(self, check, answer, password):
        expected = {"one.example": "test-shared", "two.example": "test-other"}
        check.side_effect = lambda user, host, value=None: value == expected[host]
        self.assertEqual(collect_passwords("labuser", list(expected)), expected)
        self.assertEqual(password.call_count, 2)
        self.assertIn("two.example", password.call_args.args[0])

    @patch("cluster_install.read_password", side_effect=["test-one", "test-two"])
    @patch("builtins.input", return_value="n")
    @patch("cluster_install.check_sudo")
    def test_different_passwords_are_collected_before_installation(self, check, answer, password):
        expected = {"one.example": "test-one", "two.example": "test-two"}
        check.side_effect = lambda user, host, value=None: value == expected[host]
        self.assertEqual(collect_passwords("labuser", list(expected)), expected)

    @patch("cluster_install.subprocess.run")
    @patch("cluster_install.read_password", return_value="test-wrong")
    @patch("cluster_install.check_sudo", return_value=False)
    def test_rejected_password_stops_before_controller_or_worker_changes(self, check, password, run):
        with self.assertRaisesRegex(RuntimeError, "Ingen installasjon"):
            install("config", "temp", "a" * 40, ["one.example"], "labuser", False)
        self.assertEqual(password.call_count, 3)
        run.assert_not_called()

    @patch("cluster_install.read_password")
    @patch("builtins.input")
    @patch("cluster_install.check_sudo", return_value=True)
    def test_passwordless_workers_and_controller_only_need_no_prompts(self, check, answer, password):
        self.assertEqual(collect_passwords("labuser", []), {})
        self.assertEqual(collect_passwords("labuser", ["one.example"]), {"one.example": ""})
        answer.assert_not_called()
        password.assert_not_called()

    @patch("cluster_install.getpass.getpass", side_effect=getpass.GetPassWarning("no terminal"))
    def test_no_echoed_password_fallback_without_terminal(self, password):
        with self.assertRaisesRegex(RuntimeError, "interaktiv terminal"):
            read_password("Sudo: ")

    @patch("cluster_install.subprocess.run", return_value=subprocess.CompletedProcess([], 0))
    def test_password_is_only_sent_over_stdin_with_strict_ssh(self, run):
        self.assertTrue(check_sudo("labuser", "one.example", "test-sensitive"))
        args, kwargs = run.call_args
        self.assertNotIn("test-sensitive", " ".join(args[0]))
        self.assertNotIn("env", kwargs)
        self.assertEqual(kwargs["input"], "test-sensitive\n")
        self.assertIn("StrictHostKeyChecking=yes", args[0])
        self.assertIn("BatchMode=yes", args[0])
        self.assertIn("sudo -k -S", args[0][-1])

    @patch("cluster_install.subprocess.run", return_value=subprocess.CompletedProcess([], 255))
    def test_ssh_failure_does_not_get_mistaken_for_wrong_password(self, run):
        with self.assertRaisesRegex(RuntimeError, "SSH feilet"):
            check_sudo("labuser", "one.example")

    @patch("cluster_install.subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 20, stderr="test-sensitive"))
    def test_timeout_message_does_not_include_subprocess_output(self, run):
        with self.assertRaises(RuntimeError) as error:
            check_sudo("labuser", "one.example", "test-sensitive")
        self.assertNotIn("test-sensitive", str(error.exception))


class InstallOrchestrationTests(unittest.TestCase):
    def setUp(self):
        broker = patch("cluster_install.PasswordBroker", side_effect=lambda path, passwords: nullcontext(SimpleNamespace(path=path)))
        self.broker = broker.start()
        self.addCleanup(broker.stop)

    def test_limits_preserve_config_order_and_reject_typos(self):
        workers = ("one.example", "two.example", "three.example")
        self.assertEqual(select_workers(workers, ["three.example", "one.example"], False), ["one.example", "three.example"])
        self.assertEqual(select_workers(workers, [], True), [])
        with self.assertRaisesRegex(RuntimeError, "Ukjent worker"):
            select_workers(workers, ["missing.example"], False)

    @patch("cluster_install.subprocess.run", return_value=subprocess.CompletedProcess([], 0))
    @patch("cluster_install.broker_passwords", return_value={"one.example": "test-session"})
    @patch("cluster_install.collect_passwords")
    def test_wizard_credentials_are_reused_without_prompting_again(self, collect, broker, run):
        self.assertEqual(install("config", "temp", "a" * 40, ["one.example"], "labuser", False,
                                 sudo_socket="/tmp/test-session.sock"), 0)
        collect.assert_not_called()
        broker.assert_called_once_with("/tmp/test-session.sock", ["one.example"])

    @patch("cluster_install.subprocess.run", return_value=subprocess.CompletedProcess([], 0))
    @patch("cluster_install.collect_passwords", return_value={"one.example": "test-private"})
    def test_credentials_precede_controller_then_one_parallel_worker_run(self, collect, run):
        order = []
        collect.side_effect = lambda *args: order.append("credentials") or {"one.example": "test-private"}
        run.side_effect = lambda *args, **kwargs: order.append(args[0][0]) or subprocess.CompletedProcess([], 0)
        result = install("config", "temp", "a" * 40, ["one.example", "two.example"], "labuser", True)
        self.assertEqual(result, 0)
        self.assertEqual(order, ["credentials", "bash", "ansible-playbook"])
        controller = run.call_args_list[0]
        self.assertIn("--regenerate-server-cert", controller.args[0])
        self.assertEqual(controller.kwargs["stdin"], subprocess.DEVNULL)
        worker = run.call_args_list[1]
        command = worker.args[0]
        self.assertEqual(command[command.index("--limit") + 1], "one.example,two.example")
        self.assertEqual(command[command.index("--forks") + 1], "2")
        self.assertNotIn("test-private", " ".join(command))
        self.assertIn("worker_sudo_socket", command[-1])
        self.assertEqual(worker.kwargs["stdin"], subprocess.DEVNULL)
        self.assertNotIn("input", worker.kwargs)
        self.assertNotIn("env", worker.kwargs)
        self.assertEqual(self.broker.call_args.args[1], {"one.example": "test-private"})

    @patch("cluster_install.subprocess.run", return_value=subprocess.CompletedProcess([], 7))
    @patch("cluster_install.collect_passwords", return_value={})
    def test_controller_failure_prevents_worker_installation(self, collect, run):
        self.assertEqual(install("config", "temp", "a" * 40, ["one.example"], "labuser", False), 7)
        run.assert_called_once()

    @patch("cluster_install.subprocess.run", return_value=subprocess.CompletedProcess([], 0))
    @patch("cluster_install.collect_passwords", return_value={})
    def test_controller_only_never_launches_ansible(self, collect, run):
        self.assertEqual(install("config", "temp", "a" * 40, [], "labuser", False), 0)
        run.assert_called_once()

    @patch("cluster_install.subprocess.run", side_effect=[subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 2)])
    @patch("cluster_install.collect_passwords", return_value={})
    def test_parallelism_is_bounded_and_worker_failure_is_propagated(self, collect, run):
        workers = [f"worker-{i}.example" for i in range(20)]
        self.assertEqual(install("config", "temp", "a" * 40, workers, "labuser", False), 2)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--forks") + 1], "10")


@unittest.skipIf(os.name == "nt", "Requires Unix sockets; run in Linux/WSL")
class PasswordBrokerTests(unittest.TestCase):
    def request(self, path, host):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(str(path))
            connection.sendall(json.dumps(host).encode() + b"\n")
            with connection.makefile("rb") as response:
                return json.loads(response.readline())

    def test_literal_passwords_private_socket_unknown_hosts_and_cleanup(self):
        password = 'test-{{ lookup("env", "HOME") }}: \\ " æ'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sudo.sock"
            with PasswordBroker(path, {"one.example": password}):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(self.request(path, "one.example"), {"password": password})
                self.assertEqual(self.request(path, "missing.example"), {"error": "Unknown worker"})
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
