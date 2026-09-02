"""HTTPS-klient og lett statuscache for cluster coordinator-tjenesten."""

from __future__ import annotations

import json
import socket
import ssl
import threading
import time
from copy import deepcopy
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cluster_auth import load_cluster_credentials
from cluster_tls import create_client_ssl_context
from config import ClusterConfig


class CoordinatorUnavailable(RuntimeError):
    """Coordinatoren kunne ikke levere et gyldig svar."""


class CoordinatorAuthenticationError(CoordinatorUnavailable):
    """Coordinatoren svarte, men avviste lokal credential."""


def disabled_cluster_status() -> dict[str, Any]:
    return {
        "enabled": False,
        "available": False,
        "status": "disabled",
        "message": "Cluster-integrasjonen er deaktivert",
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "queued_jobs": [],
        "running_jobs": [],
        "results": [],
        "batches": [],
    }


def unavailable_cluster_status(status: str = "unavailable") -> dict[str, Any]:
    messages = {
        "checking": "Kobler til cluster coordinator",
        "authentication_failed": "Cluster-credential mangler eller ble avvist",
        "unavailable": "Cluster coordinator svarer ikke",
    }
    return {
        "enabled": True,
        "available": False,
        "status": status,
        "message": messages.get(status, "Cluster coordinator svarer ikke"),
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "queued_jobs": [],
        "running_jobs": [],
        "results": [],
        "batches": [],
    }


class ClusterCoordinatorClient:
    def __init__(
        self,
        config: ClusterConfig,
        timeout_seconds: float = 2.0,
        bearer_token: str | None = None,
    ) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.bearer_token = (
            load_cluster_credentials(config.credentials_file).admin_token
            if bearer_token is None
            else bearer_token
        )
        self._ssl_context: ssl.SSLContext | None = None

    def _request_json(
        self,
        path: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        allow_empty: bool = False,
        worker_identity: str = "",
        authenticated: bool = True,
    ) -> dict[str, Any] | None:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json", "User-Agent": "Pi-display-lab/1"}
        if authenticated and self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        if worker_identity:
            headers["X-Worker-ID"] = worker_identity
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.config.coordinator_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            context = self._ssl_context
            if context is None:
                context = create_client_ssl_context(self.config)
                self._ssl_context = context
            open_kwargs: dict[str, Any] = {"timeout": self.timeout_seconds}
            if context is not None:
                open_kwargs["context"] = context
            with urlopen(request, **open_kwargs) as response:
                raw = response.read()
                if not raw and allow_empty:
                    return None
                decoded = json.loads(raw.decode("utf-8"))
        except HTTPError as error:
            if error.code in {401, 403}:
                raise CoordinatorAuthenticationError(
                    "Coordinator avviste cluster-credential"
                ) from error
            raise CoordinatorUnavailable("Coordinator svarte med HTTP-feil") from error
        except (
            URLError,
            TimeoutError,
            socket.timeout,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise CoordinatorUnavailable("Coordinator svarer ikke med gyldig JSON") from error
        if not isinstance(decoded, dict):
            raise CoordinatorUnavailable("Coordinator returnerte et ugyldig svar")
        return decoded

    def fetch_status(self) -> dict[str, Any]:
        return self._request_json("/status") or {}

    def fetch_health(self) -> dict[str, Any]:
        return self._request_json("/health", authenticated=False) or {}

    def start_prime_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            "/jobs", method="POST", payload={**payload, "job_type": "prime_count"}
        ) or {}

    def start_monte_carlo(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            "/jobs", method="POST", payload={**payload, "job_type": "monte_carlo"}
        ) or {}

    def cancel_batch(self, batch_id: int) -> dict[str, Any]:
        return self._request_json(
            f"/batches/{int(batch_id)}/cancel", method="POST"
        ) or {}

    def claim_job(self, worker: str) -> dict[str, Any] | None:
        return self._request_json(
            "/job",
            allow_empty=True,
            worker_identity=worker,
        )

    def submit_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        worker = payload.get("worker")
        return self._request_json(
            "/result",
            method="POST",
            payload=payload,
            worker_identity=worker if isinstance(worker, str) else "",
        ) or {}


class ClusterStatusCache:
    """Oppdater status i bakgrunnen slik at /api/state aldri venter på nettverk."""

    def __init__(self, client: ClusterCoordinatorClient) -> None:
        self.client = client
        self._state = (
            unavailable_cluster_status("checking")
            if client.config.enabled
            else disabled_cluster_status()
        )
        self._last_attempt = 0.0
        self._refreshing = False
        self._lock = threading.Lock()

    def snapshot(self) -> dict[str, Any]:
        if not self.client.config.enabled:
            return disabled_cluster_status()
        now = time.monotonic()
        with self._lock:
            if (
                not self._refreshing
                and now - self._last_attempt >= self.client.config.poll_interval_seconds
            ):
                self._refreshing = True
                self._last_attempt = now
                threading.Thread(target=self._refresh, daemon=True, name="cluster-status").start()
            return deepcopy(self._state)

    def store(self, payload: dict[str, Any]) -> dict[str, Any]:
        compact = deepcopy(payload)
        compact["results"] = list(compact.get("results") or [])[-20:]
        compact["queued_jobs"] = list(compact.get("queued_jobs") or [])[:20]
        state = {
            **compact,
            "enabled": True,
            "available": True,
            "status": "online",
            "message": "Cluster coordinator er tilkoblet",
        }
        with self._lock:
            self._state = state
            self._last_attempt = time.monotonic()
        return deepcopy(state)

    def mark_unavailable(self, status: str = "unavailable") -> dict[str, Any]:
        state = unavailable_cluster_status(status)
        with self._lock:
            self._state = state
            self._last_attempt = time.monotonic()
        return deepcopy(state)

    def invalidate(self) -> None:
        with self._lock:
            self._last_attempt = 0.0

    def _refresh(self) -> None:
        try:
            self.store(self.client.fetch_status())
        except CoordinatorAuthenticationError:
            self.mark_unavailable("authentication_failed")
        except CoordinatorUnavailable:
            self.mark_unavailable()
        finally:
            with self._lock:
                self._refreshing = False
