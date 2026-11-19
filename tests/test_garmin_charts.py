import io
import unittest
import zipfile

from garmin_charts import MISSING, decode_activity_file, summarize_pace_target, summarize_records, summarize_route


class GarminChartTests(unittest.TestCase):
    def test_elapsed_time_bins_preserve_gaps_and_convert_speed_to_pace(self):
        heart, pace, altitude, _, _ = summarize_records([
            {"timestamp": 100, "heart_rate": 120, "speed": 3, "altitude": -12},
            {"timestamp": 101, "heart_rate": 124, "speed": 2, "altitude": -8},
            {"timestamp": 220, "heart_rate": 155, "enhanced_speed": 4, "speed": 6},
        ])
        self.assertEqual((heart[0], pace[0], altitude[0]), (122, 400, -10))
        self.assertEqual((heart[-1], pace[-1], altitude[-1]), (155, 250, MISSING))
        self.assertEqual(heart[1:-1], [MISSING] * 22)
        self.assertEqual(summarize_records([{"timestamp": 100}]), [])

    def test_route_preserves_north_and_crosses_antimeridian_without_wrapping_the_screen(self):
        route = summarize_route([
            {"position_lat": 0, "position_long": 2**31 - 100},
            {"position_lat": 100, "position_long": -2**31 + 100},
        ])
        self.assertEqual(route, [[0, 180], [240, 60]])
        self.assertEqual(summarize_route([{"position_lat": 0, "position_long": 2**31 - 1}]), [])

    def test_running_cadence_includes_fractional_cycles_before_averaging(self):
        records = [
            {"timestamp": 100, "cadence": 82, "fractional_cadence": 0.5},
            {"timestamp": 101, "cadence": 83, "fractional_cadence": 0.5},
            {"timestamp": 220, "cadence": 84, "fractional_cadence": 0.5},
            {"timestamp": 340, "fractional_cadence": 0.5},
        ]
        running = summarize_records(records, running=True)[3]
        cycling = summarize_records(records)[3]
        self.assertEqual((running[0], running[12], running[-1]), (166, 169, MISSING))
        self.assertEqual(cycling[12], 84)

    def test_download_with_gpx_or_tcx_recovers_a_route(self):
        gpx = b'<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg><trkpt lat="59" lon="10"/>\n<trkpt lat="59.001" lon="10"/></trkseg></trk></gpx>'
        tcx = b'<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"><Track><Trackpoint><Position><LatitudeDegrees>59</LatitudeDegrees><LongitudeDegrees>10</LongitudeDegrees></Position></Trackpoint><Trackpoint><Position><LatitudeDegrees>59.001</LatitudeDegrees><LongitudeDegrees>10</LongitudeDegrees></Position></Trackpoint></Track></TrainingCenterDatabase>'
        for name, contents in (("track.gpx", gpx), ("track.tcx", tcx)):
            with self.subTest(name=name):
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w") as archive:
                    archive.writestr("empty/" + name, b"<gpx/>")
                    archive.writestr(name, contents)
                details = decode_activity_file(output.getvalue())
                self.assertEqual(details["route"], [[120, 240], [120, 0]])
                self.assertEqual(details["map_coordinates"], [[59.0, 10.0], [59.001, 10.0]])

    def test_decodes_fit_inside_garmin_download(self):
        try:
            from garmin_fit_sdk import Encoder, Profile
        except ImportError:
            self.skipTest("Garmin FIT SDK unavailable")
        encoder = Encoder()
        encoder.on_mesg(Profile["mesg_num"]["WORKOUT_STEP"], {
            "target_type": "speed", "target_value": 0,
            "custom_target_value_low": 3000, "custom_target_value_high": 4000,
        })
        encoder.on_mesg(Profile["mesg_num"]["LAP"], {
            "total_timer_time": 300, "total_elapsed_time": 315,
            "total_distance": 1000, "avg_heart_rate": 145,
        })
        for seconds, heart_rate in [(1_160_000_000, 124), (1_160_000_100, 142)]:
            encoder.on_mesg(Profile["mesg_num"]["RECORD"], {
                "timestamp": seconds, "heart_rate": heart_rate,
                "enhanced_speed": 4, "enhanced_altitude": 75,
                "position_lat": 600_000_000 + heart_rate * 100,
                "position_long": 160_000_000 + heart_rate * 100,
                "cadence": 84, "fractional_cadence": 0.5, "power": 235,
            })
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("session.fit", encoder.close())
        details = decode_activity_file(output.getvalue())
        heart, pace, altitude, cadence, power = details["series"]
        self.assertEqual((heart[0], heart[-1]), (124, 142))
        self.assertEqual(pace[-1], 250)
        self.assertEqual(altitude[-1], 75)
        self.assertEqual((cadence[-1], power[-1]), (84, 235))
        self.assertEqual(decode_activity_file(output.getvalue(), running=True)["series"][3][-1], 169)
        self.assertEqual(len(details["route"]), 2)
        self.assertEqual(details["lap_total"], 1)
        self.assertEqual(details["laps"], [[300, 1000, 145]])
        self.assertEqual(details["pace_target"], [250, 333])

    def test_activity_zip_can_get_positions_from_a_later_fit_with_gps_metadata(self):
        try:
            from garmin_fit_sdk import Encoder, Profile
        except ImportError:
            self.skipTest("Garmin FIT SDK unavailable")
        record = Profile["mesg_num"]["RECORD"]
        metadata = Profile["mesg_num"]["GPS_METADATA"]
        timestamps = (1_160_000_000, 1_160_000_100)
        stats = Encoder()
        track = Encoder()
        for index, timestamp in enumerate(timestamps):
            stats.on_mesg(record, {"timestamp": timestamp, "heart_rate": 124})
            track.on_mesg(metadata, {"timestamp": timestamp,
                                      "position_lat": 600_000_000 + index * 100,
                                      "position_long": 160_000_000})
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("01-stats.fit", stats.close())
            archive.writestr("02-track.fit", track.close())
        details = decode_activity_file(output.getvalue())
        self.assertEqual(details["route"], [[120, 240], [120, 0]])
        self.assertEqual(details["series"][0][0], 124)

    def test_different_speed_targets_do_not_look_like_one_constant_target(self):
        self.assertEqual(summarize_pace_target([
            {"target_type": "speed", "custom_target_speed_low": 1, "custom_target_speed_high": 2},
            {"target_type": "speed", "custom_target_speed_low": 3, "custom_target_speed_high": 4},
        ]), [])
