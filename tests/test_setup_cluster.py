"""Tester veiviserlogikken uten å endre en Raspberry Pi."""

import json
import tempfile
import unittest
from pathlib import Path

from setup_cluster import (
    PortListener,
    add_worker,
    build_controller_config,
    looks_like_old_coordinator,
    migrate_config,
    remove_worker,
    write_local_config,
)


PROJECT_DIR = Path(__file__).resolve().parent.parent


class SetupClusterTests(unittest.TestCase):
    def test_beginner_defaults_generate_https_controller_config(self) -> None:
        payload = build_controller_config(
            "controller.example", "labuser", ["worker-01.example"]
        )
        self.assertEqual(payload["node_role"], "controller")
        self.assertEqual(payload["app_port"], 5000)
        self.assertEqual(payload["coordinator_port"], 5001)
        self.assertTrue(payload["node_heartbeat_auth"])
        self.assertTrue(payload["cluster"]["tls_enabled"])
        self.assertEqual(
            payload["cluster"]["coordinator_url"],
            "https://controller.example:5001",
        )

    def test_generated_local_values_are_not_in_committed_example(self) -> None:
        private_host = "private-controller-for-test.invalid"
        private_user = "private-test-user"
        payload = build_controller_config(
            private_host, private_user, ["private-worker-for-test.invalid"]
        )
        example = (PROJECT_DIR / "config.example.json").read_text(encoding="utf-8")
        self.assertEqual(payload["controller_host"], private_host)
        self.assertNotIn(private_host, example)
        self.assertNotIn(private_user, example)

    def test_config_write_and_migration_preserve_machine_values(self) -> None:
        old = {
            "node_role": "controller",
            "controller_host": "controller.example",
            "worker_hosts": ["worker-01.example"],
            "ssh_user": "labuser",
            "coordinator_port": 5101,
            "app_port": 5100,
            "node_heartbeat_auth": True,
            "cluster": {
                "enabled": True,
                "coordinator_url": "http://controller.example:5101",
                "poll_interval_seconds": 4,
                "credentials_file": "/etc/pi-display-lab/cluster-credentials.json",
            },
        }
        migrated = migrate_config(old)
        self.assertEqual(migrated["worker_hosts"], old["worker_hosts"])
        self.assertEqual(migrated["cluster"]["poll_interval_seconds"], 4)
        self.assertEqual(
            migrated["cluster"]["coordinator_url"],
            "https://controller.example:5101",
        )
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "config.local.json"
            write_local_config(destination, migrated)
            self.assertEqual(json.loads(destination.read_text()), migrated)

    def test_add_duplicate_and_confirmed_removal(self) -> None:
        workers = add_worker([], "worker-01.example")
        with self.assertRaisesRegex(ValueError, "flere ganger"):
            add_worker(workers, "WORKER-01.example")
        with self.assertRaises(PermissionError):
            remove_worker(workers, "worker-01.example", confirmed=False)
        self.assertEqual(
            remove_worker(workers, "worker-01.example", confirmed=True), []
        )

    def test_old_manual_coordinator_detection_is_narrow(self) -> None:
        old = PortListener(
            5001,
            123,
            "/usr/bin/python3",
            "python3 /home/labuser/coordinator.py",
        )
        current = PortListener(
            5001,
            124,
            "/usr/bin/python3",
            "python3 /home/labuser/Pi-display-lab/cluster_coordinator.py",
        )
        unrelated = PortListener(5001, 125, "/usr/bin/python3", "python3 web.py")
        self.assertTrue(looks_like_old_coordinator(old))
        self.assertFalse(looks_like_old_coordinator(current))
        self.assertFalse(looks_like_old_coordinator(unrelated))


if __name__ == "__main__":
    unittest.main()
