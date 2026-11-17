"""Small read-only client for Garmin's official Personal API.

Credentials and raw replies stay on the controller. HTTP errors deliberately
exclude response bodies and headers, which may contain personal information.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import time
import zipfile
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener

from integration_sync import write_json_atomic
from garmin_charts import MAX_FIT_BYTES, ROUTE_FORMAT, activity_download_id, decode_activity_file

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
MAX_RESPONSE = 4 * 1024 * 1024


class GarminError(Exception):
    def __init__(self, message: str, *, status: int = 0, retry_after: int = 0):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


class GarminClient:
    def __init__(self, api_key: str, cache_dir: Path, *, opener=None, clock=time.time):
        self.key = api_key.strip()
        if not self.key or not self.key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in self.key):
            raise GarminError("Garmin API key is missing or invalid", status=401)
        self.cache_dir = Path(cache_dir)
        self.opener = opener or build_opener(NoRedirect())
        self.clock = clock
        self.fingerprint = hashlib.sha256(self.key.encode()).hexdigest()
        self.token = ""

    def _request(self, path: str, authorization: str, *, post=False, download=False) -> bytes:
        limit = MAX_FIT_BYTES if download else MAX_RESPONSE
        accept = "application/zip, application/x-zip-compressed, application/octet-stream" if download else (
            "*/*" if post else "application/json")
        request = Request(BASE_URL + path, data=b"" if post else None,
                          headers={"Authorization": authorization,
                                   "Accept": accept},
                          method="POST" if post else "GET")
        try:
            with self.opener.open(request, timeout=15) as reply:
                data = reply.read(limit + 1)
                if len(data) > limit:
                    raise GarminError("Garmin response exceeded the size limit")
                return data
        except HTTPError as error:
            retry = error.headers.get("Retry-After", "900")
            try:
                delay = max(60, int(retry))
            except (ValueError, TypeError):
                try:
                    delay = max(60, int(parsedate_to_datetime(retry).timestamp() - self.clock()))
                except (ValueError, TypeError, OverflowError):
                    delay = 900
            error.close()
            raise GarminError(f"Garmin HTTP {error.code}", status=error.code,
                              retry_after=delay if error.code == 429 else 0) from None
        except (OSError, URLError):
            raise GarminError("Garmin connection unavailable") from None

    def obtain_token(self, *, force=False) -> str:
        path = self.cache_dir / "garmin-token.json"
        cached = read_cache(path)
        try:
            if (not force and cached.get("fingerprint") == self.fingerprint
                    and float(cached.get("expires_at", 0)) > self.clock() + 3600
                    and isinstance(cached.get("access_token"), str)
                    and 0 < len(cached["access_token"]) < 16384
                    and cached["access_token"].isascii()
                    and not any(c in cached["access_token"] for c in "\r\n")):
                self.token = cached["access_token"]
                return self.token
        except (TypeError, ValueError):
            pass
        token = self._request(TOKEN_PATH, "ApiKey " + self.key, post=True).decode("utf-8").strip()
        try:
            # exp is used only for cache lifetime; Garmin verifies the token.
            segment = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
            expiry = float(claims["exp"])
            if (not math.isfinite(expiry) or expiry <= self.clock() or len(token) >= 16384 or not token.isascii()
                    or any(c in token for c in "\r\n")):
                raise ValueError
        except (IndexError, KeyError, TypeError, ValueError, UnicodeError, binascii.Error):
            raise GarminError("Garmin returned an invalid access token") from None
        write_json_atomic(path, {"fingerprint": self.fingerprint, "access_token": token, "expires_at": expiry})
        self.token = token
        return token

    def get(self, path: str, params: dict | None = None):
        if params:
            path += "?" + urlencode(params)
        data = self._get_bytes(path)
        if not data:
            return None  # HTTP 204: no measurements for this account/date.
        try:
            return json.loads(data)
        except (ValueError, UnicodeError):
            raise GarminError("Garmin returned invalid JSON") from None

    def download_activity(self, activity_id: int) -> bytes:
        return self._get_bytes(f"/download-service/files/activity/{activity_id}", download=True)

    def _get_bytes(self, path: str, *, download=False) -> bytes:
        if not self.token:
            self.obtain_token()
        try:
            return self._request(path, "Bearer " + self.token, download=download)
        except GarminError as error:
            if error.status != 401:
                raise
            self.obtain_token(force=True)
            return self._request(path, "Bearer " + self.token, download=download)


def _sync_activity_charts(client: GarminClient, raw: dict, now: int) -> int:
    activities = raw.get("activities")
    if not isinstance(activities, list):
        return 0
    ordered = sorted((item for item in activities if isinstance(item, dict)),
                     key=lambda item: str(item.get("startTimeLocal") or ""), reverse=True)
    ids = [activity_download_id(item.get("activityId")) for item in ordered]
    ids = list(dict.fromkeys(value for value in ids if value is not None))[:10]
    old = raw.get("charts")
    old = old if isinstance(old, dict) else {}
    charts = {str(value): old[str(value)] for value in ids if isinstance(old.get(str(value)), dict)}
    raw["charts"] = charts
    attempted = 0
    for activity_id in ids:
        key = str(activity_id)
        cached = charts.get(key, {})
        checked = cached.get("checked")
        if cached.get("route_format") == ROUTE_FORMAT and (
            not cached.get("media_retry") or (type(checked) is int and 0 <= now - checked < 86400)
        ):
            continue
        attempted += 1
        media_error = None
        try:
            details = decode_activity_file(client.download_activity(activity_id))
            if not details:
                media_error = "unreadable_file"
        except GarminError as error:
            media_error = f"http_{error.status}" if error.status else "connection_or_file_size"
            if error.status in (401, 429):
                charts[key] = {**cached, "media_error": media_error}
                return now + (error.retry_after or 900)
            if error.status == 403:
                charts[key] = {**cached, "checked": now, "media_retry": True,
                               "route_format": ROUTE_FORMAT, "media_error": media_error}
                break
            details = {}
        except (ImportError, OSError, ValueError, RuntimeError, zipfile.BadZipFile):
            details = {}
            media_error = "unreadable_file"
        if cached.get("route") and details and not details.get("route"):
            details["route"] = cached["route"]
        charts[key] = {**cached, **details, "checked": now, "media_retry": not details,
                       "route_format": ROUTE_FORMAT, "media_error": media_error}
        if attempted == 2:
            break
    return 0


def synchronize(api_key: str, cache_dir: Path, *, today: date | None = None, client=None, clock=time.time) -> dict:
    """Fetch bounded ranges; retain successful sources when another is unavailable."""
    from garmin_data import build_dashboard

    current = today or date.today()
    end, start = current.isoformat(), (current - timedelta(days=6)).isoformat()
    cache_dir = Path(cache_dir)
    previous = read_cache(cache_dir / "garmin.json")
    client = client or GarminClient(api_key, cache_dir, clock=clock)
    raw_cache = read_cache(cache_dir / "garmin-raw.json")
    same_key = raw_cache.get("fingerprint") == client.fingerprint
    raw = raw_cache.get("data", {}) if same_key else {}
    if not isinstance(raw, dict):
        raw = {}
    raw.pop("hydration", None)
    # A failed new-day request must not label yesterday's daily values as today.
    if raw_cache.get("date") != end:
        raw.pop("daily", None)
        raw.pop("fitness_age", None)
    retry_at = previous.get("retry_at", 0)
    if same_key and isinstance(retry_at, (float, int)) and retry_at > clock():
        # Re-align the display even while network requests are suspended.
        previous.update(build_dashboard(raw, today=current))
        write_json_atomic(cache_dir / "garmin.json", previous)
        return previous
    requests = [
        ("daily", "/usersummary-service/usersummary/daily", {"calendarDate": end}),
        ("summaries", "/usersummary-service/v2/dailysummaries", {"startDate": start, "endDate": end}),
        ("sleep", "/sleep-service/sleep/dailySleepSummariesByDate", {"startDate": start, "endDate": end}),
        ("hrv", f"/hrv-service/hrv/daily/{start}/{end}", None),
        ("weight", f"/weight-service/weight/range/{start}/{end}", None),
        ("vo2", f"/metrics-service/metrics/maxmet/daily/{current - timedelta(days=29)}/{end}", None),
        ("activities", "/activitylist-service/activities/search/activities", {"start": 0, "limit": 10, "sortOrder": "desc"}),
        ("fitness_age", f"/fitnessage-service/fitnessage/v2/{end}", None),
    ]
    failures, successes, retry_at, auth_error = [], 0, 0, False
    for name, path, params in requests:
        try:
            raw[name] = client.get(path, params)
            successes += 1
        except GarminError as error:
            failures.append(f"{name}: {error}")
            if error.status in (401, 403):
                # 403 may mean that a data scope was not selected for this key.
                auth_error = True
            if error.status == 401 or error.status == 429:
                retry_at = clock() + (error.retry_after or 900)
                break
    now = int(clock())
    if not retry_at:
        retry_at = _sync_activity_charts(client, raw, now)
    payload = build_dashboard(raw, today=current)
    payload.update(source="garmin-personal-api", status="ok" if not failures else
                   "auth_error" if auth_error else "stale" if same_key and previous.get("updated_at") else "error",
                   updated_at=now if successes else previous.get("updated_at", 0) if same_key else 0,
                   attempted_at=now, retry_at=retry_at, errors=failures)
    write_json_atomic(cache_dir / "garmin-raw.json", {"fingerprint": client.fingerprint, "date": end, "data": raw})
    write_json_atomic(cache_dir / "garmin.json", payload)
    return payload
