import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


CPP = r'''#include <cassert>
#include <cstring>
#include <cstdint>
#include "navigation_gesture.h"
#include "home_content.h"

using navigation_gesture::Result;

static Result gesture(int16_t ex, int16_t ey, uint32_t start = 100,
                      uint32_t end = 200, int16_t sx = 100, int16_t sy = 150)
{
    navigation_gesture::Tracker t;
    t.begin(sx, sy, start);
    t.move(ex, ey);
    return t.finish(end);
}

static Result returningGesture()
{
    navigation_gesture::Tracker t;
    t.begin(100, 150, 100);
    t.move(100, 60);
    t.move(100, 150);
    return t.finish(200);
}

static void copyDate(char (&dest)[11], const char* date)
{
    std::strncpy(dest, date, sizeof(dest) - 1);
}

int main()
{
    assert(gesture(116, 134) == Result::Tap); // small diagonal jitter
    assert(gesture(102, 60) == Result::Up);
    assert(gesture(102, 240) == Result::Down);
    assert(gesture(180, 145) == Result::Cancel); // horizontal drag
    assert(gesture(150, 70) == Result::Cancel); // diagonal drag
    assert(returningGesture() == Result::Cancel); // moved away, then returned
    assert(gesture(100, 100) == Result::Cancel); // short vertical drag
    assert(gesture(101, 60, 100, 1701) == Result::Cancel); // long drag
    assert(gesture(104, 153, 100, 5000) == Result::Tap); // hold without travel
    assert(gesture(100, 60, UINT32_MAX - 100, 50) == Result::Up); // millis wrap

    secure_protocol::TrainingTelemetry training;
    training.available = true;
    training.count = 4;
    copyDate(training.workouts[0].date, "2026-10-04");
    copyDate(training.workouts[1].date, "2026-09-28");
    copyDate(training.workouts[2].date, "2026-10-01");
    copyDate(training.workouts[3].date, "bad");
    assert(home_content::nextWorkout(training, "2026-09-29") == 2);
    training.available = false;
    assert(home_content::nextWorkout(training, "2026-09-29") == -1);
    training.available = true;
    assert(home_content::nextWorkout(training, "") == -1);

    secure_protocol::CalendarTelemetry calendar;
    calendar.available = true;
    calendar.count = 3;
    calendar.events[0].startsAt = 300;
    calendar.events[0].endsAt = 400;
    std::strcpy(calendar.events[0].title, "later");
    calendar.events[1].startsAt = 100;
    calendar.events[1].endsAt = 200;
    calendar.events[1].allDay = true;
    std::strcpy(calendar.events[1].title, "expired all-day");
    calendar.events[2].startsAt = 150;
    calendar.events[2].endsAt = 250;
    std::strcpy(calendar.events[2].title, "active");
    assert(home_content::nextEvent(calendar, 150) == 1); // active all-day event
    assert(home_content::nextEvent(calendar, 200) == 2); // end is exclusive
    assert(home_content::nextEvent(calendar, 250) == 0); // events at/past end skipped
    calendar.events[0].startsAt = 0;
    assert(home_content::nextEvent(calendar, 100) == 1); // zero start ignored
    assert(home_content::nextEvent(calendar, 0) == -1);
    calendar.available = false;
    assert(home_content::nextEvent(calendar, 100) == -1);
}
'''


class DeskDisplayNavigationTest(unittest.TestCase):
    def test_header_behavior(self):
        compiler = shutil.which("c++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("c++ or g++ is unavailable")
        with tempfile.TemporaryDirectory(prefix="deskdisplay-navigation-") as temp:
            source = Path(temp) / "navigation_test.cpp"
            executable = Path(temp) / "navigation_test"
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


if __name__ == "__main__":
    unittest.main()
