#!/usr/bin/env python3
"""Run on the Pi as the controller service user; browser returns via SSH tunnel."""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spotify import (REDIRECT_URI, SCOPES, TOKEN_URL, SpotifyError, credentials_path,
                     spotify_request, token_credentials, write_credentials)


def authorization_request(client_id: str) -> tuple[str, str, str]:
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    url = "https://accounts.spotify.com/authorize?" + urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT_URI,
        "scope": SCOPES, "state": state, "code_challenge_method": "S256", "code_challenge": challenge})
    return url, state, verifier


def callback_code(path: str, expected_state: str) -> str | None:
    parsed = urlsplit(path)
    if parsed.path != "/callback":
        return None
    query = parse_qs(parsed.query)
    states = query.get("state", [])
    if len(states) != 1 or not secrets.compare_digest(states[0].encode("utf-8"), expected_state.encode("ascii")):
        return None
    if "error" in query:
        raise SpotifyError("access_denied")
    codes = query.get("code", [])
    return codes[0] if len(codes) == 1 and codes[0] else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, default=credentials_path())
    args = parser.parse_args()
    print("Kjør dette på Pi-en som samme bruker som pi-display-lab-tjenesten.")
    print("SSH fra PC-en må ha: -L 8888:127.0.0.1:8888")
    print(f"Spotify-appens Redirect URI må være: {REDIRECT_URI}")
    client_id = input("Client ID (Client Secret trengs ikke): ").strip()
    if not re.fullmatch(r"[a-fA-F0-9]{32}", client_id):
        print("Client ID må være 32 heksadesimale tegn.")
        return 1
    url, state, verifier = authorization_request(client_id)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        timeout = 5

        def log_message(self, *args):
            pass  # Never log callback URLs/codes.

        def do_GET(self):
            try:
                code = callback_code(self.path, state)
            except SpotifyError:
                result["denied"] = True
                code = None
            if code:
                result["code"] = code
            self.send_response(200 if code else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(("Innlogging mottatt. Se terminalen på Pi-en for resultatet."
                             if code else "Innlogging avvist eller ugyldig returadresse.").encode("utf-8"))

    try:
        with HTTPServer(("127.0.0.1", 8888), Handler) as server:
            server.timeout = 1
            print("\nÅpne denne lenken i nettleseren på PC-en:\n" + url + "\n")
            print("Venter i opptil fem minutter. Ctrl+C avbryter.")
            deadline = time.monotonic() + 300
            while not result and time.monotonic() < deadline:
                server.handle_request()
        if not result.get("code"):
            print("Ingen godkjent innlogging mottatt. Kontroller SSH-tunnelen og prøv igjen.")
            return 1
        response = spotify_request(TOKEN_URL, method="POST", form={
            "grant_type": "authorization_code", "code": result["code"],
            "redirect_uri": REDIRECT_URI, "client_id": client_id, "code_verifier": verifier})
        write_credentials(args.credentials, token_credentials(client_id, response or {}))
    except SpotifyError as error:
        print(f"Spotify avviste tilkoblingen ({error.status}). Ingen tokenverdier er skrevet ut.")
        return 1
    except (OSError, ValueError):
        print("Kunne ikke åpne returporten eller lagre tilgangsfilen. Kontroller port 8888 og filrettigheter.")
        return 1
    except KeyboardInterrupt:
        print("\nAvbrutt.")
        return 1
    print(f"Spotify koblet til. Tilgangen er lagret privat i {args.credentials}.")
    print("Etter 180 dager må dette oppsettet kjøres igjen. Start musikk i Spotify for å teste.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
