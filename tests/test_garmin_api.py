import base64
import io
import json
import tempfile
import unittest
import runpy
import sys
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from garmin import GarminProvider
from garmin_api import GarminClient, GarminError, NoRedirect, read_cache, synchronize
from integration_sync import write_json_atomic
from app import _deskdisplay_state_lines
from display_state import DashboardState


def jwt(exp=90000):
    segment = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return "header." + segment + ".signature"


def reply(payload):
    return io.BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())


class GarminApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name)

    def test_token_is_plain_jwt_cached_privately_and_bound_to_key(self):
        opener = Mock()
        opener.open.side_effect = [reply(jwt().encode()), reply({"steps": 300})]
        client = GarminClient("secret", self.cache, opener=opener, clock=lambda: 100)
        self.assertEqual(client.get("/example"), {"steps": 300})
        request = opener.open.call_args_list[0].args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Authorization"), "ApiKey secret")
        self.assertEqual(opener.open.call_args_list[1].args[0].get_header("Authorization"), "Bearer " + jwt())
        second = GarminClient("secret", self.cache, opener=Mock(), clock=lambda: 100)
        self.assertEqual(second.obtain_token(), jwt())
        second.opener.open.assert_not_called()
        third = GarminClient("changed", self.cache, opener=Mock(), clock=lambda: 100)
        third.opener.open.return_value = reply(jwt(100000).encode())
        self.assertEqual(third.obtain_token(), jwt(100000))
        third.opener.open.assert_called_once()
        if hasattr(__import__('os'), "fchmod"):
            self.assertEqual((self.cache / "garmin-token.json").stat().st_mode & 0o777, 0o600)

    def test_401_refresh_once_and_errors_never_expose_response(self):
        opener = Mock()
        error = HTTPError("https://garmin.test", 401, "no", {}, io.BytesIO(b"secret/private data"))
        opener.open.side_effect = [reply(jwt().encode()), error, reply(jwt(100000).encode()), reply([])]
        client = GarminClient("secret", self.cache, opener=opener, clock=lambda: 100)
        self.assertEqual(client.get("/example"), [])
        self.assertEqual(opener.open.call_count, 4)
        opener.open.side_effect = [HTTPError("x", 429, "no", {"Retry-After": "1800"}, io.BytesIO(b"secret"))]
        with self.assertRaises(GarminError) as caught:
            client.get("/example")
        self.assertEqual(caught.exception.retry_after, 1800)
        self.assertNotIn("secret", str(caught.exception))
        opener.open.side_effect = [HTTPError("x", 429, "no", {"Retry-After": "Thu, 01 Jan 1970 01:00:00 GMT"}, io.BytesIO())]
        with self.assertRaises(GarminError) as caught:
            client.get("/example")
        self.assertEqual(caught.exception.retry_after, 3500)

    def test_redirects_and_invalid_tokens_are_rejected(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere"))
        opener = Mock()
        opener.open.return_value = reply(b"not-a-token")
        with self.assertRaises(GarminError):
            GarminClient("secret", self.cache, opener=opener).obtain_token()

    def test_partial_sync_preserves_data_backoff_and_key_change(self):
        client = Mock(fingerprint="one")
        client.get.side_effect = [{"totalSteps": 500}, GarminError("Garmin HTTP 429", status=429, retry_after=1800)]
        result = synchronize("key", self.cache, today=date(2026, 11, 17), client=client, clock=lambda: 100)
        self.assertEqual(result["retry_at"], 1900)
        self.assertEqual(read_cache(self.cache / "garmin-raw.json")["data"]["daily"]["totalSteps"], 500)
        client.reset_mock()
        result = synchronize("key", self.cache, today=date(2026, 11, 18), client=client, clock=lambda: 200)
        client.get.assert_not_called()
        self.assertEqual(result["groups"][0]["metrics"][1]["value"], "--")
        client.fingerprint = "two"
        client.get.side_effect = None
        client.get.return_value = None
        result = synchronize("newkey", self.cache, today=date(2026, 11, 18), client=client, clock=lambda: 200)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(client.get.call_count, 9)
        self.assertNotIn("totalSteps", str(read_cache(self.cache / "garmin-raw.json")["data"]))

    def test_provider_exposes_no_credentials_and_marks_old_data_stale(self):
        path = self.cache / "garmin.json"
        write_json_atomic(path, {"status": "ok", "updated_at": 100, "api_key": "secret", "groups": []})
        state = GarminProvider(path, clock=lambda: 4000).snapshot()
        self.assertEqual(state["status"], "stale")
        self.assertNotIn("secret", str(state))
        write_json_atomic(path, {"status": "ok", "groups": 12, "updated_at": float("nan")})
        self.assertEqual(GarminProvider(path).snapshot()["groups"], [])
        write_json_atomic(path, {"status": "ok", "updated_at": 10**1000,
                                "groups": [{"metrics": [{"history": [10**1000]}]}]})
        state = GarminProvider(path).snapshot()
        self.assertEqual(state["updated_at"], 0)
        self.assertIsNone(state["groups"][0]["metrics"][0]["history"][0])

    def test_cached_garmin_reaches_dashboard_and_compact_transport(self):
        path = self.cache / "garmin.json"
        activity = {"date": "2026-11-17", "activity_type": "running", "distance_km": 5,
                    "duration_seconds": 1500, "average_pace_min_per_km": 5, "average_hr": 140}
        write_json_atomic(path, {"status": "ok", "updated_at": 100, "last_activity": activity,
                                "groups": [{"title": "Today", "metrics": [
                                    {"label": "Steps", "value": "9000", "unit": "", "history": [1000, None, 9000]}]}]})
        provider = GarminProvider(path, clock=lambda: 101)
        state = DashboardState(mock_mode=True, garmin_provider=provider).snapshot()
        self.assertEqual(state["training"]["last_activity"]["average_hr"], 140)
        text = _deskdisplay_state_lines(state, ())
        self.assertIn("garmin\t1\t100\n", text)
        self.assertIn("activity\t2026-11-17\trunning\t50\t1500\t500\t140", text)
        history = next(row for row in text.splitlines() if row.startswith("garmin_metric")).split("\t")[-1]
        self.assertEqual([int(value) for value in history.split(",")], [3333, -32768, 30000, -32768, -32768, -32768, -32768])

    def test_api_failure_does_not_stop_the_existing_calendar_sync(self):
        script = Path(__file__).resolve().parents[1] / "scripts/sync-integrations.py"
        main = runpy.run_path(str(script))["main"]
        config = self.cache / "settings.json"
        write_json_atomic(config, {"garmin": {"api_enabled": True, "api_key": "secret",
                                              "enabled": True, "calendar_url": "https://example.test/private"}})
        failure = Mock(side_effect=GarminError("Garmin HTTP 401", status=401))
        events = [{"title": "Run", "start": "2026-11-18T08:00+01:00", "end": "2026-11-18T09:00+01:00"}]
        with patch.dict(main.__globals__, {"sync_garmin": failure, "fetch_ics": Mock(return_value=b"ics"),
                                         "parse_ics_events": Mock(return_value=events)}), \
             patch.object(sys, "argv", ["sync", "--config", str(config), "--cache-dir", str(self.cache)]), \
             patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO) as error:
            self.assertEqual(main(), 1)
            self.assertNotIn("secret", error.getvalue())
        self.assertEqual(read_cache(self.cache / "garmin.json")["status"], "auth_error")
        self.assertEqual(read_cache(self.cache / "training.json")["workouts"][0]["title"], "Run")


if __name__ == "__main__":
    unittest.main()
