"""Tests for provider-independent calendar state."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from calendar_data import JsonCalendarProvider, MockCalendarProvider, normalize_calendar


class CalendarStateTests(unittest.TestCase):
    def test_normalize_sorts_future_events_and_drops_finished_events(self) -> None:
        now = datetime.fromisoformat("2026-09-20T12:00:00+02:00")
        state = normalize_calendar(
            {
                "events": [
                    {"title": "Later", "start": "2026-09-21T09:00:00+02:00"},
                    {
                        "title": "Finished",
                        "start": "2026-09-19T09:00:00+02:00",
                        "end": "2026-09-19T10:00:00+02:00",
                    },
                    {"title": "Soon", "start": "2026-09-20T13:00:00+02:00", "all_day": False},
                ]
            },
            now=now,
        )

        self.assertTrue(state["available"])
        self.assertEqual([event["title"] for event in state["events"]], ["Soon", "Later"])

    def test_json_provider_is_safe_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = JsonCalendarProvider(Path(directory) / "missing.json").snapshot()
        self.assertFalse(state["available"])
        self.assertEqual(state["source"], "local-json")

    def test_mock_provider_has_events(self) -> None:
        state = MockCalendarProvider().snapshot()
        self.assertTrue(state["available"])
        self.assertTrue(state["events"])


if __name__ == "__main__":
    unittest.main()
