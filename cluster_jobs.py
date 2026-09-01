"""Trådsikker, felles jobbkø for Pi Display Lab-clusteret."""

from __future__ import annotations

import math
import random
import secrets
import threading
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


MAX_JOBS_PER_BATCH = 10_000
MAX_PENDING_JOBS = 20_000
MAX_RESULT_HISTORY = 10_000
MAX_STATUS_RESULTS = 20
MAX_STATUS_BATCHES = 50
MAX_BATCH_HISTORY = 100
MAX_PRIME_END = 1_000_000_000
MAX_PRIME_SPAN = 100_000_000
MAX_CHUNK_SIZE = 100_000_000
MAX_MONTE_CARLO_SAMPLES = 1_000_000_000
MIN_MONTE_CARLO_SAMPLES = 10_000
MAX_VISUAL_POINTS = 720
MAX_BATCH_SLOTS = 256


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


def validate_slot_limit(payload: dict[str, Any]) -> int:
    slot_limit = _integer(payload.get("slot_limit", 1), "slot_limit", minimum=1)
    if slot_limit > MAX_BATCH_SLOTS:
        raise ValueError(f"slot_limit kan maksimalt være {MAX_BATCH_SLOTS}")
    return slot_limit


def validate_reserve_one(payload: dict[str, Any]) -> bool:
    reserve_one = payload.get("reserve_one", False)
    if not isinstance(reserve_one, bool):
        raise ValueError("reserve_one må være true eller false")
    return reserve_one


def validate_prime_range(payload: dict[str, Any]) -> tuple[int, int, int]:
    start = _integer(payload.get("start"), "start")
    end = _integer(payload.get("end"), "end")
    chunk_size = _integer(payload.get("chunk_size"), "chunk_size", minimum=1)
    if end < start:
        raise ValueError("end må være større enn eller lik start")
    if end > MAX_PRIME_END:
        raise ValueError(f"end kan maksimalt være {MAX_PRIME_END}")
    span = end - start + 1
    if span > MAX_PRIME_SPAN:
        raise ValueError(f"Ett intervall kan maksimalt inneholde {MAX_PRIME_SPAN} tall")
    if chunk_size > MAX_CHUNK_SIZE:
        raise ValueError(f"chunk_size kan maksimalt være {MAX_CHUNK_SIZE}")
    job_count = math.ceil(span / chunk_size)
    if job_count > MAX_JOBS_PER_BATCH:
        raise ValueError(f"Jobben kan maksimalt deles i {MAX_JOBS_PER_BATCH} deler")
    return start, end, chunk_size


def validate_monte_carlo(payload: dict[str, Any]) -> tuple[int, int, int]:
    samples = _integer(payload.get("samples"), "samples", minimum=MIN_MONTE_CARLO_SAMPLES)
    if samples > MAX_MONTE_CARLO_SAMPLES:
        raise ValueError(f"samples kan maksimalt være {MAX_MONTE_CARLO_SAMPLES}")
    slot_limit = validate_slot_limit(payload)
    default_chunk = max(100_000, math.ceil(samples / max(slot_limit * 8, 1)))
    samples_per_job = _integer(
        payload.get("samples_per_job", default_chunk), "samples_per_job", minimum=1
    )
    samples_per_job = min(samples_per_job, samples)
    job_count = math.ceil(samples / samples_per_job)
    if job_count > MAX_JOBS_PER_BATCH:
        raise ValueError(f"Jobben kan maksimalt deles i {MAX_JOBS_PER_BATCH} deler")
    return samples, samples_per_job, slot_limit


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


def monte_carlo_batch(
    sample_count: int, seed: int, visual_count: int = 0
) -> tuple[int, list[list[float | int]]]:
    """Beregn én Monte Carlo-deljobb med en lokal, deterministisk RNG."""

    rng = random.Random(seed)
    inside_count = 0
    points: list[list[float | int]] = []
    for index in range(sample_count):
        x = rng.random() * 2 - 1
        y = rng.random() * 2 - 1
        inside = x * x + y * y <= 1
        inside_count += int(inside)
        if index < visual_count:
            points.append([round(x, 4), round(y, 4), int(inside)])
    return inside_count, points


class ClusterJobQueue:
    """Én autoritativ kø med batchvis kapasitetsbegrensning."""

    def __init__(self) -> None:
        self._queued: deque[dict[str, Any]] = deque()
        self._running: dict[int, dict[str, Any]] = {}
        self._results: list[dict[str, Any]] = []
        self._batches: dict[int, dict[str, Any]] = {}
        self._next_job_id = 1
        self._next_batch_id = 1
        self._lock = threading.Lock()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _new_batch(
        self, job_type: str, slot_limit: int, job_count: int, **fields: Any
    ) -> dict[str, Any]:
        while len(self._batches) >= MAX_BATCH_HISTORY:
            removable = next(
                (
                    batch_id
                    for batch_id, batch in self._batches.items()
                    if batch["status"] in {"finished", "error"}
                ),
                None,
            )
            if removable is None:
                break
            del self._batches[removable]
        batch_id = self._next_batch_id
        self._next_batch_id += 1
        batch = {
            "batch_id": batch_id,
            "job_type": job_type,
            "status": "queued",
            "slot_limit": slot_limit,
            "total_jobs": job_count,
            "queued_jobs": job_count,
            "running_jobs": 0,
            "completed_jobs": 0,
            "failed_jobs": 0,
            "created_at": self._now(),
            "runtime_seconds": 0.0,
            "_started_clock": time.monotonic(),
            **fields,
        }
        self._batches[batch_id] = batch
        return batch

    def _ensure_capacity(self, job_count: int) -> None:
        if len(self._queued) + len(self._running) + job_count > MAX_PENDING_JOBS:
            raise ValueError(
                f"Køen kan maksimalt ha {MAX_PENDING_JOBS} ventende og aktive jobber"
            )

    def enqueue_prime_range(self, payload: dict[str, Any]) -> list[int]:
        start, end, chunk_size = validate_prime_range(payload)
        slot_limit = validate_slot_limit(payload)
        reserve_one = validate_reserve_one(payload)
        job_count = math.ceil((end - start + 1) / chunk_size)
        created: list[int] = []
        with self._lock:
            self._ensure_capacity(job_count)
            batch = self._new_batch(
                "prime_count", slot_limit, job_count,
                start=start, end=end, chunk_size=chunk_size, prime_count=0,
                reserve_one=reserve_one,
            )
            chunk_start = start
            while chunk_start <= end:
                job_id = self._next_job_id
                self._next_job_id += 1
                chunk_end = min(chunk_start + chunk_size - 1, end)
                self._queued.append({
                    "job_id": job_id, "batch_id": batch["batch_id"],
                    "job_type": "prime_count", "start": chunk_start, "end": chunk_end,
                })
                created.append(job_id)
                chunk_start = chunk_end + 1
        return created

    def enqueue_monte_carlo(self, payload: dict[str, Any]) -> list[int]:
        samples, samples_per_job, slot_limit = validate_monte_carlo(payload)
        reserve_one = validate_reserve_one(payload)
        job_count = math.ceil(samples / samples_per_job)
        created: list[int] = []
        with self._lock:
            self._ensure_capacity(job_count)
            batch = self._new_batch(
                "monte_carlo", slot_limit, job_count,
                samples=samples, samples_done=0, inside=0, estimate=None, points=[],
                reserve_one=reserve_one,
            )
            remaining_samples = samples
            remaining_visuals = MAX_VISUAL_POINTS
            for _index in range(job_count):
                job_id = self._next_job_id
                self._next_job_id += 1
                job_samples = min(samples_per_job, remaining_samples)
                jobs_left = job_count - len(created)
                visual_count = min(
                    job_samples,
                    math.ceil(remaining_visuals / jobs_left) if jobs_left else 0,
                )
                remaining_samples -= job_samples
                remaining_visuals -= visual_count
                self._queued.append({
                    "job_id": job_id, "batch_id": batch["batch_id"],
                    "job_type": "monte_carlo", "samples": job_samples,
                    "seed": secrets.randbits(63), "visual_count": visual_count,
                })
                created.append(job_id)
        return created

    def batch_id_for_job(self, job_id: int) -> int | None:
        with self._lock:
            for job in (*self._queued, *self._running.values()):
                if job["job_id"] == job_id:
                    return int(job["batch_id"])
            for result in reversed(self._results):
                if result["job_id"] == job_id:
                    return int(result["batch_id"])
        return None

    def claim(self, worker: str) -> dict[str, Any] | None:
        worker = worker.strip() if isinstance(worker, str) else ""
        if not worker or len(worker) > 64 or not worker.isprintable():
            raise ValueError("worker må være et gyldig navn på maksimalt 64 tegn")
        with self._lock:
            selected_index = None
            for index, candidate in enumerate(self._queued):
                batch = self._batches[candidate["batch_id"]]
                if batch["running_jobs"] < batch["slot_limit"]:
                    selected_index = index
                    break
            if selected_index is None:
                return None
            job = self._queued[selected_index]
            del self._queued[selected_index]
            running = {**job, "worker": worker, "started_at": self._now()}
            self._running[job["job_id"]] = running
            batch = self._batches[job["batch_id"]]
            batch["queued_jobs"] -= 1
            batch["running_jobs"] += 1
            batch["status"] = "running"
            return deepcopy(job)

    @staticmethod
    def _validate_points(raw_points: Any, maximum: int) -> list[list[float | int]]:
        if raw_points is None:
            return []
        if not isinstance(raw_points, list) or len(raw_points) > maximum:
            raise ValueError("points inneholder for mange visualiseringspunkter")
        points: list[list[float | int]] = []
        for point in raw_points:
            if not isinstance(point, list) or len(point) != 3:
                raise ValueError("points har ugyldig format")
            try:
                x, y = float(point[0]), float(point[1])
                inside = int(point[2])
            except (TypeError, ValueError) as error:
                raise ValueError("points har ugyldig format") from error
            if not (-1 <= x <= 1 and -1 <= y <= 1 and inside in {0, 1}):
                raise ValueError("points har verdier utenfor gyldig område")
            points.append([round(x, 4), round(y, 4), inside])
        return points

    def record_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = _integer(payload.get("job_id"), "job_id", minimum=1)
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
            batch = self._batches[running["batch_id"]]
            error_message = payload.get("error")
            if error_message is not None:
                if not isinstance(error_message, str) or not error_message.strip():
                    raise ValueError("error må være en ikke-tom tekst")
                result = {
                    "job_id": job_id, "batch_id": running["batch_id"],
                    "job_type": running["job_type"], "worker": worker,
                    "status": "failed", "error": error_message.strip()[:300],
                    "completed_at": self._now(),
                }
                batch["failed_jobs"] += 1
            elif running["job_type"] == "prime_count":
                prime_count = _integer(payload.get("prime_count"), "prime_count")
                for field in ("start", "end"):
                    if _integer(payload.get(field), field) != running[field]:
                        raise ValueError(f"{field} samsvarer ikke med jobben")
                if prime_count > running["end"] - running["start"] + 1:
                    raise ValueError("prime_count kan ikke være større enn jobbintervallet")
                result = {
                    "job_id": job_id, "batch_id": running["batch_id"],
                    "job_type": running["job_type"], "worker": worker,
                    "status": "completed", "start": running["start"],
                    "end": running["end"], "prime_count": prime_count,
                    "completed_at": self._now(),
                }
                batch["completed_jobs"] += 1
                batch["prime_count"] += prime_count
            elif running["job_type"] == "monte_carlo":
                samples = _integer(payload.get("samples"), "samples", minimum=1)
                inside = _integer(payload.get("inside"), "inside")
                if samples != running["samples"]:
                    raise ValueError("samples samsvarer ikke med jobben")
                if inside > samples:
                    raise ValueError("inside kan ikke være større enn samples")
                points = self._validate_points(payload.get("points", []), running["visual_count"])
                result = {
                    "job_id": job_id, "batch_id": running["batch_id"],
                    "job_type": running["job_type"], "worker": worker,
                    "status": "completed", "samples": samples, "inside": inside,
                    "completed_at": self._now(),
                }
                batch["completed_jobs"] += 1
                batch["samples_done"] += samples
                batch["inside"] += inside
                batch["estimate"] = round(4 * batch["inside"] / batch["samples_done"], 8)
                remaining = MAX_VISUAL_POINTS - len(batch["points"])
                batch["points"].extend(points[:remaining])
            else:
                raise ValueError("Ukjent jobbtype")

            del self._running[job_id]
            batch["running_jobs"] -= 1
            finished_jobs = batch["completed_jobs"] + batch["failed_jobs"]
            if finished_jobs == batch["total_jobs"]:
                batch["status"] = "error" if batch["failed_jobs"] else "finished"
                batch["runtime_seconds"] = round(time.monotonic() - batch["_started_clock"], 2)
                batch["completed_at"] = self._now()
            self._results.append(result)
            if len(self._results) > MAX_RESULT_HISTORY:
                del self._results[: len(self._results) - MAX_RESULT_HISTORY]
            return deepcopy(result)

    @staticmethod
    def _public_batch(batch: dict[str, Any]) -> dict[str, Any]:
        public = {
            key: deepcopy(value) for key, value in batch.items() if not key.startswith("_")
        }
        if batch["status"] in {"queued", "running"}:
            public["runtime_seconds"] = round(time.monotonic() - batch["_started_clock"], 2)
        return public

    def status(self) -> dict[str, Any]:
        with self._lock:
            failed = sum(1 for result in self._results if result["status"] == "failed")
            return {
                "queued": len(self._queued),
                "running": len(self._running),
                "completed": len(self._results) - failed,
                "failed": failed,
                "queued_jobs": [deepcopy(job) for job in list(self._queued)[:20]],
                "running_jobs": [deepcopy(job) for job in self._running.values()],
                "results": deepcopy(self._results[-MAX_STATUS_RESULTS:]),
                "batches": [
                    self._public_batch(batch)
                    for batch in sorted(
                        self._batches.values(), key=lambda item: item["batch_id"]
                    )[-MAX_STATUS_BATCHES:]
                ],
            }
