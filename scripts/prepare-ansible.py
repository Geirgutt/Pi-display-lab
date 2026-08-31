#!/usr/bin/env python3
"""Lag midlertidig Ansible-inventory og variabler fra lokal config."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from config import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("output_dir")
    args = parser.parse_args()

    settings = load_config(args.config)
    if not settings.cluster.enabled:
        raise SystemExit("Cluster må være enabled i config.local.json")
    if not settings.ssh_user:
        raise SystemExit("ssh_user mangler eller er ugyldig i config.local.json")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory = ["[cluster_workers]"]
    inventory.extend(
        f"{host} ansible_user={settings.ssh_user}" for host in settings.worker_hosts
    )
    (output_dir / "inventory.ini").write_text("\n".join(inventory) + "\n", encoding="utf-8")

    variables = {
        "project_repository": "https://github.com/Geirgutt/Pi-display-lab.git",
        "project_version": "main",
        "controller_host": settings.controller_host,
        "coordinator_port": settings.coordinator_port,
        "app_port": settings.app_port,
        "worker_poll_interval": settings.cluster.poll_interval_seconds,
    }
    (output_dir / "vars.json").write_text(
        json.dumps(variables, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
