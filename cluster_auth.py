"""Små, lokale credentials for cluster-protokollen.

Bearer-tokenene beskytter hvem som får hente arbeid og styre køen. De krypterer
ikke HTTP-trafikken; clusteret er fortsatt laget for et betrodd labnett.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MIN_TOKEN_LENGTH = 32
MAX_TOKEN_LENGTH = 512
WORKER_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _valid_token(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    if (
        not MIN_TOKEN_LENGTH <= len(value) <= MAX_TOKEN_LENGTH
        or not value.isprintable()
        or any(character.isspace() for character in value)
    ):
        return ""
    return value


def valid_worker_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = value.strip()
    return cleaned if WORKER_ID_PATTERN.fullmatch(cleaned) else ""


@dataclass(frozen=True)
class ClusterCredentials:
    """Credentials for enten controlleren eller én worker.

    Controller-filen har admin-token og et worker-tokenkart. En worker-fil har
    bare workerens egen identitet og token.
    """

    admin_token: str = ""
    worker_tokens: dict[str, str] = field(default_factory=dict)
    worker_id: str = ""
    worker_token: str = ""
    node_heartbeat_token: str = ""

    def authenticate_admin(self, supplied_token: str) -> bool:
        return bool(
            self.admin_token
            and supplied_token
            and secrets.compare_digest(self.admin_token, supplied_token)
        )

    def authenticate_worker(self, worker_id: str, supplied_token: str) -> bool:
        identity = valid_worker_id(worker_id)
        expected_token = self.worker_tokens.get(identity, "")
        return bool(
            identity
            and expected_token
            and supplied_token
            and secrets.compare_digest(expected_token, supplied_token)
        )


def load_cluster_credentials(path: str | Path) -> ClusterCredentials:
    """Les en credential-fil og feil lukket hvis den mangler eller er ugyldig."""

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return ClusterCredentials()
    if not isinstance(raw, dict):
        return ClusterCredentials()

    raw_workers = raw.get("workers")
    worker_tokens: dict[str, str] = {}
    if isinstance(raw_workers, dict):
        for raw_worker, raw_token in raw_workers.items():
            worker = valid_worker_id(raw_worker)
            token = _valid_token(raw_token)
            if worker and token:
                worker_tokens[worker] = token

    admin_token = _valid_token(raw.get("admin_token"))
    # Duplikate tokens ville blande identiteter eller roller.
    if (
        len(set(worker_tokens.values())) != len(worker_tokens)
        or admin_token in worker_tokens.values()
    ):
        worker_tokens = {}

    return ClusterCredentials(
        admin_token=admin_token,
        worker_tokens=worker_tokens,
        worker_id=valid_worker_id(raw.get("worker_id")),
        worker_token=_valid_token(raw.get("worker_token")),
        node_heartbeat_token=_valid_token(raw.get("node_heartbeat_token")),
    )


def bearer_token(authorization_header: str | None) -> str:
    """Hent et avgrenset Bearer-token uten å godta alternative formater."""

    if not isinstance(authorization_header, str):
        return ""
    scheme, separator, token = authorization_header.partition(" ")
    if separator != " " or scheme.lower() != "bearer":
        return ""
    token = token.strip()
    return token if _valid_token(token) else ""
