#!/usr/bin/env python3
"""Primær, norsk installasjonsveiviser for Pi Display Lab-clusteret."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from setup_cluster import run_wizard  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run_wizard(PROJECT_DIR))
