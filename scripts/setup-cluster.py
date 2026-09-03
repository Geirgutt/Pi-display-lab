#!/usr/bin/env python3
"""Primær, norsk installasjonsveiviser for Pi Display Lab-clusteret."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

if __name__ == "__main__":
    if sys.platform.startswith("linux") and os.environ.get("PI_DISPLAY_SETUP_READY") != "1":
        os.execvp("bash", ["bash", str(PROJECT_DIR / "scripts/setup-cluster.sh")])
    from setup_cluster import run_wizard

    try:
        raise SystemExit(run_wizard(PROJECT_DIR))
    except (KeyboardInterrupt, EOFError):
        print("\nOppsettet ble avbrutt. Du kan kjøre veiviseren på nytt.")
        raise SystemExit(130)
