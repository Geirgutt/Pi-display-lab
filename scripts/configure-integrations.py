#!/usr/bin/env python3
"""Interactive local-only setup for Garmin and calendar ICS feeds."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_CONFIG = Path("/etc/pi-display-lab/integrations.json")


def yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "[J/n]" if default else "[j/N]"
    while True:
        answer = input(f"{prompt} {suffix} ").strip().casefold()
        if not answer:
            return default
        if answer in {"j", "ja", "y", "yes"}:
            return True
        if answer in {"n", "nei", "no"}:
            return False
        print("Svar j eller n.")


def private_url(prompt: str) -> str:
    while True:
        value = getpass.getpass(prompt).strip()
        parsed = urlsplit(value)
        if parsed.scheme == "webcal":
            value = f"https://{value.removeprefix('webcal://')}"
            parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
            return value
        print("Adressen må være en full HTTPS- eller webcal-adresse uten innloggingsdata i URL-en.")


def write_private_json(path: Path, payload: dict) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Nekter å overskrive symbolsk lenke: {path}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        path.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Kan ikke lese integrasjonskonfigurasjonen: {error}") from error
    return value if isinstance(value, dict) else {}


def configure_garmin(existing: dict, resetting: bool) -> dict:
    old = existing.get("garmin")
    old = old if isinstance(old, dict) else {}
    old_api_key = str(old.get("api_key") or "")

    print("\nGarmin Personal API")
    print("Opprett API-nøkkelen i Garmin Connect: Settings -> Personal API.")
    print("Nøkkelen utløper og må fornyes når Garmin ber om det.")
    api_enabled = yes_no(
        "Vil du bruke Garmin Personal API?",
        default=bool(old.get("api_enabled", bool(old_api_key))),
    )
    api_key = old_api_key
    if api_enabled:
        while True:
            entered_key = getpass.getpass("Garmin Personal API-nøkkel (skjult, tom beholder lagret nøkkel): ").strip()
            if entered_key:
                api_key = entered_key
            if api_key and api_key.isascii() and all(33 <= ord(c) <= 126 for c in api_key):
                break
            print("Legg inn en gyldig nøkkel på én linje for å aktivere API-et.")
    elif old_api_key and resetting:
        if yes_no("Slette den lagrede Garmin API-nøkkelen?", default=False):
            api_key = ""

    print("\nGarmin kommende trening via ICS")
    print("ICS-kalenderen brukes fortsatt til å hente kommende Garmin-økter.")
    print("Garmin Connect Web: Calendar -> menyen med tre prikker -> Publish Calendar.")
    garmin_enabled = yes_no(
        "Vil du vise kommende Garmin-økter fra ICS-kalenderen?",
        default=bool(old.get("enabled", bool(old.get("calendar_url")))),
    )
    garmin_url = str(old.get("calendar_url") or "") if garmin_enabled else ""
    if garmin_enabled and (not garmin_url or not resetting):
        garmin_url = private_url("Lim inn publisert Garmin-kalenderadresse (skjult): ")
    elif garmin_enabled and resetting and yes_no("Endre Garmin ICS-adressen?", default=False):
        garmin_url = private_url("Ny publisert Garmin-kalenderadresse (skjult): ")
    return {
        **old,
        "enabled": garmin_enabled,
        "calendar_url": garmin_url,
        "api_enabled": api_enabled,
        "api_key": api_key,
    }


def configure_calendars(existing: dict, resetting: bool) -> dict:
    old = existing.get("calendar")
    old = old if isinstance(old, dict) else {}
    old_feeds = old.get("feeds")
    old_feeds = old_feeds if isinstance(old_feeds, list) else []
    if resetting and old_feeds and yes_no("Beholde de eksisterende ICS-kalenderne?", default=True):
        feeds = old_feeds
    else:
        print("\nVanlig kalender")
        print("TimeTree kan ikke eksporteres. Her kan private ICS-adresser fra f.eks. Google eller iCloud legges til.")
        calendar_enabled = yes_no("Har du en eller flere ICS-kalendere du vil legge til nå?", default=False)
        feeds: list[dict[str, str]] = []
        while calendar_enabled:
            name = input("Kort navn på kalenderen: ").strip()[:40] or f"Kalender {len(feeds) + 1}"
            feeds.append({"name": name, "url": private_url("Privat ICS-adresse (skjult): ")})
            if not yes_no("Legge til enda en kalender?"):
                break
    return {**old, "enabled": bool(feeds), "feeds": feeds}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--if-unconfigured", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)
    if args.config.exists() and args.if_unconfigured and not args.reset:
        return 0
    if not sys.stdin.isatty():
        print("Integrasjoner er ikke konfigurert. Kjør scripts/configure-integrations.sh fra en terminal.")
        return 0

    existing = load_existing(args.config)
    if args.config.exists() and not args.reset:
        print("Integrasjoner er allerede konfigurert.")
        print("Bruk --reset for å velge på nytt.")
        return 0

    garmin = configure_garmin(existing, args.reset)
    calendar = configure_calendars(existing, args.reset)
    payload = {**existing, "version": 2, "garmin": garmin, "calendar": calendar}
    write_private_json(
        args.config,
        payload,
    )
    print(f"Valgene er lagret lokalt i {args.config} med modus 0600.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
