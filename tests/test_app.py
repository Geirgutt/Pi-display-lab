"""Små tester som sjekker at de viktigste API-delene henger sammen."""

import time
import unittest

from app import create_app


class AppSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(mock_mode=True)
        self.client = self.app.test_client()

    def test_home_and_health_are_available(self) -> None:
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/health").get_json()["ok"], True)

    def test_state_has_stable_protocol_fields(self) -> None:
        response = self.client.get("/api/state")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        for key in ("protocol_version", "screen", "time", "nodes", "message"):
            self.assertIn(key, payload)
        self.assertEqual(len(payload["nodes"]), 4)

    def test_screen_can_change_and_invalid_screen_is_rejected(self) -> None:
        changed = self.client.post("/api/screen", json={"screen": "cluster"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.get_json()["state"]["screen"], "cluster")

        invalid = self.client.post("/api/screen", json={"screen": "moon"})
        self.assertEqual(invalid.status_code, 400)

    def test_demo_finishes_and_reports_an_estimate(self) -> None:
        started = self.client.post("/api/demo/start", json={"iterations": 10_000})
        self.assertEqual(started.status_code, 202)

        deadline = time.monotonic() + 3
        payload = self.client.get("/api/state").get_json()
        while payload["demo"]["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
            payload = self.client.get("/api/state").get_json()

        self.assertEqual(payload["demo"]["status"], "finished")
        self.assertGreater(payload["demo"]["estimate"], 3.0)
        self.assertLess(payload["demo"]["estimate"], 3.3)


if __name__ == "__main__":
    unittest.main()
