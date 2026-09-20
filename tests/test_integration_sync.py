"""Tests for small, secret-free integration transformations."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from integration_sync import (
    calendar_payload,
    garmin_training_payload,
    parse_ics_events,
    write_json_atomic,
)


class IntegrationSyncTests(unittest.TestCase):
    def test_ics_parser_expands_recurring_events(self) -> None:
        calendar = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:repeat@example.test\r
DTSTART:20260921T060000Z\r
DTEND:20260921T064500Z\r
RRULE:FREQ=DAILY;COUNT=2\r
SUMMARY:Easy Run\r
END:VEVENT\r
END:VCALENDAR\r
"""
        events = parse_ics_events(
            calendar,
            now=datetime.fromisoformat("2026-09-20T12:00:00+02:00"),
            horizon_days=4,
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["title"], "Easy Run")

    def test_garmin_events_become_upcoming_workouts_only(self) -> None:
        payload = garmin_training_payload(
            [
                {
                    "title": "Easy Run",
                    "start": "2026-09-21T08:00+02:00",
                    "end": "2026-09-21T08:45+02:00",
                }
            ]
        )
        self.assertEqual(payload["source"], "garmin")
        self.assertEqual(payload["workouts"][0]["activity_type"], "Run")
        self.assertEqual(payload["workouts"][0]["duration_minutes"], 45)
        self.assertNotIn("last_activity", payload)

    def test_multiple_calendar_feeds_are_sorted(self) -> None:
        merged = calendar_payload(
            [
                [{"title": "Later", "start": "2026-09-22T08:00+02:00"}],
                [{"title": "Soon", "start": "2026-09-21T08:00+02:00"}],
            ]
        )
        self.assertEqual([item["title"] for item in merged["events"]], ["Soon", "Later"])

    def test_cache_is_private_and_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "training.json"
            write_json_atomic(path, {"source": "garmin", "workouts": []})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())["source"], "garmin")


if __name__ == "__main__":
    unittest.main()
