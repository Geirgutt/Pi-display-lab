#!/usr/bin/env python3
"""Skriv én validert lokal config-verdi for installasjonsskriptene."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from config import ConfigValidationError, load_config, validate_controller_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "key",
        choices=(
            "app_port",
            "cluster_enabled",
            "cluster_credentials_file",
            "cluster_ca_file",
            "cluster_server_cert_file",
            "cluster_server_key_file",
            "controller_host",
            "coordinator_port",
            "node_heartbeat_auth",
            "node_role",
            "ssh_user",
            "worker_hosts",
        ),
    )
    parser.add_argument("--config", default=str(PROJECT_DIR / "config.local.json"))
    parser.add_argument(
        "--validate",
        action="store_true",
        help="avvis ugyldig JSON og valider controller-config strengt når cluster er på",
    )
    args = parser.parse_args()
    if args.validate:
        try:
            raw = json.loads(Path(args.config).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SystemExit("Lokal config mangler eller er ugyldig JSON") from error
        if not isinstance(raw, dict):
            raise SystemExit("Lokal config må inneholde et JSON-objekt")
        try:
            settings = (
                validate_controller_config(args.config)
                if isinstance(raw.get("cluster"), dict)
                and raw["cluster"].get("enabled") is True
                else load_config(args.config)
            )
        except ConfigValidationError as error:
            raise SystemExit(str(error)) from error
    else:
        settings = load_config(args.config)
    if args.key == "cluster_credentials_file":
        value = settings.cluster.credentials_file
    elif args.key == "cluster_ca_file":
        value = settings.cluster.ca_certificate_file
    elif args.key == "cluster_server_cert_file":
        value = settings.cluster.server_certificate_file
    elif args.key == "cluster_server_key_file":
        value = settings.cluster.server_key_file
    elif args.key == "cluster_enabled":
        value = settings.cluster.enabled
    else:
        value = getattr(settings, args.key)
    if args.key == "worker_hosts":
        print("\n".join(settings.worker_hosts))
        return 0
    if isinstance(value, bool):
        value = "true" if value else "false"
    print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
