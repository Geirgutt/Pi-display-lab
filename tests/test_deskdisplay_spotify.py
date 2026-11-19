"""Exercise the actual Linux gateway encoder against the firmware decoder."""

import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C = r'''
#define main gateway_main
#include "deskdisplay/tools/secure_peer.c"
#undef main
#include <assert.h>
int main(int argc, char** argv) {
    assert(argc == 2);
    strcpy(state_host, "127.0.0.1");
    strcpy(state_path, "/api/deskdisplay/state");
    state_port = (uint16_t)atoi(argv[1]);
    struct controller_state state;
    assert(fetch_controller_state(&state));
    assert(state.spotify.status == 1 && state.spotify.capabilities == 5);
    assert(!strcmp(state.spotify.title, "Test song"));
    unsigned char frame[STATE_FRAME_MAX];
    const size_t length = make_spotify_frame(frame, 42, 0, &state.spotify, 0, 0);
    assert(fwrite(frame, 1, length, stdout) == length);
    const size_t media_length = make_spotify_frame(frame, 43, 0, &state.spotify, 1, 0);
    assert(fwrite(frame, 1, media_length, stdout) == media_length);
    latest_state = state;
    const size_t cover_length = make_cover_frame(frame, 44);
    assert(fwrite(frame, 1, cover_length, stdout) == cover_length);
    const size_t library_length = make_spotify_frame(frame, 45, 0, &state.spotify, 1, 1);
    assert(fwrite(frame, 1, library_length, stdout) == library_length);
    return 0;
}
'''
CPP = r'''
#include "secure_protocol.h"
#include <cassert>
#include <cstdio>
int main() {
    using namespace secure_protocol;
    unsigned char frame[spotifyFrameSize];
    assert(fread(frame, 1, sizeof(frame), stdin) == sizeof(frame));
    SpotifyTelemetry state;
    uint64_t sequence = 0;
    assert(decodeSpotifyTelemetry(frame, sizeof(frame), sequence, state));
    assert(sequence == 42 && state.status == 1 && state.capabilities == 5);
    assert(state.progressMs == 2500 && state.durationMs == 180000);
    assert(!strcmp(state.title, "Test song") && !strcmp(state.artist, "Artist"));
    assert(!strcmp(state.device, "PC"));
    frame[headerSize + 1] = 13; // Capabilities plus pending state.
    assert(decodeSpotifyTelemetry(frame, sizeof(frame), sequence, state));
    frame[headerSize + 1] = 16;
    assert(!decodeSpotifyTelemetry(frame, sizeof(frame), sequence, state));
    frame[headerSize + 1] = 5;
    assert(!decodeSpotifyTelemetry(frame, sizeof(frame) - 1, sequence, state));
    frame[headerSize + spotifyPayloadSize - 1] = 'x';
    assert(!decodeSpotifyTelemetry(frame, sizeof(frame), sequence, state));
    frame[headerSize + spotifyPayloadSize - 1] = 0;
    frame[headerSize] = 8;
    assert(!decodeSpotifyTelemetry(frame, sizeof(frame), sequence, state));
    unsigned char media[spotifyMediaFrameSize];
    assert(fread(media, 1, sizeof(media), stdin) == sizeof(media));
    assert(decodeSpotifyTelemetry(media, sizeof(media), sequence, state));
    assert(sequence == 43 && !strcmp(state.trackId, "abcdefghijklmnopqrstuv"));
    unsigned char cover[headerSize + spotifyTrackIdSize + 4];
    assert(fread(cover, 1, sizeof(cover), stdin) == sizeof(cover));
    assert(cover[3] == spotifyCoverType && get64(cover + 6) == 44);
    assert(!memcmp(cover + headerSize, state.trackId, spotifyTrackIdSize));
    assert(cover[sizeof(cover) - 1] == 0xd9);
    unsigned char library[spotifyLibraryFrameSize];
    assert(fread(library, 1, sizeof(library), stdin) == sizeof(library));
    assert(decodeSpotifyTelemetry(library, sizeof(library), sequence, state));
    assert(sequence == 45 && state.library == 3);
    return 0;
}
'''


class SpotifyWireTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Linux gateway requires POSIX/OpenSSL")
    def test_controller_http_through_gateway_to_firmware(self):
        cc, cxx = shutil.which("cc"), shutil.which("c++")
        if not cc or not cxx:
            self.skipTest("C/C++ compiler unavailable")
        with tempfile.TemporaryDirectory(prefix="spotify-wire-") as directory:
            temp = Path(directory)
            source, decoder = temp / "gateway.c", temp / "decoder.cpp"
            source.write_text(C)
            decoder.write_text(CPP)
            built = subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-I", str(ROOT),
                                    str(source), "-pthread", "-lssl", "-lcrypto", "-o", str(temp / "gateway")],
                                   capture_output=True, text=True)
            if "openssl/" in built.stderr and "No such file" in built.stderr:
                self.skipTest("OpenSSL development headers unavailable")
            self.assertEqual(built.returncode, 0, built.stderr)
            built = subprocess.run([cxx, "-std=c++11", "-Wall", "-Wextra", "-I", str(ROOT / "deskdisplay/src"),
                                    str(decoder), "-o", str(temp / "decoder")], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass

                def do_GET(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"DSSTATE/2\nspotify\t1\t5\t2500\t180000\tTest song\tArtist\tPC\n"
                                     b"spotify_track\tabcdefghijklmnopqrstuv\nspotify_library\t3\nspotify_cover\t/9j/2Q==\n")

            with HTTPServer(("127.0.0.1", 0), Handler) as server:
                worker = threading.Thread(target=server.handle_request, daemon=True)
                worker.start()
                encoded = subprocess.run([str(temp / "gateway"), str(server.server_port)], capture_output=True, timeout=10)
                worker.join(timeout=3)
            self.assertEqual(encoded.returncode, 0, encoded.stderr)
            decoded = subprocess.run([str(temp / "decoder")], input=encoded.stdout, capture_output=True, timeout=10)
            self.assertEqual(decoded.returncode, 0, decoded.stderr)


if __name__ == "__main__":
    unittest.main()
