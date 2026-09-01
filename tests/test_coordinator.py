"""Tester coordinatorflyt og skillet mellom worker- og admin-credentials."""

import secrets
import unittest

from cluster_auth import ClusterCredentials
from cluster_coordinator import create_coordinator_app
from cluster_jobs import ClusterJobQueue


class CoordinatorApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = ClusterJobQueue()
        self.admin_token = secrets.token_urlsafe(32)
        self.worker_tokens = {
            "worker-01": secrets.token_urlsafe(32),
            "worker-02": secrets.token_urlsafe(32),
        }
        credentials = ClusterCredentials(
            admin_token=self.admin_token,
            worker_tokens=self.worker_tokens,
        )
        self.client = create_coordinator_app(
            self.queue,
            credentials=credentials,
        ).test_client()

    def admin_headers(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.admin_token}"}

    def worker_headers(
        self,
        worker: str = "worker-01",
        token: str | None = None,
    ) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token or self.worker_tokens[worker]}",
            "X-Worker-ID": worker,
        }

    def create_one_job(self) -> None:
        response = self.client.post(
            "/jobs",
            json={"start": 1, "end": 100, "chunk_size": 100},
            headers=self.admin_headers(),
        )
        self.assertEqual(response.status_code, 201)

    def test_health_remains_unauthenticated(self) -> None:
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_empty_job_queue_returns_204_for_valid_worker(self) -> None:
        response = self.client.get("/job", headers=self.worker_headers())
        self.assertEqual(response.status_code, 204)

    def test_missing_and_invalid_worker_token_are_rejected(self) -> None:
        self.assertEqual(
            self.client.get("/job", headers={"X-Worker-ID": "worker-01"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                "/job",
                headers=self.worker_headers(token=secrets.token_urlsafe(32)),
            ).status_code,
            401,
        )

    def test_worker_token_cannot_claim_as_another_identity(self) -> None:
        headers = self.worker_headers("worker-02", token=self.worker_tokens["worker-01"])
        self.assertEqual(self.client.get("/job", headers=headers).status_code, 401)

    def test_worker_token_cannot_create_jobs_or_read_status(self) -> None:
        headers = self.worker_headers()
        self.assertEqual(
            self.client.post(
                "/jobs",
                json={"start": 1, "end": 100, "chunk_size": 100},
                headers=headers,
            ).status_code,
            401,
        )
        self.assertEqual(self.client.get("/status", headers=headers).status_code, 401)

    def test_missing_and_invalid_admin_token_are_rejected(self) -> None:
        self.assertEqual(self.client.get("/status").status_code, 401)
        self.assertEqual(
            self.client.get(
                "/status",
                headers=self.admin_headers(secrets.token_urlsafe(32)),
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/jobs",
                json={"start": 1, "end": 100, "chunk_size": 100},
            ).status_code,
            401,
        )

    def test_valid_admin_can_create_jobs_and_read_status(self) -> None:
        self.create_one_job()
        status = self.client.get("/status", headers=self.admin_headers())
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["queued"], 1)

    def test_valid_job_result_and_status_flow(self) -> None:
        self.create_one_job()
        job = self.client.get("/job", headers=self.worker_headers()).get_json()
        running = self.client.get("/status", headers=self.admin_headers()).get_json()
        self.assertEqual(running["running"], 1)
        self.assertEqual(running["running_jobs"][0]["worker"], "worker-01")

        accepted = self.client.post(
            "/result",
            json={**job, "worker": "worker-01", "prime_count": 25},
            headers=self.worker_headers(),
        )
        self.assertEqual(accepted.status_code, 202)
        status = self.client.get("/status", headers=self.admin_headers()).get_json()
        self.assertEqual(status["completed"], 1)
        self.assertEqual(status["results"][0]["prime_count"], 25)

    def test_result_requires_correct_worker_authentication(self) -> None:
        self.create_one_job()
        job = self.client.get("/job", headers=self.worker_headers()).get_json()
        body = {**job, "worker": "worker-01", "prime_count": 25}
        self.assertEqual(self.client.post("/result", json=body).status_code, 401)
        self.assertEqual(
            self.client.post(
                "/result",
                json=body,
                headers=self.worker_headers(
                    "worker-01", token=self.worker_tokens["worker-02"]
                ),
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/result",
                json={**body, "worker": "worker-02"},
                headers=self.worker_headers("worker-01"),
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
