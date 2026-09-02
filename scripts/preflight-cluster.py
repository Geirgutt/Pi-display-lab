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
                f"SSH-nøkkel på workeren først med: ssh-copy-id {user}@{host}"
            )
        else:
            detail = "SSH-kommandoen feilet eller brukte for lang tid."
        raise RuntimeError(f"{host}: {detail}") from error
    return result.stdout.strip()


def _known_host(host: str) -> bool:
    try:
        result = subprocess.run(
            ["ssh-keygen", "-F", host],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


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
        print(f"\nTester {host} ...", flush=True)
        try:
            socket.getaddrinfo(host, 22)
            print("✓ DNS/IP kan nås", flush=True)
            if not _known_host(host):
                raise RuntimeError(
                    f"{host}: SSH host key er ikke godkjent. Kjør først:\n\n"
                    f"ssh {settings.ssh_user}@{host}\n\n"
                    "Kontroller fingerprint og svar yes hvis den er riktig."
                )
            print("✓ SSH host key er godkjent", flush=True)
            identity = valid_worker_id(_ssh(settings.ssh_user, host, "hostname"))
            if not identity:
                raise RuntimeError(f"{host}: hostname er tomt eller ugyldig")
            print("✓ SSH-nøkkel fungerer", flush=True)
            print(f"✓ Hostname: {identity}", flush=True)
            _ssh(settings.ssh_user, host, "command", "-v", "python3")
            print("✓ Python finnes", flush=True)
            _ssh(settings.ssh_user, host, "command", "-v", "sudo")
            print("✓ sudo finnes", flush=True)
            _ssh(settings.ssh_user, host, "command", "-v", "apt-get")
            print("✓ apt-get finnes", flush=True)
            _ssh(
                settings.ssh_user,
                host,
                "getent",
                "ahosts",
                settings.controller_host,
            )
            print("✓ Controller-adressen kan slås opp fra workeren", flush=True)
        except socket.gaierror as error:
            raise SystemExit(
                f"Preflight stoppet før workerne ble endret: {host} kan ikke slås opp"
            ) from error
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
