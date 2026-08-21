"""Forretningslogikken: målinger, valgt skjerm og beregningsdemo."""

from __future__ import annotations

import math
import os
import random
import re
import socket
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any


class SystemMonitor:
    """Les enkle systemverdier uten tunge tredjepartsbiblioteker."""

    def __init__(self, mock_mode: bool = False) -> None:
        self.mock_mode = mock_mode
        self._previous_cpu: tuple[int, int] | None = None
        self._mock_tick = 0

    def read(self) -> dict[str, Any]:
        if self.mock_mode:
            return self._mock_values()

        local_ip = self._local_ip()
        return {
            "cpu": self._cpu_percent(),
            "temp": self._temperature_celsius(),
            "ram": self._memory_percent(),
            "ip": local_ip,
            "online": local_ip != "127.0.0.1",
        }

    def _mock_values(self) -> dict[str, Any]:
        self._mock_tick += 1
        wave = math.sin(self._mock_tick / 3)
        return {
            "cpu": round(34 + wave * 14, 1),
            "temp": round(50.5 + wave * 2.4, 1),
            "ram": round(47 + math.cos(self._mock_tick / 4) * 5, 1),
            "ip": "192.0.2.42",
            "online": True,
        }

    def _cpu_percent(self) -> float | None:
        """Beregn CPU-bruk fra to avlesninger av Linux-filen /proc/stat."""

        try:
            fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
            values = [int(value) for value in fields]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
            previous = self._previous_cpu
            self._previous_cpu = (idle, total)
            if previous is None:
                load = os.getloadavg()[0] / max(os.cpu_count() or 1, 1)
                return round(min(max(load * 100, 0), 100), 1)

            idle_delta = idle - previous[0]
            total_delta = total - previous[1]
            if total_delta <= 0:
                return 0.0
            return round(100 * (1 - idle_delta / total_delta), 1)
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _temperature_celsius() -> float | None:
        try:
            raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text(encoding="utf-8")
            return round(float(raw.strip()) / 1000, 1)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _memory_percent() -> float | None:
        try:
            values: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0])
            total = values["MemTotal"]
            available = values["MemAvailable"]
            return round((total - available) / total * 100, 1)
        except (OSError, ValueError, KeyError):
            return None

    @staticmethod
    def _local_ip() -> str:
        """Finn LAN-adressen uten å sende data ut på internett."""

        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            return str(probe.getsockname()[0])
        except OSError:
            return "127.0.0.1"
        finally:
            probe.close()

    @staticmethod
    def model_name() -> str:
        """Les maskinmodell på Raspberry Pi, med en nøytral fallback."""

        try:
            model = Path("/proc/device-tree/model").read_text(encoding="utf-8")
            return model.rstrip("\x00").strip()[:48] or "Raspberry Pi"
        except OSError:
            return "Raspberry Pi"


class NodeRegistry:
    """Holder siste heartbeat fra ekte, eksterne noder i minnet."""

    MAX_REGISTERED_NODES = 32

    def __init__(
        self,
        offline_after_seconds: float = 20.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.offline_after_seconds = offline_after_seconds
        self._clock = clock
        self._nodes: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _text(value: Any, field: str, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} må være tekst")
        cleaned = value.strip()
        if len(cleaned) > max_length:
            raise ValueError(f"{field} kan være maksimalt {max_length} tegn")
        if not cleaned.isprintable():
            raise ValueError(f"{field} inneholder ugyldige tegn")
        return cleaned

    @staticmethod
    def _number(value: Any, field: str, minimum: float, maximum: float) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{field} må være et tall")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field} må være et tall") from error
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(f"{field} må være mellom {minimum:g} og {maximum:g}")
        return round(number, 1)

    def heartbeat(self, payload: dict[str, Any], source_ip: str | None = None) -> dict[str, Any]:
        node_id = self._text(payload.get("node_id"), "node_id", 64)
        if re.fullmatch(r"[A-Za-z0-9._-]+", node_id) is None:
            raise ValueError("node_id kan bare inneholde bokstaver, tall, punktum, bindestrek og understrek")
        name = self._text(payload.get("name", node_id), "name", 24)
        model = self._text(payload.get("model", "Raspberry Pi"), "model", 48)
        cpu = self._number(payload.get("cpu"), "cpu", 0, 100)
        ram = self._number(payload.get("ram"), "ram", 0, 100)
        raw_temp = payload.get("temp")
        temp = None if raw_temp is None else self._number(raw_temp, "temp", -40, 150)
        now = self._clock()

        node = {
            "id": node_id,
            "name": name,
            "model": model,
            "cpu": cpu,
            "temp": temp,
            "ram": ram,
            "ip": source_ip,
            "kind": "remote",
            "mock": False,
            "last_seen": now,
        }
        with self._lock:
            if node_id not in self._nodes and len(self._nodes) >= self.MAX_REGISTERED_NODES:
                raise ValueError("Noderegisteret er fullt")
            self._nodes[node_id] = node
        return self._public_node(node, now)

    def snapshot(self, limit: int = 3) -> list[dict[str, Any]]:
        now = self._clock()
        with self._lock:
            nodes = [dict(node) for node in self._nodes.values()]
        nodes.sort(key=lambda node: (str(node["name"]).casefold(), str(node["id"])))
        return [self._public_node(node, now) for node in nodes[:limit]]

    def _public_node(self, node: dict[str, Any], now: float) -> dict[str, Any]:
        age = max(0.0, now - float(node["last_seen"]))
        return {
            "id": node["id"],
            "name": node["name"],
            "model": node["model"],
            "cpu": node["cpu"],
            "temp": node["temp"],
            "ram": node["ram"],
            "ip": node["ip"],
            "online": age <= self.offline_after_seconds,
            "kind": node["kind"],
            "mock": node["mock"],
            "last_seen_seconds": round(age, 1),
        }


class MonteCarloDemo:
    """Bakgrunnsjobb som estimerer pi og rapporterer fremdrift underveis."""

    MIN_ITERATIONS = 10_000
    MAX_ITERATIONS = 100_000_000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = "idle"
        self._samples_done = 0
        self._iterations = 0
        self._inside = 0
        self._estimate: float | None = None
        self._started_at = 0.0
        self._runtime_seconds = 0.0
        self._error: str | None = None

    def start(self, iterations: int) -> bool:
        iterations = min(max(iterations, self.MIN_ITERATIONS), self.MAX_ITERATIONS)
        with self._lock:
            if self._status == "running":
                return False
            self._status = "running"
            self._samples_done = 0
            self._iterations = iterations
            self._inside = 0
            self._estimate = None
            self._runtime_seconds = 0.0
            self._started_at = time.perf_counter()
            self._error = None

        worker = threading.Thread(target=self._calculate, daemon=True, name="pi-demo")
        worker.start()
        return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            runtime = self._runtime_seconds
            if self._status == "running":
                runtime = time.perf_counter() - self._started_at
            progress = self._samples_done / self._iterations * 100 if self._iterations else 0
            return {
                "status": self._status,
                "progress": round(progress, 1),
                "samples_done": self._samples_done,
                "iterations": self._iterations,
                "estimate": self._estimate,
                "runtime_seconds": round(runtime, 2),
                "error": self._error,
            }

    def _calculate(self) -> None:
        rng = random.Random()
        batch_size = 10_000
        try:
            while True:
                with self._lock:
                    remaining = self._iterations - self._samples_done
                if remaining <= 0:
                    break

                current_batch = min(batch_size, remaining)
                hits = 0
                for _ in range(current_batch):
                    x = rng.random()
                    y = rng.random()
                    if x * x + y * y <= 1:
                        hits += 1

                with self._lock:
                    self._inside += hits
                    self._samples_done += current_batch
                    self._estimate = round(4 * self._inside / self._samples_done, 6)

                # Gir nettleseren tid til å vise noen mellomresultater også på en rask PC.
                time.sleep(0.005)

            with self._lock:
                self._runtime_seconds = time.perf_counter() - self._started_at
                self._status = "finished"
        except Exception as error:  # Sikrer at UI-et ikke blir stående på "running".
            with self._lock:
                self._runtime_seconds = time.perf_counter() - self._started_at
                self._status = "error"
                self._error = str(error)


class DashboardState:
    """Samler all state i ett stabilt, skjerm-uavhengig JSON-format."""

    SCREENS = {"home", "cluster", "nerd"}

    def __init__(self, mock_mode: bool = False) -> None:
        self.monitor = SystemMonitor(mock_mode=mock_mode)
        self.nodes = NodeRegistry()
        self.demo = MonteCarloDemo()
        self.mock_mode = mock_mode
        self._screen = "home"
        self._lock = threading.Lock()

    def set_screen(self, screen: str | None) -> None:
        if screen not in self.SCREENS:
            allowed = ", ".join(sorted(self.SCREENS))
            raise ValueError(f"Ukjent skjerm. Velg en av: {allowed}")
        with self._lock:
            self._screen = screen

    def start_demo(self, iterations: int) -> bool:
        return self.demo.start(iterations)

    def register_node(self, payload: dict[str, Any], source_ip: str | None = None) -> dict[str, Any]:
        return self.nodes.heartbeat(payload, source_ip)

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now().astimezone()
        system = self.monitor.read()
        with self._lock:
            screen = self._screen

        nodes = [
            {
                "id": socket.gethostname(),
                "name": "Pi2" if self.mock_mode else socket.gethostname()[:12],
                "model": self.monitor.model_name(),
                "cpu": system["cpu"],
                "temp": system["temp"],
                "ram": system["ram"],
                "ip": system["ip"],
                "online": system["online"],
                "kind": "local",
                "mock": self.mock_mode,
                "last_seen_seconds": 0.0,
            }
        ]
        nodes.extend(self.nodes.snapshot(limit=3))

        demo = self.demo.snapshot()
        if demo["status"] == "running":
            message = "Beregner pi ..."
        elif demo["status"] == "finished":
            message = "Beregning fullført"
        else:
            message = "Ready"

        return {
            "protocol_version": 1,
            "screen": screen,
            "time": now.strftime("%H:%M:%S"),
            "timestamp": now.isoformat(timespec="seconds"),
            "nodes": nodes,
            "system": {
                "cpu": system["cpu"],
                "temp": system["temp"],
                "ram": system["ram"],
            },
            "network": {"online": system["online"], "ip": system["ip"]},
            "demo": demo,
            "message": message,
            "mock_mode": self.mock_mode,
            "backend": f"Python {sys.version_info.major}.{sys.version_info.minor}",
        }

    @staticmethod
    def protocol_example() -> dict[str, Any]:
        return {
            "protocol_version": 1,
            "screen": "home",
            "time": "12:34:56",
            "nodes": [
                {
                    "id": "pi2-main",
                    "name": "Pi2",
                    "model": "Raspberry Pi 2 Model B",
                    "cpu": 42.0,
                    "temp": 51.2,
                    "ram": 48.0,
                    "online": True,
                    "kind": "local",
                }
            ],
            "network": {"online": True, "ip": "192.0.2.42"},
            "demo": {"status": "idle", "progress": 0, "estimate": None, "runtime_seconds": 0},
            "message": "Ready",
        }
