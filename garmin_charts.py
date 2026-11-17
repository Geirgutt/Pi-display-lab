"""Compact elapsed-time graphs from Garmin FIT activity records."""
from __future__ import annotations

import io
import math
import zipfile

SAMPLES = 24
MISSING = -32768
MAX_FIT_BYTES = 8 * 1024 * 1024
LAP_LIMIT = 20
ROUTE_LIMIT = 80


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


def decode_activity_file(data: bytes) -> dict:
    from garmin_fit_sdk import Decoder, Stream

    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            member = next((item for item in archive.infolist()
                           if not item.is_dir() and item.filename.lower().endswith(".fit")
                           and item.file_size <= MAX_FIT_BYTES), None)
            if member is None:
                return {}
            with archive.open(member) as handle:
                data = handle.read(MAX_FIT_BYTES + 1)
    if len(data) > MAX_FIT_BYTES:
        return {}
    messages, errors = Decoder(Stream.from_byte_array(bytearray(data))).read(
        convert_datetimes_to_dates=False)
    if errors:
        return {}
    total, laps = summarize_laps(messages.get("lap_mesgs", []))
    records = messages.get("record_mesgs", [])
    return {"series": summarize_records(records), "route": summarize_route(records),
            "lap_total": total, "laps": laps}
