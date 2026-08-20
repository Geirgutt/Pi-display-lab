"""Transportlaget: samme payload kan sendes til ulike typer skjermer."""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from copy import deepcopy
from typing import Any


class DeviceTransport(ABC):
    """Felles kontrakt for alle mottakere av skjerm-state."""

    @abstractmethod
    def send(self, payload: dict[str, Any]) -> None:
        """Send én fullstendig state-melding til mottakeren."""


class BrowserTransport(DeviceTransport):
    """Lagrer siste melding til nettleserens GET /api/state-kall."""

    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}
        self._lock = threading.Lock()

    def send(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._payload = deepcopy(payload)

    def latest(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._payload)


class Esp32Transport(DeviceTransport):
    """Stub for senere MQTT-publisering til en ESP32-S3.

    `sender` blir senere en funksjon som publiserer tekst til MQTT-topicet
    `pilab/display/state`. I denne versjonen utføres ingen nettverkstrafikk.
    """

    def __init__(
        self,
        enabled: bool = False,
        sender: Callable[[str], None] | None = None,
    ) -> None:
        self.enabled = enabled
        self.sender = sender
        self.last_encoded: str | None = None

    def send(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self.last_encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if self.sender is not None:
            self.sender(self.last_encoded)


class TransportHub:
    """Sender samme state til alle tilkoblede transporter."""

    def __init__(self, transports: Iterable[DeviceTransport]) -> None:
        self.transports = list(transports)

    def publish(self, payload: dict[str, Any]) -> None:
        for transport in self.transports:
            transport.send(payload)
