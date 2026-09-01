#!/usr/bin/env python3
"""Kontroller config, SSH, host keys og worker-forutsetninger før utrulling."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from cluster_auth import valid_worker_id  # noqa: E402
from config import ConfigValidationError, validate_controller_config  # noqa: E402


def _ssh_target(user: str, host: str) -> str:
    return f"{user}@[{host}]" if ":" in host else f"{user}@{host}"


def _ssh(user: str, host: str, *remote_command: str) -> str:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "LogLevel=ERROR",
        _ssh_target(user, host),
        *remote_command,
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as error:
        raise RuntimeError("Fant ikke ssh-klienten på controlleren") from error
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        stderr = getattr(error, "stderr", "") or ""
        if "Host key verification failed" in stderr or "IDENTIFICATION HAS CHANGED" in stderr:
            detail = (
                "SSH host key er ikke godkjent. Koble manuelt til workeren, "
                "kontroller fingerprint og godkjenn riktig nøkkel før du prøver igjen."
            )
        elif "Permission denied" in stderr:
            detail = (
                "SSH-nøkkelen ble avvist. Installer controller-brukerens offentlige "
                "SSH-nøkkel på workeren først."
            )
        else:
            detail = "SSH-kommandoen feilet eller brukte for lang tid."
        raise RuntimeError(f"{host}: {detail}") from error
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("output")
    args = parser.parse_args()
    try:
        settings = validate_controller_config(args.config)
    except ConfigValidationError as error:
        raise SystemExit(str(error)) from error

    try:
        socket.getaddrinfo(settings.controller_host, settings.app_port)
    except socket.gaierror as error:
        raise SystemExit(
            f"controller_host kan ikke slås opp lokalt: {settings.controller_host}"
        ) from error

    identities: dict[str, str] = {}
    for host in settings.worker_hosts:
        try:
            identity = valid_worker_id(_ssh(settings.ssh_user, host, "hostname"))
            if not identity:
                raise RuntimeError(f"{host}: hostname er tomt eller ugyldig")
            _ssh(settings.ssh_user, host, "command", "-v", "python3")
            _ssh(settings.ssh_user, host, "command", "-v", "sudo")
            _ssh(settings.ssh_user, host, "command", "-v", "apt-get")
            _ssh(
                settings.ssh_user,
                host,
                "getent",
                "hosts",
                settings.controller_host,
            )
        except RuntimeError as error:
            raise SystemExit(f"Preflight stoppet før workerne ble endret: {error}") from error
        identities[host] = identity

    if len(set(identities.values())) != len(identities):
        raise SystemExit("Preflight stoppet: flere workers rapporterer samme hostname")
    output = Path(args.output)
    output.write_text(json.dumps(identities, indent=2) + "\n", encoding="utf-8")
    os.chmod(output, 0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
