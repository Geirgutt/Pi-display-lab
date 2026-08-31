"""Liten HTTP-klient for den separate cluster coordinator-tjenesten."""

from __future__ import annotations

import json
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import ClusterConfig


class CoordinatorUnavailable(RuntimeError):
    """Coordinatoren kunne ikke levere en gyldig status."""


class ClusterCoordinatorClient:
    def __init__(self, config: ClusterConfig, timeout_seconds: float = 2.0) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def fetch_status(self) -> dict[str, Any]:
        request = Request(
            f"{self.config.coordinator_url}/status",
            headers={"Accept": "application/json", "User-Agent": "Pi-display-lab/1"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, socket.timeout, OSError, json.JSONDecodeError) as error:
            raise CoordinatorUnavailable("Coordinator svarer ikke med gyldig JSON") from error

        if not isinstance(payload, dict):
            raise CoordinatorUnavailable("Coordinator returnerte et ugyldig svar")
        return payload
