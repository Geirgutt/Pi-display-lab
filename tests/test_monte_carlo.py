"""Tester beregningsbiter, kjernegrenser og visualiseringsdata."""

import unittest

from display_state import MonteCarloDemo, _monte_carlo_batch


class MonteCarloTests(unittest.TestCase):
    def test_batch_returns_hits_and_real_visual_points(self) -> None:
        hits, points = _monte_carlo_batch(2_000, seed=1234, visual_count=25)
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

    def test_reserve_one_can_be_enabled_or_disabled(self) -> None:
        demo = MonteCarloDemo(cpu_count=4)
        self.assertEqual(demo.resolve_worker_count(4, reserve_one=True), 3)
        self.assertEqual(demo.resolve_worker_count(4, reserve_one=False), 4)
        self.assertEqual(demo.resolve_worker_count(2, reserve_one=True), 2)


if __name__ == "__main__":
    unittest.main()
