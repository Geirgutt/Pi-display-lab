"""Compact elapsed-time graphs from Garmin FIT activity records."""
from __future__ import annotations

import io
import math
import xml.etree.ElementTree as ET
import zipfile

SAMPLES = 24
MISSING = -32768
MAX_FIT_BYTES = 8 * 1024 * 1024
LAP_LIMIT = 20
ROUTE_LIMIT = 80
ROUTE_FORMAT = 3


def activity_download_id(value) -> int | None:
    if isinstance(value, str) and 1 <= len(value) <= 19 and value.isascii() and value.isdecimal():
        value = int(value)
    return value if type(value) is int and 0 < value < 2**63 else None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def summarize_records(records: list[dict]) -> list[list[int]]:
    records = [row for row in records if _finite(row.get("timestamp"))]
    if len(records) < 2:
        return []
    start = min(row["timestamp"] for row in records)
    span = max(row["timestamp"] for row in records) - start
    if span <= 0:
        return []
    totals = [[0.0] * SAMPLES for _ in range(5)]
    counts = [[0] * SAMPLES for _ in totals]
    for row in records:
        slot = min(SAMPLES - 1, int((row["timestamp"] - start) / span * SAMPLES))
        values = (row.get("heart_rate"), row.get("enhanced_speed", row.get("speed")),
                  row.get("enhanced_altitude", row.get("altitude")),
                  row.get("cadence"), row.get("power"))
        for index, value in enumerate(values):
            if not _finite(value) or not (-1000 <= value <= 10000):
                continue
            if (index == 0 and value <= 0) or (index == 1 and value < 0.2) or (index >= 3 and value < 0):
                continue
            totals[index][slot] += value
            counts[index][slot] += 1
    result = []
    for index, (totals_row, counts_row) in enumerate(zip(totals, counts)):
        series = []
        for total, count in zip(totals_row, counts_row):
            if not count:
                series.append(MISSING)
            else:
                mean = total / count
                series.append(round(1000 / mean if index == 1 else mean))
        result.append(series)
    return result if any(sample != MISSING for series in result for sample in series) else []


def summarize_route(records: list[dict]) -> list[list[int]]:
    # FIT coordinates are semicircles. Project locally, retaining aspect ratio
    # but send only relative screen points, without geographic coordinates.
    points = []
    for row in records:
        lat, lon = row.get("position_lat"), row.get("position_long")
        if (type(lat) is int and type(lon) is int and abs(lat) <= 2**30
            and -2**31 <= lon < 2**31 and lon != 2**31 - 1):
            points.append((lat, lon))
    if len(points) < 2:
        return []
    lat0, lon0 = points[0]
    stretch = math.cos(lat0 * math.pi / 2**31)
    projected = [(((lon - lon0 + 2**31) % 2**32 - 2**31) * stretch, lat0 - lat)
                 for lat, lon in points]
    xs, ys = zip(*projected)
    low_x, high_x, low_y, high_y = min(xs), max(xs), min(ys), max(ys)
    extent = max(high_x - low_x, high_y - low_y)
    if extent <= 0:
        return []
    count = min(len(projected), ROUTE_LIMIT)
    def fit(x, low, high):
        return max(0, min(240, round(120 + 240 * (x - (high + low) / 2) / extent)))

    return [[fit(x, low_x, high_x), fit(y, low_y, high_y)]
            for x, y in (projected[i * (len(projected) - 1) // (count - 1)] for i in range(count))]


def summarize_laps(records: list[dict]) -> tuple[int, list[list[int]]]:
    def bounded(value, maximum):
        return round(value) if _finite(value) and 0 < value <= maximum else 0

    laps = []
    for row in records:
        duration = row.get("total_timer_time", row.get("total_elapsed_time"))
        laps.append([
            bounded(duration, 0xFFFFFFFF),
            bounded(row.get("total_distance"), 0xFFFFFFFF),
            bounded(row.get("avg_heart_rate"), 255),
        ])
    return min(len(laps), 65535), laps[:LAP_LIMIT]


def summarize_pace_target(steps: list[dict]) -> list[int]:
    ranges = set()
    for step in steps:
        if step.get("target_type") != "speed":
            continue
        low = step.get("custom_target_speed_low")
        high = step.get("custom_target_speed_high")
        if not (_finite(low) and _finite(high) and 0.2 <= low <= high <= 120):
            return []
        ranges.add((round(1000 / high), round(1000 / low)))
    return list(next(iter(ranges))) if len(ranges) == 1 else []


def _decode_fit(data: bytes) -> dict:
    from garmin_fit_sdk import Decoder, Stream

    messages, errors = Decoder(Stream.from_byte_array(bytearray(data))).read(
        convert_datetimes_to_dates=False)
    if errors:
        return {}
    total, laps = summarize_laps(messages.get("lap_mesgs", []))
    records = messages.get("record_mesgs", [])
    return {"series": summarize_records(records), "route": summarize_route(records),
            "lap_total": total, "laps": laps,
            "pace_target": summarize_pace_target(messages.get("workout_step_mesgs", []))}


def _decode_xml_route(data: bytes) -> dict:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    kind = root.tag.rsplit("}", 1)[-1]
    if kind not in {"gpx", "TrainingCenterDatabase"}:
        return {}
    positions = []
    for point in root.iter():
        tag = point.tag.rsplit("}", 1)[-1]
        if kind == "gpx" and tag == "trkpt":
            lat, lon = point.get("lat"), point.get("lon")
        elif kind == "TrainingCenterDatabase" and tag == "Position":
            lat = point.findtext("{*}LatitudeDegrees")
            lon = point.findtext("{*}LongitudeDegrees")
        else:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            semicircle_lon = (round(lon * 2**31 / 180) + 2**31) % 2**32 - 2**31
            positions.append({"position_lat": round(lat * 2**31 / 180),
                              "position_long": semicircle_lon})
    return {"route": summarize_route(positions)}


def decode_activity_file(data: bytes) -> dict:
    if len(data) > MAX_FIT_BYTES:
        return {}
    if data[:4] != b"PK\x03\x04":
        return _decode_fit(data) if data[8:12] == b".FIT" else _decode_xml_route(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        details: dict = {}
        for extension in (".fit", ".gpx", ".tcx"):
            member = next((item for item in archive.infolist()
                           if not item.is_dir() and item.filename.lower().endswith(extension)
                           and item.file_size <= MAX_FIT_BYTES), None)
            if member is None:
                continue
            with archive.open(member) as handle:
                contents = handle.read(MAX_FIT_BYTES + 1)
            if len(contents) > MAX_FIT_BYTES:
                continue
            result = _decode_fit(contents) if extension == ".fit" else _decode_xml_route(contents)
            if result:
                details.update(result)
                if details.get("route"):
                    break
        return details
