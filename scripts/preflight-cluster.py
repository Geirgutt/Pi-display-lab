#!/usr/bin/env python3
"""Kontroller config, SSH, host keys og worker-forutsetninger før utrulling."""

from __future__ import annotations

import argparse
import json
import os
import socket
import shlex
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from cluster_bootstrap import inspect_worker, known_host, parallel, ansible_target_python_limit, check_worker_python
from cluster_ssh import ssh_run, require_ssh
from cluster_auth import valid_worker_id  # noqa: E402
from config import ConfigValidationError, validate_controller_config  # noqa: E402


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

    highest_python_minor = ansible_target_python_limit(PROJECT_DIR)

    def check(host):
        if not known_host(host):
            raise RuntimeError("SSH-vertsnøkkel er ikke godkjent. Kjør bash scripts/setup-cluster.sh.")
        node = inspect_worker(settings.ssh_user, host, settings.ssh_identity_file)
        identity = valid_worker_id(node["hostname"])
        if not identity:
            raise RuntimeError("Worker-hostname er ugyldig")
        check_worker_python(settings.ssh_user, host, settings.ssh_identity_file, highest_python_minor)
        result = ssh_run(settings.ssh_user, host, "getent ahosts "
                         + shlex.quote(settings.controller_host), identity_file=settings.ssh_identity_file)
        require_ssh(result, host)
        return identity

    try:
        checked = parallel(list(settings.worker_hosts), check, "Kontrollerer SSH, Python og controller-oppslag")
    except RuntimeError as error:
        raise SystemExit(f"Preflight stoppet: {error}") from None
    identities = {host: checked[host] for host in settings.worker_hosts}

    if len(set(identities.values())) != len(identities):
        raise SystemExit("Preflight stoppet: flere workers rapporterer samme hostname")
    output = Path(args.output)
    output.write_text(json.dumps(identities, indent=2) + "\n", encoding="utf-8")
    os.chmod(output, 0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
