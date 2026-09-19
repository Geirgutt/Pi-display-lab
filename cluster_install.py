"""Collect worker sudo credentials up front and orchestrate parallel installation."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shlex
import socket
import socketserver
import subprocess
import sys
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from config import ConfigValidationError, validate_controller_config
from cluster_ssh import require_ssh, ssh_options, ssh_run

PROJECT_DIR = Path(__file__).resolve().parent
MAX_FORKS = 10
IDENTIFY_SCRIPT = r'''set -eu
count="$1"
led=""
for candidate in /sys/class/leds/led0 /sys/class/leds/ACT; do
  if [ -d "$candidate" ]; then led="$candidate"; break; fi
done
[ -n "$led" ] || exit 3
trigger="$led/trigger"
brightness="$led/brightness"
old="$(sed -n 's/.*\[\([^]]*\)\].*/\1/p' "$trigger" 2>/dev/null || true)"
printf '%s\n' none > "$trigger"
restore() { [ -n "$old" ] && printf '%s\n' "$old" > "$trigger" || true; }
trap restore EXIT INT TERM
i=0
while [ "$i" -lt "$count" ]; do
  printf '%s\n' 1 > "$brightness"
  sleep 0.45
  printf '%s\n' 0 > "$brightness"
  sleep 0.45
  i=$((i + 1))
done
sleep 2
'''


def select_workers(configured: tuple[str, ...], limits: list[str], controller_only: bool) -> list[str]:
    unknown = set(limits) - set(configured)
    if unknown:
        raise RuntimeError("Ukjent worker: " + ", ".join(sorted(unknown)))
    if controller_only:
        return []
    return [host for host in configured if not limits or host in limits]


def check_sudo(user: str, host: str, password: str | None = None, *, identity_file: str = "") -> bool:
    # -k prevents an old SSH sudo timestamp from hiding a required password.
    remote = "sudo -k -n /usr/bin/true" if password is None else "sudo -k -S -p '' /usr/bin/true"
    command = ssh_options(identity_file) + [f"{user}@{host}", remote]
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


def collect_passwords(user: str, workers: list[str], *, identity_file: str = "",
                      initial_passwords: dict[str, str] | None = None, input_fn=None) -> dict[str, str]:
    if not workers:
        return {}
    input_fn = input if input_fn is None else input_fn
    def check(host, password=None):
        kwargs = {"identity_file": identity_file} if identity_file else {}
        return check_sudo(user, host, password, **kwargs) if password is not None else check_sudo(user, host, **kwargs)

    print("Kontrollerer sudo på valgte workers ...", flush=True)
    with ThreadPoolExecutor(max_workers=min(MAX_FORKS, len(workers))) as pool:
        passwordless = list(pool.map(check, workers))
    needed = [host for host, ready in zip(workers, passwordless) if not ready]
    passwords = {host: "" for host, ready in zip(workers, passwordless) if ready}
    candidates = [host for host in needed if initial_passwords and host in initial_passwords]
    if candidates:
        with ThreadPoolExecutor(max_workers=min(MAX_FORKS, len(candidates))) as pool:
            accepted = list(pool.map(lambda host: check(host, initial_passwords[host]), candidates))
        passwords.update({host: initial_passwords[host] for host, valid in zip(candidates, accepted) if valid})
        needed = [host for host in needed if host not in passwords]
    if not needed:
        return passwords

    print("Sudo-passord brukes bare under denne kjøringen og lagres ikke.", flush=True)
    shared = False
    if len(needed) > 1:
        while True:
            answer = input_fn("Bruke samme sudo-passord på alle workers som trenger passord? [J/n]: ").strip().lower()
            if answer in ("", "j", "ja", "y", "yes", "n", "nei", "no"):
                shared = answer not in ("n", "nei", "no")
                break
    if shared:
        password = read_password("Felles sudo-passord for workerne: ")
        with ThreadPoolExecutor(max_workers=min(MAX_FORKS, len(needed))) as pool:
            accepted = list(pool.map(lambda host: check(host, password), needed))
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
            if check(host, password):
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


def broker_passwords(path: str, workers: list[str]) -> dict[str, str]:
    passwords = {}
    for host in workers:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(10)
                connection.connect(path)
                connection.sendall(json.dumps(host).encode() + b"\n")
                with connection.makefile("rb") as response:
                    password = json.loads(response.readline(1024 * 1024)).get("password")
            if not isinstance(password, str):
                raise ValueError("Missing password")
            passwords[host] = password
        except (OSError, ValueError, AttributeError):
            raise RuntimeError(f"{host}: passordøkten er avsluttet. Kjør veiviseren på nytt.") from None
    return passwords


def install(config: str, temp_dir: str, revision: str, workers: list[str], user: str,
            regenerate: bool, *, identity_file: str = "", sudo_socket: str = "",
            display_port: str = "", display_wifi_ssid: str = "", display_no_flash: bool = False,
            display_attached: bool | None = None, display_host: str = "",
            display_serial_port: str = "", controller_host: str = "",
            display_gateway_port: int = 4567, display_psk_file: str = "",
            configured_wifi_ssid: str = "", display_wifi_configured: bool | None = None,
            display_identify_pending: bool = False, worker_order: list[str] | None = None) -> int:
    passwords = broker_passwords(sudo_socket, workers) if sudo_socket else collect_passwords(
        user, workers, **({"identity_file": identity_file} if identity_file else {}))
    print("Passordkontrollen er ferdig. Installerer controlleren ...", flush=True)
    controller = ["bash", "scripts/install-cluster-controller.sh", config, temp_dir, revision]
    if regenerate:
        controller.append("--regenerate-server-cert")
    result = subprocess.run(controller, cwd=PROJECT_DIR, stdin=subprocess.DEVNULL)
    if result.returncode:
        return result.returncode
    if not workers:
        if display_identify_pending and display_attached is True:
            if identify_display_nodes(
                display_host, workers, passwords, user, identity_file,
                worker_order or workers,
            ):
                mark_display_identification_done(config)
        result = provision_configured_display(
            display_port, display_wifi_ssid or configured_wifi_ssid, display_no_flash,
            display_attached=display_attached, display_host=display_host,
            display_serial_port=display_serial_port, controller_host=controller_host,
            display_gateway_port=display_gateway_port, display_psk_file=display_psk_file,
            display_wifi_configured=display_wifi_configured,
            user=user, identity_file=identity_file, workers=workers,
        )
        if result == 0 and display_attached is True:
            mark_display_wifi_configured(config)
        return result

    forks = min(MAX_FORKS, len(workers))
    print(f"Installerer {len(workers)} workers, inntil {forks} samtidig, til commit {revision} ...", flush=True)
    command = [
        str(PROJECT_DIR / ".ansible-venv/bin/ansible-playbook")
        if (PROJECT_DIR / ".ansible-venv/bin/ansible-playbook").is_file() else "ansible-playbook",
        "-i", str(Path(temp_dir) / "inventory.ini"),
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
    if display_identify_pending:
        if identify_display_nodes(
            display_host, workers, passwords, user, identity_file,
            worker_order or workers,
        ):
            mark_display_identification_done(config)
    result = provision_configured_display(
        display_port, display_wifi_ssid or configured_wifi_ssid, display_no_flash,
        display_attached=display_attached, display_host=display_host,
        display_serial_port=display_serial_port, controller_host=controller_host,
        display_gateway_port=display_gateway_port, display_psk_file=display_psk_file,
        display_wifi_configured=display_wifi_configured,
        user=user, identity_file=identity_file, workers=workers,
    )
    if result == 0 and display_attached is True:
        mark_display_wifi_configured(config)
    return result


def identify_display_nodes(target: str, selected_workers: list[str], passwords: dict[str, str],
                           user: str, identity_file: str, worker_order: list[str]) -> bool:
    if target == "controller":
        result = subprocess.run(["sudo", "-n", "sh", "-c", IDENTIFY_SCRIPT, "identify", "1"])
        if result.returncode:
            print("Kunne ikke blinke controllerens ACT-diode; fortsetter likevel.", file=sys.stderr)
            return False
        return True
    candidates = [host for host in worker_order if host in selected_workers]
    if len(candidates) > 10:
        candidates = candidates[:9] + ([target] if target not in candidates[:9] else [])
    success = True
    for ordinal, host in enumerate(worker_order, start=1):
        if host not in candidates:
            continue
        count = min(ordinal, 9)
        print(f"Identifiserer {host}: {count} blink ...", flush=True)
        sudo = "sudo -S -p ''" if passwords.get(host, "") else "sudo -n"
        remote = f"{sudo} /bin/sh -c {shlex.quote(IDENTIFY_SCRIPT)} identify {count}"
        result = ssh_run(
            user, host, remote, identity_file=identity_file,
            stdin=(passwords.get(host, "") + "\n") if passwords.get(host, "") else "",
            timeout=30,
        )
        if result.returncode:
            success = False
            print(f"Kunne ikke blinke ACT-dioden på {host}; fortsetter likevel.", file=sys.stderr)
    return success


def _display_command(port: str, wifi_ssid: str, no_flash: bool) -> list[str]:
    command = ["bash", "scripts/provision-deskdisplay.sh"]
    if port:
        command += ["--port", port]
    if wifi_ssid:
        command += ["--wifi-ssid", wifi_ssid]
    if no_flash:
        command.append("--no-flash")
    return command


def provision_display(port: str, wifi_ssid: str, no_flash: bool) -> int:
    print("Provisjonerer DeskDisplay lokalt ...", flush=True)
    return subprocess.run(_display_command(port, wifi_ssid, no_flash), cwd=PROJECT_DIR).returncode


def provision_remote_display(host: str, port: str, wifi_ssid: str, no_flash: bool,
                             *, user: str, identity_file: str, controller_host: str,
                             gateway_port: int, psk_file: str,
                             wifi_password: str = "") -> int:
    try:
        psk = Path(psk_file).read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        print(f"Kan ikke lese DeskDisplay-PSK på controlleren: {psk_file}", file=sys.stderr)
        return 1
    if re.fullmatch(r"[0-9A-Fa-f]{64}", psk) is None:
        print("DeskDisplay-PSK på controlleren er ugyldig.", file=sys.stderr)
        return 1
    command = _display_command(port, wifi_ssid, no_flash)
    command += ["--psk-stdin", "--controller-host", controller_host,
                "--gateway-port", str(gateway_port)]
    if wifi_password:
        command.append("--wifi-password-stdin")
    remote = "cd \"$HOME/Pi-display-lab\" && " + " ".join(
        shlex.quote(part) for part in command
    )
    print(f"Provisjonerer DeskDisplay på worker {host} ...", flush=True)
    result = ssh_run(
        user, host, remote, identity_file=identity_file,
        stdin=psk + "\n" + (wifi_password + "\n" if wifi_password else ""), timeout=900,
    )
    if result.returncode:
        require_ssh(result, host)
        return result.returncode
    print(result.stdout, end="", flush=True)
    return 0


def provision_configured_display(port: str, wifi_ssid: str, no_flash: bool, *,
                                 display_attached: bool | None, display_host: str,
                                 display_serial_port: str, controller_host: str,
                                 display_gateway_port: int, display_psk_file: str,
                                 display_wifi_configured: bool | None,
                                 user: str, identity_file: str,
                                 workers: list[str]) -> int:
    if port:
        return provision_display(port, wifi_ssid, no_flash)
    if display_attached is not True:
        return 0
    serial_port = display_serial_port
    if display_host == "controller":
        return provision_display(serial_port, wifi_ssid, no_flash)
    if display_host not in workers:
        print(
            f"Displayet er registrert på {display_host}, men denne installasjonen "
            "oppdaterte ikke den workeren. Kjør installasjonen uten --limit-worker.",
            file=sys.stderr,
        )
        return 1
    wifi_password = ""
    if wifi_ssid and display_wifi_configured is not True:
        wifi_password = read_password("Wi-Fi-passord for DeskDisplay: ")
    return provision_remote_display(
        display_host, serial_port, wifi_ssid, no_flash,
        user=user, identity_file=identity_file, controller_host=controller_host,
        gateway_port=display_gateway_port, psk_file=display_psk_file,
        wifi_password=wifi_password,
    )


def mark_display_wifi_configured(config: str) -> None:
    path = Path(config)
    payload = json.loads(path.read_text(encoding="utf-8"))
    deskdisplay = payload.get("deskdisplay")
    if isinstance(deskdisplay, dict):
        deskdisplay["display_wifi_configured"] = True
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)


def mark_display_identification_done(config: str) -> None:
    path = Path(config)
    payload = json.loads(path.read_text(encoding="utf-8"))
    deskdisplay = payload.get("deskdisplay")
    if isinstance(deskdisplay, dict):
        deskdisplay["display_identify_pending"] = False
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("temp_dir")
    parser.add_argument("revision")
    parser.add_argument("--controller-only", action="store_true")
    parser.add_argument("--limit-worker", action="append", default=[])
    parser.add_argument("--regenerate-server-cert", action="store_true")
    parser.add_argument("--sudo-socket", default="")
    parser.add_argument("--display-port", default="")
    parser.add_argument("--display-wifi-ssid", default="")
    parser.add_argument("--display-no-flash", action="store_true")
    args = parser.parse_args()
    try:
        settings = validate_controller_config(args.config)
        workers = select_workers(settings.worker_hosts, args.limit_worker, args.controller_only)
        return install(args.config, args.temp_dir, args.revision, workers, settings.ssh_user,
                       args.regenerate_server_cert, identity_file=settings.ssh_identity_file,
                       sudo_socket=args.sudo_socket, display_port=args.display_port,
                       display_wifi_ssid=args.display_wifi_ssid,
                       display_no_flash=args.display_no_flash,
                       display_attached=settings.deskdisplay.display_attached,
                       display_host=settings.deskdisplay.display_host,
                       display_serial_port=settings.deskdisplay.display_serial_port,
                       controller_host=settings.controller_host,
                       display_gateway_port=settings.deskdisplay.port,
                       display_psk_file=settings.deskdisplay.psk_file,
                       configured_wifi_ssid=settings.deskdisplay.display_wifi_ssid,
                       display_wifi_configured=settings.deskdisplay.display_wifi_configured,
                       display_identify_pending=settings.deskdisplay.display_identify_pending,
                       worker_order=list(settings.worker_hosts))
    except (ConfigValidationError, RuntimeError, OSError, EOFError) as error:
        print(f"Installasjonen stoppet: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInstallasjonen avbrutt.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
