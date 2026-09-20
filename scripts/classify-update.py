#!/usr/bin/env python3
"""Classify a Git revision range for the smallest safe update path."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from update_policy import classify_paths  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("previous")
    parser.add_argument("current")
    args = parser.parse_args()
    result = subprocess.run(
        ["git", "diff", "--name-only", args.previous, args.current],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        sys.stderr.write(result.stderr)
        return result.returncode
    mode, display_changed, _unknown = classify_paths(result.stdout.splitlines())
    print(f"{mode}\t{'true' if display_changed else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
