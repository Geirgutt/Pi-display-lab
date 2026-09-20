#!/usr/bin/env python3
"""Synchronize configured private calendar feeds into local display caches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from integration_sync import (  # noqa: E402
    calendar_payload,
    fetch_ics,
    garmin_training_payload,
    parse_ics_events,
    write_json_atomic,
)

DEFAULT_CONFIG = Path("/etc/pi-display-lab/integrations.json")
DEFAULT_CACHE_DIR = Path("/var/lib/pi-display-lab/integrations")


def load_settings(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Integration settings must be a JSON object")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    args = parser.parse_args()
    if not args.config.exists():
        print("No integration settings; nothing to synchronize.")
        return 0

    settings = load_settings(args.config)
    failures: list[str] = []
    garmin = settings.get("garmin") if isinstance(settings.get("garmin"), dict) else {}
    if garmin.get("enabled"):
        try:
            events = parse_ics_events(fetch_ics(str(garmin.get("calendar_url") or "")))
            write_json_atomic(args.cache_dir / "training.json", garmin_training_payload(events))
            print(f"Garmin calendar: {len(events)} upcoming entries synchronized.")
        except Exception as error:
            failures.append(f"Garmin calendar: {error}")
    else:
        (args.cache_dir / "training.json").unlink(missing_ok=True)

    calendar = settings.get("calendar") if isinstance(settings.get("calendar"), dict) else {}
    if calendar.get("enabled"):
        groups = []
        calendar_failures: list[str] = []
        feeds = calendar.get("feeds") if isinstance(calendar.get("feeds"), list) else []
        for index, feed in enumerate(feeds, start=1):
            if not isinstance(feed, dict):
                calendar_failures.append(f"Calendar feed {index}: invalid settings")
                continue
            try:
                groups.append(parse_ics_events(fetch_ics(str(feed.get("url") or ""))))
            except Exception as error:
                calendar_failures.append(f"Calendar feed {index}: {error}")
        failures.extend(calendar_failures)
        if groups and not calendar_failures:
            merged = calendar_payload(groups)
            write_json_atomic(args.cache_dir / "calendar.json", merged)
            print(f"Calendar: {len(merged['events'])} upcoming entries synchronized.")
    else:
        (args.cache_dir / "calendar.json").unlink(missing_ok=True)

    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
