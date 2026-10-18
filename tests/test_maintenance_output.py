"""Tests for the stdlib-only maintenance terminal renderer."""

import io
import threading
import unittest
from unittest.mock import patch

from maintenance_output import MaintenanceOutput, STAGES


class QuietStream(io.StringIO):
    def isatty(self):
        return False


class TTYStream(io.StringIO):
    def __init__(self):
        super().__init__()
        self.pulse_written = threading.Event()

    def isatty(self):
        return True

    def write(self, value):
        if value.startswith("\rpi-one:"):
            self.pulse_written.set()
        return super().write(value)


class MaintenanceOutputTests(unittest.TestCase):
    def test_package_version_changes_and_new_installs_are_reported(self):
        stream = QuietStream()
        output = MaintenanceOutput(["pi-one"], upgrade=True, stream=stream)
        output.result("pi-one", "before", {
            "stdout": "installed\tbase-files\t12.4\ninstalled\told-only\t1.0\n"
                      "deinstall\tremoved\t<none>\n",
        })
        output.result("pi-one", "after", {
            "stdout": "installed\tbase-files\t12.5\ninstalled\tnew-tool\t2.0\n",
        })
        output.finish()

        text = stream.getvalue()
        self.assertIn("2 installerte pakker endret", text)
        self.assertIn("base-files 12.4 → 12.5", text)
        self.assertIn("new-tool 2.0 (ny installasjon)", text)
        self.assertIn("1 nye pakker; 1 oppgradert", text)
        self.assertNotIn("removed", text)

    def test_available_and_remaining_show_counts_names_and_versions(self):
        stream = QuietStream()
        output = MaintenanceOutput(["pi-one"], upgrade=False, stream=stream)
        apt_output = (
            "Listing... Done\n"
            "openssl/stable-security 3.0.14-1~deb12u2 arm64 [upgradable from: 3.0.14-1~deb12u1]\n"
            "kernel/stable 6.1.1 arm64 [upgradable from: 6.1.0]\n"
        )
        output.result("pi-one", "available", {"stdout": apt_output})
        output.result("pi-one", "remaining", {"stdout": apt_output.splitlines()[0] + "\n" + apt_output.splitlines()[1]})

        text = stream.getvalue()
        self.assertIn("2 oppgraderinger tilgjengelig", text)
        self.assertIn("openssl: 3.0.14-1~deb12u1 → 3.0.14-1~deb12u2", text)
        self.assertIn("1 oppgraderinger gjenstår", text)
        self.assertIn("kernel", text)

    def test_update_only_uses_available_packages_as_remaining_and_reports_zero_changes(self):
        stream = QuietStream()
        output = MaintenanceOutput(["pi-one"], upgrade=False, stream=stream)
        output.result("pi-one", "available", {
            "stdout": "pkg/stable 2.0 amd64 [upgradable from: 1.0]\n",
        })
        output.result("pi-one", "upgrade", {}, skipped=True)
        output.finish()

        text = stream.getvalue()
        self.assertIn("pakkeoppgraderingen ble ikke kjørt", text)
        self.assertIn("0 nye pakker; 0 oppgradert; 1 oppgraderinger gjenstår", text)

    def test_tty_pulse_stops_and_joins_before_next_stage_resets_event(self):
        stream = TTYStream()
        output = MaintenanceOutput(["pi-one"], upgrade=True, stream=stream)
        # Make the pulse thread emit once, then exit, without waiting five seconds.
        with patch.object(output._pulse_stop, "wait", side_effect=[False, True, True]) as wait, \
                patch("maintenance_output.time.monotonic", side_effect=[10.0, 15.0, 20.0]):
            output.start("pi-one", "refresh")
            self.assertTrue(stream.pulse_written.wait(1))
            first_thread = output._pulse_thread
            output.result("pi-one", "refresh", {})
            self.assertFalse(first_thread.is_alive())

            output.start("pi-one", "upgrade")
            second_thread = output._pulse_thread
            second_thread.join(1)
            self.assertFalse(second_thread.is_alive())
            output.result("pi-one", "upgrade", {})

        self.assertEqual(wait.call_count, 3)
        self.assertIn("… 5s", stream.getvalue())

    def test_skipped_stages_advance_node_progress_and_reboot_is_measured(self):
        stream = QuietStream()
        output = MaintenanceOutput(["pi-one", "pi-two"], upgrade=False, stream=stream)
        for stage in STAGES:
            output.result("pi-one", stage, {"stat": {"exists": False}}, skipped=stage != "reboot")
        output.result("pi-two", "refresh", {}, skipped=True)
        output.fail("pi-two", "apt feilet")
        output.finish()

        text = stream.getvalue()
        self.assertIn("trinn 7/7", text)
        self.assertIn("[###-----------------] trinn 1/7", text)
        self.assertIn("operativsystemet melder ikke behov for omstart", text)
        self.assertIn("1 fullført, 1 feilet, 0 ufullstendig", text)
        self.assertIn("omstart ikke meldt", text)
        self.assertIn("pi-two: feilet", text)

    def test_unknown_worker_or_stage_is_rejected(self):
        output = MaintenanceOutput(["pi-one"], upgrade=False, stream=QuietStream())
        with self.assertRaises(ValueError):
            output.start("missing", "refresh")
        with self.assertRaises(ValueError):
            output.start("pi-one", "preflight")


if __name__ == "__main__":
    unittest.main()
