"""Small Spotify PKCE client. Credentials stay on the controller, never in state."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCOPES = "user-read-playback-state user-modify-playback-state"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1/me/player"
COMMANDS = {"play": ("PUT", "/play"), "pause": ("PUT", "/pause"),
            "next": ("POST", "/next"), "previous": ("POST", "/previous")}


def credentials_path() -> Path:
    return Path(os.environ.get("PI_DISPLAY_SPOTIFY_CREDENTIALS") or
                Path.home() / ".local/state/pi-display-lab/spotify.credentials.json")


def write_credentials(path: Path, payload: dict) -> None:
    """Atomically replace a private file, also when Spotify rotates its token."""
    if path.is_symlink():
        raise ValueError("Credentials file must not be a symbolic link")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".spotify-", dir=path.parent)
    temporary = Path(name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


class SpotifyError(Exception):
    def __init__(self, status: str, retry_after: float = 30):
        super().__init__(status)
        self.status = status
        self.retry_after = retry_after


def spotify_request(url: str, *, method: str = "GET", form: dict | None = None,
                    token: str | None = None) -> dict | None:
    headers = {"Accept": "application/json"}
    data = None
    if form is not None:
        data = urlencode(form).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=8) as response:
            if response.status == 204:
                return None
            raw = response.read(262145)
            if len(raw) > 262144:
                raise SpotifyError("unavailable")
            return json.loads(raw) if raw else None
    except HTTPError as error:
        if error.code == 429:
            try:
                delay = min(max(float(error.headers.get("Retry-After", "60")), 1), 86400)
            except ValueError:
                delay = 60
            raise SpotifyError("rate_limited", delay) from None
        if error.code == 400:
            try:
                detail = json.loads(error.read(4096))
            except (ValueError, OSError):
                detail = {}
            if isinstance(detail, dict) and detail.get("error") == "invalid_grant":
                raise SpotifyError("reauthorize") from None
        status = {401: "unauthorized", 403: "forbidden", 404: "no_device"}.get(error.code, "unavailable")
        raise SpotifyError(status) from None
    except (URLError, OSError, ValueError):
        raise SpotifyError("unavailable") from None


def token_credentials(client_id: str, response: dict, *, previous: dict | None = None) -> dict:
    previous = previous or {}
    if not isinstance(response, dict):
        raise SpotifyError("reauthorize")
    refresh = response.get("refresh_token") or previous.get("refresh_token")
    access = response.get("access_token")
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
        raise SpotifyError("reauthorize")
    now = time.time()
    return {"client_id": client_id, "refresh_token": refresh, "access_token": access,
            "expires_at": now + float(response.get("expires_in", 3600)),
            # Refreshing must never reset Spotify's 180-day authorization lifetime.
            "authorized_at": previous.get("authorized_at", now)}


def empty_state(status: str = "not_configured") -> dict:
    return {"status": status, "available": False, "is_playing": False,
            "title": "", "artist": "", "device": "", "progress_ms": 0,
            "duration_ms": 0, "pending": False, "can_control": False, "can_next": False,
            "can_previous": False}


class SpotifyProvider:
    """Serve cached state immediately; at most one short worker contacts Spotify."""
    def __init__(self, path: Path | None = None, *, mock: bool = False):
        self.path = path or credentials_path()
        self.mock = mock
        self._state = empty_state()
        self._lock = threading.Lock()
        self._operation = threading.Lock()
        self._next_poll = 0.0
        self._busy = False
        self._command_busy = False
        self._signature = None
        self._reauthorize = False

    def snapshot(self) -> dict:
        if self.mock:
            return dict(empty_state("not_configured"))
        with self._lock:
            if not self._busy and not self._command_busy and time.monotonic() >= self._next_poll:
                self._busy = True
                threading.Thread(target=self._poll, daemon=True, name="spotify-poll").start()
            return dict(self._state)

    def _credentials(self) -> dict:
        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if signature != self._signature:
                self._reauthorize = False
                self._signature = signature
            if self._reauthorize:
                raise SpotifyError("reauthorize", 60)
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not data.get("client_id") or not data.get("refresh_token"):
                raise SpotifyError("reauthorize")
            return data
        except FileNotFoundError:
            raise SpotifyError("not_configured", 10) from None
        except (OSError, ValueError):
            raise SpotifyError("reauthorize") from None

    def _token(self, *, force: bool = False) -> str:
        data = self._credentials()
        if force or not data.get("access_token") or float(data.get("expires_at", 0)) < time.time() + 60:
            try:
                response = spotify_request(TOKEN_URL, method="POST", form={
                    "grant_type": "refresh_token", "refresh_token": data["refresh_token"],
                    "client_id": data["client_id"]})
                data = token_credentials(data["client_id"], response or {}, previous=data)
                write_credentials(self.path, data)
            except SpotifyError as error:
                if error.status == "reauthorize":
                    self._reauthorize = True
                raise
        return data["access_token"]

    def _api(self, suffix: str = "", method: str = "GET") -> dict | None:
        token = self._token()
        try:
            return spotify_request(API_URL + suffix, method=method, token=token)
        except SpotifyError as error:
            if error.status != "unauthorized":
                raise
        return spotify_request(API_URL + suffix, method=method, token=self._token(force=True))

    def _poll(self) -> None:
        with self._operation:
            self._poll_locked()

    def _poll_locked(self) -> None:
        delay = 10
        state = empty_state("unavailable")
        try:
            raw = self._api()
            state = empty_state("no_device")
            if raw:
                item = raw.get("item") or {}
                device = raw.get("device") or {}
                disallows = (raw.get("actions") or {}).get("disallows") or {}
                playing = bool(raw.get("is_playing"))
                control = bool(device) and not device.get("is_restricted", False)
                state.update(status="playing" if playing else "paused", available=True,
                             is_playing=playing, title=str(item.get("name") or "")[:128],
                             artist=", ".join(str(a.get("name") or "") for a in item.get("artists", []))[:128],
                             device=str(device.get("name") or "")[:64],
                             progress_ms=max(0, min(int(raw.get("progress_ms") or 0), 0xFFFFFFFF)),
                             duration_ms=max(0, min(int(item.get("duration_ms") or 0), 0xFFFFFFFF)),
                             can_control=control and not disallows.get("pausing" if playing else "resuming", False),
                             can_next=control and not disallows.get("skipping_next", False),
                             can_previous=control and not disallows.get("skipping_prev", False))
        except SpotifyError as error:
            state = empty_state(error.status)
            delay = max(delay, error.retry_after)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            state = empty_state("unavailable")
            delay = 30
        finally:
            with self._lock:
                state["pending"] = self._command_busy
                self._state = state
                self._next_poll = time.monotonic() + delay
                self._busy = False

    def command(self, action: str) -> bool:
        if action not in COMMANDS or self.mock:
            return False
        with self._lock:
            # Accept one command during a poll; never queue repeated taps.
            capability = "can_next" if action == "next" else "can_previous" if action == "previous" else "can_control"
            if self._command_busy or self._state.get("pending") or not self._state.get(capability) or time.monotonic() < getattr(self, "_next_command", 0):
                return False
            self._command_busy = True
            self._state["pending"] = True
            self._next_command = time.monotonic() + 0.75
        threading.Thread(target=self._command, args=(action,), daemon=True, name="spotify-command").start()
        return True

    def _command(self, action: str) -> None:
        acquired = False
        try:
            acquired = self._operation.acquire(timeout=5)
            if not acquired:
                raise SpotifyError("unavailable", 5)
            capability = "can_next" if action == "next" else "can_previous" if action == "previous" else "can_control"
            with self._lock:
                # The preceding poll may have discovered a rate limit, revoked
                # access or a missing device. Preserve its status and deadline.
                if not self._state.get(capability):
                    self._state["pending"] = False
                    return
            method, suffix = COMMANDS[action]
            self._api(suffix, method)
            with self._lock:
                self._next_poll = time.monotonic() + 1
        except SpotifyError as error:
            with self._lock:
                self._state = empty_state(error.status)
                self._next_poll = time.monotonic() + error.retry_after
        except (OSError, ValueError, TypeError, KeyError):
            with self._lock:
                self._state = empty_state("unavailable")
                self._next_poll = time.monotonic() + 30
        finally:
            if acquired:
                self._operation.release()
            with self._lock:
                self._command_busy = False
