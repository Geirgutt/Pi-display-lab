"""Oppdater OS-pakker på registrerte workers fra controlleren."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cluster_install import MAX_FORKS, PasswordBroker, collect_passwords, select_workers
from config import AppConfig, ConfigValidationError, validate_controller_config

PROJECT_DIR = Path(__file__).resolve().parent


def run_maintenance(settings: AppConfig, workers: list[str], upgrade: bool) -> int:
    workers = select_workers(settings.worker_hosts, workers, False)
    if not workers:
        raise RuntimeError("Ingen workers er konfigurert.")
    bundled = PROJECT_DIR / ".ansible-venv/bin/ansible-playbook"
    ansible = str(bundled) if bundled.is_file() else shutil.which("ansible-playbook")
    if not ansible:
        raise RuntimeError("Ansible mangler. Kjør bash scripts/setup-cluster.sh først.")

    action = "Oppgraderer OS-pakker" if upgrade else "Oppdaterer pakkelister"
    print(f"{action} på: {', '.join(workers)}", flush=True)
    passwords = collect_passwords(
        settings.ssh_user, workers, identity_file=settings.ssh_identity_file,
    )
    # Only inventory and public connection settings go on disk. Sudo passwords
    # stay in memory and are served through the existing private socket broker.
    with tempfile.TemporaryDirectory(prefix="pi-maintenance-") as directory:
        temp_dir = Path(directory)
        os.chmod(temp_dir, 0o700)
        inventory = temp_dir / "inventory.ini"
        inventory.write_text(
            "[cluster_workers]\n" + "\n".join(workers) + "\n", encoding="utf-8",
        )
        variables = {
            "ansible_user": settings.ssh_user,
            "ansible_connection": "ansible.builtin.ssh",
            "ansible_python_interpreter": "/usr/bin/python3",
            "ansible_ssh_common_args": "-o StrictHostKeyChecking=yes",
            "maintenance_upgrade": upgrade,
        }
        if settings.ssh_identity_file:
            variables["ansible_ssh_private_key_file"] = settings.ssh_identity_file
            variables["ansible_ssh_common_args"] += " -o IdentitiesOnly=yes"
        vars_file = temp_dir / "vars.json"
        vars_file.write_text(json.dumps(variables, indent=2) + "\n", encoding="utf-8")
        os.chmod(inventory, 0o600)
        os.chmod(vars_file, 0o600)
        with PasswordBroker(temp_dir / "worker-sudo.sock", passwords) as broker:
            result = subprocess.run(
                [ansible, "-i", str(inventory), "ansible/maintain-workers.yml",
                 "--forks", str(min(MAX_FORKS, len(workers))),
                 "--extra-vars", "@" + str(vars_file),
                 "--extra-vars", json.dumps({"worker_sudo_socket": str(broker.path)})],
                cwd=PROJECT_DIR, stdin=subprocess.DEVNULL,
            )
    if result.returncode:
        print("Vedlikeholdet feilet. Se resultatet per node i Ansible-oppsummeringen.", file=sys.stderr)
    else:
        print("Vedlikehold fullført. Se omstartsstatus per node over.", flush=True)
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_DIR / "config.local.json")
    parser.add_argument("--upgrade", action="store_true",
                        help="Oppdater pakkelister og kjør vanlig apt-get upgrade.")
    parser.add_argument("--worker", action="append", default=[], metavar="HOST",
                        help="Velg en registrert worker. Kan gjentas. Standard: alle workers.")
    args = parser.parse_args(argv)
    try:
        settings = validate_controller_config(args.config)
        workers = select_workers(settings.worker_hosts, args.worker, False)
        if not workers:
            raise RuntimeError("Ingen workers er konfigurert.")
        return run_maintenance(settings, workers, args.upgrade)
    except (ConfigValidationError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nVedlikeholdet ble avbrutt. Kontroller nodestatus før ny kjøring.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
