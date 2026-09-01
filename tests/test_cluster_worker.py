"""Tester at workeren regner og sender tilbake én primtallsjobb."""

import json
import secrets
import unittest
from unittest.mock import patch

from cluster_client import ClusterCoordinatorClient
from cluster_worker import process_one_job
from config import ClusterConfig


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeWorkerClient:
    def __init__(self, job: dict | None) -> None:
        self.job = job
        self.result: dict | None = None

    def claim_job(self, _worker: str) -> dict | None:
        return self.job

    def submit_result(self, payload: dict) -> dict:
        self.result = payload
        return {"ok": True}


class ClusterWorkerTests(unittest.TestCase):
    def test_worker_counts_primes_and_submits_result(self) -> None:
        client = FakeWorkerClient(
            {"job_id": 7, "job_type": "prime_count", "start": 1, "end": 100}
        )
        self.assertTrue(process_one_job(client, "worker-02"))
        self.assertEqual(client.result["prime_count"], 25)
        self.assertEqual(client.result["worker"], "worker-02")

    def test_worker_handles_empty_queue(self) -> None:
        self.assertFalse(process_one_job(FakeWorkerClient(None), "worker-02"))

    @patch("cluster_client.urlopen")
    def test_real_client_sends_worker_token_and_hostname(self, mocked_urlopen) -> None:
        mocked_urlopen.side_effect = [
            FakeResponse(
                {"job_id": 7, "job_type": "prime_count", "start": 1, "end": 10}
            ),
            FakeResponse({"ok": True}),
        ]
        token = secrets.token_urlsafe(32)
        client = ClusterCoordinatorClient(
            ClusterConfig(enabled=True, coordinator_url="http://controller.example:5001"),
            bearer_token=token,
        )

        self.assertTrue(process_one_job(client, "worker-02"))
        for call in mocked_urlopen.call_args_list:
            request = call.args[0]
            self.assertEqual(request.get_header("Authorization"), f"Bearer {token}")
            self.assertEqual(request.get_header("X-worker-id"), "worker-02")


if __name__ == "__main__":
    unittest.main()
