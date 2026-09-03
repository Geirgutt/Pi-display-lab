#!/usr/bin/env python3
"""Lag midlertidig Ansible-inventory og variabler fra lokal config."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from config import ConfigValidationError, validate_controller_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("output_dir")
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()

    try:
        settings = validate_controller_config(args.config)
    except ConfigValidationError as error:
        raise SystemExit(str(error)) from error
    if re.fullmatch(r"[0-9a-f]{40}", args.revision) is None:
        raise SystemExit("Git-revisjonen må være en full 40-tegns commit-SHA")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory = ["[cluster_workers]"]
    inventory.extend(
        f"{host} ansible_user={settings.ssh_user}" for host in settings.worker_hosts
    )
    (output_dir / "inventory.ini").write_text("\n".join(inventory) + "\n", encoding="utf-8")
    os.chmod(output_dir / "inventory.ini", 0o600)

    variables = {
        "ansible_connection": "ansible.builtin.ssh",
        # Use the same system Python that worker bootstrap and preflight validate.
        "ansible_python_interpreter": "/usr/bin/python3",
        "project_repository": "https://github.com/Geirgutt/Pi-display-lab.git",
        "project_version": args.revision,
        "controller_host": settings.controller_host,
        "coordinator_port": settings.coordinator_port,
        "app_port": settings.app_port,
        "worker_poll_interval": settings.cluster.poll_interval_seconds,
        "cluster_credentials_file": settings.cluster.credentials_file,
        "cluster_ca_file": settings.cluster.ca_certificate_file,
    }
    if settings.ssh_identity_file:
        variables["ansible_ssh_private_key_file"] = settings.ssh_identity_file
        variables["ansible_ssh_common_args"] = "-o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"
    (output_dir / "vars.json").write_text(
        json.dumps(variables, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(output_dir / "vars.json", 0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
