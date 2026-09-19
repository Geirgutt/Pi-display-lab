#!/usr/bin/env python3
"""Ask once where the optional USB-connected DeskDisplay is attached."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def prompt(message: str, *, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        with open("/dev/tty", "r+", encoding="utf-8", errors="replace") as terminal:
            terminal.write(message + suffix + ": ")
            terminal.flush()
            answer = terminal.readline().strip()
    except OSError:
        if not sys.stdin.isatty():
            raise RuntimeError(
                "DeskDisplay er ikke konfigurert ennå, men installasjonen har ingen interaktiv terminal. "
                "Kjør installasjonen manuelt én gang for å velge displayplassering."
            ) from None
        answer = input(message + suffix + ": ").strip()
    return answer or default


def yes_no(message: str) -> bool:
    while True:
        answer = prompt(message + " [j/N]").casefold()
        if answer in {"", "n", "nei", "no"}:
            return False
        if answer in {"j", "ja", "y", "yes"}:
            return True
        print("Svar j eller n.")


def main() -> int:
    if len(sys.argv) not in {2, 3} or (len(sys.argv) == 3 and sys.argv[2] != "--reset"):
        print(f"Bruk: {sys.argv[0]} CONFIG [--reset]", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Kan ikke lese lokal config: {error}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print("Lokal config må inneholde et JSON-objekt.", file=sys.stderr)
        return 1

    deskdisplay = payload.setdefault("deskdisplay", {})
    if not isinstance(deskdisplay, dict):
        print("deskdisplay må være et JSON-objekt.", file=sys.stderr)
        return 1
    if isinstance(deskdisplay.get("display_attached"), bool) and len(sys.argv) == 2:
        return 0

    workers = payload.get("worker_hosts", [])
    if not isinstance(workers, list):
        workers = []
    workers = [worker for worker in workers if isinstance(worker, str) and worker]

    print("\nDeskDisplay er ikke konfigurert for USB-provisjonering ennå.")
    if not yes_no("Er displayet koblet med USB-data til en Pi nå?"):
        deskdisplay.update({
            "display_attached": False,
            "display_host": "",
            "display_serial_port": "",
            "display_wifi_ssid": "",
            "display_wifi_configured": False,
        })
    else:
        choices = [("controller", "controlleren")]
        choices.extend((worker, worker) for worker in workers)
        print("Velg Pi-en som displayet er koblet til:")
        for index, (_, label) in enumerate(choices, start=1):
            print(f"  {index}. {label}")
        while True:
            selected = prompt("Pi-nummer")
            try:
                target = choices[int(selected) - 1][0]
                break
            except (ValueError, IndexError):
                print("Velg et av numrene over.")
        serial_port = prompt(
            "Seriell port på denne Pi-en (tom = finn automatisk)",
        )
        wifi_ssid = prompt(
            "Wi-Fi-SSID (tom = behold allerede lagret Wi-Fi)",
        )
        deskdisplay.update({
            "enabled": True,
            "display_attached": True,
            "display_host": target,
            "display_serial_port": serial_port,
            "display_wifi_ssid": wifi_ssid,
            "display_wifi_configured": not bool(wifi_ssid),
        })

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    print("Displayvalget er lagret i config.local.json.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"Installasjonen stoppet: {error}", file=sys.stderr)
        raise SystemExit(1)
