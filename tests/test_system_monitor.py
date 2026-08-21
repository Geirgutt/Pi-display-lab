"""Tester dekoding og fallback for Raspberry Pi-klokke og strupestatus."""

import unittest
from unittest.mock import patch

from display_state import SystemMonitor, decode_throttle_flags


class SystemMonitorTests(unittest.TestCase):
    def test_active_undervoltage_and_throttling_are_decoded(self) -> None:
        status = decode_throttle_flags(0x50005)
        self.assertTrue(status["under_voltage"])
        self.assertTrue(status["throttled"])
        self.assertTrue(status["active"])
        self.assertTrue(status["occurred"])
        self.assertEqual(status["raw"], "0x50005")
        self.assertIn("UNDERVOLTAGE", status["summary"])

    def test_history_bits_are_not_reported_as_current(self) -> None:
        status = decode_throttle_flags(0x50000)
        self.assertFalse(status["active"])
        self.assertTrue(status["occurred"])
        self.assertTrue(status["summary"].startswith("TIDLIGERE:"))

    def test_vcgencmd_output_is_parsed_without_a_shell(self) -> None:
        with patch.object(SystemMonitor, "_run_vcgencmd", return_value="throttled=0x50005"):
            self.assertEqual(SystemMonitor._throttle_status()["flags"], 0x50005)

        with (
            patch("pathlib.Path.read_text", side_effect=OSError),
            patch.object(SystemMonitor, "_run_vcgencmd", return_value="frequency(48)=1000000000"),
        ):
            self.assertEqual(SystemMonitor._cpu_frequency_mhz(), 1000.0)


if __name__ == "__main__":
    unittest.main()
