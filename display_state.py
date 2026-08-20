"""Forretningslogikken: målinger, valgt skjerm og beregningsdemo."""

from __future__ import annotations

import math
import os
import random
import socket
import sys
import threading
import time
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


class MonteCarloDemo:
    """Bakgrunnsjobb som estimerer pi og rapporterer fremdrift underveis."""

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
        iterations = min(max(iterations, 10_000), 5_000_000)
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

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now().astimezone()
        system = self.monitor.read()
        with self._lock:
            screen = self._screen

        nodes = [
            {
                "name": "Pi2" if self.mock_mode else socket.gethostname()[:12],
                "cpu": system["cpu"],
                "temp": system["temp"],
                "ram": system["ram"],
                "online": system["online"],
                "mock": self.mock_mode,
            },
            {"name": "ESP-LAB", "cpu": 18.0, "temp": 43.8, "ram": 28.0, "online": True, "mock": True},
            {"name": "NAS-01", "cpu": 61.0, "temp": 48.3, "ram": 72.0, "online": True, "mock": True},
            {"name": "NODE-04", "cpu": 0.0, "temp": None, "ram": 0.0, "online": False, "mock": True},
        ]

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
            "nodes": [{"name": "Pi2", "cpu": 42.0, "temp": 51.2, "ram": 48.0, "online": True}],
            "network": {"online": True, "ip": "192.0.2.42"},
            "demo": {"status": "idle", "progress": 0, "estimate": None, "runtime_seconds": 0},
            "message": "Ready",
        }
