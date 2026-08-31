"""Trådsikker in-memory jobbkø for den første cluster-prototypen."""

from __future__ import annotations

import math
import threading
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


MAX_JOBS_PER_BATCH = 10_000


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} må være et heltall")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} må være et heltall") from error
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field} må være et heltall")
    if number < minimum:
        raise ValueError(f"{field} må være minst {minimum}")
    return number


def validate_prime_range(payload: dict[str, Any]) -> tuple[int, int, int]:
    start = _integer(payload.get("start"), "start")
    end = _integer(payload.get("end"), "end")
    chunk_size = _integer(payload.get("chunk_size"), "chunk_size", minimum=1)
    if end < start:
        raise ValueError("end må være større enn eller lik start")
    job_count = math.ceil((end - start + 1) / chunk_size)
    if job_count > MAX_JOBS_PER_BATCH:
        raise ValueError(f"Jobben kan maksimalt deles i {MAX_JOBS_PER_BATCH} deler")
    return start, end, chunk_size


def count_primes(start: int, end: int) -> int:
    """Tell primtall i et inklusivt intervall uten tredjepartsbiblioteker."""

    total = 0
    for candidate in range(max(start, 2), end + 1):
        limit = math.isqrt(candidate)
        is_prime = True
        for divisor in range(2, limit + 1):
            if candidate % divisor == 0:
                is_prime = False
                break
        if is_prime:
            total += 1
    return total


class ClusterJobQueue:
    """Holder kø, aktive jobber og resultathistorikk i minnet."""

    def __init__(self) -> None:
        self._queued: deque[dict[str, Any]] = deque()
        self._running: dict[int, dict[str, Any]] = {}
        self._results: list[dict[str, Any]] = []
        self._next_job_id = 1
        self._lock = threading.Lock()

    def enqueue_prime_range(self, payload: dict[str, Any]) -> list[int]:
        start, end, chunk_size = validate_prime_range(payload)
        created: list[int] = []
        with self._lock:
            chunk_start = start
            while chunk_start <= end:
                job_id = self._next_job_id
                self._next_job_id += 1
                chunk_end = min(chunk_start + chunk_size - 1, end)
                self._queued.append(
                    {
                        "job_id": job_id,
                        "job_type": "prime_count",
                        "start": chunk_start,
                        "end": chunk_end,
                    }
                )
                created.append(job_id)
                chunk_start = chunk_end + 1
        return created

    def claim(self, worker: str) -> dict[str, Any] | None:
        worker = worker.strip() if isinstance(worker, str) else ""
        if not worker or len(worker) > 64 or not worker.isprintable():
            raise ValueError("worker må være et gyldig navn på maksimalt 64 tegn")
        with self._lock:
            if not self._queued:
                return None
            job = self._queued.popleft()
            running = {
                **job,
                "worker": worker,
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._running[job["job_id"]] = running
            return deepcopy(job)

    def record_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = _integer(payload.get("job_id"), "job_id", minimum=1)
        prime_count = _integer(payload.get("prime_count"), "prime_count")
        worker = payload.get("worker")
        if not isinstance(worker, str) or not worker.strip() or len(worker.strip()) > 64:
            raise ValueError("worker må være et gyldig navn på maksimalt 64 tegn")
        worker = worker.strip()

        with self._lock:
            running = self._running.get(job_id)
            if running is None:
                raise ValueError("job_id er ikke registrert som kjørende")
            if worker != running["worker"]:
                raise ValueError("resultatet kommer fra feil worker")
            for field in ("start", "end"):
                if _integer(payload.get(field), field) != running[field]:
                    raise ValueError(f"{field} samsvarer ikke med jobben")

            result = {
                "job_id": job_id,
                "job_type": running["job_type"],
                "worker": worker,
                "start": running["start"],
                "end": running["end"],
                "prime_count": prime_count,
                "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            del self._running[job_id]
            self._results.append(result)
            return deepcopy(result)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "queued": len(self._queued),
                "running": len(self._running),
                "completed": len(self._results),
                "queued_jobs": [deepcopy(job) for job in list(self._queued)[:20]],
                "running_jobs": [deepcopy(job) for job in self._running.values()],
                "results": deepcopy(self._results),
            }
