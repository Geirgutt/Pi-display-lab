"""First access, platform selection and scale, without changing real nodes."""

import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cluster_bootstrap import (
    INSTALL_KEY, ensure_key, inspect_worker, parallel, plan_hostnames,
    prepare_ssh, prerequisite_script, trust_hosts,
    prepare_removal, stop_removed_workers,
    ansible_target_python_limit, check_worker_python,
)
from cluster_ssh import ssh_run


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        printer = patch("builtins.print")
        printer.start()
        self.addCleanup(printer.stop)

    @patch("cluster_bootstrap.scan_key", return_value=("one.example ssh-ed25519 dGVzdA==", "SHA256:test"))
    def test_host_key_approval_is_required_before_writing_known_hosts(self, scan):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "known_hosts"
            with self.assertRaisesRegex(RuntimeError, "ikke godkjent"):
                trust_hosts(["one.example"], lambda _: "n", path)
            self.assertFalse(path.exists())
            trust_hosts(["one.example"], lambda _: "j", path)
            self.assertIn("one.example ssh-ed25519", path.read_text())

    @patch("cluster_bootstrap.ensure_key")
    @patch("cluster_bootstrap.trust_hosts")
    @patch("cluster_bootstrap.ssh_run", return_value=subprocess.CompletedProcess([], 255, "", "REMOTE HOST IDENTIFICATION HAS CHANGED"))
    def test_changed_known_host_stops_without_password_or_key_installation(self, run, trust, key):
        with self.assertRaisesRegex(RuntimeError, "erstattes ikke"):
            prepare_ssh({"ssh_user": "labuser"}, ["one.example"], lambda _: "j")
        key.assert_not_called()

    @patch("cluster_bootstrap.subprocess.run")
    def test_existing_key_material_is_never_overwritten(self, run):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key"
            Path(str(path) + ".pub").write_text("test-public")
            with self.assertRaisesRegex(RuntimeError, "overskrives ikke"):
                ensure_key(str(path))
            run.assert_not_called()
            self.assertEqual(Path(str(path) + ".pub").read_text(), "test-public")

    @patch("cluster_bootstrap.ssh_run")
    def test_detects_supported_mixed_platforms_without_python_on_workers(self, run):
        for distro, arch in (("debian", "aarch64"), ("ubuntu", "x86_64"), ("fedora", "x86_64")):
            run.return_value = subprocess.CompletedProcess([], 0, f"{distro}\n{arch}\n1000\nworker-01\n{'a' * 32}\n", "")
            node = inspect_worker("labuser", "one.example")
            self.assertEqual((node["os"], node["arch"]), (distro, arch))
            self.assertNotIn("python3", run.call_args.args[2])
        run.return_value = subprocess.CompletedProcess([], 0, f"fedora\nx86_64\n0\nworker-01\n{'a' * 32}\n", "")
        with self.assertRaisesRegex(RuntimeError, "ikke root"):
            inspect_worker("root", "one.example")

    def test_prerequisites_select_apt_or_dnf_and_do_not_assume_pi_architecture(self):
        for os_name in ("debian", "ubuntu", "raspbian"):
            script = prerequisite_script(os_name)
            self.assertIn("apt-get install", script)
            self.assertIn("python3-venv", script)
            self.assertNotIn("dnf ", script)
        fedora = prerequisite_script("fedora")
        self.assertIn("dnf --refresh -y install", fedora)
        self.assertIn("python3-libdnf5", fedora)
        self.assertNotIn("python3-venv", fedora)
        with self.assertRaises(RuntimeError):
            prerequisite_script("unknown")

    @patch("cluster_bootstrap.subprocess.run")
    def test_ansible_version_selects_supported_worker_python_range(self, run):
        for version, maximum in (("2.19.12", 13), ("2.20.7", 14), ("2.21.3", 14)):
            run.return_value = subprocess.CompletedProcess([], 0, version + "\n", "")
            self.assertEqual(ansible_target_python_limit(Path("project")), maximum)

    @patch("cluster_bootstrap.ssh_run")
    def test_python_314_worker_requires_newer_ansible_and_probe_runs_as_written(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "3.14\n", "")
        with self.assertRaisesRegex(RuntimeError, "koordinatoren"):
            check_worker_python("labuser", "one.example", "", 13)
        check_worker_python("labuser", "one.example", "", 14)
        command = shlex.split(run.call_args.args[2])
        result = subprocess.run([sys.executable, *command[1:]], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), f"{sys.version_info.major}.{sys.version_info.minor}")

    def test_duplicate_hostnames_get_unique_names_without_changing_existing_nodes(self):
        nodes = {"two.example": {"hostname": "worker", "machine_id": "b" * 32},
                 "three.example": {"hostname": "worker", "machine_id": "c" * 32}}
        renames = plan_hostnames(nodes, ["worker"], "a" * 32)
        self.assertEqual(renames, {"two.example": "worker-001", "three.example": "worker-002"})
        with self.assertRaisesRegex(RuntimeError, "samme maskin"):
            plan_hostnames(nodes, existing_ids=["b" * 32])
        with self.assertRaisesRegex(RuntimeError, "samme maskin"):
            plan_hostnames(nodes, local_machine_id="b" * 32)

    def test_one_hundred_workers_use_at_most_ten_concurrent_operations(self):
        lock = threading.Lock()
        active = peak = 0
        def operation(host):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.005)
            with lock:
                active -= 1
            return host
        workers = [f"worker-{i}.example" for i in range(100)]
        result = parallel(workers, operation, "test")
        self.assertEqual(set(result), set(workers))
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 10)

    def test_sshpass_receives_password_only_in_inherited_pipe_and_closes_it(self):
        captured = {}
        def run(command, **kwargs):
            read_fd = kwargs["pass_fds"][0]
            captured["fd"] = read_fd
            self.assertEqual(os.read(read_fd, 4096), b"test-private\n")
            self.assertEqual(kwargs["input"], "test-public-key\n")
            self.assertNotIn("test-private", " ".join(command))
            self.assertNotIn("env", kwargs)
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertEqual(command[:2], ["sshpass", "-d"])
            return subprocess.CompletedProcess(command, 0, "", "")
        with patch("cluster_ssh.subprocess.run", side_effect=run):
            ssh_run("labuser", "one.example", INSTALL_KEY, login_password="test-private", stdin="test-public-key\n")
        with self.assertRaises(OSError):
            os.fstat(captured["fd"])

    def test_hostname_hosts_update_writes_real_newlines(self):
        script = prerequisite_script("fedora", "worker-003")
        command = shlex.split(script.splitlines()[-1])
        with tempfile.TemporaryDirectory() as directory:
            hosts = Path(directory) / "hosts"
            hosts.write_text("127.0.0.1 localhost\n127.0.1.1 old-name\n", encoding="utf-8")
            code = command[-1].replace("Path('/etc/hosts')", "Path(" + repr(str(hosts)) + ")")
            exec(code, {})
            self.assertEqual(hosts.read_text(), "127.0.0.1 localhost\n127.0.1.1 worker-003\n")

    @patch("cluster_bootstrap.collect_passwords", return_value={})
    @patch("cluster_bootstrap.ssh_run", side_effect=RuntimeError("offline"))
    def test_offline_worker_can_be_removed_without_password_prompt(self, run, collect):
        self.assertEqual(prepare_removal({"ssh_user": "labuser"}, ["one.example"], lambda _: "j"), {})
        self.assertEqual(collect.call_args.args[1], [])

    @patch("cluster_bootstrap.ssh_run", return_value=subprocess.CompletedProcess([], 0, "", ""))
    def test_removal_only_disables_our_services_and_uses_stdin_for_sudo(self, run):
        self.assertTrue(stop_removed_workers({"ssh_user": "labuser"}, {"one.example": "test-private"}))
        command = run.call_args.args[2]
        self.assertIn("cluster-worker.service", command)
        self.assertIn("pi-display-node-agent.service", command)
        self.assertIn("disable --now", command)
        self.assertNotIn("rm ", command)
        self.assertNotIn("test-private", command)
        self.assertEqual(run.call_args.kwargs["stdin"], "test-private\n")

    @unittest.skipIf(os.name == "nt", "Requires a Unix shell")
    def test_key_install_is_idempotent_and_preserves_existing_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".ssh").mkdir()
            authorized = root / ".ssh/authorized_keys"
            authorized.write_text("test-existing-key\n")
            environment = dict(os.environ, TEST_WORKER_HOME=directory)
            script = INSTALL_KEY.replace("$HOME", "$TEST_WORKER_HOME")
            for _ in range(2):
                subprocess.run(["sh", "-c", script], input="test-new-public-key\n", text=True,
                               env=environment, check=True, timeout=10)
            self.assertEqual(authorized.read_text().count("test-new-public-key"), 1)
            self.assertIn("test-existing-key", authorized.read_text())


if __name__ == "__main__":
    unittest.main()
