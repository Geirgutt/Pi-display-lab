import io
import unittest
import zipfile

from garmin_charts import MISSING, decode_activity_file, summarize_records


class GarminChartTests(unittest.TestCase):
    def test_elapsed_time_bins_preserve_gaps_and_convert_speed_to_pace(self):
        heart, pace, altitude = summarize_records([
            {"timestamp": 100, "heart_rate": 120, "speed": 3, "altitude": -12},
            {"timestamp": 101, "heart_rate": 124, "speed": 2, "altitude": -8},
            {"timestamp": 220, "heart_rate": 155, "enhanced_speed": 4, "speed": 6},
        ])
        self.assertEqual((heart[0], pace[0], altitude[0]), (122, 400, -10))
        self.assertEqual((heart[-1], pace[-1], altitude[-1]), (155, 250, MISSING))
        self.assertEqual(heart[1:-1], [MISSING] * 22)
        self.assertEqual(summarize_records([{"timestamp": 100}]), [])

    def test_decodes_fit_inside_garmin_download(self):
        try:
            from garmin_fit_sdk import Encoder, Profile
        except ImportError:
            self.skipTest("Garmin FIT SDK unavailable")
        encoder = Encoder()
        encoder.on_mesg(Profile["mesg_num"]["LAP"], {
            "total_timer_time": 300, "total_elapsed_time": 315,
            "total_distance": 1000, "avg_heart_rate": 145,
        })
        for seconds, heart_rate in [(1_160_000_000, 124), (1_160_000_100, 142)]:
            encoder.on_mesg(Profile["mesg_num"]["RECORD"], {
                "timestamp": seconds, "heart_rate": heart_rate,
                "enhanced_speed": 4, "enhanced_altitude": 75,
            })
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("session.fit", encoder.close())
        details = decode_activity_file(output.getvalue())
        heart, pace, altitude = details["series"]
        self.assertEqual((heart[0], heart[-1]), (124, 142))
        self.assertEqual(pace[-1], 250)
        self.assertEqual(altitude[-1], 75)
        self.assertEqual(details["lap_total"], 1)
        self.assertEqual(details["laps"], [[300, 1000, 145]])
