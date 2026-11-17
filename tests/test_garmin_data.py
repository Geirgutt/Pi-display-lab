from datetime import date
import math
import unittest

from garmin_data import build_dashboard


class GarminDashboardTests(unittest.TestCase):
    def test_documented_nested_shapes_units_and_calendar_gaps(self):
        today = date(2026, 11, 17)
        days = [date(2026, 11, d) for d in (11, 13, 17)]
        raw = {
            "daily": {
                "calendarDate": "2026-11-17", "bodyBatteryMostRecentValue": 62,
                "totalSteps": 8123, "averageStressLevel": 28, "restingHeartRate": 48,
                "totalKilocalories": 2310, "hydrationValueInML": 1800,
                "latestSpo2": 97, "latestRespirationValue": 14.2,
                "moderateIntensityMinutes": 20, "vigorousIntensityMinutes": 15,
            },
            "summaries": {"data": [
                {"calendarDate": d.isoformat(), "bodyBattery": {"latestValue": i * 10},
                 "movement": {"steps": {"value": i * 1000}}, "stress": {"avgLevel": i + 10},
                 "heartRate": {"restingValue": 50 + i}, "calories": {"burnedTotal": 2000 + i},
                 "hydration": {"consumedInFractionalMl": 1200 + i},
                 "pulseOx": {"latestValue": 96}, "respiration": {"latestValue": 13 + i},
                 "intensityMinutes": {"moderate": 10 + i, "vigorous": 2}}
                for i, d in enumerate(days, 1)
            ]},
            "sleep": [
                {"calendarDate": "2026-11-17", "sleepTimeSeconds": 25200,
                 "deepSleepSeconds": 3600, "remSleepSeconds": 5400,
                 "sleepScores": {"overall": {"value": 84}}}
            ],
            "hrv": {"hrvSummaries": [
                {"calendarDate": "2026-11-17", "lastNightAvg": 52, "status": "BALANCED"},
                {"calendarDate": "2026-11-16", "lastNightAvg": -1, "status": "LOW"},
            ]},
            "weight": {"dailyWeightSummaries": [
                {"summaryDate": "2026-11-16", "latestWeight": {"weight": 71.25}}
            ]},
            "hydration": [
                {"calendarDate": "2026-11-11", "valueInML": 900},
                {"calendarDate": "2026-11-17", "valueInML": 1800},
            ],
            "vo2": [{"generic": {"calendarDate": "2026-11-15", "vo2MaxValue": 48.6}}],
            "fitness_age": {"fitnessAge": 32.5},
            "activities": [{
                "startTimeLocal": "2026-11-16 08:15:00", "activityType": {"typeKey": "running"},
                "distance": 5200, "duration": 1560, "averageHR": 145,
                "aerobicTrainingEffect": 3.2, "activityTrainingLoad": 105,
            }],
        }
        result = build_dashboard(raw, today=today)
        groups = result["groups"]
        self.assertEqual(len(groups), 4)
        self.assertTrue(all(len(group["metrics"]) == 6 for group in groups))
        self.assertEqual(groups[0]["metrics"][0]["value"], "62")
        self.assertEqual(groups[0]["metrics"][1]["value"], "8123")
        # History always spans the last seven calendar dates; omitted dates stay missing.
        self.assertEqual(groups[0]["metrics"][1]["history"], [1000.0, None, 2000.0, None, None, None, 3000.0])
        self.assertEqual(groups[1]["metrics"][0]["value"], "7.0")
        self.assertEqual(groups[1]["metrics"][1]["value"], "84")
        self.assertEqual(groups[1]["metrics"][4]["value"], "52")
        self.assertEqual(groups[1]["metrics"][4]["history"][5], None)
        self.assertEqual(groups[2]["metrics"][0]["value"], "71.2")
        self.assertEqual(groups[2]["metrics"][1]["value"], "48.6")
        self.assertEqual(groups[2]["metrics"][2]["value"], "32.5")
        self.assertEqual(groups[2]["metrics"][5]["value"], "50")
        self.assertEqual(groups[2]["metrics"][5]["history"][0], 15)
        self.assertEqual(groups[3]["title"], "Activity 2026-11-16")
        self.assertEqual(result["last_activity"], {
            "date": "2026-11-16", "activity_type": "running", "distance_km": 5.2,
            "duration_seconds": 1560.0, "average_pace_min_per_km": 5.0, "average_hr": 145.0,
        })

    def test_missing_or_malformed_data_stays_missing_and_current_day_is_not_backfilled(self):
        out = build_dashboard({
            "daily": {"calendarDate": "2026-11-16", "totalSteps": 9000},
            "summaries": {"data": [
                {"calendarDate": "2026-11-17", "movement": {"steps": {"value": True}},
                 "intensityMinutes": {"moderate": 10}},
                {"calendarDate": "not-a-date", "movement": {"steps": {"value": 33}}},
            ]},
            "sleep": [{"calendarDate": "2026-11-17", "sleepTimeSeconds": math.inf}],
            "hrv": {"hrvSummaries": [{"calendarDate": "2026-11-17", "lastNightAvg": -1}]},
            "activities": [],
        }, today=date(2026, 11, 17))
        self.assertEqual(out["groups"][0]["metrics"][0]["value"], "--")
        self.assertEqual(out["groups"][0]["metrics"][1]["value"], "--")
        self.assertEqual(out["groups"][0]["metrics"][1]["history"][-1], None)
        self.assertEqual(out["groups"][1]["metrics"][0]["value"], "--")
        self.assertEqual(out["groups"][1]["metrics"][4]["value"], "--")
        self.assertEqual(out["groups"][2]["metrics"][5]["history"][-1], None)
        self.assertIsNone(out["last_activity"])
        for group in out["groups"]:
            for metric in group["metrics"]:
                self.assertLessEqual(len(metric["label"]), 20)
                self.assertLessEqual(len(metric["value"]), 16)
                self.assertLessEqual(len(metric["unit"]), 12)
                self.assertTrue(metric["value"].isascii())


if __name__ == "__main__":
    unittest.main()
