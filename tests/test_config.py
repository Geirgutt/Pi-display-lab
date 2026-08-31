"""Tester lokal konfigurasjon og sikre standardverdier."""

import json
import tempfile
import unittest
from pathlib import Path

from config import DEFAULT_COORDINATOR_URL, load_config


class ConfigTests(unittest.TestCase):
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
                        }
                    }
                ),
                encoding="utf-8",
            )
            settings = load_config(path)

        self.assertTrue(settings.cluster.enabled)
        self.assertEqual(settings.cluster.coordinator_url, "http://192.0.2.20:5001")
        self.assertEqual(settings.cluster.poll_interval_seconds, 3)
        self.assertEqual(settings.node_role, "controller")
        self.assertEqual(settings.controller_host, "controller.local")
        self.assertEqual(settings.worker_hosts, ("worker-01.local", "worker-02.local"))
        self.assertEqual(settings.ssh_user, "pi")
        self.assertEqual(settings.coordinator_port, 5101)
        self.assertEqual(settings.app_port, 5100)


if __name__ == "__main__":
    unittest.main()
