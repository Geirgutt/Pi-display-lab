#!/usr/bin/env python3
"""Mark the locally provisioned DeskDisplay firmware as OTA-capable."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Bruk: {sys.argv[0]} CONFIG", file=sys.stderr)
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
    deskdisplay["display_ota_ready"] = True
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    print("DeskDisplay er markert som OTA-klargjort lokalt på controlleren.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
