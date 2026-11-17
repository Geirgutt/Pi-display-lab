"""Focused tests for the Garmin and ICS configuration wizard."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "configure-integrations.py"
SPEC = importlib.util.spec_from_file_location("configure_integrations", SCRIPT)
configure_integrations = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(configure_integrations)


class GarminSetupTests(unittest.TestCase):
    def test_reset_keeps_existing_api_key_and_calendar_feeds(self) -> None:
        old = {
            "version": 1,
            "other_setting": {"keep": True},
            "garmin": {
                "enabled": True,
                "calendar_url": "https://example.test/garmin.ics",
                "api_enabled": True,
                "api_key": "private-api-key",
            },
            "calendar": {
                "enabled": True,
                "feeds": [{"name": "Work", "url": "https://example.test/work.ics"}],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "integrations.json"
            path.write_text(json.dumps(old), encoding="utf-8")
            with patch.object(configure_integrations.sys.stdin, "isatty", return_value=True), \
                    patch("builtins.input", side_effect=["j", "j", "n", "j"]), \
                    patch.object(configure_integrations.getpass, "getpass", return_value=""), \
                    patch("builtins.print") as printed:
                    self.assertEqual(configure_integrations.main(["--config", str(path), "--reset"]), 0)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], 2)
            self.assertEqual(saved["other_setting"], old["other_setting"])
            self.assertEqual(saved["garmin"]["api_key"], "private-api-key")
            self.assertEqual(saved["garmin"]["calendar_url"], old["garmin"]["calendar_url"])
            self.assertEqual(saved["calendar"]["feeds"], old["calendar"]["feeds"])
            self.assertNotIn("private-api-key", " ".join(str(call) for call in printed.call_args_list))

    def test_new_setup_stores_hidden_personal_api_key_and_ics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "integrations.json"
            with patch.object(configure_integrations.sys.stdin, "isatty", return_value=True), \
                    patch("builtins.input", side_effect=["j", "j", "n"]), \
                    patch.object(
                        configure_integrations.getpass,
                        "getpass",
                        side_effect=["api-secret", "https://example.test/garmin.ics"],
                    ), \
                    patch("builtins.print") as printed:
                self.assertEqual(configure_integrations.main(["--config", str(path)]), 0)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], 2)
            self.assertEqual(saved["garmin"]["api_enabled"], True)
            self.assertEqual(saved["garmin"]["api_key"], "api-secret")
            self.assertEqual(saved["garmin"]["enabled"], True)
            self.assertEqual(saved["garmin"]["calendar_url"], "https://example.test/garmin.ics")
            self.assertNotIn("api-secret", " ".join(str(call) for call in printed.call_args_list))

    def test_reset_can_remove_api_key_and_calendar_feeds(self) -> None:
        old = {
            "garmin": {"enabled": True, "calendar_url": "https://example.test/garmin.ics", "api_enabled": True, "api_key": "secret"},
            "calendar": {"enabled": True, "feeds": [{"name": "Work", "url": "https://example.test/work.ics"}]},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "integrations.json"
            path.write_text(json.dumps(old), encoding="utf-8")
            with patch.object(configure_integrations.sys.stdin, "isatty", return_value=True), \
                    patch("builtins.input", side_effect=["n", "j", "n", "n", "n"]), \
                    patch.object(configure_integrations.getpass, "getpass", return_value=""), \
                    patch("builtins.print"):
                self.assertEqual(configure_integrations.main(["--config", str(path), "--reset"]), 0)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["garmin"]["api_key"], "")
            self.assertEqual(saved["garmin"]["enabled"], False)
            self.assertEqual(saved["garmin"]["calendar_url"], "")
            self.assertEqual(saved["calendar"]["feeds"], [])
            self.assertEqual(saved["calendar"]["enabled"], False)


if __name__ == "__main__":
    unittest.main()
