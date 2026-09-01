"""Trygg lasting av lokale innstillinger som ikke skal inn i Git."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


DEFAULT_COORDINATOR_URL = "https://127.0.0.1:5001"
DEFAULT_CLUSTER_CREDENTIALS_FILE = "/etc/pi-display-lab/cluster-credentials.json"
DEFAULT_CLUSTER_CA_FILE = "/etc/pi-display-lab/pki/ca.crt"
DEFAULT_COORDINATOR_CERT_FILE = "/etc/pi-display-lab/pki/coordinator.crt"
DEFAULT_COORDINATOR_KEY_FILE = "/etc/pi-display-lab/pki/coordinator.key"


class ConfigValidationError(ValueError):
    """Lokal installasjonsconfig mangler eller er utrygg/ufullstendig."""


@dataclass(frozen=True)
class ClusterConfig:
    enabled: bool = False
    coordinator_url: str = DEFAULT_COORDINATOR_URL
    poll_interval_seconds: float = 2.0
    credentials_file: str = DEFAULT_CLUSTER_CREDENTIALS_FILE
    tls_enabled: bool = True
    ca_certificate_file: str = DEFAULT_CLUSTER_CA_FILE
    server_certificate_file: str = DEFAULT_COORDINATOR_CERT_FILE
    server_key_file: str = DEFAULT_COORDINATOR_KEY_FILE


@dataclass(frozen=True)
class AppConfig:
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    node_role: str = "standalone"
    controller_host: str = "127.0.0.1"
    worker_hosts: tuple[str, ...] = ()
    ssh_user: str = ""
    coordinator_port: int = 5001
    app_port: int = 5000
    node_heartbeat_auth: bool = False


def _valid_coordinator_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip().rstrip("/")
    parsed = urlsplit(cleaned)
    try:
        parsed_port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (parsed_port is not None and not 1 <= parsed_port <= 65535)
    ):
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
    if (
        not cleaned
        or len(cleaned) > 253
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,252}", cleaned) is None
    ):
        return default
    return cleaned


def _safe_private_file(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    cleaned = value.strip()
    if (
        not cleaned.startswith("/")
        or len(cleaned) > 4096
        or re.fullmatch(r"/[A-Za-z0-9_./-]+", cleaned) is None
        or ".." in Path(cleaned).parts
    ):
        return default
    return cleaned


def _safe_credentials_file(value: Any) -> str:
    return _safe_private_file(value, DEFAULT_CLUSTER_CREDENTIALS_FILE)


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
            credentials_file=_safe_credentials_file(cluster.get("credentials_file")),
            tls_enabled=cluster.get("tls_enabled", True) is True,
            ca_certificate_file=_safe_private_file(
                cluster.get("ca_certificate_file"), DEFAULT_CLUSTER_CA_FILE
            ),
            server_certificate_file=_safe_private_file(
                cluster.get("server_certificate_file"), DEFAULT_COORDINATOR_CERT_FILE
            ),
            server_key_file=_safe_private_file(
                cluster.get("server_key_file"), DEFAULT_COORDINATOR_KEY_FILE
            ),
        ),
        node_role=role,
        controller_host=_safe_host(raw.get("controller_host"), "127.0.0.1"),
        worker_hosts=worker_hosts,
        ssh_user=ssh_user,
        coordinator_port=_safe_port(raw.get("coordinator_port"), 5001),
        app_port=_safe_port(raw.get("app_port"), 5000),
        node_heartbeat_auth=raw.get("node_heartbeat_auth") is True,
    )


def validate_controller_config(path: str | Path) -> AppConfig:
    """Valider config strengt før installasjon gjør endringer på maskiner."""

    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigValidationError(f"Mangler lokal config: {config_path}") from error
    except OSError as error:
        raise ConfigValidationError(f"Kan ikke lese lokal config: {config_path}") from error
    except json.JSONDecodeError as error:
        raise ConfigValidationError(
            f"config.local.json er ikke gyldig JSON (linje {error.lineno})"
        ) from error

    if not isinstance(raw, dict):
        raise ConfigValidationError("config.local.json må inneholde et JSON-objekt")
    cluster = raw.get("cluster")
    errors: list[str] = []
    if raw.get("node_role") != "controller":
        errors.append("node_role må være 'controller'")

    controller_host = _safe_host(raw.get("controller_host"))
    if not controller_host:
        errors.append("controller_host mangler eller er ugyldig")
    elif ":" in controller_host:
        errors.append("controller_host støtter foreløpig hostname eller IPv4, ikke IPv6")
    elif controller_host.casefold() in {"localhost", "localhost.localdomain", "127.0.0.1", "::1"}:
        errors.append("controller_host må være en adresse workerne kan nå, ikke loopback")

    workers = raw.get("worker_hosts")
    if not isinstance(workers, list) or not workers:
        errors.append("worker_hosts må inneholde minst én worker")
    else:
        cleaned_workers = [_safe_host(worker) for worker in workers]
        if any(not worker for worker in cleaned_workers):
            errors.append("worker_hosts inneholder et ugyldig vertsnavn eller adresse")
        elif any(":" in worker for worker in cleaned_workers):
            errors.append("worker_hosts støtter foreløpig hostname eller IPv4, ikke IPv6")
        elif len(set(cleaned_workers)) != len(cleaned_workers):
            errors.append("worker_hosts kan ikke inneholde duplikater")

    ssh_user = raw.get("ssh_user")
    if not isinstance(ssh_user, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,32}", ssh_user) is None:
        errors.append("ssh_user mangler eller er ugyldig")
    if ssh_user == "root":
        errors.append("ssh_user kan ikke være root")

    for key in ("coordinator_port", "app_port"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
            errors.append(f"{key} må være et heltall mellom 1 og 65535")
    if raw.get("coordinator_port") == raw.get("app_port"):
        errors.append("coordinator_port og app_port må være forskjellige")

    if not isinstance(cluster, dict):
        errors.append("cluster må være et JSON-objekt")
    else:
        if cluster.get("enabled") is not True:
            errors.append("cluster.enabled må være true")
        coordinator_url = _valid_coordinator_url(cluster.get("coordinator_url"))
        if coordinator_url is None:
            errors.append("cluster.coordinator_url mangler eller er ugyldig")
        elif urlsplit(coordinator_url).scheme != "https":
            errors.append("cluster.coordinator_url må bruke https")
        elif controller_host and urlsplit(coordinator_url).hostname != controller_host:
            errors.append("cluster.coordinator_url må bruke samme adresse som controller_host")
        elif urlsplit(coordinator_url).port != raw.get("coordinator_port"):
            errors.append("cluster.coordinator_url må bruke coordinator_port")
        if cluster.get("tls_enabled", True) is not True:
            errors.append("cluster.tls_enabled må være true")
        poll = cluster.get("poll_interval_seconds", 2)
        if (
            isinstance(poll, bool)
            or not isinstance(poll, (int, float))
            or not 0.5 <= float(poll) <= 60
        ):
            errors.append("cluster.poll_interval_seconds må være mellom 0.5 og 60")
        credentials_file = cluster.get(
            "credentials_file", DEFAULT_CLUSTER_CREDENTIALS_FILE
        )
        if (
            _safe_credentials_file(credentials_file) != credentials_file
            or not credentials_file.startswith("/etc/pi-display-lab/")
        ):
            errors.append(
                "cluster.credentials_file må ligge under /etc/pi-display-lab/"
            )
        tls_files = {
            "ca_certificate_file": DEFAULT_CLUSTER_CA_FILE,
            "server_certificate_file": DEFAULT_COORDINATOR_CERT_FILE,
            "server_key_file": DEFAULT_COORDINATOR_KEY_FILE,
        }
        for key, default in tls_files.items():
            value = cluster.get(key, default)
            if (
                _safe_private_file(value, default) != value
                or not value.startswith("/etc/pi-display-lab/pki/")
            ):
                errors.append(f"cluster.{key} må ligge under /etc/pi-display-lab/pki/")

    if not isinstance(raw.get("node_heartbeat_auth", False), bool):
        errors.append("node_heartbeat_auth må være true eller false")

    if errors:
        raise ConfigValidationError("Ugyldig config.local.json:\n- " + "\n- ".join(errors))
    return load_config(config_path)
