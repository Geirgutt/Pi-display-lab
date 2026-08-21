"""Lettvektsagent som sender Raspberry Pi-målinger til cluster-visningen."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from display_state import SystemMonitor


def build_payload(monitor: SystemMonitor, name: str) -> dict[str, Any]:
    values = monitor.read()
    return {
        "node_id": socket.gethostname(),
        "name": name,
        "model": monitor.model_name(),
        "cpu": values["cpu"],
        "temp": values["temp"],
        "ram": values["ram"],
        "cores": max(os.cpu_count() or 1, 1),
    }


def send_heartbeat(server: str, payload: dict[str, Any], token: str = "") -> None:
    endpoint = f"{server.rstrip('/')}/api/nodes/heartbeat"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Node-Token"] = token
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        if response.status != 202:
            raise RuntimeError(f"Uventet svar fra serveren: HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send systemstatus til Pi Display Lab")
    parser.add_argument("--server", required=True, help="URL til hoved-Pi-en, f.eks. http://192.0.2.42:5000")
    parser.add_argument("--name", default=socket.gethostname()[:24], help="navn som vises i clusteret")
    parser.add_argument("--interval", type=float, default=5.0, help="sekunder mellom heartbeats")
    parser.add_argument("--once", action="store_true", help="send én heartbeat og avslutt")
    args = parser.parse_args()

    interval = max(args.interval, 1.0)
    token = os.getenv("PI_DISPLAY_NODE_TOKEN", "")
    monitor = SystemMonitor(mock_mode=False)
    last_error = ""
    print(f"Sender {args.name} til {args.server} hvert {interval:g}. sekund")

    while True:
        try:
            payload = build_payload(monitor, args.name)
            send_heartbeat(args.server, payload, token)
            if last_error:
                print("Forbindelsen til hoved-Pi-en er gjenopprettet")
                last_error = ""
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as error:
            message = str(error)
            if message != last_error:
                print(f"Heartbeat feilet: {message}", file=sys.stderr)
                last_error = message

        if args.once:
            return 1 if last_error else 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
