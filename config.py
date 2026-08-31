"""Trygg lasting av lokale innstillinger som ikke skal inn i Git."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


DEFAULT_COORDINATOR_URL = "http://127.0.0.1:5001"


@dataclass(frozen=True)
class ClusterConfig:
    enabled: bool = False
    coordinator_url: str = DEFAULT_COORDINATOR_URL
    poll_interval_seconds: float = 2.0


@dataclass(frozen=True)
class AppConfig:
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    node_role: str = "standalone"
    controller_host: str = "127.0.0.1"
    worker_hosts: tuple[str, ...] = ()
    ssh_user: str = ""
    coordinator_port: int = 5001
    app_port: int = 5000


def _valid_coordinator_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip().rstrip("/")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return cleaned


def _safe_port(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65535 else default


def _safe_host(value: Any, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 253 or re.fullmatch(r"[A-Za-z0-9._:-]+", cleaned) is None:
        return default
    return cleaned


def load_config(path: str | Path | None = None) -> AppConfig:
    """Les lokal JSON-konfigurasjon, med deaktivert cluster som sikker standard."""

    config_path = Path(path) if path is not None else Path(__file__).with_name("config.local.json")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return AppConfig()

    if not isinstance(raw, dict):
        return AppConfig()

    cluster = raw.get("cluster") if isinstance(raw.get("cluster"), dict) else {}
    coordinator_url = _valid_coordinator_url(cluster.get("coordinator_url"))
    poll_interval = cluster.get("poll_interval_seconds", 2.0)
    if isinstance(poll_interval, bool) or not isinstance(poll_interval, (int, float)):
        poll_interval = 2.0
    poll_interval = min(max(float(poll_interval), 0.5), 60.0)

    raw_workers = raw.get("worker_hosts", [])
    worker_hosts = ()
    if isinstance(raw_workers, list):
        worker_hosts = tuple(
            host for value in raw_workers if (host := _safe_host(value))
        )

    role = raw.get("node_role")
    if role not in {"controller", "worker", "standalone"}:
        role = "standalone"
    ssh_user = raw.get("ssh_user")
    if not isinstance(ssh_user, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,32}", ssh_user) is None:
        ssh_user = ""

    return AppConfig(
        cluster=ClusterConfig(
            enabled=cluster.get("enabled") is True and coordinator_url is not None,
            coordinator_url=coordinator_url or DEFAULT_COORDINATOR_URL,
            poll_interval_seconds=poll_interval,
        ),
        node_role=role,
        controller_host=_safe_host(raw.get("controller_host"), "127.0.0.1"),
        worker_hosts=worker_hosts,
        ssh_user=ssh_user,
        coordinator_port=_safe_port(raw.get("coordinator_port"), 5001),
        app_port=_safe_port(raw.get("app_port"), 5000),
    )
