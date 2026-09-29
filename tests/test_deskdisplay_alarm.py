import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


CPP = r'''#include <cassert>
#include <cstdint>
#include "alarm_schedule.h"

int main()
{
    using alarm_schedule::shouldRearm;

    // Enabling and schedule edits each start a fresh alarm.
    assert(shouldRearm(false, 7, 30, true, true, 7, 30, true));
    assert(shouldRearm(true, 7, 30, true, true, 8, 30, true));
    assert(shouldRearm(true, 7, 30, true, true, 7, 31, true));
    assert(shouldRearm(true, 7, 30, true, true, 7, 30, false));

    // Turning an alarm off alone preserves its fired-date suppression. Turning
    // it back on is an explicit rearm, even with the same schedule.
    assert(!shouldRearm(true, 7, 30, true, false, 7, 30, true));
    assert(shouldRearm(false, 7, 30, true, true, 7, 30, true));

    // An unchanged daily schedule does not rearm after its date was recorded.
    assert(!shouldRearm(true, 7, 30, true, true, 7, 30, true));
}
'''


def function_body(source, signature):
    """Return one C++ function body, balancing braces within its definition."""
    match = re.search(signature, source)
    if match is None:
        raise AssertionError(f"Could not find function matching {signature!r}")
    opening = source.find("{", match.end())
    if opening < 0:
        raise AssertionError(f"Could not find body for function matching {signature!r}")
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1:index]
    raise AssertionError(f"Unclosed body for function matching {signature!r}")


class DeskDisplayAlarmTest(unittest.TestCase):
    def test_header_behavior(self):
        compiler = shutil.which("c++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("c++ or g++ is unavailable")
        with tempfile.TemporaryDirectory(prefix="deskdisplay-alarm-") as temp:
            source = Path(temp) / "alarm_test.cpp"
            executable = Path(temp) / "alarm_test"
            source.write_text(CPP, encoding="utf-8")
            compile_result = subprocess.run(
                [compiler, "-std=c++11", "-Wall", "-Wextra",
                 "-I", str(ROOT / "deskdisplay" / "src"), str(source), "-o", str(executable)],
                capture_output=True, text=True,
            )
            self.assertEqual(
                compile_result.returncode, 0,
                f"C++ compilation failed (exit {compile_result.returncode})\n"
                f"stdout:\n{compile_result.stdout}\nstderr:\n{compile_result.stderr}",
            )
            run_result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(
                run_result.returncode, 0,
                f"C++ test executable failed (exit {run_result.returncode})\n"
                f"stdout:\n{run_result.stdout}\nstderr:\n{run_result.stderr}",
            )

    def test_set_alarm_clears_fired_date_only_when_rearming(self):
        source = (ROOT / "deskdisplay" / "src" / "hardware.cpp").read_text(encoding="utf-8")
        body = function_body(source, r"\bvoid\s+setAlarm\s*\(")
        self.assertIn("alarm_schedule::shouldRearm", body)
        self.assertRegex(body, r"if\s*\(rearm\)\s*currentLastAlarmDate\s*=\s*0\s*;")
        self.assertRegex(body, r"if\s*\(rearm\)\s*preferences\.putUInt\(lastAlarmDateKey,\s*0\s*\)\s*;")

    def test_daily_fired_date_is_checked_before_scheduled_alarm_starts(self):
        source = (ROOT / "deskdisplay" / "src" / "app.cpp").read_text(encoding="utf-8")
        start_body = function_body(source, r"\bvoid\s+startAlarm\s*\(")
        check_body = function_body(source, r"\bvoid\s+checkAlarm\s*\(")

        self.assertNotIn("markAlarmFired", start_body)
        self.assertRegex(check_body, r"date\s*==\s*hardware::lastAlarmDate\(\)")
        self.assertIn("hardware::markAlarmFired(date, !model.alarmRepeats)", check_body)
        self.assertLess(check_body.index("hardware::markAlarmFired"), check_body.index("startAlarm()"))

    def test_test_alarm_starts_preview_without_saving_schedule(self):
        app_source = (ROOT / "deskdisplay" / "src" / "app.cpp").read_text(encoding="utf-8")
        ui_source = (ROOT / "deskdisplay" / "src" / "ui.cpp").read_text(encoding="utf-8")
        switch_start = app_source.index("switch (button)")
        preview_start = app_source.index("case 19:", switch_start)
        next_case = app_source.index("case 10:", preview_start)
        preview_case = app_source[preview_start:next_case]
        alarm_ui = function_body(ui_source, r"\bvoid\s+alarmSettings\s*\(")

        self.assertIn("startAlarm();", preview_case)
        self.assertNotIn("markAlarmFired", preview_case)
        self.assertNotIn("setAlarm", preview_case)
        self.assertRegex(alarm_ui, r'button\(19,\s*"Test alarm"')


if __name__ == "__main__":
    unittest.main()
