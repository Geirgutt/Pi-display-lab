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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--if-unconfigured", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.config.exists() and args.if_unconfigured and not args.reset:
        return 0
    if not sys.stdin.isatty():
        print("Integrasjoner er ikke konfigurert. Kjør scripts/configure-integrations.sh fra en terminal.")
        return 0

    if args.config.exists() and not args.reset:
        print("Integrasjoner er allerede konfigurert.")
        print("Bruk --reset for å velge på nytt.")
        return 0

    print("\nGarmin kommende trening")
    print("Garmin Connect Web: Calendar -> menyen med tre prikker -> Publish Calendar.")
    print("Den unike adressen behandles som en hemmelighet og lagres bare lokalt.")
    garmin_enabled = yes_no("Vil du vise kommende Garmin-økter?", default=True)
    garmin_url = private_url("Lim inn publisert Garmin-kalenderadresse (skjult): ") if garmin_enabled else ""

    print("\nVanlig kalender")
    print("TimeTree kan ikke eksporteres. Her kan private ICS-adresser fra f.eks. Google eller iCloud legges til.")
    calendar_enabled = yes_no("Har du en eller flere ICS-kalendere du vil legge til nå?")
    feeds: list[dict[str, str]] = []
    while calendar_enabled:
        name = input("Kort navn på kalenderen: ").strip()[:40] or f"Kalender {len(feeds) + 1}"
        feeds.append({"name": name, "url": private_url("Privat ICS-adresse (skjult): ")})
        if not yes_no("Legge til enda en kalender?"):
            break

    write_private_json(
        args.config,
        {
            "version": 1,
            "garmin": {"enabled": garmin_enabled, "calendar_url": garmin_url},
            "calendar": {"enabled": bool(feeds), "feeds": feeds},
        },
    )
    print(f"Valgene er lagret lokalt i {args.config} med modus 0600.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
