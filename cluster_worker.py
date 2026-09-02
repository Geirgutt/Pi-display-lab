"""Flerkjernet worker som trekker jobber fra én autoritativ coordinator-kø."""

from __future__ import annotations

import argparse
import os
import secrets
import signal
import socket
import sys
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from typing import Any, Callable

from cluster_auth import load_cluster_credentials
from cluster_client import (
    ClusterCoordinatorClient,
    CoordinatorAuthenticationError,
    CoordinatorUnavailable,
)
from cluster_jobs import count_primes, monte_carlo_batch
from config import load_config


def compute_job(job: dict[str, Any]) -> dict[str, Any]:
    """Kjør bare CPU-arbeidet. Denne funksjonen utføres i en child process."""

    job_id = int(job["job_id"])
    job_type = job.get("job_type")
    common = {"job_id": job_id}
    if job_type == "prime_count":
        start = int(job["start"])
        end = int(job["end"])
        return {
            **common,
            "start": start,
            "end": end,
            "prime_count": count_primes(start, end),
        }
    if job_type == "monte_carlo":
        samples = int(job["samples"])
        inside, points = monte_carlo_batch(
            samples,
            int(job["seed"]),
            int(job.get("visual_count", 0)),
        )
        return {
            **common,
            "samples": samples,
            "inside": inside,
            "points": points,
        }
    raise ValueError(f"Ukjent jobbtype: {job_type}")


def process_one_job(client: ClusterCoordinatorClient, worker_name: str) -> bool:
    """Bakoverkompatibel én-jobb-hjelper, også nyttig i små tester."""

    job = client.claim_job(worker_name)
    if job is None:
        return False
    client.submit_result({**compute_job(job), "worker": worker_name})
    return True


def _failed_result(job: dict[str, Any], worker_name: str, error: BaseException) -> dict[str, Any]:
    return {
        "job_id": int(job["job_id"]),
        "worker": worker_name,
        "error": f"{type(error).__name__}: {error}",
    }


def run_worker(
    client: ClusterCoordinatorClient,
    worker_name: str,
    slots: int,
    poll_interval: float,
    *,
    once: bool = False,
    executor_factory: Callable[..., Any] = ProcessPoolExecutor,
    stop_event: threading.Event | None = None,
) -> int:
    """Hold slottene fulle uten busy-loop og lever alle resultater fra parent process."""

    pending: dict[Future[dict[str, Any]], dict[str, Any]] = {}
    ready: deque[dict[str, Any]] = deque()
    initial_fill_done = False
    slots = max(1, slots)

    with executor_factory(max_workers=slots) as executor:
        while True:
            made_progress = False

            # Et ferdig resultat beholder sloten til coordinatoren har kvittert.
            while ready:
                try:
                    client.submit_result(ready[0])
                except CoordinatorAuthenticationError:
                    raise
                except CoordinatorUnavailable:
                    time.sleep(poll_interval)
                    break
                ready.popleft()
                made_progress = True

            done = {future for future in pending if future.done()}
            for future in done:
                job = pending.pop(future)
                try:
                    result = future.result()
                    ready.append({**result, "worker": worker_name})
                except Exception as error:  # Én ødelagt deljobb skal ikke stoppe tjenesten.
                    ready.append(_failed_result(job, worker_name, error))
                made_progress = True

            stopping = stop_event is not None and stop_event.is_set()
            can_claim = not stopping and not (once and initial_fill_done)
            claim_failed = False
            while can_claim and len(pending) + len(ready) < slots:
                try:
                    job = client.claim_job(worker_name)
                except CoordinatorAuthenticationError:
                    raise
                except CoordinatorUnavailable:
                    time.sleep(poll_interval)
                    claim_failed = True
                    break
                if job is None:
                    break
                pending[executor.submit(compute_job, job)] = job
                made_progress = True
            if not claim_failed:
                initial_fill_done = True

            if once and claim_failed and not pending and not ready:
                return 1

            if once and not pending and not ready:
                return 0
            if stopping and not pending and not ready:
                return 0

            if ready:
                continue
            if pending and not made_progress:
                wait(tuple(pending), timeout=poll_interval, return_when=FIRST_COMPLETED)
            elif not made_progress:
                time.sleep(poll_interval)


def main() -> int:
    settings = load_config()
    default_slots = settings.cluster.worker_slots or max(os.cpu_count() or 1, 1)
    parser = argparse.ArgumentParser(description="Pi Display Lab cluster worker")
    parser.add_argument("--once", action="store_true", help="fyll slottene én gang og avslutt")
    parser.add_argument(
        "--slots",
        type=int,
        default=default_slots,
        help="lokale compute-slots (standard: config eller antall CPU-kjerner)",
    )
    args = parser.parse_args()

    if not settings.cluster.enabled:
        print("Cluster er deaktivert i config.local.json", file=sys.stderr)
        return 2
    if not 1 <= args.slots <= max(os.cpu_count() or 1, 1):
        print("--slots må være mellom 1 og antall lokale CPU-kjerner", file=sys.stderr)
        return 2

    worker_name = socket.gethostname()
    credentials = load_cluster_credentials(settings.cluster.credentials_file)
    if not credentials.worker_id or not credentials.worker_token:
        print("Worker-credential mangler eller er ugyldig", file=sys.stderr)
        return 2
    if not secrets.compare_digest(credentials.worker_id, worker_name):
        print("Worker-credential tilhører ikke denne maskinens hostname", file=sys.stderr)
        return 2
    client = ClusterCoordinatorClient(
        settings.cluster,
        bearer_token=credentials.worker_token,
    )
    interval = settings.cluster.poll_interval_seconds
    print(
        f"Worker {worker_name} bruker {args.slots} slot(er) mot "
        f"{settings.cluster.coordinator_url}"
    )
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        if not stop_event.is_set():
            print("Worker avslutter etter aktive deljobber")
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    while True:
        try:
            return run_worker(
                client,
                worker_name,
                args.slots,
                interval,
                once=args.once,
                stop_event=stop_event,
            )
        except (CoordinatorUnavailable, OSError, RuntimeError, TypeError, ValueError) as error:
            print(f"Worker-feil: {error}", file=sys.stderr)
            if args.once:
                return 1
            time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
