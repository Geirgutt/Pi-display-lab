"""Collect worker sudo credentials up front and orchestrate parallel installation."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import socketserver
import subprocess
import sys
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from config import ConfigValidationError, validate_controller_config

PROJECT_DIR = Path(__file__).resolve().parent
MAX_FORKS = 10


def select_workers(configured: tuple[str, ...], limits: list[str], controller_only: bool) -> list[str]:
    unknown = set(limits) - set(configured)
    if unknown:
        raise RuntimeError("Ukjent worker: " + ", ".join(sorted(unknown)))
    if controller_only:
        return []
    return [host for host in configured if not limits or host in limits]


def check_sudo(user: str, host: str, password: str | None = None) -> bool:
    # -k prevents an old SSH sudo timestamp from hiding a required password.
    remote = "sudo -k -n /usr/bin/true" if password is None else "sudo -k -S -p '' /usr/bin/true"
    command = [
        "ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=8", "-o", "LogLevel=ERROR", f"{user}@{host}", remote,
    ]
    try:
        result = subprocess.run(
            command, input="" if password is None else password + "\n",
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Never include subprocess input/output in errors involving passwords.
        raise RuntimeError(f"{host}: SSH/sudo-kontrollen kunne ikke fullføres.") from None
    if result.returncode == 255:
        raise RuntimeError(f"{host}: SSH feilet. Kontroller nøkkelinnlogging og godkjent host key.")
    return result.returncode == 0


def read_password(prompt: str) -> str:
    # getpass otherwise falls back to echoed stdin when no terminal is present.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            password = getpass.getpass(prompt)
        except (getpass.GetPassWarning, EOFError):
            raise RuntimeError("Passord krever en interaktiv terminal. Kjør skriptet over SSH.") from None
    if "\n" in password or "\r" in password or "\0" in password:
        raise RuntimeError("Sudo-passordet kan ikke inneholde linjeskift eller NUL.")
    return password


def collect_passwords(user: str, workers: list[str]) -> dict[str, str]:
    if not workers:
        return {}
    print("Kontrollerer sudo på valgte workers ...", flush=True)
    with ThreadPoolExecutor(max_workers=min(MAX_FORKS, len(workers))) as pool:
        passwordless = list(pool.map(lambda host: check_sudo(user, host), workers))
    needed = [host for host, ready in zip(workers, passwordless) if not ready]
    passwords = {host: "" for host, ready in zip(workers, passwordless) if ready}
    if not needed:
        return passwords

    print("Sudo-passord brukes bare under denne kjøringen og lagres ikke.", flush=True)
    shared = False
    if len(needed) > 1:
        while True:
            answer = input("Bruke samme sudo-passord på alle workers som trenger passord? [J/n]: ").strip().lower()
            if answer in ("", "j", "ja", "y", "yes", "n", "nei", "no"):
                shared = answer not in ("n", "nei", "no")
                break
    if shared:
        password = read_password("Felles sudo-passord for workerne: ")
        with ThreadPoolExecutor(max_workers=min(MAX_FORKS, len(needed))) as pool:
            accepted = list(pool.map(lambda host: check_sudo(user, host, password), needed))
        for host, valid in zip(needed, accepted):
            if valid:
                passwords[host] = password
            else:
                print(f"{host}: felles passord ble avvist; oppgi passordet for denne workeren.", flush=True)

    for host in needed:
        if host in passwords:
            continue
        for attempt in range(3):
            password = read_password(f"Sudo-passord for {host}: ")
            if check_sudo(user, host, password):
                passwords[host] = password
                break
            print(f"{host}: sudo avvist ({attempt + 1}/3).", flush=True)
        else:
            raise RuntimeError(f"{host}: sudo-kontrollen feilet. Ingen installasjon ble startet.")
    return passwords


class PasswordBroker:
    """Serve credentials from memory through a private local Unix socket."""

    def __init__(self, path: Path, passwords: dict[str, str]):
        self.path = path
        self.passwords = passwords

    def __enter__(self):
        passwords = self.passwords

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(5)
                try:
                    host = json.loads(self.rfile.readline(1024))
                    if not isinstance(host, str) or host not in passwords:
                        response = {"error": "Unknown worker"}
                    else:
                        response = {"password": passwords[host]}
                    self.wfile.write(json.dumps(response).encode("utf-8") + b"\n")
                except (OSError, ValueError):
                    pass

        # The parent installer creates the socket's directory with mode 0700.
        self.server = socketserver.UnixStreamServer(str(self.path), Handler)
        os.chmod(self.path, 0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.path.unlink(missing_ok=True)


def install(config: str, temp_dir: str, revision: str, workers: list[str], user: str, regenerate: bool) -> int:
    passwords = collect_passwords(user, workers)
    print("Passordkontrollen er ferdig. Installerer controlleren ...", flush=True)
    controller = ["bash", "scripts/install-cluster-controller.sh", config, temp_dir, revision]
    if regenerate:
        controller.append("--regenerate-server-cert")
    result = subprocess.run(controller, cwd=PROJECT_DIR, stdin=subprocess.DEVNULL)
    if result.returncode:
        return result.returncode
    if not workers:
        return 0

    forks = min(MAX_FORKS, len(workers))
    print(f"Installerer {len(workers)} workers, inntil {forks} samtidig, til commit {revision} ...", flush=True)
    command = [
        "ansible-playbook", "-i", str(Path(temp_dir) / "inventory.ini"),
        "ansible/install-workers.yml", "--limit", ",".join(workers), "--forks", str(forks),
        "--extra-vars", "@" + str(Path(temp_dir) / "vars.json"),
        "--extra-vars", "@" + str(Path(temp_dir) / "worker-secrets.json"),
    ]
    # Only the socket path is passed to Ansible; passwords stay in this process.
    with PasswordBroker(Path(temp_dir) / "worker-sudo.sock", passwords) as broker:
        command += ["--extra-vars", json.dumps({"worker_sudo_socket": str(broker.path)})]
        result = subprocess.run(command, cwd=PROJECT_DIR, stdin=subprocess.DEVNULL)
    if result.returncode:
        print("Worker-installasjonen feilet. Se Ansible-oppsummeringen over; rett feilen og kjør igjen.", flush=True)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("temp_dir")
    parser.add_argument("revision")
    parser.add_argument("--controller-only", action="store_true")
    parser.add_argument("--limit-worker", action="append", default=[])
    parser.add_argument("--regenerate-server-cert", action="store_true")
    args = parser.parse_args()
    try:
        settings = validate_controller_config(args.config)
        workers = select_workers(settings.worker_hosts, args.limit_worker, args.controller_only)
        return install(args.config, args.temp_dir, args.revision, workers, settings.ssh_user, args.regenerate_server_cert)
    except (ConfigValidationError, RuntimeError, OSError, EOFError) as error:
        print(f"Installasjonen stoppet: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInstallasjonen avbrutt.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
