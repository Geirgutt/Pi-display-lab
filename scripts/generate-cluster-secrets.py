#!/usr/bin/env python3
"""Generer eller bevar lokale cluster-tokens uten å skrive dem til Git."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from cluster_auth import load_cluster_credentials, valid_worker_id  # noqa: E402
from config import validate_controller_config  # noqa: E402


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("identities")
    parser.add_argument("output_dir")
    args = parser.parse_args()

    settings = validate_controller_config(args.config)
    identities_path = Path(args.identities)
    try:
        identities = json.loads(identities_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit("Kunne ikke lese validerte worker-identiteter") from error
    if not isinstance(identities, dict):
        raise SystemExit("Worker-identitetsfilen er ugyldig")

    normalized: dict[str, str] = {}
    for host in settings.worker_hosts:
        identity = valid_worker_id(identities.get(host))
        if not identity:
            raise SystemExit(f"Mangler gyldig hostname for konfigurert worker {host}")
        normalized[host] = identity
    if len(set(normalized.values())) != len(normalized):
        raise SystemExit("To worker-adresser rapporterer samme hostname")

    credentials_path = Path(settings.cluster.credentials_file)
    existing = load_cluster_credentials(credentials_path)
    if credentials_path.exists() and not existing.admin_token:
        raise SystemExit(
            f"Eksisterende credential-fil er ugyldig: {credentials_path}. "
            "Flytt den til et trygt sted og kjør installasjonen på nytt."
        )

    admin_token = existing.admin_token or _new_token()
    worker_tokens = {
        identity: existing.worker_tokens.get(identity) or _new_token()
        for identity in normalized.values()
    }
    node_token = ""
    if settings.node_heartbeat_auth:
        node_token = existing.node_heartbeat_token or _new_token()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    controller_payload: dict[str, object] = {
        "version": 1,
        "admin_token": admin_token,
        "workers": worker_tokens,
    }
    if node_token:
        controller_payload["node_heartbeat_token"] = node_token
    _write_private_json(output_dir / "cluster-credentials.json", controller_payload)

    worker_credentials = {
        host: {
            "worker_id": identity,
            "worker_token": worker_tokens[identity],
        }
        for host, identity in normalized.items()
    }
    _write_private_json(
        output_dir / "worker-secrets.json",
        {
            "worker_credentials": worker_credentials,
            "node_heartbeat_enabled": settings.node_heartbeat_auth,
            "node_heartbeat_token": node_token,
        },
    )

    if node_token:
        environment_file = output_dir / "node-heartbeat.env"
        environment_file.write_text(
            f"PI_DISPLAY_NODE_TOKEN={node_token}\n", encoding="utf-8"
        )
        os.chmod(environment_file, 0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
