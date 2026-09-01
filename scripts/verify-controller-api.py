#!/usr/bin/env python3
"""Verifiser controller-API-er uten å vise eller sende tokens via kommandolinjen."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from cluster_auth import load_cluster_credentials  # noqa: E402
from cluster_client import ClusterCoordinatorClient, CoordinatorUnavailable  # noqa: E402
from config import validate_controller_config  # noqa: E402


def _check_json(url: str, token: str = "") -> dict[str, object]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Ingen gyldig respons fra {url}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Ugyldig JSON-objekt fra {url}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()
    settings = validate_controller_config(args.config)
    credentials = load_cluster_credentials(settings.cluster.credentials_file)
    if not credentials.admin_token:
        raise SystemExit("Controllerens admin-credential mangler eller er ugyldig")

    app_base = f"http://127.0.0.1:{settings.app_port}"
    coordinator = ClusterCoordinatorClient(
        settings.cluster,
        bearer_token=credentials.admin_token,
    )
    try:
        if not _check_json(f"{app_base}/api/health").get("ok"):
            raise RuntimeError("Pi Display Lab health rapporterte feil")
        if not coordinator.fetch_health().get("ok"):
            raise RuntimeError("Coordinator health rapporterte feil")
        coordinator.fetch_status()
        cluster_status = _check_json(f"{app_base}/api/cluster-jobs")
        if cluster_status.get("status") in {"unavailable", "authentication_failed"}:
            raise RuntimeError("Pi Display Lab får ikke autentisert coordinator-status")
    except (CoordinatorUnavailable, RuntimeError, OSError, ValueError) as error:
        raise SystemExit(str(error)) from error
    print("Controller-API, verifisert coordinator-HTTPS og appens cluster-API svarer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
