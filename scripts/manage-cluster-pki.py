#!/usr/bin/env python3
"""Lag/bevar privat lab-CA og coordinator-sertifikat i en privat stagingmappe."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from cluster_pki import prepare_pki  # noqa: E402
from config import ConfigValidationError, validate_controller_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("output_dir")
    parser.add_argument("--regenerate-server", action="store_true")
    args = parser.parse_args()
    try:
        settings = validate_controller_config(args.config)
        result = prepare_pki(
            settings,
            args.output_dir,
            allow_server_regeneration=args.regenerate_server,
        )
    except (ConfigValidationError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
    ca_text = "bevart" if result["ca_preserved"] else "opprettet"
    server_text = "bevart" if result["server_preserved"] else "opprettet"
    print(f"Privat CA {ca_text}; coordinator-sertifikat {server_text}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
