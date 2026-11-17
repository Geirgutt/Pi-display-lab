"""Read the controller's sanitized Garmin cache without contacting Garmin."""
from __future__ import annotations

import os
import time
from pathlib import Path

from garmin_api import read_cache

DEFAULT_CACHE = Path("/var/lib/pi-display-lab/integrations/garmin.json")


class GarminProvider:
    def __init__(self, path: str | Path | None = None, *, clock=time.time):
        self.path = Path(path or os.getenv("PI_DISPLAY_GARMIN_FILE", "") or DEFAULT_CACHE)
        self.clock = clock

    def snapshot(self) -> dict:
        raw = read_cache(self.path)
        status = raw.get("status", "not_configured")
        if status not in {"not_configured", "ok", "stale", "auth_error", "error"}:
            status = "error"
        updated = raw.get("updated_at", 0)
        if (not isinstance(updated, (float, int)) or isinstance(updated, bool)
                or not 0 <= updated <= 0xffffffff):
            updated = 0
        if status == "ok" and self.clock() - updated > 3600:
            status = "stale"
        groups = []
        raw_groups = raw.get("groups")
        for group in (raw_groups if isinstance(raw_groups, list) else [])[:4]:
            if not isinstance(group, dict):
                continue
            metrics = []
            raw_metrics = group.get("metrics")
            for metric in (raw_metrics if isinstance(raw_metrics, list) else [])[:6]:
                if not isinstance(metric, dict):
                    continue
                history = []
                values = metric.get("history")
                for value in (values if isinstance(values, list) else [])[:7]:
                    history.append(value if isinstance(value, (float, int)) and not isinstance(value, bool)
                                   and -1e12 <= value <= 1e12 else None)
                history.extend([None] * (7 - len(history)))
                metrics.append({"label": str(metric.get("label") or "")[:20],
                                "value": str(metric.get("value") or "--")[:16],
                                "unit": str(metric.get("unit") or "")[:12], "history": history})
            groups.append({"title": str(group.get("title") or "Garmin")[:20], "metrics": metrics})
        activities = raw.get("activities")
        return {"status": status, "updated_at": max(0, min(0xffffffff, int(updated))),
                "groups": groups, "last_activity": raw.get("last_activity"),
                "activities": activities[:10] if isinstance(activities, list) else []}
