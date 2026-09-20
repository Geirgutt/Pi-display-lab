"""Small provider boundary for calendar data shared by all renderers."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_CALENDAR_CACHE = Path("/var/lib/pi-display-lab/integrations/calendar.json")


def _now() -> datetime:
    return datetime.now().astimezone()


def _empty_state(source: str, error: str | None = None) -> dict[str, Any]:
    return {
        "available": error is None,
        "source": source,
        "updated_at": _now().isoformat(timespec="seconds"),
        "events": [],
        "error": error,
    }


def _text(value: Any, default: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    return value.strip()[:maximum]


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_now().tzinfo)
    return parsed.astimezone()


def normalize_calendar(
    raw: Any,
    *,
    now: datetime | None = None,
    source: str = "local-json",
) -> dict[str, Any]:
    """Normalize a deliberately small provider-independent calendar shape."""

    if not isinstance(raw, dict):
        return _empty_state(source, "Calendar data must be a JSON object")
    current = (now or _now()).astimezone()
    raw_events = raw.get("events", [])
    if not isinstance(raw_events, list):
        raw_events = []
    events: list[dict[str, Any]] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        start = _datetime(item.get("start"))
        if start is None:
            continue
        end = _datetime(item.get("end")) or start
        if end < start:
            end = start
        # Keep ongoing events and a small future window. Providers can retain a
        # larger cache without forcing that entire cache onto the display.
        if end < current:
            continue
        events.append(
            {
                "title": _text(item.get("title"), "Calendar event", 80),
                "start": start.isoformat(timespec="minutes"),
                "end": end.isoformat(timespec="minutes"),
                "all_day": bool(item.get("all_day", False)),
                "location": _text(item.get("location"), "", 80),
            }
        )
    events.sort(key=lambda item: (item["start"], item["title"]))
    return {
        "available": True,
        "source": source,
        "updated_at": _now().isoformat(timespec="seconds"),
        "events": events[:8],
        "error": None,
    }


class CalendarProvider(ABC):
    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        raise NotImplementedError


class JsonCalendarProvider(CalendarProvider):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def snapshot(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _empty_state("local-json", f"Calendar file not found: {self.path}")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return _empty_state("local-json", "Calendar file could not be read")
        source = str(raw.get("source") or "local-json") if isinstance(raw, dict) else "local-json"
        return normalize_calendar(raw, source=source)


class MockCalendarProvider(CalendarProvider):
    def snapshot(self) -> dict[str, Any]:
        now = _now().replace(second=0, microsecond=0)
        return normalize_calendar(
            {
                "events": [
                    {
                        "title": "Project check-in",
                        "start": (now + timedelta(hours=2)).isoformat(),
                        "end": (now + timedelta(hours=2, minutes=30)).isoformat(),
                    },
                    {
                        "title": "Easy run",
                        "start": (now + timedelta(days=1, hours=1)).isoformat(),
                        "end": (now + timedelta(days=1, hours=1, minutes=45)).isoformat(),
                        "location": "Home",
                    },
                ]
            },
            now=now,
            source="mock",
        )


class UnconfiguredCalendarProvider(CalendarProvider):
    def snapshot(self) -> dict[str, Any]:
        return _empty_state("none", "No calendar provider configured")


def load_calendar_provider(mock_mode: bool = False) -> CalendarProvider:
    configured_path = os.getenv("PI_DISPLAY_CALENDAR_FILE", "").strip()
    if configured_path:
        return JsonCalendarProvider(configured_path)
    if DEFAULT_CALENDAR_CACHE.exists() or not mock_mode:
        return JsonCalendarProvider(DEFAULT_CALENDAR_CACHE)
    return MockCalendarProvider()
