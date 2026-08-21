"""Små tester som sjekker at de viktigste API-delene henger sammen."""

import time
import unittest

from app import create_app


class FakeUpdateManager:
    def __init__(self) -> None:
        self.checked = False
        self.state = {
            "status": "available",
            "message": "En ny versjon er tilgjengelig",
            "current_commit": "11111111",
            "available_commit": "22222222",
            "commit_url": "https://github.com/example/project/commit/22222222",
            "worktree_clean": True,
        }

    def status(self) -> dict:
        return dict(self.state)

    def check_async(self) -> bool:
        self.checked = True
        return True


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
        self.assertEqual(len(payload["nodes"]), 1)
        self.assertEqual(payload["nodes"][0]["kind"], "local")

    def test_remote_node_appears_after_heartbeat(self) -> None:
        heartbeat = {
            "node_id": "pi3-office",
            "name": "Pi 3B+",
            "model": "Raspberry Pi 3 Model B Plus",
            "cpu": 27.4,
            "temp": 48.2,
            "ram": 39.1,
            "cores": 4,
        }
        accepted = self.client.post("/api/nodes/heartbeat", json=heartbeat)
        self.assertEqual(accepted.status_code, 202)

        nodes = self.client.get("/api/state").get_json()["nodes"]
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[1]["id"], "pi3-office")
        self.assertEqual(nodes[1]["kind"], "remote")
        self.assertEqual(nodes[1]["ip"], "127.0.0.1")
        self.assertEqual(nodes[1]["cores"], 4)

    def test_heartbeat_validates_metrics_and_optional_token(self) -> None:
        invalid = self.client.post(
            "/api/nodes/heartbeat",
            json={"node_id": "bad", "cpu": 101, "temp": 40, "ram": 20},
        )
        self.assertEqual(invalid.status_code, 400)

        self.app.config["NODE_TOKEN"] = "lab-token"
        heartbeat = {"node_id": "pi4", "cpu": 10, "temp": 45, "ram": 30}
        self.assertEqual(self.client.post("/api/nodes/heartbeat", json=heartbeat).status_code, 401)
        accepted = self.client.post(
            "/api/nodes/heartbeat",
            json=heartbeat,
            headers={"X-Node-Token": "lab-token"},
        )
        self.assertEqual(accepted.status_code, 202)

    def test_update_status_and_check_are_read_only(self) -> None:
        updater = FakeUpdateManager()
        app = create_app(mock_mode=True, update_manager=updater)
        client = app.test_client()

        status = client.get("/api/update/status").get_json()
        self.assertEqual(status["status"], "available")
        self.assertEqual(client.post("/api/update/check").status_code, 202)
        self.assertTrue(updater.checked)

        self.assertEqual(client.post("/api/update/apply", json={}).status_code, 404)

    def test_screen_can_change_and_invalid_screen_is_rejected(self) -> None:
        changed = self.client.post("/api/screen", json={"screen": "cluster"})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.get_json()["state"]["screen"], "cluster")

        invalid = self.client.post("/api/screen", json={"screen": "moon"})
        self.assertEqual(invalid.status_code, 400)

    def test_demo_finishes_and_reports_an_estimate(self) -> None:
        started = self.client.post(
            "/api/demo/start",
            json={"iterations": 10_000, "cores": 1, "reserve_one": False},
        )
        self.assertEqual(started.status_code, 202)

        deadline = time.monotonic() + 3
        payload = self.client.get("/api/state").get_json()
        while payload["demo"]["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
            payload = self.client.get("/api/state").get_json()

        self.assertEqual(payload["demo"]["status"], "finished")
        self.assertGreater(payload["demo"]["estimate"], 3.0)
        self.assertLess(payload["demo"]["estimate"], 3.3)
        self.assertEqual(payload["demo"]["inside"] + payload["demo"]["outside"], 10_000)
        self.assertGreater(len(payload["demo"]["points"]), 0)
        self.assertEqual(payload["demo"]["worker_count"], 1)

    def test_demo_rejects_invalid_core_controls(self) -> None:
        self.assertEqual(
            self.client.post("/api/demo/start", json={"iterations": 10_000, "cores": 0}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/demo/start",
                json={"iterations": 10_000, "cores": 1, "reserve_one": "yes"},
            ).status_code,
            400,
        )


if __name__ == "__main__":
    unittest.main()
