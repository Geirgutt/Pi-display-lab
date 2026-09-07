"""Tests for the provider-independent training state."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from training import JsonTrainingProvider, MockTrainingProvider, normalize_training


class TrainingStateTests(unittest.TestCase):
    def test_normalize_separates_today_upcoming_and_last_activity(self):
        state = normalize_training(
            {
                "workouts": [
                    {"date": "2026-09-09", "title": "Long Run", "duration_minutes": 65},
                    {"date": "2026-09-07", "title": "Base Run", "activity_type": "Run", "duration_minutes": 42},
                    {"date": "invalid", "title": "Ignored"},
                ],
                "last_activity": {
                    "date": "2026-09-06",
                    "activity_type": "Run",
                    "distance_km": 7.4,
                    "duration_seconds": 2538,
                    "average_hr": 148,
                },
            },
            today=date(2026, 9, 7),
        )

        self.assertTrue(state["available"])
        self.assertEqual(state["today"]["title"], "Base Run")
        self.assertEqual([item["title"] for item in state["upcoming"]], ["Long Run"])
        self.assertEqual(state["last_activity"]["average_hr"], 148.0)

    def test_json_provider_is_safe_when_file_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            state = JsonTrainingProvider(Path(directory) / "missing.json").snapshot()
        self.assertFalse(state["available"])
        self.assertEqual(state["source"], "local-json")
        self.assertEqual(state["today"], None)

    def test_mock_provider_has_the_same_normalized_shape(self):
        state = MockTrainingProvider().snapshot()
        self.assertEqual(set(state), {"available", "source", "updated_at", "today", "upcoming", "last_activity", "error"})
        self.assertTrue(state["available"])
        self.assertTrue(state["today"])


if __name__ == "__main__":
    unittest.main()
