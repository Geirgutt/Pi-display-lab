#!/usr/bin/env python3
"""Authorize Spotify on the Pi using a pasted return URL or an SSH tunnel."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import re
import secrets
import sys
import time
import warnings
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
    try:
        parsed = urlsplit(path)
        if parsed.path != "/callback":
            return None
        query = parse_qs(parsed.query, max_num_fields=16)
    except ValueError:
        return None
    states = query.get("state", [])
    if len(states) != 1 or not secrets.compare_digest(states[0].encode("utf-8"), expected_state.encode("ascii")):
        return None
    if "error" in query:
        raise SpotifyError("access_denied")
    codes = query.get("code", [])
    return codes[0] if len(codes) == 1 and codes[0] else None


def pasted_callback_code(url: str, expected_state: str) -> str | None:
    if len(url) > 8192:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    expected = urlsplit(REDIRECT_URI)
    if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path):
        return None
    return callback_code(url, expected_state)


def saved_client_id(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    client_id = data.get("client_id") if isinstance(data, dict) else None
    return client_id if isinstance(client_id, str) and re.fullmatch(r"[a-fA-F0-9]{32}", client_id) else ""


def open_login(url: str) -> None:
    print("\nÅpne denne lenken i nettleseren på PC-en:\n" + url + "\n", flush=True)


def read_pasted_callback(url: str, state: str) -> str | None:
    open_login(url)
    print("Godkjenn i Spotify. Nettleseren kan si at 127.0.0.1 ikke kan åpnes.")
    print("Kopier da hele adressen fra adressefeltet og lim den inn her.")
    while True:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            callback = getpass.getpass("Returadresse (skjult, tom avbryter): ").strip()
        if not callback:
            return None
        code = pasted_callback_code(callback, state)
        if code:
            return code
        print("Returadressen samsvarte ikke med denne innloggingen. Bruk hele adressen som nettleseren viser etter godkjenningen.")


def wait_for_callback(url: str, state: str) -> str | None:
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

    with HTTPServer(("127.0.0.1", 8888), Handler) as server:
        server.timeout = 1
        open_login(url)
        print("Venter i opptil fem minutter. Ctrl+C avbryter.")
        deadline = time.monotonic() + 300
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if result.get("denied"):
        raise SpotifyError("access_denied")
    return result.get("code")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, default=credentials_path())
    parser.add_argument("--tunnel", action="store_true", help="Ta imot nettleserens retur på port 8888.")
    args = parser.parse_args()
    print("Kjør dette på Pi-en som samme bruker som pi-display-lab-tjenesten.")
    print(f"Spotify-appens Redirect URI må være: {REDIRECT_URI}")
    saved = saved_client_id(args.credentials)
    prompt = "Client ID [Enter beholder lagret ID]: " if saved else "Client ID (Client Secret trengs ikke): "
    try:
        client_id = input(prompt).strip() or saved
        if not re.fullmatch(r"[a-fA-F0-9]{32}", client_id):
            print("Client ID må være 32 heksadesimale tegn.")
            return 1
        url, state, verifier = authorization_request(client_id)
        if args.tunnel:
            code = wait_for_callback(url, state)
            if not code:
                print("Ingen retur kom gjennom tunnelen. Prøv oppsettet igjen uten --tunnel.")
                return 1
        else:
            code = read_pasted_callback(url, state)
            if not code:
                print("Avbrutt. Kjør oppsettet igjen for å få en ny innloggingslenke.")
                return 1
        response = spotify_request(TOKEN_URL, method="POST", form={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT_URI, "client_id": client_id, "code_verifier": verifier})
        write_credentials(args.credentials, token_credentials(client_id, response or {}))
    except SpotifyError as error:
        print(f"Spotify avviste tilkoblingen ({error.status}). Ingen tokenverdier er skrevet ut.")
        return 1
    except getpass.GetPassWarning:
        print("Returadressen krever en interaktiv terminal med skjult inntasting.")
        return 1
    except (OSError, ValueError):
        print("Kunne ikke åpne returporten eller lagre tilgangsfilen."
              if args.tunnel else "Kunne ikke lese returadressen eller lagre tilgangsfilen.")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nAvbrutt.")
        return 1
    print(f"Spotify koblet til. Tilgangen er lagret privat i {args.credentials}.")
    print("Etter 180 dager må dette oppsettet kjøres igjen. Start musikk i Spotify for å teste.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
