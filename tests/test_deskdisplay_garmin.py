"""Check Garmin framing and the actual gateway parser against firmware decoding."""

import os
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = [-32768, 250, 310, 420, 500, 620, 710]
BODY = ("DSSTATE/2\ngarmin\t1\t1794900000\ngarmin_group\tToday\n"
        "garmin_metric\tBody Battery\t71\tpercent\t" + ",".join(map(str, HISTORY)) + "\t1\n"
        "garmin_history_end\t20774\n")
ACTIVITY_FIELDS = ("2026-11-17", "Morning run", "running", "5.20", "26", "5:00", "145", "3.2", "105.0")
ACTIVITY_ID = 4_294_967_300
MAP_JPEG = b"\xff\xd8\x00\x01\xff\xd9"
BODY += "garmin_activity\t" + "\t".join(ACTIVITY_FIELDS) + "\n"
BODY += f"garmin_activity_id\t{ACTIVITY_ID}\n"
CHART = [128] + [-32768] * 22 + [152]
BODY += "garmin_chart\t0\t" + ",".join(map(str, CHART)) + "\n"
BODY += "garmin_lap_total\t1\ngarmin_lap\t300\t1000\t145\n"
BODY += "garmin_route\t00b4f03c\ngarmin_chart\t3\t" + ",".join(["84"] * 24) + "\n"
BODY += "garmin_pace_target\t280\t310\n"


def fixture():
    payload = bytearray(1654)
    struct.pack_into("<BIB", payload, 0, 1, 1794900000, 1)
    payload[6:11] = b"Today"
    payload[27] = 1
    payload[28:40] = b"Body Battery"
    payload[49:51] = b"71"
    payload[66:73] = b"percent"
    struct.pack_into("<7h", payload, 79, *HISTORY)
    activity = bytearray(b"\x01")
    for field, width in zip(ACTIVITY_FIELDS, (11, 49, 25, 17, 17, 17, 17, 17, 17)):
        activity.extend(field.encode().ljust(width, b"\x00"))
    activity.extend(bytes(9 * 187))
    scaled = payload + struct.pack("<2I", 20774, 1) + bytes(23 * 4)
    charted = activity + struct.pack("<72h", *CHART, *([-32768] * 48)) + bytes(9 * 144)
    lapped = charted + struct.pack("<HBiih", 1, 1, 300, 1000, 145) + bytes(19 * 10 + 9 * 203)
    media = (lapped + bytes([2, 0, 180, 240, 60]) + bytes(156)
             + struct.pack("<48h", *([84] * 24), *([-32768] * 24)) + bytes(9 * 257))
    target = media + struct.pack("<2H", 280, 310) + bytes(36)
    mapped = target + struct.pack("<Q", ACTIVITY_ID) + bytes(9 * 8)
    return (b"DS\x01\x06" + struct.pack("<HQ", len(payload), 42) + payload
            + b"DS\x01\x07" + struct.pack("<HQ", len(activity), 43) + activity
            + b"DS\x01\x06" + struct.pack("<HQ", len(scaled), 44) + scaled
            + b"DS\x01\x07" + struct.pack("<HQ", len(charted), 45) + charted
            + b"DS\x01\x07" + struct.pack("<HQ", len(lapped), 46) + lapped
            + b"DS\x01\x07" + struct.pack("<HQ", len(media), 47) + media
            + b"DS\x01\x07" + struct.pack("<HQ", len(target), 48) + target
            + b"DS\x01\x07" + struct.pack("<HQ", len(mapped), 49) + mapped)


CPP = r'''
#include "secure_protocol.h"
#include <cassert>
#include <cstdio>
int main() {
    using namespace secure_protocol;
    unsigned char frame[garminFrameSize];
    assert(fread(frame, 1, sizeof(frame), stdin) == sizeof(frame));
    GarminTelemetry state;
    uint64_t sequence = 0;
    assert(decodeGarminTelemetry(frame, sizeof(frame), sequence, state));
    assert(sequence == 42 && state.status == 1 && state.updatedAt == 1794900000);
    assert(state.count == 1 && state.groups[0].count == 1);
    assert(!strcmp(state.groups[0].title, "Today"));
    const GarminMetric& metric = state.groups[0].metrics[0];
    assert(!strcmp(metric.label, "Body Battery") && !strcmp(metric.value, "71"));
    assert(!strcmp(metric.unit, "percent"));
    assert(metric.history[0] == INT16_MIN && metric.history[1] == 250 && metric.history[6] == 710);
    const size_t positions[] = {headerSize, headerSize + 5, headerSize + 27,
        headerSize + 26, headerSize + 48, headerSize + 65, headerSize + 78};
    const unsigned char bad[] = {5, 5, 7, 'x', 'x', 'x', 'x'};
    for (size_t index = 0; index < sizeof(positions) / sizeof(positions[0]); ++index) {
        const unsigned char saved = frame[positions[index]];
        frame[positions[index]] = bad[index];
        sequence = 99;
        assert(!decodeGarminTelemetry(frame, sizeof(frame), sequence, state));
        assert(sequence == 99 && state.groups[0].metrics[0].history[6] == 710);
        frame[positions[index]] = saved;
    }
    assert(!decodeGarminTelemetry(frame, sizeof(frame) - 1, sequence, state));
    frame[4] = 0;
    assert(!decodeGarminTelemetry(frame, sizeof(frame), sequence, state));
    unsigned char activities[activityFrameSize];
    assert(fread(activities, 1, sizeof(activities), stdin) == sizeof(activities));
    ActivityTelemetry history;
    assert(decodeActivityTelemetry(activities, sizeof(activities), sequence, history));
    assert(sequence == 43 && history.count == 1);
    assert(!strcmp(history.items[0].title, "Morning run"));
    assert(!strcmp(history.items[0].values[2], "5:00"));
    activities[15 + 11 + 48] = 'x';
    assert(!decodeActivityTelemetry(activities, sizeof(activities), sequence, history));
    unsigned char scaled[garminScaleFrameSize];
    assert(fread(scaled, 1, sizeof(scaled), stdin) == sizeof(scaled));
    assert(decodeGarminTelemetry(scaled, sizeof(scaled), sequence, state));
    assert(sequence == 44 && state.historyEnd == 20774 && state.groups[0].metrics[0].scale == 1);
    unsigned char charted[activityChartFrameSize];
    assert(fread(charted, 1, sizeof(charted), stdin) == sizeof(charted));
    assert(decodeActivityTelemetry(charted, sizeof(charted), sequence, history));
    assert(sequence == 45 && history.items[0].chartsAvailable);
    assert(history.items[0].charts[0][0] == 128 && history.items[0].charts[0][23] == 152);
    assert(history.items[0].charts[1][0] == INT16_MIN);
    unsigned char lapped[activityLapFrameSize];
    assert(fread(lapped, 1, sizeof(lapped), stdin) == sizeof(lapped));
    assert(decodeActivityTelemetry(lapped, sizeof(lapped), sequence, history));
    assert(sequence == 46 && history.items[0].lapCount == 1 && history.items[0].lapTotal == 1);
    assert(history.items[0].laps[0].seconds == 300 && history.items[0].laps[0].metres == 1000);
    assert(history.items[0].laps[0].heartRate == 145);
    lapped[activityChartFrameSize + 2] = 21;
    assert(!decodeActivityTelemetry(lapped, sizeof(lapped), sequence, history));
    unsigned char media[activityMediaFrameSize];
    assert(fread(media, 1, sizeof(media), stdin) == sizeof(media));
    assert(decodeActivityTelemetry(media, sizeof(media), sequence, history));
    assert(sequence == 47 && history.items[0].routeCount == 2);
    assert(history.items[0].route[2] == 240 && history.items[0].extraCharts[0][23] == 84);
    unsigned char target[activityTargetFrameSize];
    assert(fread(target, 1, sizeof(target), stdin) == sizeof(target));
    assert(decodeActivityTelemetry(target, sizeof(target), sequence, history));
    assert(sequence == 48 && history.items[0].paceTargetFast == 280 && history.items[0].paceTargetSlow == 310);
    assert(history.items[0].id == 0);
    unsigned char mapped[activityIdFrameSize];
    assert(fread(mapped, 1, sizeof(mapped), stdin) == sizeof(mapped));
    assert(decodeActivityTelemetry(mapped, sizeof(mapped), sequence, history));
    assert(sequence == 49 && history.items[0].id == UINT64_C(4294967300));
    return 0;
}
'''
C = r'''
#define main gateway_main
#include "deskdisplay/tools/secure_peer.c"
#undef main
#include <assert.h>
int main(int argc, char** argv) {
    assert(argc == 3);
    strcpy(state_host, "127.0.0.1");
    strcpy(state_path, "/api/deskdisplay/state");
    state_port = (uint16_t)atoi(argv[1]);
    struct controller_state state;
    if (!strcmp(argv[2], "bad")) { assert(!fetch_controller_state(&state)); return 0; }
    assert(fetch_controller_state(&state));
    assert(state.garmin.count == 1 && state.garmin.groups[0].count == 1);
    unsigned char frame[STATE_FRAME_MAX];
    const size_t length = make_garmin_frame(frame, 42, 0, &state.garmin, 0);
    assert(fwrite(frame, 1, length, stdout) == length);
    latest_state = state;
    const size_t activity_length = make_activity_frame(frame, 43, 0, 0, 0, 0, 0);
    assert(fwrite(frame, 1, activity_length, stdout) == activity_length);
    const size_t scaled_length = make_garmin_frame(frame, 44, 0, &state.garmin, 1);
    assert(fwrite(frame, 1, scaled_length, stdout) == scaled_length);
    const size_t charted_length = make_activity_frame(frame, 45, 1, 0, 0, 0, 0);
    assert(fwrite(frame, 1, charted_length, stdout) == charted_length);
    const size_t lapped_length = make_activity_frame(frame, 46, 1, 1, 0, 0, 0);
    assert(fwrite(frame, 1, lapped_length, stdout) == lapped_length);
    const size_t media_length = make_activity_frame(frame, 47, 1, 1, 1, 0, 0);
    assert(fwrite(frame, 1, media_length, stdout) == media_length);
    const size_t target_length = make_activity_frame(frame, 48, 1, 1, 1, 1, 0);
    assert(fwrite(frame, 1, target_length, stdout) == target_length);
    const size_t mapped_length = make_activity_frame(frame, 49, 1, 1, 1, 1, 1);
    assert(fwrite(frame, 1, mapped_length, stdout) == mapped_length);
    struct garmin_map_transfer map_transfer = {0};
    atomic_init(&map_transfer.ready, 0);
    uint64_t sequence = 50;
    assert(start_garmin_map(NULL, &sequence, &map_transfer, state.activity_ids[0]));
    assert(map_transfer.pending && sequence == 50);
    assert(!pthread_join(map_transfer.thread, NULL));
    assert(atomic_load(&map_transfer.ready) && map_transfer.jpeg_length == 6);
    assert(!memcmp(map_transfer.jpeg, "\xff\xd8\x00\x01\xff\xd9", 6));
    assert(!fetch_garmin_map(state.activity_ids[0] + 1, map_transfer.jpeg));
    return 0;
}
'''


class GarminWireTests(unittest.TestCase):
    def test_firmware_decoder(self):
        cxx = shutil.which("c++")
        zig = ROOT / ".venv/Lib/site-packages/ziglang/zig.exe"
        if cxx:
            compiler = [cxx]
        elif os.name == "nt" and zig.exists():
            compiler = [str(zig), "c++", "-target", "x86_64-windows-gnu"]
        else:
            self.skipTest("C++ compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="garmin-decoder-") as directory:
            source = Path(directory) / "decoder.cpp"
            source.write_text(CPP)
            executable = Path(directory) / ("decoder.exe" if os.name == "nt" else "decoder")
            # Match the existing protocol regression: GCC warns about legacy
            # memset initialization elsewhere in this shared header.
            built = subprocess.run(compiler + ["-std=c++11", "-Wall", "-Wextra", "-I",
                str(ROOT / "deskdisplay/src"), str(source), "-o", str(executable)], capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stderr)
            decoded = subprocess.run([str(executable)], input=fixture(), capture_output=True, timeout=10)
            self.assertEqual(decoded.returncode, 0, decoded.stderr)

    @unittest.skipUnless(os.name == "posix", "Linux gateway requires POSIX/OpenSSL")
    def test_gateway_parser_and_encoder(self):
        cc = shutil.which("cc")
        if not cc:
            self.skipTest("C compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="garmin-gateway-") as directory:
            source = Path(directory) / "gateway.c"
            executable = Path(directory) / "gateway"
            source.write_text(C)
            built = subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-I", str(ROOT), str(source),
                                    "-pthread", "-lssl", "-lcrypto", "-o", str(executable)], capture_output=True, text=True)
            if "openssl/" in built.stderr and "No such file" in built.stderr:
                self.skipTest("OpenSSL development headers unavailable")
            self.assertEqual(built.returncode, 0, built.stderr)
            bodies = [BODY, BODY.replace("71\tpercent", "x" * 17 + "\tpercent"),
                      BODY.replace(",710", ",32768"), BODY.replace(",710", ""),
                      BODY.replace("garmin_group\tToday\n", ""),
                      BODY + "garmin_group\tMore\n" * 4,
                      BODY + ("garmin_metric" + BODY.split("garmin_metric", 1)[1].splitlines()[0] + "\n") * 6,
                      BODY.replace("Morning run", "x" * 49),
                      BODY.replace(str(ACTIVITY_ID), str(1 << 63)),
                      BODY.replace(str(ACTIVITY_ID), "-1"),
                      BODY.replace(f"garmin_activity_id\t{ACTIVITY_ID}\n",
                                   f"garmin_activity_id\t{ACTIVITY_ID}\n" * 2),
                      BODY + ("garmin_activity\t" + "\t".join(ACTIVITY_FIELDS) + "\n") * 10]

            class Handler(BaseHTTPRequestHandler):
                body = BODY

                def log_message(self, *args):
                    pass

                def do_GET(self):
                    is_state = self.path == "/api/deskdisplay/state"
                    is_map = self.path == f"/api/deskdisplay/garmin/map/{ACTIVITY_ID}"
                    valid = (is_state or is_map) and self.headers.get("X-DeskDisplay-Maps") == "1"
                    self.send_response(200 if valid else 404)
                    self.end_headers()
                    if valid:
                        self.wfile.write(MAP_JPEG if is_map else self.body.encode())

            with HTTPServer(("127.0.0.1", 0), Handler) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    for index, body in enumerate(bodies):
                        Handler.body = body
                        encoded = subprocess.run([str(executable), str(server.server_port), "good" if index == 0 else "bad"],
                                                 capture_output=True, timeout=10)
                        self.assertEqual(encoded.returncode, 0, encoded.stderr)
                        if index == 0:
                            self.assertEqual(encoded.stdout, fixture())
                finally:
                    server.shutdown()
                    worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
