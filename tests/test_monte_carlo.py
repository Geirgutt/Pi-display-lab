"""Tester beregningsbiter, kjernegrenser og visualiseringsdata."""

import unittest

from cluster_jobs import monte_carlo_batch
from display_state import DashboardState


class MonteCarloTests(unittest.TestCase):
    def test_batch_returns_hits_and_real_visual_points(self) -> None:
        hits, points = monte_carlo_batch(2_000, seed=1234, visual_count=25)
        self.assertGreater(hits, 1_400)
        self.assertLess(hits, 1_700)
        self.assertEqual(len(points), 25)
        for x, y, inside in points:
            self.assertGreaterEqual(x, -1)
            self.assertLessEqual(x, 1)
            self.assertGreaterEqual(y, -1)
            self.assertLessEqual(y, 1)
            if inside:
                self.assertLessEqual(x * x + y * y, 1.001)
            else:
                self.assertGreaterEqual(x * x + y * y, 0.999)

    def test_dashboard_projects_aggregated_cluster_batch(self) -> None:
        dashboard = DashboardState(mock_mode=True)
        payload = dashboard.snapshot(cluster_status={
            "enabled": True,
            "available": True,
            "batches": [{
                "batch_id": 9,
                "job_type": "monte_carlo",
                "status": "finished",
                "samples": 10_000,
                "samples_done": 10_000,
                "inside": 7_850,
                "estimate": 3.14,
                "runtime_seconds": 2.5,
                "slot_limit": 2,
                "failed_jobs": 0,
                "points": [[0.1, 0.2, 1]],
            }],
        })
        self.assertEqual(payload["demo"]["status"], "finished")
        self.assertEqual(payload["demo"]["estimate"], 3.14)
        self.assertEqual(payload["demo"]["inside"] + payload["demo"]["outside"], 10_000)
        self.assertEqual(payload["demo"]["batch_id"], 9)


if __name__ == "__main__":
    unittest.main()
