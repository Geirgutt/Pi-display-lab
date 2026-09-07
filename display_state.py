"""Forretningslogikken: målinger, noder og samlet dashboard-state."""

from __future__ import annotations

import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from training import TrainingProvider, load_training_provider

def decode_throttle_flags(flags: int, available: bool = True) -> dict[str, Any]:
    """Gjør Raspberry Pi-bitfeltet lesbart for API og grensesnitt."""

    active_labels = []
    history_labels = []
    if flags & (1 << 0):
        active_labels.append("UNDERVOLTAGE")
    if flags & (1 << 1):
        active_labels.append("FREKVENS BEGRENSET")
    if flags & (1 << 2):
        active_labels.append("STRUPING")
    if flags & (1 << 3):
        active_labels.append("TEMPERATURGRENSE")
    if flags & (1 << 16):
        history_labels.append("UNDERVOLTAGE")
    if flags & (1 << 17):
        history_labels.append("FREKVENS BEGRENSET")
    if flags & (1 << 18):
        history_labels.append("STRUPING")
    if flags & (1 << 19):
        history_labels.append("TEMPERATURGRENSE")

    if not available:
        summary = "STATUS UTILGJENGELIG"
    elif active_labels:
        summary = " · ".join(active_labels)
    elif history_labels:
        summary = f"TIDLIGERE: {' · '.join(history_labels)}"
    else:
        summary = "INGEN STRUPING"

    return {
        "flags": flags,
        "raw": f"0x{flags:x}",
        "available": available,
        "active": bool(active_labels),
        "occurred": bool(history_labels),
        "under_voltage": bool(flags & (1 << 0)),
        "frequency_capped": bool(flags & (1 << 1)),
        "throttled": bool(flags & (1 << 2)),
        "soft_temp_limit": bool(flags & (1 << 3)),
        "summary": summary,
    }


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
            "frequency_mhz": self._cpu_frequency_mhz(),
            "throttle": self._throttle_status(),
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
            "frequency_mhz": 1000.0 if wave > -0.2 else 600.0,
            "throttle": decode_throttle_flags(0),
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
    def _run_vcgencmd(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["vcgencmd", *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=1,
            )
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    @classmethod
    def _cpu_frequency_mhz(cls) -> float | None:
        paths = (
            Path("/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq"),
            Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"),
        )
        for path in paths:
            try:
                return round(float(path.read_text(encoding="utf-8").strip()) / 1000, 1)
            except (OSError, ValueError):
                continue

        output = cls._run_vcgencmd("measure_clock", "arm")
        match = re.fullmatch(r"frequency\(\d+\)=(\d+)", output or "")
        return round(int(match.group(1)) / 1_000_000, 1) if match else None

    @classmethod
    def _throttle_status(cls) -> dict[str, Any]:
        output = cls._run_vcgencmd("get_throttled")
        match = re.fullmatch(r"throttled=(0x[0-9a-fA-F]+)", output or "")
        return decode_throttle_flags(
            int(match.group(1), 16) if match else 0,
            available=match is not None,
        )

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
        raw_cores = payload.get("cores", 1)
        cores_number = self._number(raw_cores, "cores", 1, 256)
        if not cores_number.is_integer():
            raise ValueError("cores må være et heltall")
        cores = int(cores_number)
        raw_frequency = payload.get("frequency_mhz")
        frequency_mhz = (
            None
            if raw_frequency is None
            else self._number(raw_frequency, "frequency_mhz", 1, 10_000)
        )
        throttle_available = "throttle_flags" in payload
        raw_throttle_flags = payload.get("throttle_flags", 0)
        if isinstance(raw_throttle_flags, bool):
            raise ValueError("throttle_flags må være et heltall")
        try:
            throttle_flags = int(raw_throttle_flags)
        except (TypeError, ValueError) as error:
            raise ValueError("throttle_flags må være et heltall") from error
        if throttle_flags != raw_throttle_flags or not 0 <= throttle_flags <= 0xFFFFF:
            raise ValueError("throttle_flags er utenfor gyldig område")
        now = self._clock()

        node = {
            "id": node_id,
            "name": name,
            "model": model,
            "cpu": cpu,
            "temp": temp,
            "ram": ram,
            "cores": cores,
            "frequency_mhz": frequency_mhz,
            "throttle": decode_throttle_flags(throttle_flags, throttle_available),
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

    def snapshot(self, limit: int = MAX_REGISTERED_NODES) -> list[dict[str, Any]]:
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
            "cores": node["cores"],
            "frequency_mhz": node["frequency_mhz"],
            "throttle": dict(node["throttle"]),
            "ip": node["ip"],
            "online": age <= self.offline_after_seconds,
            "kind": node["kind"],
            "mock": node["mock"],
            "last_seen_seconds": round(age, 1),
        }


class DashboardState:
    """Samler all state i ett stabilt, skjerm-uavhengig JSON-format."""

    SCREENS = {"home", "cluster", "nerd", "training"}

    def __init__(self, mock_mode: bool = False, training_provider: TrainingProvider | None = None) -> None:
        self.monitor = SystemMonitor(mock_mode=mock_mode)
        self.nodes = NodeRegistry()
        self.training_provider = training_provider or load_training_provider(mock_mode)
        self.mock_mode = mock_mode
        self._screen = "home"
        self._lock = threading.Lock()

    def set_screen(self, screen: str | None) -> None:
        if screen not in self.SCREENS:
            allowed = ", ".join(sorted(self.SCREENS))
            raise ValueError(f"Ukjent skjerm. Velg en av: {allowed}")
        with self._lock:
            self._screen = screen

    def register_node(self, payload: dict[str, Any], source_ip: str | None = None) -> dict[str, Any]:
        return self.nodes.heartbeat(payload, source_ip)

    def cluster_capacity(self, reserve_one: bool = False) -> int:
        """Summer bare online compute-workers; controlleren er aldri med."""

        capacity = 0
        for node in self.nodes.snapshot():
            if node["online"]:
                cores = int(node.get("cores") or 0)
                capacity += max(0, cores - (1 if reserve_one else 0))
        return capacity

    def _cluster_demo(self, cluster_status: dict[str, Any] | None) -> dict[str, Any]:
        batches = list((cluster_status or {}).get("batches") or [])
        monte_batches = [batch for batch in batches if batch.get("job_type") == "monte_carlo"]
        batch = monte_batches[-1] if monte_batches else None
        if batch is None:
            return {
                "status": "idle", "progress": 0.0, "samples_done": 0,
                "iterations": 0, "estimate": None, "runtime_seconds": 0.0,
                "error": None, "inside": 0, "outside": 0, "points": [],
                "available_cores": self.cluster_capacity(), "requested_cores": 1,
                "worker_count": 1, "reserve_one": True, "batch_id": None,
            }
        samples = int(batch.get("samples") or 0)
        samples_done = int(batch.get("samples_done") or 0)
        inside = int(batch.get("inside") or 0)
        batch_status = str(batch.get("status") or "queued")
        status = {
            "queued": "running", "running": "running", "finished": "finished",
            "error": "error",
        }.get(batch_status, "error")
        return {
            "status": status,
            "progress": round(samples_done / samples * 100, 1) if samples else 0.0,
            "samples_done": samples_done,
            "iterations": samples,
            "estimate": batch.get("estimate"),
            "runtime_seconds": float(batch.get("runtime_seconds") or 0),
            "error": "En eller flere deljobber feilet" if batch.get("failed_jobs") else None,
            "inside": inside,
            "outside": samples_done - inside,
            "points": [list(point) for point in batch.get("points") or []],
            "available_cores": self.cluster_capacity(),
            "requested_cores": int(batch.get("slot_limit") or 1),
            "worker_count": int(batch.get("slot_limit") or 1),
            "reserve_one": bool(batch.get("reserve_one")),
            "batch_id": batch.get("batch_id"),
        }

    def snapshot(self, cluster_status: dict[str, Any] | None = None) -> dict[str, Any]:
        now = datetime.now().astimezone()
        system = self.monitor.read()
        demo = self._cluster_demo(cluster_status)
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
                "cores": max(os.cpu_count() or 1, 1),
                "frequency_mhz": system["frequency_mhz"],
                "throttle": system["throttle"],
                "ip": system["ip"],
                "online": system["online"],
                "kind": "local",
                "mock": self.mock_mode,
                "last_seen_seconds": 0.0,
            }
        ]
        nodes.extend(self.nodes.snapshot())

        cluster_payload = dict(cluster_status or {})
        cluster_payload["capacity"] = {
            "total_slots": self.cluster_capacity(False),
            "reserved_slots": self.cluster_capacity(True),
            "online_workers": sum(
                1 for node in nodes if node["kind"] == "remote" and node["online"]
            ),
        }

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
                "frequency_mhz": system["frequency_mhz"],
                "throttle": system["throttle"],
            },
            "network": {"online": system["online"], "ip": system["ip"]},
            "demo": demo,
            "cluster": cluster_payload
            if cluster_status is not None
            else {
                "enabled": False,
                "available": False,
                "status": "disabled",
                "queued": 0,
                "running": 0,
                "completed": 0,
                "queued_jobs": [],
                "running_jobs": [],
                "results": [],
            },
            "training": self.training_provider.snapshot(),
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
                    "cores": 4,
                    "frequency_mhz": 1000.0,
                    "throttle": decode_throttle_flags(0),
                    "online": True,
                    "kind": "local",
                }
            ],
            "network": {"online": True, "ip": "192.0.2.42"},
            "demo": {
                "status": "idle",
                "progress": 0,
                "estimate": None,
                "runtime_seconds": 0,
                "worker_count": 1,
                "points": [],
            },
            "cluster": {
                "enabled": True,
                "available": True,
                "status": "online",
                "queued": 2,
                "running": 1,
                "completed": 3,
                "queued_jobs": [],
                "running_jobs": [
                    {
                        "job_id": 4,
                        "job_type": "prime_count",
                        "worker": "worker-01",
                        "start": 300001,
                        "end": 400000,
                    }
                ],
                "results": [
                    {
                        "job_id": 3,
                        "job_type": "prime_count",
                        "worker": "worker-02",
                        "start": 200001,
                        "end": 300000,
                        "prime_count": 8013,
                    }
                ],
            },
            "training": {
                "available": True,
                "source": "mock",
                "updated_at": "2026-09-07T12:34:56+02:00",
                "today": {
                    "date": "2026-09-07",
                    "title": "Base Run",
                    "activity_type": "Run",
                    "duration_minutes": 42,
                    "distance_km": None,
                },
                "upcoming": [],
                "last_activity": None,
                "error": None,
            },
            "message": "Ready",
        }
