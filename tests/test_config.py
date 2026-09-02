"""Tester lokal konfigurasjon og sikre standardverdier."""

import json
import tempfile
import unittest
from pathlib import Path

from config import (
    DEFAULT_COORDINATOR_URL,
    ConfigValidationError,
    load_config,
    validate_controller_config,
)


class ConfigTests(unittest.TestCase):
    @staticmethod
    def valid_controller_config() -> dict:
        return {
            "node_role": "controller",
            "controller_host": "controller.example",
            "worker_hosts": ["worker-01.example"],
            "ssh_user": "labuser",
            "coordinator_port": 5001,
            "app_port": 5000,
            "node_heartbeat_auth": True,
            "cluster": {
                "enabled": True,
                "coordinator_url": "https://controller.example:5001",
                "poll_interval_seconds": 2,
                "credentials_file": "/etc/pi-display-lab/cluster-credentials.json",
            },
        }

    def test_missing_local_config_uses_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = load_config(Path(directory) / "config.local.json")

        self.assertFalse(settings.cluster.enabled)
        self.assertEqual(settings.cluster.coordinator_url, DEFAULT_COORDINATOR_URL)

    def test_local_config_enables_configured_coordinator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.local.json"
            path.write_text(
                json.dumps(
                    {
                        "node_role": "controller",
                        "controller_host": "controller.local",
                        "worker_hosts": ["worker-01.local", "worker-02.local"],
                        "ssh_user": "pi",
                        "coordinator_port": 5101,
                        "app_port": 5100,
                        "cluster": {
                            "enabled": True,
                            "coordinator_url": "http://192.0.2.20:5001/",
                            "poll_interval_seconds": 3,
                            "worker_slots": 2,
                        }
                    }
                ),
                encoding="utf-8",
            )
            settings = load_config(path)

        self.assertTrue(settings.cluster.enabled)
        self.assertEqual(settings.cluster.coordinator_url, "http://192.0.2.20:5001")
        self.assertEqual(settings.cluster.poll_interval_seconds, 3)
        self.assertEqual(settings.cluster.worker_slots, 2)
        self.assertEqual(settings.node_role, "controller")
        self.assertEqual(settings.controller_host, "controller.local")
        self.assertEqual(settings.worker_hosts, ("worker-01.local", "worker-02.local"))
        self.assertEqual(settings.ssh_user, "pi")
        self.assertEqual(settings.coordinator_port, 5101)
        self.assertEqual(settings.app_port, 5100)

    def test_install_config_validation_accepts_complete_controller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.local.json"
            path.write_text(json.dumps(self.valid_controller_config()), encoding="utf-8")
            settings = validate_controller_config(path)

        self.assertEqual(settings.node_role, "controller")
        self.assertTrue(settings.cluster.enabled)
        self.assertTrue(settings.node_heartbeat_auth)

    def test_install_config_validation_rejects_missing_workers_and_loopback(self) -> None:
        invalid = self.valid_controller_config()
        invalid["controller_host"] = "127.0.0.1"
        invalid["worker_hosts"] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.local.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ConfigValidationError) as context:
                validate_controller_config(path)

        self.assertIn("controller_host", str(context.exception))
        self.assertIn("worker_hosts", str(context.exception))

    def test_install_config_validation_rejects_disabled_cluster_and_root_ssh(self) -> None:
        invalid = self.valid_controller_config()
        invalid["ssh_user"] = "root"
        invalid["cluster"]["enabled"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.local.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ConfigValidationError) as context:
                validate_controller_config(path)

        self.assertIn("ssh_user", str(context.exception))
        self.assertIn("cluster.enabled", str(context.exception))

    def test_install_config_rejects_credentials_in_url_or_project_secret_path(self) -> None:
        invalid = self.valid_controller_config()
        invalid["cluster"]["coordinator_url"] = "http://name:password@controller.example:5001"
        invalid["cluster"]["credentials_file"] = "/home/labuser/Pi-display-lab/credentials.json"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.local.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ConfigValidationError) as context:
                validate_controller_config(path)

        self.assertIn("coordinator_url", str(context.exception))
        self.assertIn("/etc/pi-display-lab/", str(context.exception))

    def test_install_config_requires_https_and_matching_controller_identity(self) -> None:
        invalid = self.valid_controller_config()
        invalid["cluster"]["coordinator_url"] = "http://controller.example:5001"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.local.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ConfigValidationError) as context:
                validate_controller_config(path)
        self.assertIn("bruke https", str(context.exception))

        invalid["cluster"]["coordinator_url"] = "https://other.example:5001"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.local.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ConfigValidationError) as context:
                validate_controller_config(path)
        self.assertIn("samme adresse", str(context.exception))


if __name__ == "__main__":
    unittest.main()
