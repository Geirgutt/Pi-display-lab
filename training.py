"""Small provider boundary for training data shared by the web renderers."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


def _now() -> datetime:
    return datetime.now().astimezone()


def _empty_state(source: str, error: str | None = None) -> dict[str, Any]:
    return {
        "available": error is None,
        "source": source,
        "updated_at": _now().isoformat(timespec="seconds"),
        "today": None,
        "upcoming": [],
        "last_activity": None,
        "error": error,
    }


def _text(value: Any, default: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    return value.strip()[:maximum]


def _number(value: Any, minimum: float, maximum: float) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not minimum <= number <= maximum:
        return None
    return round(number, 2)


def _date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _workout(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    workout_date = _date(raw.get("date"))
    title = _text(raw.get("title"), "Workout", 64)
    if workout_date is None:
        return None
    return {
        "date": workout_date,
        "title": title,
        "activity_type": _text(raw.get("activity_type"), "Workout", 24),
        "duration_minutes": _number(raw.get("duration_minutes"), 1, 1440),
        "distance_km": _number(raw.get("distance_km"), 0, 1000),
    }


def _last_activity(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    activity_date = _date(raw.get("date"))
    if activity_date is None:
        return None
    return {
        "date": activity_date,
        "activity_type": _text(raw.get("activity_type"), "Activity", 24),
        "distance_km": _number(raw.get("distance_km"), 0, 1000),
        "duration_seconds": _number(raw.get("duration_seconds"), 1, 172800),
        "average_pace_min_per_km": _number(raw.get("average_pace_min_per_km"), 0, 60),
        "average_hr": _number(raw.get("average_hr"), 1, 260),
    }


def normalize_training(raw: Any, *, today: date | None = None, source: str = "local-json") -> dict[str, Any]:
    """Normalize a deliberately small local/provider-independent training shape."""

    if not isinstance(raw, dict):
        return _empty_state(source, "Training data must be a JSON object")
    current = today or _now().date()
    raw_workouts = raw.get("workouts", [])
    if not isinstance(raw_workouts, list):
        raw_workouts = []
    workouts = [_workout(item) for item in raw_workouts]
    valid_workouts = sorted(
        (item for item in workouts if item is not None),
        key=lambda item: (item["date"], item["title"]),
    )
    today_text = current.isoformat()
    today_workout = next((item for item in valid_workouts if item["date"] == today_text), None)
    upcoming = [item for item in valid_workouts if item["date"] > today_text][:5]
    return {
        "available": True,
        "source": source,
        "updated_at": _now().isoformat(timespec="seconds"),
        "today": today_workout,
        "upcoming": upcoming,
        "last_activity": _last_activity(raw.get("last_activity")),
        "error": None,
    }


class TrainingProvider(ABC):
    """Server-side source contract; renderers only consume its normalized state."""

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        raise NotImplementedError


class MockTrainingProvider(TrainingProvider):
    def snapshot(self) -> dict[str, Any]:
        today = _now().date()
        return normalize_training(
            {
                "workouts": [
                    {
                        "date": today.isoformat(),
                        "title": "Base Run",
                        "activity_type": "Run",
                        "duration_minutes": 42,
                    },
                    {
                        "date": (today + timedelta(days=2)).isoformat(),
                        "title": "Long Run",
                        "activity_type": "Run",
                        "duration_minutes": 65,
                    },
                    {
                        "date": (today + timedelta(days=4)).isoformat(),
                        "title": "Threshold",
                        "activity_type": "Run",
                        "duration_minutes": 38,
                    },
                ],
                "last_activity": {
                    "date": (today - timedelta(days=1)).isoformat(),
                    "activity_type": "Run",
                    "distance_km": 7.4,
                    "duration_seconds": 2538,
                    "average_pace_min_per_km": 5.68,
                    "average_hr": 148,
                },
            },
            today=today,
            source="mock",
        )


class JsonTrainingProvider(TrainingProvider):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def snapshot(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _empty_state("local-json", f"Training file not found: {self.path}")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return _empty_state("local-json", "Training file could not be read")
        return normalize_training(raw, source="local-json")


class UnconfiguredTrainingProvider(TrainingProvider):
    def snapshot(self) -> dict[str, Any]:
        return _empty_state("none", "No training provider configured")


def load_training_provider(mock_mode: bool = False) -> TrainingProvider:
    configured_path = os.getenv("PI_DISPLAY_TRAINING_FILE", "").strip()
    if configured_path:
        return JsonTrainingProvider(configured_path)
    return MockTrainingProvider() if mock_mode else UnconfiguredTrainingProvider()
