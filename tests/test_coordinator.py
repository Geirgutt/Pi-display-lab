"""Tester coordinatorens eksisterende prototype-endepunkter."""

import unittest

from cluster_coordinator import create_coordinator_app
from cluster_jobs import ClusterJobQueue


class CoordinatorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = ClusterJobQueue()
        self.client = create_coordinator_app(self.queue).test_client()

    def test_empty_job_queue_returns_204(self) -> None:
        self.assertEqual(self.client.get("/job?worker=worker-01").status_code, 204)

    def test_job_result_and_status_flow(self) -> None:
        created = self.client.post(
            "/jobs",
            json={"start": 1, "end": 100, "chunk_size": 100},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["created"], 1)

        job = self.client.get("/job?worker=worker-01").get_json()
        running = self.client.get("/status").get_json()
        self.assertEqual(running["running"], 1)
        self.assertEqual(running["running_jobs"][0]["worker"], "worker-01")

        accepted = self.client.post(
            "/result",
            json={**job, "worker": "worker-01", "prime_count": 25},
        )
        self.assertEqual(accepted.status_code, 202)
        status = self.client.get("/status").get_json()
        self.assertEqual(status["completed"], 1)
        self.assertEqual(status["queued"], 0)
        self.assertEqual(status["results"][0]["prime_count"], 25)


if __name__ == "__main__":
    unittest.main()
