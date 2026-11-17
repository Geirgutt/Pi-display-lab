"""Normalize documented Garmin Personal API responses for the dashboard."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _num(value: Any, *, allow_zero: bool = True) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        return None
    return number


def _day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _fmt(value: Any, places: int = 0, *, suffix: str = "") -> str:
    number = _num(value)
    if number is None:
        return "--"
    text = f"{number:.{places}f}{suffix}"
    return text[:16] if text.isascii() else "--"


def _metric(label: str, value: Any, unit: str, history: list[Any], places: int = 0) -> dict[str, Any]:
    return {
        "label": label[:20],
        "value": _fmt(value, places),
        "unit": unit[:12],
        "history": [_num(item) for item in history[-7:]],
    }


def _title(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _activity_metrics(activity: dict) -> list[dict[str, Any]]:
    distance = _num(activity.get("distance"))
    duration = _num(activity.get("duration"))
    seconds_per_km = _num(duration / distance * 1000) if duration and distance else None
    if seconds_per_km is not None:
        pace_seconds = round(seconds_per_km)
        pace_text = f"{pace_seconds // 60}:{pace_seconds % 60:02d}"
    else:
        pace_text = "--"
    return [
        _metric("Distance", distance / 1000 if distance is not None else None, "km", [None] * 7, 2),
        _metric("Time", duration / 60 if duration is not None else None, "min", [None] * 7),
        {**_metric("Pace", None, "min/km", [None] * 7), "value": pace_text[:16]},
        _metric("Avg HR", activity.get("averageHR"), "bpm", [None] * 7),
        _metric("Aerobic TE", activity.get("aerobicTrainingEffect"), "", [None] * 7, 1),
        _metric("Load", activity.get("activityTrainingLoad"), "", [None] * 7, 1),
    ]


def build_dashboard(raw: dict, *, today: date) -> dict:
    """Build four compact groups from documented Garmin DTOs.

    V2 daily summaries wrap metric values in named objects and the list
    response wraps its records in ``data``. Sleep scores are similarly nested
    under ``sleepScores.overall.value``.
    """
    if not isinstance(raw, dict):
        raw = {}
    daily = _obj(raw.get("daily"))
    response = _obj(raw.get("summaries"))
    rows = response.get("data", [])
    if not isinstance(rows, list):
        rows = []
    by_date: dict[date, dict[str, Any]] = {}
    for row in rows:
        row = _obj(row)
        d = _day(row.get("calendarDate"))
        if d:
            by_date[d] = row
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    aligned = [by_date.get(d, {}) for d in days]

    # Current-day values come exclusively from `daily` when its date is today.
    if _day(daily.get("calendarDate")) != today:
        daily = {}
    # UserDailySummaryDto (the singular current-day endpoint) is a flat DTO;
    # the seven-day API uses the grouped V2 DTO handled by history().

    def history(section: str, key: str) -> list[Any]:
        result = []
        for row in aligned:
            value = _obj(_obj(row).get(section)).get(key)
            if section == "movement":
                value = _obj(value).get("value")
            result.append(value)
        return result

    today_group = [
        _metric("Body Battery", daily.get("bodyBatteryMostRecentValue"), "", history("bodyBattery", "latestValue")),
        _metric("Steps", daily.get("totalSteps"), "", history("movement", "steps")),
        _metric("Stress", daily.get("averageStressLevel"), "", history("stress", "avgLevel")),
        _metric("Resting HR", daily.get("restingHeartRate"), "bpm", history("heartRate", "restingValue")),
        _metric("Calories", daily.get("totalKilocalories"), "kcal", history("calories", "burnedTotal")),
    ]

    sleep_rows = raw.get("sleep", [])
    if not isinstance(sleep_rows, list):
        sleep_rows = []
    sleep_by_date = {d: _obj(x) for x in sleep_rows if (d := _day(_obj(x).get("calendarDate")))}
    sleep_aligned = [sleep_by_date.get(d, {}) for d in days]
    current_sleep = sleep_by_date.get(today, {})

    def sleep_history(key: str, divisor: float = 1) -> list[Any]:
        return [(_num(_obj(x).get(key)) / divisor if _num(_obj(x).get(key)) is not None else None) for x in sleep_aligned]

    def score_for(row: dict[str, Any]) -> Any:
        return _obj(_obj(row.get("sleepScores")).get("overall")).get("value")

    hrv_response = _obj(raw.get("hrv"))
    hrv_rows = hrv_response.get("hrvSummaries", [])
    if not isinstance(hrv_rows, list):
        hrv_rows = []
    hrv_map = {_day(_obj(x).get("calendarDate")): _obj(x) for x in hrv_rows if _day(_obj(x).get("calendarDate"))}
    hrv_current = hrv_map.get(today, {})
    hrv_hist = [_obj(hrv_map.get(d)).get("lastNightAvg") for d in days]
    sleep_group = [
        _metric("Sleep", _num(current_sleep.get("sleepTimeSeconds")) / 3600 if _num(current_sleep.get("sleepTimeSeconds")) is not None else None, "h", sleep_history("sleepTimeSeconds", 3600), 1),
        _metric("Sleep score", score_for(current_sleep), "", [score_for(x) for x in sleep_aligned]),
        _metric("Deep sleep", _num(current_sleep.get("deepSleepSeconds")) / 60 if _num(current_sleep.get("deepSleepSeconds")) is not None else None, "min", sleep_history("deepSleepSeconds", 60)),
        _metric("REM", _num(current_sleep.get("remSleepSeconds")) / 60 if _num(current_sleep.get("remSleepSeconds")) is not None else None, "min", sleep_history("remSleepSeconds", 60)),
        _metric("HRV", hrv_current.get("lastNightAvg"), "ms", hrv_hist),
        {"label": "HRV status", "value": ((_title(hrv_current.get("status"))[:16] or "--") if _title(hrv_current.get("status")).isascii() else "--"), "unit": "", "history": [None] * 7},
    ]

    weight_rows = _obj(raw.get("weight")).get("dailyWeightSummaries", [])
    if not isinstance(weight_rows, list):
        weight_rows = []
    weight_by_date = {_day(_obj(x).get("summaryDate")): _obj(x) for x in weight_rows if _day(_obj(x).get("summaryDate"))}
    weight_series = []
    for d in days:
        item = _obj(_obj(weight_by_date.get(d)).get("latestWeight"))
        grams = _num(item.get("weight"), allow_zero=False)
        weight_series.append(grams / 1000 if grams is not None else None)
    last_weight_index = next((i for i in range(6, -1, -1) if _num(weight_series[i]) is not None), None)
    last_weight = weight_series[last_weight_index] if last_weight_index is not None else None

    vo2_raw = raw.get("vo2", [])
    if not isinstance(vo2_raw, list):
        vo2_raw = []
    vo2_points = []
    for item in vo2_raw:
        generic = _obj(_obj(item).get("generic"))
        d = _day(generic.get("calendarDate"))
        if d and d <= today:
            vo2_points.append((d, generic.get("vo2MaxValue")))
    vo2_latest = sorted(vo2_points, key=lambda x: x[0])[-1] if vo2_points else None
    vo2_recent = vo2_latest[1] if vo2_latest else None
    vo2_histmap = {d: v for d, v in vo2_points}
    fitness = _obj(raw.get("fitness_age"))

    # Legacy current-day DTO exposes pulse ox and respiration directly; the
    # V2 daily summary carries these in their named nested objects.
    intensity = _num(daily.get("moderateIntensityMinutes"))
    vigorous = _num(daily.get("vigorousIntensityMinutes"))
    def intensity_total(row: Any) -> float | None:
        section = _obj(_obj(row).get("intensityMinutes"))
        moderate = _num(section.get("moderate"))
        vigorous_value = _num(section.get("vigorous"))
        # Garmin gives vigorous minutes double credit toward intensity goals.
        return moderate + 2 * vigorous_value if moderate is not None and vigorous_value is not None else None

    weight_label = "Weight"
    if last_weight_index is not None and days[last_weight_index] != today:
        weight_label = f"Weight {days[last_weight_index].strftime('%m-%d')}"
    vo2_label = "VO2 max"
    if vo2_latest and vo2_latest[0] != today:
        vo2_label = f"VO2 {vo2_latest[0].strftime('%m-%d')}"
    health_group = [
        _metric(weight_label, last_weight, "kg", weight_series, 1),
        _metric(vo2_label, vo2_recent, "", [vo2_histmap.get(d) for d in days], 1),
        _metric("Fitness age", fitness.get("fitnessAge"), "", [None] * 7, 1),
        _metric("SpO2", daily.get("latestSpo2"), "%", history("pulseOx", "latestValue")),
        _metric("Respiration", daily.get("latestRespirationValue"), "br/min", history("respiration", "latestValue"), 1),
        _metric("Intensity min", intensity + 2 * vigorous if intensity is not None and vigorous is not None else None, "min", [intensity_total(row) for row in aligned]),
    ]

    activities = raw.get("activities", [])
    if not isinstance(activities, list):
        activities = []
    valid_activities = []
    for activity in activities:
        activity = _obj(activity)
        d = _day(activity.get("startTimeLocal"))
        if d and d <= today:
            valid_activities.append((d, activity))
    valid_activities.sort(key=lambda entry: entry[1]["startTimeLocal"], reverse=True)
    activity = valid_activities[0][1] if valid_activities else {}
    activity_day = _day(activity.get("startTimeLocal"))
    activity_title = f"Activity {activity_day.isoformat()}" if activity_day else "Last activity"
    act_distance = _num(activity.get("distance"))
    duration = _num(activity.get("duration"))
    pace = _num(duration / act_distance * (1000 / 60)) if duration and act_distance else None
    atype = _obj(activity.get("activityType"))
    last_activity = None
    if activity:
        last_activity = {
            "date": activity_day.isoformat(),
            "activity_type": (_title(atype.get("typeKey")) or "Activity")[:24],
            "distance_km": round(act_distance / 1000, 2) if act_distance is not None else None,
            "duration_seconds": duration,
            "average_pace_min_per_km": round(pace, 2) if pace is not None else None,
            "average_hr": _num(activity.get("averageHR")),
        }
    recent_activities = []
    charts = _obj(raw.get("charts"))
    for day, item in valid_activities[:10]:
        kind = _title(_obj(item.get("activityType")).get("typeKey")).replace("_", " ")
        recent_activities.append({
            "date": day.isoformat(),
            "title": _title(item.get("activityName"))[:48] or kind[:48] or "Activity",
            "kind": kind[:24],
            "values": [metric["value"] for metric in _activity_metrics(item)],
            "charts": _obj(charts.get(str(item.get("activityId")))).get("series", []),
        })
    return {"groups": [
        {"title": "Today", "metrics": today_group},
        {"title": "Sleep", "metrics": sleep_group},
        {"title": "Health", "metrics": health_group},
        {"title": activity_title[:20], "metrics": _activity_metrics(activity)},
    ], "last_activity": last_activity, "activities": recent_activities,
        "history_end": today.toordinal() - date(1970, 1, 1).toordinal()}
