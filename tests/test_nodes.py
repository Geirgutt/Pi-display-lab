"""Tester registeret som holder ekte Raspberry Pi-heartbeats."""

import unittest

from display_state import NodeRegistry


class NodeRegistryTests(unittest.TestCase):
    def test_node_becomes_offline_when_heartbeat_expires(self) -> None:
        now = [100.0]
        registry = NodeRegistry(offline_after_seconds=20, clock=lambda: now[0])
        registry.heartbeat(
            {
                "node_id": "pi3-office",
                "name": "Pi 3B+",
                "cpu": 20,
                "temp": 45,
                "ram": 30,
                "cores": 4,
                "frequency_mhz": 900,
                "throttle_flags": 0x50000,
            },
            "192.0.2.43",
        )
        self.assertTrue(registry.snapshot()[0]["online"])

        now[0] += 21
        node = registry.snapshot()[0]
        self.assertFalse(node["online"])
        self.assertEqual(node["last_seen_seconds"], 21.0)
        self.assertEqual(node["cores"], 4)
        self.assertEqual(node["throttle"]["raw"], "0x50000")
        self.assertTrue(node["throttle"]["occurred"])
        self.assertFalse(node["throttle"]["active"])

    def test_node_id_rejects_unsafe_characters(self) -> None:
        registry = NodeRegistry()
        with self.assertRaises(ValueError):
            registry.heartbeat(
                {"node_id": "bad node\n", "cpu": 20, "temp": 45, "ram": 30}
            )


if __name__ == "__main__":
    unittest.main()
