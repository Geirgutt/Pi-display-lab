"""Fetch private ICS feeds and write small controller-side display caches."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_ICS_BYTES = 4 * 1024 * 1024
USER_AGENT = "Pi-Display-Lab/1.0"


@lru_cache(maxsize=1)
def _local_timezone():
    candidates = [os.getenv("TZ", "").strip()]
    try:
        candidates.append(Path("/etc/timezone").read_text(encoding="utf-8").strip())
    except OSError:
        pass
    try:
        target = Path("/etc/localtime").resolve()
        marker = "/zoneinfo/"
        if marker in str(target):
            candidates.append(str(target).split(marker, 1)[1])
    except OSError:
        pass
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            continue
    return datetime.now().astimezone().tzinfo


def _as_datetime(value: date | datetime, *, end: bool = False) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_local_timezone())
        return value.astimezone(), False
    # RFC 5545 uses an exclusive DTEND for all-day events. Keep that value;
    # normalize_calendar will correctly regard the event as active until then.
    return datetime.combine(value, time.min, tzinfo=_local_timezone()), True


def fetch_ics(url: str, *, timeout: float = 12.0) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Calendar address must be an HTTPS URL without embedded credentials")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/calendar"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_ICS_BYTES:
                raise ValueError("Calendar response is too large")
            payload = response.read(MAX_ICS_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"calendar server returned HTTP {error.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("calendar server could not be reached") from None
    if len(payload) > MAX_ICS_BYTES:
        raise ValueError("Calendar response is too large")
    return payload


def parse_ics_events(
    payload: bytes,
    *,
    now: datetime | None = None,
    horizon_days: int = 45,
) -> list[dict[str, Any]]:
    """Expand recurring VEVENTs into the small shape used by the dashboard."""

    import icalendar
    import recurring_ical_events

    current = (now or datetime.now().astimezone()).astimezone()
    calendar = icalendar.Calendar.from_ical(payload)
    components = recurring_ical_events.of(calendar, skip_bad_series=True).between(
        current - timedelta(days=1), current + timedelta(days=horizon_days)
    )
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for component in components:
        if getattr(component, "name", "") != "VEVENT" or "DTSTART" not in component:
            continue
        start, all_day = _as_datetime(component.decoded("DTSTART"))
        if "DTEND" in component:
            end, _ = _as_datetime(component.decoded("DTEND"), end=True)
        elif "DURATION" in component:
            end = start + component.decoded("DURATION")
        else:
            end = start + (timedelta(days=1) if all_day else timedelta())
        if end < current:
            continue
        title = str(component.get("SUMMARY") or "Calendar event").strip()
        location = str(component.get("LOCATION") or "").strip()
        uid = str(component.get("UID") or title)
        identity = (uid, start.isoformat())
        if identity in seen:
            continue
        seen.add(identity)
        result.append(
            {
                "title": title,
                "start": start.isoformat(timespec="minutes"),
                "end": end.isoformat(timespec="minutes"),
                "all_day": all_day,
                "location": location,
            }
        )
    result.sort(key=lambda event: (event["start"], event["title"]))
    return result


def _activity_type(title: str) -> str:
    lowered = title.casefold()
    choices = (
        (("run", "løp", "jogg"), "Run"),
        (("cycle", "cycling", "bike", "sykkel"), "Ride"),
        (("swim", "svøm"), "Swim"),
        (("walk", "gåtur", "tur"), "Walk"),
        (("strength", "styrke"), "Strength"),
    )
    for needles, label in choices:
        if any(needle in lowered for needle in needles):
            return label
    return "Workout"


def garmin_training_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    workouts = []
    for event in events:
        try:
            start = datetime.fromisoformat(str(event["start"]))
            end = datetime.fromisoformat(str(event["end"]))
        except (KeyError, ValueError):
            continue
        duration = None if event.get("all_day") else max(1, int((end - start).total_seconds() // 60))
        workouts.append(
            {
                "date": start.date().isoformat(),
                "title": str(event.get("title") or "Workout"),
                "activity_type": _activity_type(str(event.get("title") or "")),
                "duration_minutes": duration,
                "distance_km": None,
            }
        )
    return {"source": "garmin", "workouts": workouts}


def calendar_payload(event_groups: list[list[dict[str, Any]]]) -> dict[str, Any]:
    events = [event for group in event_groups for event in group]
    events.sort(key=lambda event: (event["start"], event["title"]))
    return {"source": "ics", "events": events}


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
