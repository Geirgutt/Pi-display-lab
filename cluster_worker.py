"""Worker som henter primtallsjobber fra coordinatoren."""

from __future__ import annotations

import argparse
import secrets
import socket
import sys
import time

from cluster_auth import load_cluster_credentials
from cluster_client import ClusterCoordinatorClient, CoordinatorUnavailable
from cluster_jobs import count_primes
from config import load_config


def process_one_job(client: ClusterCoordinatorClient, worker_name: str) -> bool:
    job = client.claim_job(worker_name)
    if job is None:
        return False
    if job.get("job_type") != "prime_count":
        raise ValueError(f"Ukjent jobbtype: {job.get('job_type')}")

    start = int(job["start"])
    end = int(job["end"])
    result = {
        "job_id": int(job["job_id"]),
        "worker": worker_name,
        "start": start,
        "end": end,
        "prime_count": count_primes(start, end),
    }
    client.submit_result(result)
    return True


def main() -> int:
    settings = load_config()
    parser = argparse.ArgumentParser(description="Pi Display Lab cluster worker")
    parser.add_argument("--once", action="store_true", help="kjør én poll og avslutt")
    args = parser.parse_args()

    if not settings.cluster.enabled:
        print("Cluster er deaktivert i config.local.json", file=sys.stderr)
        return 2

    worker_name = socket.gethostname()
    credentials = load_cluster_credentials(settings.cluster.credentials_file)
    if not credentials.worker_id or not credentials.worker_token:
        print("Worker-credential mangler eller er ugyldig", file=sys.stderr)
        return 2
    if not secrets.compare_digest(credentials.worker_id, worker_name):
        print(
            "Worker-credential tilhører ikke denne maskinens hostname",
            file=sys.stderr,
        )
        return 2
    client = ClusterCoordinatorClient(
        settings.cluster,
        bearer_token=credentials.worker_token,
    )
    interval = settings.cluster.poll_interval_seconds
    last_error = ""
    print(f"Worker {worker_name} henter jobber fra {settings.cluster.coordinator_url}")

    while True:
        try:
            processed = process_one_job(client, worker_name)
            if last_error:
                print("Forbindelsen til coordinatoren er gjenopprettet")
                last_error = ""
            if not processed:
                time.sleep(interval)
        except (CoordinatorUnavailable, OSError, RuntimeError, TypeError, ValueError) as error:
            message = str(error)
            if message != last_error:
                print(f"Worker-feil: {message}", file=sys.stderr)
                last_error = message
            time.sleep(interval)

        if args.once:
            return 1 if last_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
