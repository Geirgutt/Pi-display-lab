import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


CPP = r'''#include <cassert>
#include <cstdint>
#include "alarm_input.h"

int main()
{
    alarm_input::Editor editor;

    editor.begin(23);
    assert(editor.maximum == 23 && editor.value == 0 && editor.length == 0);
    assert(!editor.valid()); // empty input cannot be saved
    assert(editor.digit(2));
    assert(editor.digit(3)); // 23 is a valid hour
    assert(editor.valid() && editor.value == 23 && editor.length == 2);

    editor.clear();
    assert(editor.digit(2));
    assert(!editor.digit(4)); // 24 is rejected without changing prior input
    assert(editor.value == 2 && editor.length == 1 && editor.error && !editor.valid());
    editor.erase(); // clears the error and erases the partial value
    assert(editor.value == 0 && editor.length == 0 && !editor.error);
    assert(editor.digit(2) && editor.digit(3));
    assert(editor.valid() && editor.value == 23);

    editor.begin(59);
    assert(editor.maximum == 59 && !editor.valid());
    assert(editor.digit(4) && editor.digit(4)); // 44 is a valid minute
    assert(editor.valid() && editor.value == 44);
    assert(!editor.digit(5)); // reject a third digit without changing the value
    assert(editor.value == 44 && editor.length == 2 && editor.error && !editor.valid());

    editor.begin(59);
    assert(editor.digit(6));
    assert(!editor.digit(0)); // 60 is outside the minute range
    assert(editor.value == 6 && editor.length == 1 && editor.error && !editor.valid());

    editor.begin(59);
    assert(editor.digit(0) && editor.digit(0)); // leading-zero 00
    assert(editor.valid() && editor.value == 0 && editor.length == 2);
    editor.begin(59);
    assert(editor.digit(0) && editor.digit(5)); // leading-zero 05
    assert(editor.valid() && editor.value == 5 && editor.length == 2);

    editor.begin(23);
    assert(editor.digit(5)); // one-digit values are valid
    assert(editor.valid() && editor.value == 5 && editor.length == 1);
    assert(!editor.digit(10)); // keypad input must be one decimal digit
    assert(editor.value == 5 && editor.length == 1 && editor.error && !editor.valid());
    editor.clear();
    assert(editor.value == 0 && editor.length == 0 && !editor.error && !editor.valid());
}
'''


class DeskDisplayAlarmInputTest(unittest.TestCase):
    def run_cpp(self, program):
        compiler = shutil.which("c++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("c++ or g++ is unavailable")
        with tempfile.TemporaryDirectory(prefix="deskdisplay-alarm-input-") as temp:
            source = Path(temp) / "alarm_input_test.cpp"
            executable = Path(temp) / "alarm_input_test"
            source.write_text(program, encoding="utf-8")
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

    def test_header_behavior(self):
        self.run_cpp(CPP)

    def test_alarm_number_save_and_cancel_actions(self):
        source = (ROOT / "deskdisplay" / "src" / "app.cpp").read_text(encoding="utf-8")
        action_match = re.search(r"\bvoid\s+action\s*\(\s*uint8_t\s+button\s*\)", source)
        self.assertIsNotNone(action_match, "Could not find action(uint8_t button)")
        opening = source.find("{", action_match.end())
        self.assertGreaterEqual(opening, 0, "Could not find action() body")

        def body_at(open_brace):
            depth = 0
            for index in range(open_brace, len(source)):
                if source[index] == "{":
                    depth += 1
                elif source[index] == "}":
                    depth -= 1
                    if depth == 0:
                        return source[open_brace + 1:index]
            self.fail("Unclosed C++ block in app.cpp")

        action_body = body_at(opening)
        alarm_match = re.search(r"if\s*\(\s*model\.page\s*==\s*app_state::Page::AlarmNumber\s*\)", action_body)
        self.assertIsNotNone(alarm_match, "Could not find AlarmNumber action branch")
        alarm_opening = action_body.find("{", alarm_match.end())
        self.assertGreaterEqual(alarm_opening, 0)
        alarm_branch = body_at(opening + 1 + alarm_opening)

        save_match = re.search(r"else\s+if\s*\(\s*button\s*==\s*52\s*\)", alarm_branch)
        self.assertIsNotNone(save_match, "Could not find save action 52")
        save_opening = alarm_branch.find("{", save_match.end())
        self.assertGreaterEqual(save_opening, 0)
        # Balance braces in the extracted branch itself.
        save_depth = 0
        for index in range(save_opening, len(alarm_branch)):
            if alarm_branch[index] == "{":
                save_depth += 1
            elif alarm_branch[index] == "}":
                save_depth -= 1
                if save_depth == 0:
                    save_branch = alarm_branch[save_opening + 1:index]
                    break
        else:
            self.fail("Unclosed save action 52 branch")

        cancel_match = re.search(r"else\s+if\s*\(\s*button\s*==\s*53\s*\)\s*\{([^}]*)\}", alarm_branch)
        self.assertIsNotNone(cancel_match, "Could not find cancel action 53")
        cancel_branch = cancel_match.group(1)
        self.assertIn("hardware::setAlarm", save_branch)
        self.assertEqual(alarm_branch.count("hardware::setAlarm"), 1)
        self.assertIn("model.page = app_state::Page::Alarm", cancel_branch)
        self.assertIn("return", cancel_branch)
        self.assertNotIn("hardware::setAlarm", cancel_branch)


if __name__ == "__main__":
    unittest.main()
