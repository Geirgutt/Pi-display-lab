#!/usr/bin/env python3
"""Fast, read-only PKI health check used before a quick cluster update."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from cluster_pki import inspect_pki  # noqa: E402
from config import ConfigValidationError, validate_controller_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()
    try:
        status = inspect_pki(validate_controller_config(args.config))
    except (ConfigValidationError, OSError, RuntimeError) as error:
        print(f"PKI-kontrollen feilet: {error}", file=sys.stderr)
        return 1
    if not status.ca_is_valid or not status.server_is_current or not status.server_matches_address:
        print("Cluster-PKI mangler, er ugyldig, utløper snart eller matcher ikke controlleren.", file=sys.stderr)
        return 1
    print("Eksisterende cluster-PKI er gyldig; ingen redistribusjon er nødvendig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
