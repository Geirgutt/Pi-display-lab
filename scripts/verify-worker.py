#!/usr/bin/env python3
"""Verifiser workerens identitet og TLS uten å skrive credentials til output."""

from __future__ import annotations

import argparse
import secrets
import socket
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from cluster_auth import load_cluster_credentials  # noqa: E402
from cluster_client import ClusterCoordinatorClient, CoordinatorUnavailable  # noqa: E402
from config import load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()
    settings = load_config(args.config)
    credentials = load_cluster_credentials(settings.cluster.credentials_file)
    hostname = socket.gethostname()
    if not credentials.worker_id or not credentials.worker_token:
        raise SystemExit("Worker-credential mangler eller er ugyldig")
    if not secrets.compare_digest(credentials.worker_id, hostname):
        raise SystemExit("Worker-credential tilhører ikke denne maskinens hostname")
    if not settings.cluster.coordinator_url.startswith("https://"):
        raise SystemExit("Workerens coordinator_url bruker ikke HTTPS")
    try:
        health = ClusterCoordinatorClient(
            settings.cluster,
            bearer_token=credentials.worker_token,
        ).fetch_health()
    except (CoordinatorUnavailable, OSError, ValueError) as error:
        raise SystemExit("Worker kan ikke validere coordinatorens HTTPS-sertifikat") from error
    if health.get("service") != "cluster-coordinator":
        raise SystemExit("Coordinatorens health-svar er ugyldig")
    print(f"{hostname}: HTTPS/CA og worker-identitet er verifisert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
