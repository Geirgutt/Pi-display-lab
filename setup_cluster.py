"""Testbar logikk for den norske cluster-oppsettsveiviseren."""

from __future__ import annotations

import getpass
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cluster_pki import inspect_pki
from config import (
    DEFAULT_CLUSTER_CA_FILE,
    DEFAULT_CLUSTER_CREDENTIALS_FILE,
    DEFAULT_COORDINATOR_CERT_FILE,
    DEFAULT_COORDINATOR_KEY_FILE,
    ConfigValidationError,
    load_config,
    validate_controller_config,
)


InputFunction = Callable[[str], str]


@dataclass(frozen=True)
class DetectedValues:
    username: str
    hostname: str
    lan_address: str
    project_dir: Path
    branch: str
    commit: str
    installed_services: tuple[str, ...]


@dataclass(frozen=True)
class PortListener:
    port: int
    pid: int | None
    executable: str
    command_line: str


def run_text(command: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def detect_lan_ipv4() -> str:
    """Finn sannsynlig utgående IPv4 uten å sende applikasjonsdata."""

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    finally:
        probe.close()
    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except socket.gaierror:
        return ""
    candidates = [address for address in addresses if not address.startswith("127.")]
    return candidates[0] if len(candidates) == 1 else ""


def detect_values(project_dir: str | Path) -> DetectedValues:
    project = Path(project_dir).resolve()
    services = tuple(
        service
        for service in (
            "pi-display-lab.service",
            "cluster-coordinator.service",
            "coordinator.service",
            "pi-cluster-coordinator.service",
            "cluster-worker.service",
            "pi-display-node-agent.service",
        )
        if run_text(["systemctl", "cat", service])
    )
    return DetectedValues(
        username=getpass.getuser(),
        hostname=socket.gethostname(),
        lan_address=detect_lan_ipv4(),
        project_dir=project,
        branch=run_text(["git", "branch", "--show-current"], project),
        commit=run_text(["git", "rev-parse", "--short", "HEAD"], project),
        installed_services=services,
    )


def build_controller_config(
    controller_host: str,
    ssh_user: str,
    worker_hosts: list[str],
    *,
    app_port: int = 5000,
    coordinator_port: int = 5001,
    poll_interval_seconds: float = 2,
    node_heartbeat_auth: bool = True,
) -> dict[str, Any]:
    workers = normalize_workers(worker_hosts)
    return {
        "node_role": "controller",
        "controller_host": controller_host.strip(),
        "worker_hosts": workers,
        "ssh_user": ssh_user.strip(),
        "coordinator_port": coordinator_port,
        "app_port": app_port,
        "node_heartbeat_auth": node_heartbeat_auth,
        "cluster": {
            "enabled": True,
            "coordinator_url": f"https://{controller_host.strip()}:{coordinator_port}",
            "poll_interval_seconds": poll_interval_seconds,
            "worker_slots": 0,
            "credentials_file": DEFAULT_CLUSTER_CREDENTIALS_FILE,
            "tls_enabled": True,
            "ca_certificate_file": DEFAULT_CLUSTER_CA_FILE,
            "server_certificate_file": DEFAULT_COORDINATOR_CERT_FILE,
            "server_key_file": DEFAULT_COORDINATOR_KEY_FILE,
        },
    }


def normalize_workers(workers: list[str]) -> list[str]:
    cleaned = [worker.strip() for worker in workers if worker.strip()]
    folded = [worker.casefold() for worker in cleaned]
    if len(set(folded)) != len(folded):
        raise ValueError("Samme worker kan ikke legges til flere ganger")
    return cleaned


def add_worker(workers: list[str], worker: str) -> list[str]:
    return normalize_workers([*workers, worker])


def remove_worker(workers: list[str], worker: str, *, confirmed: bool) -> list[str]:
    if not confirmed:
        raise PermissionError("Fjerning av worker krever bekreftelse")
    return [item for item in workers if item.casefold() != worker.casefold()]


def migrate_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Legg TLS-standarder til gammel lokal config uten å endre maskinverdier."""

    controller = str(raw.get("controller_host", "")).strip()
    coordinator_port = raw.get("coordinator_port", 5001)
    cluster = dict(raw.get("cluster") or {})
    cluster.update(
        {
            "enabled": True,
            "coordinator_url": f"https://{controller}:{coordinator_port}",
            "credentials_file": cluster.get(
                "credentials_file", DEFAULT_CLUSTER_CREDENTIALS_FILE
            ),
            "tls_enabled": True,
            "ca_certificate_file": cluster.get(
                "ca_certificate_file", DEFAULT_CLUSTER_CA_FILE
            ),
            "server_certificate_file": cluster.get(
                "server_certificate_file", DEFAULT_COORDINATOR_CERT_FILE
            ),
            "server_key_file": cluster.get(
                "server_key_file", DEFAULT_COORDINATOR_KEY_FILE
            ),
        }
    )
    migrated = dict(raw)
    migrated["node_role"] = "controller"
    migrated["cluster"] = cluster
    migrated.setdefault("node_heartbeat_auth", True)
    return migrated


def write_local_config(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    temporary = destination.with_name(f"{destination.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(destination)
    os.chmod(destination, 0o600)


def detect_port_listener(port: int) -> PortListener | None:
    output = run_text(["ss", "-ltnp", f"sport = :{port}"])
    lines = [line for line in output.splitlines() if f":{port}" in line]
    if not lines:
        return None
    line = lines[-1]
    match = re.search(r"pid=(\d+)", line)
    pid = int(match.group(1)) if match else None
    command_line = ""
    executable = ""
    if pid is not None:
        try:
            command_line = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            ).strip()
            executable = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            pass
    return PortListener(port, pid, executable, command_line or line)


def looks_like_old_coordinator(listener: PortListener) -> bool:
    command = listener.command_line.replace("\\", "/")
    return bool(
        listener.pid
        and re.search(r"(^|\s|/)coordinator\.py(?:\s|$)", command)
        and "cluster_coordinator.py" not in command
    )


def old_prototype_files(home: str | Path) -> tuple[Path, ...]:
    root = Path(home)
    return tuple(path for name in ("coordinator.py", "worker.py") if (path := root / name).is_file())


def yes_no(prompt: str, *, default: bool, input_fn: InputFunction = input) -> bool:
    suffix = " [J/n] " if default else " [j/N] "
    answer = input_fn(prompt + suffix).strip().casefold()
    if not answer:
        return default
    return answer in {"j", "ja", "y", "yes"}


def ask_value(prompt: str, default: str, input_fn: InputFunction = input) -> str:
    suffix = f" [{default}]" if default else ""
    return input_fn(f"{prompt}{suffix}: ").strip() or default


def ask_workers(input_fn: InputFunction = input) -> list[str]:
    workers: list[str] = []
    while True:
        worker = input_fn(f"Adresse/hostname til worker {len(workers) + 1}:\n> ").strip()
        if not worker:
            if workers:
                return workers
            print("Minst én worker må legges til.")
            continue
        try:
            workers = add_worker(workers, worker)
        except ValueError as error:
            print(f"! {error}")
            continue
        if not yes_no("Legge til en worker til?", default=True, input_fn=input_fn):
            return workers


def _load_raw_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigValidationError("Eksisterende config.local.json kan ikke leses") from error
    if not isinstance(value, dict):
        raise ConfigValidationError("Eksisterende config.local.json må være et JSON-objekt")
    return value


def _print_detected(values: DetectedValues) -> None:
    print("\nOppdaget:")
    print(f"  Hostname: {values.hostname}")
    print(f"  LAN-adresse: {values.lan_address or 'uklar – må oppgis'}")
    print(f"  Bruker: {values.username}")
    print(f"  Prosjekt: {values.project_dir}")
    print(f"  Git: {values.branch or 'ukjent'} @ {values.commit or 'ukjent'}")
    if values.installed_services:
        print(f"  Installerte tjenester: {', '.join(values.installed_services)}")


def _preflight(project: Path, payload: dict[str, Any]) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="pi-display-preflight-") as directory:
        temporary = Path(directory)
        config_path = temporary / "config.json"
        identities_path = temporary / "identities.json"
        write_local_config(config_path, payload)
        validate_controller_config(config_path)
        subprocess.run(
            [
                sys.executable,
                str(project / "scripts" / "preflight-cluster.py"),
                str(config_path),
                str(identities_path),
            ],
            cwd=project,
            check=True,
        )
        identities = json.loads(identities_path.read_text(encoding="utf-8"))
        return identities if isinstance(identities, dict) else {}


def _stop_old_listener(listener: PortListener) -> None:
    if not looks_like_old_coordinator(listener) or listener.pid is None:
        raise RuntimeError("Porten brukes av en prosess veiviseren ikke kan stoppe trygt")
    os.kill(listener.pid, 15)
    for _attempt in range(30):
        if not Path(f"/proc/{listener.pid}").exists():
            return
        time.sleep(0.1)
    raise RuntimeError("Prosessen avsluttet ikke etter SIGTERM; stopp den manuelt")


def _existing_config_choice(input_fn: InputFunction) -> str:
    print("\nEksisterende config.local.json ble funnet:")
    print("  1. Verifiser nåværende cluster")
    print("  2. Reinstaller/oppdater nåværende konfigurasjon")
    print("  3. Endre workers")
    print("  4. Endre controller/nettverksinnstillinger")
    print("  5. Avbryt")
    return input_fn("> ").strip()


def run_wizard(project_dir: str | Path, input_fn: InputFunction = input) -> int:
    project = Path(project_dir).resolve()
    if os.name != "posix" or not sys.platform.startswith("linux"):
        print("Setup-veiviseren må kjøres på controlleren med Raspberry Pi OS/Linux.")
        return 2
    if os.geteuid() == 0:
        print("Kjør veiviseren som vanlig controller-bruker, ikke som root.")
        return 2

    print("-" * 50)
    print("PI DISPLAY LAB – CLUSTER-OPPSETT")
    print("-" * 50)
    print("Denne maskinen blir CONTROLLER.")
    detected = detect_values(project)
    _print_detected(detected)
    config_path = project / "config.local.json"
    raw: dict[str, Any] | None = None
    mode = "fresh"
    original_workers: list[str] = []

    if config_path.exists():
        try:
            raw = migrate_config(_load_raw_config(config_path))
            original_workers = list(raw.get("worker_hosts") or [])
        except ConfigValidationError as error:
            print(f"! {error}")
            return 2
        choice = _existing_config_choice(input_fn)
        if choice == "1":
            return subprocess.run(["bash", "scripts/verify-cluster.sh"], cwd=project).returncode
        if choice == "5" or choice not in {"2", "3", "4"}:
            print("Ingen endringer ble gjort.")
            return 0
        mode = {"2": "reinstall", "3": "workers", "4": "network"}[choice]

    if raw is None:
        candidate = detected.lan_address
        if candidate and yes_no(
            f"Bruke {candidate} som controller-adresse?",
            default=True,
            input_fn=input_fn,
        ):
            controller_host = candidate
        else:
            controller_host = ask_value("Controller-adresse/hostname", "", input_fn)
        ssh_user = ask_value("SSH-bruker på workerne", detected.username, input_fn)
        workers = ask_workers(input_fn)
        raw = build_controller_config(controller_host, ssh_user, workers)
    else:
        if mode == "workers":
            current_workers = list(raw.get("worker_hosts") or [])
            print(f"Nåværende workers: {', '.join(current_workers)}")
            requested = ask_workers(input_fn)
            removed = [item for item in current_workers if item not in requested]
            for worker in removed:
                if not yes_no(
                    f"Fjerne {worker} og tilbakekalle worker-tokenet?",
                    default=False,
                    input_fn=input_fn,
                ):
                    requested.append(worker)
            raw["worker_hosts"] = normalize_workers(requested)
        elif mode == "network":
            raw["controller_host"] = ask_value(
                "Controller-adresse/hostname", str(raw.get("controller_host", "")), input_fn
            )
            raw["ssh_user"] = ask_value(
                "SSH-bruker på workerne", str(raw.get("ssh_user", "")), input_fn
            )
        raw = migrate_config(raw)

    if yes_no("Aktivere tokenbeskyttelse for node-heartbeats?", default=True, input_fn=input_fn):
        raw["node_heartbeat_auth"] = True
    try:
        workers_by_address = _preflight(project, raw)
    except (ConfigValidationError, subprocess.CalledProcessError, OSError) as error:
        print(f"\nPreflight stoppet før noen maskiner ble endret: {error}")
        return 2

    settings = load_config_from_payload(raw)
    pki_status = inspect_pki(settings)
    credentials_exist = Path(settings.cluster.credentials_file).is_file()
    print("\nEksisterende lokal sikkerhet:")
    print(f"  Cluster-credentials: {'funnet (bevares)' if credentials_exist else 'ikke funnet (opprettes)'}")
    ca_text = (
        "funnet og validert (bevares)"
        if pki_status.ca_is_valid
        else "funnet, men ugyldig/ufullstendig"
        if pki_status.ca_exists
        else "ikke funnet (opprettes)"
    )
    print(f"  Privat CA: {ca_text}")
    print(f"  Coordinator-sertifikat: {'funnet' if pki_status.server_exists else 'ikke funnet (opprettes)'}")
    if pki_status.ca_exists and not pki_status.ca_is_valid:
        print(
            "Veiviseren erstatter aldri en eksisterende ugyldig CA automatisk. "
            "Ta sikkerhetskopi og rydd /etc/pi-display-lab/pki manuelt før nytt forsøk."
        )
        return 2
    regenerate_server = False
    if pki_status.server_exists and (
        not pki_status.server_matches_address or not pki_status.server_is_current
    ):
        print(
            "\nCoordinator-sertifikatet er utløpt, utløper snart eller matcher ikke "
            "den valgte controller-adressen."
        )
        regenerate_server = yes_no(
            "Regenerere bare coordinatorens serversertifikat og beholde CA-en?",
            default=True,
            input_fn=input_fn,
        )
        if not regenerate_server:
            print("Ingen endringer ble gjort.")
            return 0

    app_listener = detect_port_listener(int(raw["app_port"]))
    if app_listener:
        print(f"\nPort {app_listener.port} er i bruk.")
        print(f"  PID: {app_listener.pid or 'ukjent'}")
        print(f"  Program: {app_listener.executable or 'ukjent'}")
        print(f"  Kommando: {app_listener.command_line}")
        if "pi-display-lab.service" not in detected.installed_services:
            print(
                "Porten er ikke knyttet til en oppdaget Pi Display Lab-tjeneste. "
                "Stopp eller flytt prosessen manuelt før installasjon."
            )
            return 2

    listener = detect_port_listener(int(raw["coordinator_port"]))
    if listener:
        print(f"\nPort {listener.port} er i bruk.")
        print(f"  PID: {listener.pid or 'ukjent'}")
        print(f"  Program: {listener.executable or 'ukjent'}")
        print(f"  Kommando: {listener.command_line}")
        if looks_like_old_coordinator(listener):
            print("Det ser ut som den gamle manuelle coordinatoren fortsatt kjører.")
        elif (
            "cluster_coordinator.py" not in listener.command_line
            and "cluster-coordinator.service" not in detected.installed_services
        ):
            print("Porten brukes ikke tydelig av Pi Display Lab. Veiviseren stopper her.")
            return 2

    prototype_files = old_prototype_files(Path.home())
    if prototype_files:
        print("Gamle prototypefiler ble funnet og beholdes:")
        for path in prototype_files:
            print(f"  {path}")

    print("\n" + "-" * 50)
    print("OPPSUMMERING")
    print("-" * 50)
    print(f"Controller:\n  {detected.hostname}\n  {raw['controller_host']}")
    print("\nWorkers:")
    for address in raw["worker_hosts"]:
        print(f"  {workers_by_address.get(address, 'ukjent')} ({address})")
    print(f"\nDashboard:\n  HTTP port {raw['app_port']} (ingen innlogging)")
    print(f"\nCoordinator:\n  HTTPS port {raw['coordinator_port']}")
    print("\nWorker authentication:\n  individuelle tokens")
    print("\nCluster encryption:\n  HTTPS / TLS aktivert")
    heartbeat_text = "aktivert" if raw.get("node_heartbeat_auth") is True else "deaktivert"
    print(f"\nHeartbeat authentication:\n  {heartbeat_text}")
    print("\nController som compute-worker:\n  NEI")
    if not yes_no("\nFortsette installasjonen?", default=True, input_fn=input_fn):
        print("Ingen endringer ble gjort.")
        return 0

    if listener and looks_like_old_coordinator(listener):
        if yes_no("Stoppe den gamle manuelle coordinator-prosessen nå?", default=False, input_fn=input_fn):
            try:
                _stop_old_listener(listener)
            except (OSError, RuntimeError) as error:
                print(f"Kunne ikke stoppe den gamle coordinatoren trygt: {error}")
                return 2
        else:
            print("Installasjonen avbrytes fordi port 5001 fortsatt er opptatt.")
            return 2

    write_local_config(config_path, raw)
    command = ["bash", "scripts/install-cluster.sh"]
    if regenerate_server:
        command.append("--regenerate-server-cert")
    if mode == "workers":
        added_workers = [
            worker for worker in raw["worker_hosts"] if worker not in original_workers
        ]
        if added_workers:
            for worker in added_workers:
                command.extend(("--limit-worker", worker))
        else:
            command.append("--controller-only")
    result = subprocess.run(command, cwd=project)
    if result.returncode:
        print("\nInstallasjonen ble ikke fullført. config.local.json er bevart for nytt forsøk.")
        return result.returncode

    commit = run_text(["git", "rev-parse", "--short", "HEAD"], project)
    print("\n" + "=" * 48)
    print("PI DISPLAY LAB CLUSTER ER KLART")
    print("=" * 48)
    print("Controller:\n✓ Pi Display Lab\n✓ Coordinator\n✓ HTTPS/TLS\n✓ Admin authentication")
    for address in raw["worker_hosts"]:
        identity = workers_by_address.get(address, address)
        print(f"\n{identity}:\n✓ SSH\n✓ Worker\n✓ Node agent\n✓ Worker token\n✓ TLS verification")
    print(f"\nVersion:\n✓ alle noder kjører commit {commit}")
    print(f"\nDashboard:\nhttp://{raw['controller_host']}:{raw['app_port']}")
    print(f"\nCoordinator:\nhttps://{raw['controller_host']}:{raw['coordinator_port']}")
    print(f"\nWorkers online:\n{len(raw['worker_hosts'])}")
    print("\nDu kan nå åpne dashboardet og starte en primtallsjobb.")
    print("\nNyttige kommandoer:")
    print("systemctl status pi-display-lab")
    print("systemctl status cluster-coordinator")
    print("bash scripts/verify-cluster.sh")
    return 0


def load_config_from_payload(payload: dict[str, Any]):
    """Valider en payload via tempfil; nyttig både i veiviseren og tester."""

    with tempfile.TemporaryDirectory(prefix="pi-display-config-") as directory:
        path = Path(directory) / "config.json"
        write_local_config(path, payload)
        return validate_controller_config(path)
