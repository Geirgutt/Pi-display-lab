import io
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from garmin_maps import IMAGE_SIZE, MAX_MAP_BYTES, USER_AGENT, _tile, _viewport, render_route_map


class GarminMapTests(unittest.TestCase):
    def test_viewport_crosses_antimeridian_at_local_scale(self):
        zoom, _, _, line = _viewport([[60, 179.998], [60, -179.998]])
        self.assertGreaterEqual(zoom, 15)
        self.assertGreater(line[1][0], line[0][0])
        self.assertTrue(all(24 <= x <= IMAGE_SIZE - 24 for x, _ in line))

    def test_tile_revalidates_expired_entry_and_reuses_fresh_entry(self):
        png = b"\x89PNG\r\n\x1a\n" + b"cached"
        response = io.BytesIO(png)
        response.headers = {"ETag": '"first"', "Cache-Control": "max-age=0",
                            "Last-Modified": "Tue, 17 Nov 2026 12:00:00 GMT"}
        not_modified = HTTPError(
            "https://tile.openstreetmap.org/1/0/1.png", 304, "Not Modified",
            {"Cache-Control": "max-age=120"}, io.BytesIO(),
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "garmin_maps.urlopen", side_effect=[response, not_modified]
        ) as request:
            for _ in range(3):
                self.assertEqual(_tile(Path(directory), 1, 0, 1, 1), png)
        self.assertEqual(request.call_count, 2)
        first, second = [call.args[0] for call in request.call_args_list]
        self.assertEqual(first.full_url, "https://tile.openstreetmap.org/1/0/1.png")
        self.assertEqual(first.get_header("User-agent"), USER_AGENT)
        self.assertEqual(second.get_header("If-none-match"), '"first"')
        self.assertEqual(second.get_header("If-modified-since"), "Tue, 17 Nov 2026 12:00:00 GMT")

    def test_map_draws_track_over_visible_tiles_and_fits_transport(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow unavailable")
        tile = io.BytesIO()
        Image.new("RGB", (256, 256), "silver").save(tile, format="PNG")
        points = [[59.900, 10.7], [59.9025, 10.7], [59.905, 10.7]]
        with patch("garmin_maps._tile", return_value=tile.getvalue()) as request:
            result = render_route_map(points, Path("unused"))
        self.assertGreater(len(result), 0)
        self.assertLessEqual(len(result), MAX_MAP_BYTES)
        self.assertIn(request.call_count, range(1, 10))
        self.assertEqual(len({call.args[1:4] for call in request.call_args_list}), request.call_count)
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual((image.format, image.size), ("JPEG", (IMAGE_SIZE, IMAGE_SIZE)))
            red, green, blue = image.getpixel((IMAGE_SIZE // 2, IMAGE_SIZE // 2))
            self.assertGreater(blue, max(red, green) + 50)

    def test_unavailable_tiles_return_track_only_fallback(self):
        with patch("garmin_maps._tile", side_effect=OSError("network unavailable")):
            self.assertEqual(render_route_map([[59.9, 10.7], [59.905, 10.7]], Path("unused")), b"")
