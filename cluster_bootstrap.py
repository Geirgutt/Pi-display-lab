"""Guided first access to workers, before Python or Ansible is available there."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import re
import shlex
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from cluster_auth import valid_worker_id
from cluster_install import MAX_FORKS, collect_passwords, read_password
from cluster_ssh import require_ssh, ssh_run


def confirm(prompt, input_fn=input, default=True):
    while True:
        answer = input_fn(prompt + (" [J/n]: " if default else " [j/N]: ")).strip().lower()
        if not answer:
            return default
        if answer in {"j", "ja", "y", "yes", "n", "nei", "no"}:
            return answer in {"j", "ja", "y", "yes"}


def parallel(workers, operation, label):
    results, errors = {}, []
    if not workers:
        return results
    print(f"{label}: {len(workers)} workers, inntil {MAX_FORKS} samtidig ...", flush=True)
    with ThreadPoolExecutor(max_workers=min(MAX_FORKS, len(workers))) as pool:
        futures = {pool.submit(operation, host): host for host in workers}
        for future in as_completed(futures):
            host = futures[future]
            try:
                results[host] = future.result()
                status = "krever oppfølging" if results[host] is False else "OK"
                print(f"  {host}: {status} ({len(results) + len(errors)}/{len(workers)})", flush=True)
            except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
                errors.append(f"{host}: {error}")
                print(f"  {host}: FEILET", flush=True)
    if errors:
        raise RuntimeError("\n".join(errors) + "\nRett feilen og kjør veiviseren igjen; ferdige nøkler og pakker gjenbrukes.")
    return results


def known_host(host, known_hosts=None):
    files = [Path(known_hosts)] if known_hosts else [Path.home() / ".ssh/known_hosts", Path("/etc/ssh/ssh_known_hosts")]
    for path in files:
        if path.is_file():
            result = subprocess.run(["ssh-keygen", "-F", host, "-f", str(path)], capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return True
    return False


def scan_key(host):
    result = subprocess.run(["ssh-keyscan", "-T", "8", "-t", "ed25519", host],
                            capture_output=True, text=True, timeout=15)
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == host and fields[1] == "ssh-ed25519":
            try:
                data = base64.b64decode(fields[2], validate=True)
            except ValueError:
                continue
            fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
            return line, fingerprint
    raise RuntimeError("Ingen SSH-vertsnøkkel ble funnet. Kontroller IP-adresse, nettverk og at SSH er aktivert.")


def trust_hosts(workers, input_fn=input, known_hosts=None):
    unknown = [host for host in workers if not known_host(host, known_hosts)]
    scanned = parallel(unknown, scan_key, "Henter SSH-nøkkelavtrykk")
    if not scanned:
        return
    print("\nNye SSH-verter. Kontroller disse nøkkelavtrykkene mot nodene:")
    for host in unknown:
        print(f"  {host}: {scanned[host][1]}")
    print("På en node kan avtrykket vises med: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub")
    if not confirm("Godkjenne disse vertsnøklene?", input_fn, default=False):
        raise RuntimeError("SSH-vertsnøklene ble ikke godkjent. Ingen nøkkelinnlogging er konfigurert.")
    destination = Path(known_hosts) if known_hosts else Path.home() / ".ssh/known_hosts"
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as stream:
        stream.write("\n" + "\n".join(scanned[host][0] for host in unknown) + "\n")
    os.chmod(destination, 0o600)


def ensure_key(identity_file=""):
    # A default OpenSSH identity also works on future updates without an agent
    # or per-host overrides, and does not replace access to older cluster nodes.
    path = Path(identity_file) if identity_file else Path.home() / ".ssh/id_ed25519"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.exists():
        if Path(str(path) + ".pub").exists():
            raise RuntimeError(f"{path}.pub finnes uten privat nøkkel. Eksisterende nøkkelmateriale overskrives ikke.")
        print(f"Oppretter egen SSH-nøkkel for clusteret: {path}")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "pi-display-lab", "-f", str(path)], check=True)
    public = subprocess.run(["ssh-keygen", "-y", "-P", "", "-f", str(path)], capture_output=True, text=True)
    if public.returncode:
        raise RuntimeError(f"Kan ikke bruke {path} uten passfrase. Oppgi en egen clusternøkkel uten passfrase; eksisterende nøkkel beholdes.")
    os.chmod(path, 0o600)
    return str(path), public.stdout.strip()


def login_passwords(user, workers, input_fn=input):
    if not workers:
        return {}
    passwords = {}
    shared = len(workers) > 1 and confirm("Samme SSH-innloggingspassord på de nye workerne?", input_fn)

    def accepted(host, password):
        result = ssh_run(user, host, "true", login_password=password)
        if result.returncode in {5, 255} and ("Permission denied" in result.stderr or result.returncode == 5):
            return False
        require_ssh(result, host)
        return True

    if shared:
        password = read_password("Felles SSH-innloggingspassord: ")
        result = parallel(workers, lambda host: accepted(host, password), "Kontrollerer SSH-passord")
        passwords.update({host: password for host in workers if result[host]})
    for host in workers:
        if host in passwords:
            continue
        for _ in range(3):
            password = read_password(f"SSH-innloggingspassord for {user}@{host}: ")
            if accepted(host, password):
                passwords[host] = password
                break
            print(f"{host}: innlogging avvist. Prøv igjen.")
        else:
            raise RuntimeError(f"{host}: innlogging ble avvist. Kontroller brukeren og at passordinnlogging er tillatt.")
    return passwords


INSTALL_KEY = r'''set -eu
umask 077
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
key=$(cat)
if ! grep -qxF -- "$key" "$HOME/.ssh/authorized_keys"; then
  printf '\n%s\n' "$key" >> "$HOME/.ssh/authorized_keys"
fi
'''


def prepare_ssh(payload, workers, input_fn=input):
    if not workers:
        return {}
    trust_hosts(workers, input_fn)
    user = payload["ssh_user"]
    identity = payload.get("ssh_identity_file", "")

    def probe(host):
        result = ssh_run(user, host, "true", identity_file=identity)
        if result.returncode == 255 and "Permission denied" in result.stderr:
            return False
        require_ssh(result, host)
        return True

    ready = parallel(workers, probe, "Kontrollerer nøkkelinnlogging")
    needed = [host for host in workers if not ready[host]]
    if not needed:
        return {}
    print("Disse workerne trenger en SSH-nøkkel: " + ", ".join(needed))
    if not confirm("Klargjøre en clusternøkkel og legge den til på disse workerne?", input_fn):
        raise RuntimeError("Nøkkeloppsettet ble avbrutt.")
    identity, public = ensure_key(identity)
    passwords = login_passwords(user, needed, input_fn)

    def copy_key(host):
        result = ssh_run(user, host, INSTALL_KEY, login_password=passwords[host], stdin=public + "\n")
        require_ssh(result, host)
        require_ssh(ssh_run(user, host, "true", identity_file=identity), host)

    parallel(needed, copy_key, "Installerer og kontrollerer offentlig SSH-nøkkel")
    # If we selected a dedicated key, all selected hosts must accept it. Existing
    # accessible hosts can authorize it using their already working SSH access.
    for host in workers:
        if host not in needed:
            require_ssh(ssh_run(user, host, INSTALL_KEY, identity_file=payload.get("ssh_identity_file", ""), stdin=public + "\n"), host)
    return passwords


PROBE = r'''set -eu
. /etc/os-release
printf '%s\n' "$ID" "$(uname -m)" "$(id -u)" "$(hostname)" "$(cat /etc/machine-id)"
command -v sudo >/dev/null
command -v systemctl >/dev/null
case "$ID" in
  debian|ubuntu|raspbian) command -v apt-get >/dev/null ;;
  fedora) command -v dnf >/dev/null ;;
  *) exit 40 ;;
esac
if command -v git >/dev/null; then
  git -C "$HOME/Pi-display-lab" rev-parse HEAD 2>/dev/null || true
fi
'''


def inspect_worker(user, host, identity=""):
    result = ssh_run(user, host, PROBE, identity_file=identity)
    if result.returncode == 255:
        require_ssh(result, host)
    if result.returncode:
        raise RuntimeError("Krever Debian/Ubuntu/Raspberry Pi OS eller Fedora, systemd og en bruker med sudo.")
    lines = result.stdout.strip().splitlines()
    if len(lines) not in {5, 6} or lines[1] not in {"x86_64", "aarch64", "armv7l", "armv8l"}:
        raise RuntimeError("Ustøttet eller ukjent prosessorarkitektur; forventet x86-64 eller ARM.")
    if lines[2] == "0":
        raise RuntimeError("SSH-brukeren må være en vanlig bruker, ikke root.")
    if not re.fullmatch(r"[0-9a-f]{32}", lines[4]):
        raise RuntimeError("Maskinen mangler en gyldig /etc/machine-id.")
    return {"os": lines[0], "arch": lines[1], "hostname": lines[3], "machine_id": lines[4],
            "revision": lines[5] if len(lines) == 6 else ""}


def ansible_target_python_limit(project):
    """Match the supported target range to the Ansible actually installed locally."""
    result = subprocess.run(
        [str(Path(project) / ".ansible-venv/bin/python"), "-c",
         "from ansible.release import __version__; print(__version__)"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    version = result.stdout.strip().split(".")[:2]
    if version == ["2", "19"]:
        return 13
    if version in (["2", "20"], ["2", "21"]):
        return 14
    raise RuntimeError("Ansible-versjonen støttes ikke av oppsettet. Kjør bash scripts/setup-cluster.sh.")


def check_worker_python(user, host, identity, highest_minor):
    code = 'import sys; print(".".join(map(str, sys.version_info[:2])))'
    result = ssh_run(user, host, "python3 -c " + shlex.quote(code), identity_file=identity)
    require_ssh(result, host)
    if not re.fullmatch(r"3\.\d+", result.stdout.strip()):
        raise RuntimeError("Kunne ikke lese workerens Python-versjon.")
    if not 10 <= int(result.stdout.strip().split(".")[1]) <= highest_minor:
        raise RuntimeError(
            f"Python {result.stdout.strip()} støttes ikke av denne installasjonen (3.10–3.{highest_minor}). "
            "Workers med Python 3.14 krever Python 3.12–3.14 på koordinatoren og oppdatert Ansible. "
            "Oppgrader koordinatorens OS/Python og kjør oppsettet på nytt."
        )


def plan_hostnames(nodes, existing_names=(), local_machine_id="", existing_ids=()):
    seen_ids = set(existing_ids) | ({local_machine_id} if local_machine_id else set())
    reserved = set(existing_names) | {socket.gethostname()}
    renames = {}
    for host, node in nodes.items():
        if node["machine_id"] in seen_ids:
            raise RuntimeError(f"{host}: samme maskin er registrert flere ganger, eller nodene har klonet machine-id.")
        seen_ids.add(node["machine_id"])
        name = node["hostname"]
        if not valid_worker_id(name) or name in reserved:
            index = 1
            while f"worker-{index:03d}" in reserved or any(n["hostname"] == f"worker-{index:03d}" for n in nodes.values()):
                index += 1
            renames[host] = f"worker-{index:03d}"
            name = renames[host]
        reserved.add(name)
    return renames


def prerequisite_script(family, hostname=""):
    if family in {"debian", "ubuntu", "raspbian"}:
        script = r'''set -eu
export DEBIAN_FRONTEND=noninteractive
missing=""
for package in git python3 python3-venv python3-packaging; do
  [ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" = 'install ok installed' ] || missing="$missing $package"
done
if [ -n "$missing" ]; then
  apt-get update
  apt-get install -y -o Dpkg::Options::=--force-confold $missing
fi
'''
    elif family == "fedora":
        script = r'''set -eu
missing=""
for package in git python3 python3-pip python3-packaging python3-libdnf5; do
  rpm -q "$package" >/dev/null 2>&1 || missing="$missing $package"
done
if [ -n "$missing" ]; then dnf --refresh -y install $missing; fi
'''
    else:
        raise RuntimeError(f"Ustøttet operativsystem: {family}")
    script += "python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'\n"
    if hostname:
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", hostname) is None:
            raise RuntimeError("Ugyldig nytt hostname")
        # Keep the loopback name consistent to avoid sudo hostname warnings.
        update_hosts = "from pathlib import Path; p=Path('/etc/hosts'); s=p.read_text(); lines=s.splitlines(); lines=[line for line in lines if not line.split() or line.split()[0]!='127.0.1.1']; p.write_text('\\n'.join(lines)+'\\n127.0.1.1 '+" + repr(hostname) + "+'\\n')"
        script += "hostnamectl set-hostname " + shlex.quote(hostname) + "\n"
        script += "python3 -c " + shlex.quote(update_hosts) + "\n"
    return script


def prepare_workers(payload, workers, *, existing_nodes=None, input_fn=input):
    login = prepare_ssh(payload, workers, input_fn)
    user, identity = payload["ssh_user"], payload.get("ssh_identity_file", "")
    nodes = parallel(workers, lambda host: inspect_worker(user, host, identity), "Kontrollerer operativsystem og nodeidentitet")
    local_id = Path("/etc/machine-id").read_text().strip() if Path("/etc/machine-id").is_file() else ""
    # Keep registration order independent of completion order in the parallel probe.
    nodes = {host: nodes[host] for host in workers}
    existing_nodes = existing_nodes or {}
    renames = plan_hostnames(nodes, [node['hostname'] for node in existing_nodes.values()], local_id,
                             [node['machine_id'] for node in existing_nodes.values()])
    for host in renames:
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            raise RuntimeError(f"{host}: hostname må endres. Registrer denne noden med IPv4-adresse så forbindelsen beholdes etter navnebyttet.") from None
    for host, node in nodes.items():
        print(f"  {host}: {node['os']}, {node['arch']}, {node['hostname']}")
    if renames:
        for host, name in renames.items():
            print(f"  Nytt unikt hostname: {host} → {name}")
        if not confirm("Bruke disse nye vertsnavnene?", input_fn):
            raise RuntimeError("Sett unike vertsnavn på nodene og kjør veiviseren igjen.")
    reuse = bool(login) and confirm("Prøve SSH-innloggingspassordene også som sudo-passord?", input_fn)
    passwords = collect_passwords(user, workers, identity_file=identity,
                                  initial_passwords=login if reuse else None, input_fn=input_fn)
    if workers and not confirm("Klargjøre nødvendige systempakker på disse workerne nå?", input_fn):
        raise RuntimeError("Klargjøringen ble avbrutt; opprettede SSH-nøkler er bevart.")

    def provision(host):
        script = prerequisite_script(nodes[host]["os"], renames.get(host, ""))
        password = passwords[host]
        sudo = "sudo -S -p ''" if password else "sudo -n"
        result = ssh_run(user, host, sudo + " /bin/sh -c " + shlex.quote(script),
                         identity_file=identity, stdin=password + "\n" if password else "", timeout=900)
        if result.returncode:
            detail = "\n".join((result.stderr or result.stdout).splitlines()[-8:])
            raise RuntimeError("Pakkeoppsett feilet. Worker trenger Python 3.10+ og fungerende pakkekilder.\n" + detail)

    parallel(workers, provision, "Klargjør worker-pakker")
    return passwords


def prepare_removal(payload, removed, input_fn=input):
    if not confirm("Også stoppe og deaktivere worker- og node-agent-tjenestene på nodene som fjernes?", input_fn):
        return {}
    user, identity = payload["ssh_user"], payload.get("ssh_identity_file", "")

    def reachable(host):
        try:
            result = ssh_run(user, host, "true", identity_file=identity)
            require_ssh(result, host)
            return True
        except RuntimeError:
            print(f"{host}: kan ikke nås med godkjent SSH-nøkkel. Tilgangen tilbakekalles likevel på koordinatoren.", flush=True)
            return False

    ready = parallel(removed, reachable, "Kontrollerer noder som skal fjernes")
    available = [host for host in removed if ready[host]]
    try:
        return collect_passwords(user, available, identity_file=identity, input_fn=input_fn)
    except RuntimeError as error:
        print(f"Kunne ikke klargjøre stopp av tjenester: {error}")
        if confirm("Fortsette med tilbakekalling av tilgang uten å stoppe tjenestene?", input_fn):
            return {}
        raise


def stop_removed_workers(payload, passwords):
    script = r'''set -eu
for service in cluster-worker.service pi-display-node-agent.service; do
  if systemctl cat "$service" >/dev/null 2>&1; then
    systemctl disable --now "$service"
  fi
done
'''
    user, identity = payload["ssh_user"], payload.get("ssh_identity_file", "")

    def stop(host):
        password = passwords[host]
        sudo = "sudo -S -p ''" if password else "sudo -n"
        result = ssh_run(user, host, sudo + " /bin/sh -c " + shlex.quote(script),
                         identity_file=identity, stdin=password + "\n" if password else "", timeout=90)
        require_ssh(result, host)

    try:
        parallel(list(passwords), stop, "Stopper og deaktiverer fjernede worker-tjenester")
        return True
    except RuntimeError as error:
        print(f"Tilgangen er tilbakekalt, men noen tjenester kunne ikke stoppes:\n{error}")
        return False
