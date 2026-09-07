#!/usr/bin/env python3
"""Generer eller bevar lokale cluster-tokens uten å skrive dem til Git."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from cluster_auth import (  # noqa: E402
    load_cluster_credentials,
    merge_controller_credentials,
    valid_worker_id,
)
from config import validate_controller_config  # noqa: E402


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _read_deskdisplay_psk(path: str) -> str:
    try:
        content = Path(path).read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise SystemExit(
            f"Mangler DeskDisplay-PSK-filen utenfor prosjektet: {path}"
        ) from error
    compact = "".join(content.split())
    if re.fullmatch(r"[0-9a-fA-F]{64}", compact) is None:
        raise SystemExit("DeskDisplay-PSK-filen må inneholde nøyaktig 64 hex-tegn")
    return compact.lower()


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

    merged = merge_controller_credentials(
        existing,
        list(normalized.values()),
        heartbeat_enabled=settings.node_heartbeat_auth,
    )
    admin_token = merged.admin_token
    worker_tokens = merged.worker_tokens
    node_token = merged.node_heartbeat_token

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    controller_payload: dict[str, object] = {
        "version": 1,
        "admin_token": admin_token,
        "workers": worker_tokens,
        "retired_workers": list(merged.retired_worker_ids),
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
    deskdisplay_psk = None
    if settings.deskdisplay.enabled:
        deskdisplay_psk = _read_deskdisplay_psk(settings.deskdisplay.psk_file)
    ca_certificate_path = output_dir / "ca.crt"
    try:
        ca_certificate = ca_certificate_path.read_text(encoding="ascii")
    except OSError as error:
        raise SystemExit("Mangler klargjort offentlig CA-sertifikat") from error
    if "BEGIN CERTIFICATE" not in ca_certificate:
        raise SystemExit("Klargjort offentlig CA-sertifikat er ugyldig")
    worker_secrets: dict[str, object] = {
        "worker_credentials": worker_credentials,
        "node_heartbeat_enabled": settings.node_heartbeat_auth,
        "node_heartbeat_token": node_token,
        # Bare offentlig CA-sertifikat distribueres. CA-nøkkelen leses aldri her.
        "cluster_ca_certificate": ca_certificate,
    }
    if deskdisplay_psk is not None:
        worker_secrets["deskdisplay_peer_psk"] = deskdisplay_psk
    _write_private_json(output_dir / "worker-secrets.json", worker_secrets)

    if node_token:
        environment_file = output_dir / "node-heartbeat.env"
        environment_file.write_text(
            f"PI_DISPLAY_NODE_TOKEN={node_token}\n", encoding="utf-8"
        )
        os.chmod(environment_file, 0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
