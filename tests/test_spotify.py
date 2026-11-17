"""OAuth lifetime, private credentials, playback errors and command authorization."""

import base64
import hashlib
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from spotify import SpotifyError, SpotifyProvider, album_cover_url, token_credentials, write_credentials

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("configure_spotify", ROOT / "scripts/configure-spotify.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SpotifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "spotify.credentials.json"
        write_credentials(self.path, {"client_id": "a" * 32, "access_token": "private-access",
                                     "refresh_token": "private-refresh", "expires_at": time.time() + 3600,
                                     "authorized_at": 1234})
        self.provider = SpotifyProvider(self.path)

    def test_pkce_challenge_and_callback_state(self):
        url, state, verifier = setup.authorization_request("a" * 32)
        query = parse_qs(urlsplit(url).query)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(query["code_challenge"], [challenge])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotIn(verifier, url)
        self.assertIsNone(setup.callback_code("/callback?code=secret&state=wrong", state))
        self.assertIsNone(setup.callback_code("/callback?code=secret&state=%C3%B8", state))
        self.assertIsNone(setup.callback_code(f"/other?code=secret&state={state}", state))
        self.assertIsNone(setup.callback_code(f"/callback?code=x&state={state}&state=wrong", state))
        self.assertEqual(setup.callback_code(f"/callback?code=secret&state={state}", state), "secret")
        with self.assertRaises(SpotifyError):
            setup.callback_code(f"/callback?error=access_denied&state={state}", state)

    def test_refresh_rotation_preserves_authorization_date(self):
        previous = json.loads(self.path.read_text())
        previous["expires_at"] = 0
        write_credentials(self.path, previous)
        with patch("spotify.spotify_request", return_value={"access_token": "new-access", "refresh_token": "rotated",
                                                            "expires_in": 3600}) as request:
            self.assertEqual(self.provider._token(), "new-access")
        self.assertEqual(request.call_args.kwargs["form"]["grant_type"], "refresh_token")
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["refresh_token"], "rotated")
        self.assertEqual(saved["authorized_at"], 1234)
        self.assertNotIn("client_secret", saved)
        retained = token_credentials("id", {"access_token": "new"}, previous=saved)
        self.assertEqual(retained["refresh_token"], "rotated")

    def test_expired_refresh_requires_reconnect_and_new_file_recovers(self):
        data = json.loads(self.path.read_text())
        data["expires_at"] = 0
        write_credentials(self.path, data)
        with patch("spotify.spotify_request", side_effect=SpotifyError("reauthorize")) as request:
            self.provider._poll()
            self.provider._poll()
            self.assertEqual(request.call_count, 1)
        self.assertEqual(self.provider._state["status"], "reauthorize")
        data["access_token"] = "reconnected-token"
        data["expires_at"] = time.time() + 3600
        write_credentials(self.path, data)
        with patch("spotify.spotify_request", return_value=None):
            self.provider._poll()
        self.assertEqual(self.provider._state["status"], "no_device")

    def test_playback_capabilities_and_no_credentials_in_state(self):
        playback = {"is_playing": True, "progress_ms": 2000,
                    "item": {"name": "Song", "artists": [{"name": "Artist"}], "duration_ms": 120000},
                    "device": {"name": "PC", "is_restricted": False},
                    "actions": {"disallows": {"skipping_next": True}}}
        with patch("spotify.spotify_request", return_value=playback):
            self.provider._poll()
        state = self.provider.snapshot()
        self.assertEqual(state["title"], "Song")
        self.assertTrue(state["can_control"])
        self.assertFalse(state["can_next"])
        self.assertNotIn("private-", json.dumps(state))
        self.assertFalse(self.provider.command("next"))
        self.assertFalse(self.provider.command("arbitrary"))
        self.provider._busy = True  # A poll must not silently discard this tap.
        with patch("spotify.threading.Thread") as worker:
            self.assertTrue(self.provider.command("pause"))
            self.assertTrue(self.provider.snapshot()["pending"])
            self.assertFalse(self.provider.command("pause"))
            worker.assert_called_once()

    def test_successful_command_stays_pending_until_new_state(self):
        self.provider._state.update(can_control=True, status="playing", pending=True)
        self.provider._command_busy = True
        with patch("spotify.spotify_request", return_value=None):
            self.provider._command("pause")
        self.assertTrue(self.provider._state["pending"])
        self.assertFalse(self.provider._command_busy)
        self.assertFalse(self.provider.command("pause"))
        with patch("spotify.spotify_request", return_value=None):
            self.provider._poll()
        self.assertFalse(self.provider._state["pending"])

    def test_cover_selects_a_small_spotify_image_and_only_serves_the_current_track(self):
        url = "https://i.scdn.co/image/abc123"
        item = {"id": "a" * 22, "type": "track",
                "album": {"images": [
                    {"url": "https://i.scdn.co/image/large", "width": 300, "height": 300},
                    {"url": "https://example.com/image/wrong", "width": 80, "height": 80},
                    {"url": url, "width": 64, "height": 64},
                ]}}
        self.assertEqual(album_cover_url(item), url)
        with patch.object(self.provider, "_api", return_value={"item": item, "is_playing": True}):
            self.provider._poll()
        with patch("spotify._download_album_cover", return_value=b"\xff\xd8\xff\xd9"):
            self.provider._fetch_cover(url)
        self.assertEqual(self.provider.cover_for_track("a" * 22), b"\xff\xd8\xff\xd9")
        self.assertEqual(self.provider.cover_for_track("b" * 22), b"")

    def test_playback_clock_advances_between_polls_and_stops_at_duration(self):
        playback = {"is_playing": True, "progress_ms": 2000,
                    "item": {"name": "Song", "duration_ms": 5500}}
        with patch("spotify.spotify_request", return_value=playback):
            with patch("spotify.time.monotonic", return_value=100):
                self.provider._poll()
            with patch("spotify.time.monotonic", return_value=103):
                self.assertEqual(self.provider.snapshot()["progress_ms"], 5000)
            with patch("spotify.time.monotonic", return_value=104):
                self.assertEqual(self.provider.snapshot()["progress_ms"], 5500)
                self.provider._state.update(status="paused", is_playing=False)
                self.assertEqual(self.provider.snapshot()["progress_ms"], 2000)

    def test_skip_tolerates_one_empty_snapshot_without_resending_command(self):
        self.provider._state.update(can_next=True, status="playing", title="Old song", pending=True)
        self.provider._command_busy = True
        with patch("spotify.spotify_request", return_value=None) as request:
            self.provider._command("next")
            self.provider._poll()
            self.assertEqual(self.provider.snapshot()["title"], "Old song")
            self.assertTrue(self.provider.snapshot()["pending"])
            self.provider._poll()
            self.assertEqual(self.provider.snapshot()["status"], "no_device")
            self.assertFalse(self.provider.snapshot()["pending"])
        self.assertEqual([call.kwargs["method"] for call in request.call_args_list],
                         ["POST", "GET", "GET"])

    def test_rate_limit_preserves_retry_after_and_401_refreshes_once(self):
        with patch("spotify.spotify_request", side_effect=SpotifyError("rate_limited", 240)):
            before = time.monotonic()
            self.provider._poll()
        self.assertEqual(self.provider._state["status"], "rate_limited")
        self.assertGreaterEqual(self.provider._next_poll, before + 240)
        with patch("spotify.spotify_request", side_effect=[SpotifyError("unauthorized"),
                   {"access_token": "fresh", "expires_in": 3600}, None]) as request:
            self.assertIsNone(self.provider._api())
        self.assertEqual(request.call_count, 3)

    def test_failed_skip_is_never_retried(self):
        self.provider._state["can_next"] = True
        with patch("spotify.spotify_request", side_effect=SpotifyError("unavailable")) as request:
            self.provider._command("next")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.provider._state["status"], "unavailable")

    def test_waiting_command_preserves_a_new_rate_limit(self):
        self.provider._state.update(status="rate_limited", pending=True)
        self.provider._next_poll = time.monotonic() + 240
        deadline = self.provider._next_poll
        self.provider._command_busy = True
        with patch("spotify.spotify_request") as request:
            self.provider._command("next")
        request.assert_not_called()
        self.assertEqual(self.provider._state["status"], "rate_limited")
        self.assertEqual(self.provider._next_poll, deadline)
        self.assertFalse(self.provider._state["pending"])


class SpotifyRouteTests(unittest.TestCase):
    def setUp(self):
        from app import create_app
        self.app = create_app(mock_mode=True)
        self.client = self.app.test_client()
        self.route = "/api/deskdisplay/spotify/command"

    def test_only_loopback_json_without_browser_origin_can_control(self):
        with patch.object(self.app.extensions["dashboard"].spotify_provider, "command", return_value=True) as command:
            self.assertEqual(self.client.post(self.route, json={"action": "next"},
                                             base_url="http://127.0.0.1").status_code, 202)
            for options in ({"environ_base": {"REMOTE_ADDR": "192.0.2.5"}},
                            {"headers": {"Origin": "http://evil.example"}},
                            {"headers": {"Host": "evil.example"}}):
                self.assertEqual(self.client.post(self.route, json={"action": "next"},
                                                 base_url="http://127.0.0.1", **options).status_code, 403)
            self.assertEqual(self.client.post(self.route, data={"action": "next"},
                                             base_url="http://127.0.0.1").status_code, 403)
            self.assertEqual(self.client.post(self.route, json={"action": []},
                                             base_url="http://127.0.0.1").status_code, 400)
            command.assert_called_once_with("next")

    def test_state_protocol_has_bounded_sanitized_utf8_fields(self):
        from app import _deskdisplay_state_lines
        payload = {"spotify": {"status": "playing", "can_control": True, "can_next": True,
                               "title": "ø" * 200 + "\nnode\tinjected", "artist": "a\tb", "device": "PC"}}
        line = next(line for line in _deskdisplay_state_lines(payload, ()).splitlines() if line.startswith("spotify\t"))
        fields = line.split("\t")
        self.assertEqual(len(fields), 8)
        self.assertEqual(fields[1:3], ["1", "3"])
        self.assertLessEqual(len(fields[5].encode()), 96)
        self.assertEqual(fields[6], "a b")


if __name__ == "__main__":
    unittest.main()
