#!/usr/bin/env python3
"""Skriv én validert lokal config-verdi for installasjonsskriptene."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from config import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "key",
        choices=("app_port", "controller_host", "coordinator_port", "node_role", "ssh_user"),
    )
    parser.add_argument("--config", default=str(PROJECT_DIR / "config.local.json"))
    args = parser.parse_args()
    settings = load_config(args.config)
    print(getattr(settings, args.key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
