"""Testbar logikk for den norske cluster-oppsettsveiviseren."""

from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cluster_pki import inspect_pki
from cluster_bootstrap import inspect_worker, parallel, prepare_workers, prepare_removal, stop_removed_workers
from cluster_install import PasswordBroker
from config import (
    DEFAULT_CLUSTER_CA_FILE,
    DEFAULT_CLUSTER_CREDENTIALS_FILE,
    DEFAULT_COORDINATOR_CERT_FILE,
    DEFAULT_COORDINATOR_KEY_FILE,
    ConfigValidationError,
    load_config,
    validate_controller_config,
    _safe_host,
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
    if len(cleaned) > 100:
        raise ValueError("Clusteret kan ha høyst 100 workers")
    if any(not _safe_host(host) or ":" in host for host in cleaned):
        raise ValueError("Oppgi gyldige IPv4-adresser eller vertsnavn uten mellomrom")
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


def ask_workers(input_fn: InputFunction = input, *, maximum: int = 100,
                existing: list[str] | None = None) -> list[str]:
    if maximum < 1:
        raise ValueError("Clusteret har allerede 100 workers")
    while True:
        answer = input_fn(f"Hvor mange {'nye ' if existing else ''}workers vil du registrere (1–{maximum})? ").strip()
        if answer.isdigit() and 1 <= int(answer) <= maximum:
            count = int(answer)
            break
        print(f"Oppgi et heltall mellom 1 og {maximum}.")
    print("Skriv eller lim inn adresser. Bruk mellomrom, komma, semikolon eller én adresse per linje.")
    workers: list[str] = []
    while len(workers) < count:
        entered = input_fn(f"Workers {len(workers)}/{count}:\n> ").strip()
        batch = [item for item in re.split(r"[\s,;]+", entered) if item]
        try:
            if not batch:
                raise ValueError(f"Det mangler {count - len(workers)} adresser")
            if len(workers) + len(batch) > count:
                raise ValueError(f"Du oppga flere adresser enn de {count} som skal registreres")
            normalize_workers([*(existing or []), *workers, *batch])
        except ValueError as error:
            print(f"! {error}")
            continue
        workers.extend(batch)
    return workers


def ask_removals(workers: list[str], input_fn: InputFunction) -> list[str]:
    for number, host in enumerate(workers, 1):
        print(f"  {number}. {host}")
    while True:
        answer = input_fn("Numrene til workers som skal fjernes (tomt avbryter): ").strip()
        if not answer:
            return workers
        try:
            selected = {int(item) for item in re.split(r"[\s,;]+", answer)}
            if not selected or min(selected) < 1 or max(selected) > len(workers):
                raise ValueError
            remaining = [host for i, host in enumerate(workers, 1) if i not in selected]
            if not remaining:
                raise ValueError
        except ValueError:
            print("Velg gyldige nummer. Minst én worker må beholdes.")
            continue
        removed = [host for i, host in enumerate(workers, 1) if i in selected]
        if yes_no("Fjerne og tilbakekalle tilgang for " + ", ".join(removed) + "?", default=False, input_fn=input_fn):
            return remaining
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
    print("  3. Legg til workers")
    print("  4. Endre controller/nettverksinnstillinger")
    print("  5. Avbryt")
    print("  6. Fjern workers")
    return input_fn("> ").strip()


def setup_firewall(raw: dict[str, Any], input_fn: InputFunction) -> None:
    """Offer concrete rules when a supported local firewall is active."""
    ports = [f"{raw['app_port']}/tcp", f"{raw['coordinator_port']}/tcp"]
    if shutil.which("firewall-cmd"):
        state = run_text(["sudo", "-n", "firewall-cmd", "--state"])
        if state == "running":
            active = run_text(["sudo", "-n", "firewall-cmd", "--get-active-zones"])
            zones = [line.split()[0] for line in active.splitlines() if line and not line[0].isspace()]
            if not zones:
                raise RuntimeError("firewalld er aktiv uten kjent aktiv sone. Konfigurer lab-nettet før installasjon.")
            print("\nAktive firewalld-soner:\n" + active)
            while True:
                zone = ask_value("Sonen som inneholder lab-nettet", zones[0], input_fn)
                if zone in zones:
                    break
                print("Velg en av de aktive sonene over.")
            if yes_no(f"Åpne {', '.join(ports)} i firewalld-sonen {zone}, også etter omstart?",
                      default=False, input_fn=input_fn):
                for port in ports:
                    for persistence in ([], ["--permanent"]):
                        subprocess.run(["sudo", "-n", "firewall-cmd", *persistence,
                                        f"--zone={zone}", f"--add-port={port}"], check=True)
            else:
                print("Brannmuren beholdes. Sørg for at lab-nettet allerede har tilgang til disse portene.")
            return
    if shutil.which("ufw"):
        status = run_text(["sudo", "-n", "env", "LC_ALL=C", "ufw", "status"])
        if status.startswith("Status: active"):
            if yes_no(f"UFW er aktiv. Tillate innkommende TCP til portene {', '.join(ports)} på koordinatoren?",
                      default=False, input_fn=input_fn):
                for port in ports:
                    subprocess.run(["sudo", "-n", "ufw", "allow", port], check=True)


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
    if run_text(["git", "status", "--porcelain"], project):
        print("Prosjektet har lokale Git-endringer. Kontroller git status før klargjøring av noder.")
        return 2
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
        if choice == "5" or choice not in {"2", "3", "4", "6"}:
            print("Ingen cluster-installasjon ble startet. Eventuell klargjøring er bevart.")
            return 0
        mode = {"2": "reinstall", "3": "add", "4": "network", "6": "remove"}[choice]

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
        if mode == "add":
            current_workers = list(raw.get("worker_hosts") or [])
            print(f"Nåværende workers: {', '.join(current_workers)}")
            if len(current_workers) >= 100:
                print("Clusteret har allerede 100 workers. Fjern en worker før du legger til flere.")
                return 2
            added = ask_workers(input_fn, maximum=100 - len(current_workers), existing=current_workers)
            raw["worker_hosts"] = normalize_workers([*current_workers, *added])
        elif mode == "remove":
            raw["worker_hosts"] = ask_removals(list(raw.get("worker_hosts") or []), input_fn)
            if raw["worker_hosts"] == original_workers:
                print("Ingen workers ble fjernet.")
                return 0
        elif mode == "network":
            raw["controller_host"] = ask_value(
                "Controller-adresse/hostname", str(raw.get("controller_host", "")), input_fn
            )
            raw["ssh_user"] = ask_value(
                "SSH-bruker på workerne", str(raw.get("ssh_user", "")), input_fn
            )
        raw = migrate_config(raw)

    if mode not in {"add", "remove"} and yes_no("Aktivere tokenbeskyttelse for node-heartbeats?", default=True, input_fn=input_fn):
        raw["node_heartbeat_auth"] = True
    try:
        load_config_from_payload(raw)
        selected_workers = ([host for host in raw["worker_hosts"] if host not in original_workers]
                            if mode == "add" else [] if mode == "remove" else list(raw["worker_hosts"]))
        existing_nodes = {}
        removed_passwords = {}
        if mode in {"add", "remove"}:
            remaining_original = [host for host in original_workers if host in raw["worker_hosts"]]
            existing_nodes = parallel(remaining_original, lambda host: inspect_worker(
                raw["ssh_user"], host, raw.get("ssh_identity_file", "")), "Kontrollerer eksisterende workers")
            revision = run_text(["git", "rev-parse", "HEAD"], project)
            outdated = [host for host in remaining_original if existing_nodes[host]["revision"] != revision]
            if outdated:
                print("Disse eksisterende workerne trenger samme versjon som koordinatoren: " + ", ".join(outdated))
                if not yes_no("Oppdatere også disse under installasjonen?", default=True, input_fn=input_fn):
                    print("Kjør update.sh for å oppdatere eksisterende cluster før du endrer workers.")
                    return 0
                selected_workers = [*outdated, *selected_workers]
                existing_nodes = {host: node for host, node in existing_nodes.items() if host not in outdated}
        if mode == "remove":
            removed = [host for host in original_workers if host not in raw["worker_hosts"]]
            removed_passwords = prepare_removal(raw, removed, input_fn)
        sudo_passwords = prepare_workers(raw, selected_workers, existing_nodes=existing_nodes, input_fn=input_fn)
        workers_by_address = _preflight(project, raw)
    except (ConfigValidationError, subprocess.SubprocessError, OSError, RuntimeError) as error:
        print(f"\nKlargjøringen stoppet: {error}\nSSH-nøkler og ferdige pakker er bevart for neste forsøk.")
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
            print("Ingen cluster-installasjon ble startet. Eventuell klargjøring er bevart.")
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
        print("Ingen cluster-installasjon ble startet. Eventuell klargjøring er bevart.")
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
    try:
        setup_firewall(raw, input_fn)
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Brannmuroppsettet stoppet: {error}. Lokal config er bevart.")
        return 2
    command = ["bash", "scripts/install-cluster.sh"]
    if regenerate_server:
        command.append("--regenerate-server-cert")
    if mode in {"add", "remove"}:
        if selected_workers:
            for worker in selected_workers:
                command.extend(("--limit-worker", worker))
        else:
            command.append("--controller-only")
    with tempfile.TemporaryDirectory(prefix="pi-display-setup-") as directory:
        with PasswordBroker(Path(directory) / "sudo.sock", sudo_passwords) as broker:
            command.extend(("--sudo-socket", str(broker.path)))
            result = subprocess.run(command, cwd=project)
    if result.returncode:
        print("\nInstallasjonen ble ikke fullført. config.local.json er bevart for nytt forsøk.")
        return result.returncode
    if mode == "remove":
        stop_removed_workers(raw, removed_passwords)
        print("\nFjernet fra clusteret og tilbakekalt tilgang: " + ", ".join(removed))
        not_stopped = [host for host in removed if host not in removed_passwords]
        if not_stopped:
            print("Tjenestene ble ikke stoppet på: " + ", ".join(not_stopped) + ". Stopp dem lokalt når nodene er tilgjengelige.")

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
