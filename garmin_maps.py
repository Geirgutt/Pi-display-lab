"""Render the visible Garmin route viewport over OpenStreetMap raster tiles."""

from __future__ import annotations

import io
import json
import math
import tempfile
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

IMAGE_SIZE = 296
MAX_MAP_BYTES = 24 * 1024
TILE_SIZE = 256
MAX_TILE_BYTES = 512 * 1024
MAX_CACHE_TILES = 256
DEFAULT_TILE_TTL = 7 * 86400
USER_AGENT = "Pi-display-lab (+https://github.com/Geirgutt/Pi-display-lab)"
ATTRIBUTION = "© OpenStreetMap contributors"


def _viewport(points):
    projected = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            continue
        lat, lon = point
        if (type(lat) not in (int, float) or type(lon) not in (int, float)
                or not (-90 <= lat <= 90 and -180 <= lon <= 180)):
            continue
        x = (lon + 180) / 360
        if projected:
            # Use the closest world copy to the preceding point.
            x += round(projected[-1][0] - x)
        lat = max(-85.05112878, min(85.05112878, lat))
        y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2
        projected.append((x, y))
    if len(projected) < 2:
        return None
    xs, ys = zip(*projected)
    west, east, north, south = min(xs), max(xs), min(ys), max(ys)
    span = max(east - west, south - north)
    if span > 1:
        return None
    available = IMAGE_SIZE - 48
    zoom = min(18, max(0, math.floor(math.log2(available / (TILE_SIZE * max(span, 1e-12))))))
    world = TILE_SIZE * (1 << zoom)
    left = round((west + east) * world / 2 - IMAGE_SIZE / 2)
    top = round((north + south) * world / 2 - IMAGE_SIZE / 2)
    return zoom, left, top, [(round(x * world - left), round(y * world - top)) for x, y in projected]


def _cache_metadata(headers, now, previous):
    directives = {key.strip().lower(): value.strip().strip('"') for key, _, value in
                  (entry.partition("=") for entry in headers.get("Cache-Control", "").split(","))}
    try:
        age = max(0, int(headers.get("Age", "0")))
    except ValueError:
        age = 0
    try:
        ttl = max(0, int(directives["max-age"]))
    except (ValueError, KeyError):
        ttl = previous.get("ttl", DEFAULT_TILE_TTL)
        if headers.get("Expires"):
            try:
                ttl = max(0, parsedate_to_datetime(headers["Expires"]).timestamp() - now)
            except (TypeError, ValueError, OverflowError):
                pass
    revalidate = ("no-cache" in directives if headers.get("Cache-Control")
                  else previous.get("revalidate", False))
    return {
        "expires": now if revalidate else now + max(0, ttl - age),
        "ttl": ttl,
        "revalidate": revalidate,
        "etag": headers.get("ETag", previous.get("etag")),
        "modified": headers.get("Last-Modified", previous.get("modified")),
    }, "no-store" not in directives


def _read_tile(path):
    try:
        with path.open("rb") as handle:
            metadata = json.loads(handle.readline(8192))
            data = handle.read(MAX_TILE_BYTES + 1)
        if (isinstance(metadata, dict) and type(metadata.get("expires")) in (int, float)
                and 0 < len(data) <= MAX_TILE_BYTES):
            return metadata, data
    except (OSError, ValueError):
        pass
    return {}, b""


def _write_tile(path, metadata, data):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(metadata).encode("ascii") + b"\n" + data)
        temporary.replace(path)
        tiles = list(path.parent.glob("*.tile"))
        if len(tiles) > MAX_CACHE_TILES:
            for old in sorted(tiles, key=lambda item: item.stat().st_mtime)[:-MAX_CACHE_TILES]:
                old.unlink(missing_ok=True)
    except OSError:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _tile(cache_dir, zoom, x, y, timeout):
    path = cache_dir / f"{zoom}-{x}-{y}.tile"
    metadata, data = _read_tile(path)
    now = time.time()
    if data and metadata["expires"] > now:
        return data
    headers = {"User-Agent": USER_AGENT}
    if metadata.get("etag"):
        headers["If-None-Match"] = metadata["etag"]
    if metadata.get("modified"):
        headers["If-Modified-Since"] = metadata["modified"]
    request = Request(f"https://tile.openstreetmap.org/{zoom}/{x}/{y}.png", headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_TILE_BYTES + 1)
            metadata, store = _cache_metadata(response.headers, now, {})
    except HTTPError as error:
        with error:
            if error.code != 304 or not data:
                raise
            metadata, store = _cache_metadata(error.headers, now, metadata)
    if not 0 < len(data) <= MAX_TILE_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid OpenStreetMap tile")
    if store:
        _write_tile(path, metadata, data)
    else:
        path.unlink(missing_ok=True)
    return data


def render_route_map(points, cache_dir: Path) -> bytes:
    """Render a bounded JPEG for the active Map view, or use the track-only fallback."""
    if not isinstance(points, (list, tuple)) or len(points) > 400:
        return b""
    viewport = _viewport(points)
    if viewport is None:
        return b""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return b""
    zoom, left, top, line = viewport
    tiles_per_axis = 1 << zoom
    image = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), "#eeeae2")
    deadline = time.monotonic() + 4
    requested = {}
    try:
        for tile_y in range(max(0, top // TILE_SIZE),
                            min(tiles_per_axis, (top + IMAGE_SIZE - 1) // TILE_SIZE + 1)):
            for tile_x in range(left // TILE_SIZE, (left + IMAGE_SIZE - 1) // TILE_SIZE + 1):
                key = tile_x % tiles_per_axis, tile_y
                if key not in requested:
                    timeout = min(1.5, deadline - time.monotonic())
                    if timeout <= 0:
                        return b""
                    data = _tile(cache_dir, zoom, *key, timeout)
                    with Image.open(io.BytesIO(data), formats=["PNG"]) as tile:
                        if tile.size != (TILE_SIZE, TILE_SIZE):
                            return b""
                        requested[key] = tile.convert("RGB")
                image.paste(requested[key], (tile_x * TILE_SIZE - left, tile_y * TILE_SIZE - top))
    except (OSError, ValueError, Image.DecompressionBombError):
        return b""

    draw = ImageDraw.Draw(image)
    draw.line(line, fill="white", width=7, joint="curve")
    draw.line(line, fill="#1749c6", width=4, joint="curve")
    for (x, y), color in ((line[0], "#15803d"), (line[-1], "#b91c1c")):
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color, outline="white")
    # Leave the provider credit visible in the image itself on the physical display.
    width = math.ceil(draw.textlength(ATTRIBUTION))
    draw.rectangle((IMAGE_SIZE - width - 8, IMAGE_SIZE - 16, IMAGE_SIZE, IMAGE_SIZE), fill="white")
    draw.text((IMAGE_SIZE - width - 4, IMAGE_SIZE - 15), ATTRIBUTION, fill="black")
    for quality in (82, 66, 48, 32):
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True)
        if output.tell() <= MAX_MAP_BYTES:
            return output.getvalue()
    return b""
