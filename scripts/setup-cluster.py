#!/usr/bin/env python3
"""Primær, norsk installasjonsveiviser for Pi Display Lab-clusteret."""

from __future__ import annotations

import os
import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("verify", "reinstall", "add", "network", "remove"),
                        help="Åpne en bestemt del av veiviseren direkte.")
    args = parser.parse_args()
    if sys.platform.startswith("linux") and os.environ.get("PI_DISPLAY_SETUP_READY") != "1":
        os.execvp("bash", ["bash", str(PROJECT_DIR / "scripts/setup-cluster.sh"), *sys.argv[1:]])
    from setup_cluster import run_wizard

    try:
        raise SystemExit(run_wizard(PROJECT_DIR, action=args.action))
    except (KeyboardInterrupt, EOFError):
        print("\nOppsettet ble avbrutt. Du kan kjøre veiviseren på nytt.")
        raise SystemExit(130)
