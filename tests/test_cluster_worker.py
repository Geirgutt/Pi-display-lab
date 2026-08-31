"""Tester at workeren regner og sender tilbake én primtallsjobb."""

import unittest

from cluster_worker import process_one_job


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


if __name__ == "__main__":
    unittest.main()
