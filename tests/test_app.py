"""Små tester som sjekker at de viktigste API-delene henger sammen."""

import unittest

from app import create_app
from config import ClusterConfig


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


class FakeClusterCoordinator:
    def __init__(self) -> None:
        self.config = ClusterConfig(
            enabled=True,
            coordinator_url="http://controller.example:5001",
            tls_enabled=False,
        )
        self.monte_payload: dict | None = None

    def fetch_status(self) -> dict:
        return {
            "queued": 0, "running": 0, "completed": 0, "failed": 0,
            "queued_jobs": [], "running_jobs": [], "results": [], "batches": [],
        }

    def start_monte_carlo(self, payload: dict) -> dict:
        self.monte_payload = payload
        return {"ok": True, "batch_id": 4, "created": 8}


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
        for key in ("protocol_version", "screen", "time", "nodes", "cluster", "message"):
            self.assertIn(key, payload)
        self.assertEqual(len(payload["nodes"]), 1)
        self.assertEqual(payload["nodes"][0]["kind"], "local")
        self.assertIn("frequency_mhz", payload["system"])
        self.assertIn("throttle", payload["system"])

    def test_remote_node_appears_after_heartbeat(self) -> None:
        heartbeat = {
            "node_id": "pi3-office",
            "name": "Pi 3B+",
            "model": "Raspberry Pi 3 Model B Plus",
            "cpu": 27.4,
            "temp": 48.2,
            "ram": 39.1,
            "cores": 4,
            "frequency_mhz": 900,
            "throttle_flags": 0x50005,
        }
        accepted = self.client.post("/api/nodes/heartbeat", json=heartbeat)
        self.assertEqual(accepted.status_code, 202)

        nodes = self.client.get("/api/state").get_json()["nodes"]
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[1]["id"], "pi3-office")
        self.assertEqual(nodes[1]["kind"], "remote")
        self.assertEqual(nodes[1]["ip"], "127.0.0.1")
        self.assertEqual(nodes[1]["cores"], 4)
        self.assertEqual(nodes[1]["frequency_mhz"], 900.0)
        self.assertTrue(nodes[1]["throttle"]["active"])

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

    def test_demo_is_submitted_to_workers_instead_of_running_locally(self) -> None:
        coordinator = FakeClusterCoordinator()
        app = create_app(mock_mode=True, coordinator_client=coordinator)
        client = app.test_client()
        client.post(
            "/api/nodes/heartbeat",
            json={"node_id": "worker-01", "cpu": 10, "temp": 45, "ram": 30, "cores": 4},
        )
        started = client.post(
            "/api/demo/start",
            json={"samples": 10_000, "slot_limit": 3, "reserve_one": True},
        )
        self.assertEqual(started.status_code, 202)
        self.assertEqual(coordinator.monte_payload["samples"], 10_000)
        self.assertEqual(coordinator.monte_payload["slot_limit"], 3)
        self.assertFalse(hasattr(app.extensions["dashboard"], "demo"))

    def test_demo_rejects_invalid_core_controls(self) -> None:
        coordinator = FakeClusterCoordinator()
        app = create_app(mock_mode=True, coordinator_client=coordinator)
        client = app.test_client()
        client.post(
            "/api/nodes/heartbeat",
            json={"node_id": "worker-01", "cpu": 10, "temp": 45, "ram": 30, "cores": 4},
        )
        self.assertEqual(
            client.post("/api/demo/start", json={"samples": 10_000, "slot_limit": 0}).status_code,
            400,
        )
        self.assertEqual(
            client.post(
                "/api/demo/start",
                json={"samples": 10_000, "slot_limit": 1, "reserve_one": "yes"},
            ).status_code,
            400,
        )

    def test_state_reports_cluster_capacity_without_counting_controller(self) -> None:
        coordinator = FakeClusterCoordinator()
        app = create_app(mock_mode=True, coordinator_client=coordinator)
        client = app.test_client()
        client.post(
            "/api/nodes/heartbeat",
            json={"node_id": "worker-01", "cpu": 10, "temp": 45, "ram": 30, "cores": 4},
        )
        capacity = client.get("/api/state").get_json()["cluster"]["capacity"]
        self.assertEqual(capacity["total_slots"], 4)
        self.assertEqual(capacity["reserved_slots"], 3)
        self.assertEqual(capacity["online_workers"], 1)


if __name__ == "__main__":
    unittest.main()
