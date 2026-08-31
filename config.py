"""Trygg lasting av lokale innstillinger som ikke skal inn i Git."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


DEFAULT_COORDINATOR_URL = "http://127.0.0.1:5001"


@dataclass(frozen=True)
class ClusterConfig:
    enabled: bool = False
    coordinator_url: str = DEFAULT_COORDINATOR_URL


@dataclass(frozen=True)
class AppConfig:
    cluster: ClusterConfig = field(default_factory=ClusterConfig)


def _valid_coordinator_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip().rstrip("/")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return cleaned


def load_config(path: str | Path | None = None) -> AppConfig:
    """Les lokal JSON-konfigurasjon, med deaktivert cluster som sikker standard."""

    config_path = Path(path) if path is not None else Path(__file__).with_name("config.local.json")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return AppConfig()

    if not isinstance(raw, dict) or not isinstance(raw.get("cluster"), dict):
        return AppConfig()

    cluster = raw["cluster"]
    coordinator_url = _valid_coordinator_url(cluster.get("coordinator_url"))
    if coordinator_url is None:
        return AppConfig()

    return AppConfig(
        cluster=ClusterConfig(
            enabled=cluster.get("enabled") is True,
            coordinator_url=coordinator_url,
        )
    )
