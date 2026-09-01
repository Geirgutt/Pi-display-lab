"""Tester in-memory køen og primtallsjobben."""

import unittest
from unittest.mock import patch

from cluster_jobs import (
    MAX_JOBS_PER_BATCH,
    MAX_PRIME_END,
    MAX_PRIME_SPAN,
    ClusterJobQueue,
    count_primes,
    validate_prime_range,
)


class ClusterJobQueueTests(unittest.TestCase):
    def test_prime_range_is_split_into_inclusive_chunks(self) -> None:
        queue = ClusterJobQueue()
        job_ids = queue.enqueue_prime_range({"start": 1, "end": 250, "chunk_size": 100})

        self.assertEqual(job_ids, [1, 2, 3])
        status = queue.status()
        self.assertEqual(status["queued"], 3)
        self.assertEqual(status["queued_jobs"][0]["start"], 1)
        self.assertEqual(status["queued_jobs"][-1]["end"], 250)

    def test_empty_queue_returns_no_job(self) -> None:
        self.assertIsNone(ClusterJobQueue().claim("worker-01"))

    def test_result_moves_job_from_running_to_history(self) -> None:
        queue = ClusterJobQueue()
        queue.enqueue_prime_range({"start": 1, "end": 100, "chunk_size": 100})
        job = queue.claim("worker-01")
        self.assertIsNotNone(job)

        result = queue.record_result(
            {
                "job_id": job["job_id"],
                "worker": "worker-01",
                "start": 1,
                "end": 100,
                "prime_count": 25,
            }
        )

        self.assertEqual(result["prime_count"], 25)
        status = queue.status()
        self.assertEqual(status["running"], 0)
        self.assertEqual(status["completed"], 1)
        self.assertEqual(status["results"][0]["worker"], "worker-01")

    def test_prime_counter_uses_inclusive_range(self) -> None:
        self.assertEqual(count_primes(1, 100), 25)

    def test_prime_job_resource_limits_reject_absurd_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "end kan maksimalt"):
            validate_prime_range(
                {"start": 1, "end": MAX_PRIME_END + 1, "chunk_size": 100}
            )
        with self.assertRaisesRegex(ValueError, "intervall"):
            validate_prime_range(
                {"start": 0, "end": MAX_PRIME_SPAN, "chunk_size": 100_000}
            )
        with self.assertRaisesRegex(ValueError, str(MAX_JOBS_PER_BATCH)):
            validate_prime_range(
                {"start": 0, "end": MAX_JOBS_PER_BATCH, "chunk_size": 1}
            )

    def test_total_pending_job_limit_blocks_repeated_batches(self) -> None:
        queue = ClusterJobQueue()
        with patch("cluster_jobs.MAX_PENDING_JOBS", 2):
            queue.enqueue_prime_range({"start": 1, "end": 2, "chunk_size": 1})
            with self.assertRaisesRegex(ValueError, "Køen kan maksimalt"):
                queue.enqueue_prime_range({"start": 3, "end": 3, "chunk_size": 1})

    def test_result_cannot_claim_more_primes_than_range_size(self) -> None:
        queue = ClusterJobQueue()
        queue.enqueue_prime_range({"start": 1, "end": 10, "chunk_size": 10})
        job = queue.claim("worker-01")
        with self.assertRaisesRegex(ValueError, "prime_count"):
            queue.record_result(
                {
                    **job,
                    "worker": "worker-01",
                    "prime_count": 11,
                }
            )

    def test_monte_carlo_batch_is_claimed_and_aggregated(self) -> None:
        queue = ClusterJobQueue()
        job_ids = queue.enqueue_monte_carlo(
            {"samples": 10_000, "samples_per_job": 5_000, "slot_limit": 2}
        )
        self.assertEqual(len(job_ids), 2)
        first = queue.claim("worker-01")
        second = queue.claim("worker-02")
        self.assertNotEqual(first["seed"], second["seed"])

        queue.record_result(
            {**first, "worker": "worker-01", "inside": 3_900, "points": []}
        )
        queue.record_result(
            {**second, "worker": "worker-02", "inside": 3_950, "points": []}
        )
        batch = queue.status()["batches"][0]
        self.assertEqual(batch["status"], "finished")
        self.assertEqual(batch["samples_done"], 10_000)
        self.assertEqual(batch["inside"], 7_850)
        self.assertEqual(batch["estimate"], 3.14)

    def test_batch_slot_limit_is_enforced_across_workers(self) -> None:
        queue = ClusterJobQueue()
        queue.enqueue_prime_range(
            {"start": 1, "end": 300, "chunk_size": 100, "slot_limit": 2}
        )
        first = queue.claim("worker-01")
        self.assertIsNotNone(first)
        self.assertIsNotNone(queue.claim("worker-02"))
        self.assertIsNone(queue.claim("worker-03"))
        queue.record_result({**first, "worker": "worker-01", "prime_count": 25})
        self.assertIsNotNone(queue.claim("worker-03"))

    def test_result_from_another_worker_is_rejected(self) -> None:
        queue = ClusterJobQueue()
        queue.enqueue_prime_range({"start": 1, "end": 10, "chunk_size": 10})
        job = queue.claim("worker-01")
        with self.assertRaisesRegex(ValueError, "feil worker"):
            queue.record_result({**job, "worker": "worker-02", "prime_count": 4})


if __name__ == "__main__":
    unittest.main()
