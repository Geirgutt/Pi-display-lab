"""Tester in-memory køen og primtallsjobben."""

import unittest

from cluster_jobs import ClusterJobQueue, count_primes


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


if __name__ == "__main__":
    unittest.main()
