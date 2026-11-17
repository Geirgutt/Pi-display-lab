#!/usr/bin/env python3
"""Felles terminalmeny for oppsett, vedlikehold og status på Pi-controlleren."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from config import load_config


@dataclass(frozen=True)
class Action:
    label: str
    description: str
    command: tuple[str, ...] = ()
    config_required: bool = False
    venv_required: bool = False
    workers: bool = False
    reload_after: bool = False


SECTIONS = {
    "1": ("Konfigurasjon", (
        Action("Koble til / fornye Spotify", "Koble kontoen til denne Pi-en. Client Secret trengs ikke.",
               ("@python", "scripts/configure-spotify.py")),
        Action("Garmin og kalendere", "Sett opp Garmin API-nøkkel, kommende økter og private ICS-kalendere.",
               ("bash", "scripts/configure-integrations.sh", "--reset"), venv_required=True),
        Action("Legg til clusternoder", "Registrer og klargjør nye workers; eksisterende noder beholdes.",
               ("bash", "scripts/setup-cluster.sh", "--action", "add"), config_required=True),
        Action("Fjern clusternoder", "Velg workers som skal fjernes. Veiviseren ber om bekreftelse.",
               ("bash", "scripts/setup-cluster.sh", "--action", "remove"), config_required=True),
        Action("Endre controller / nettverksinnstillinger", "Åpne nettverksdelen av cluster-veiviseren.",
               ("bash", "scripts/setup-cluster.sh", "--action", "network"), config_required=True),
        Action("Cluster-oppsett / førstegangsinstallasjon", "Start eksisterende oppsettsveiviser.",
               ("bash", "scripts/setup-cluster.sh")),
    )),
    "2": ("Vedlikehold", (
        Action("Oppdater programvaren", "Hent siste Git-versjon og oppdater nødvendige deler av laben.",
               ("bash", "scripts/update.sh"), reload_after=True),
        Action("Oppdater bare DeskDisplay", "Hent siste versjon og velg USB eller OTA i oppdateringen.",
               ("bash", "scripts/update.sh", "--display-only"), config_required=True, reload_after=True),
        Action("Workers: oppdater pakkelister", "Velg noder. Installerte OS-pakker oppgraderes ikke.",
               ("bash", "scripts/maintain-workers.sh", "--update-only"), config_required=True, workers=True),
        Action("Workers: oppgrader OS-pakker", "Velg noder for pakkeoppgradering. Ingen automatisk omstart.",
               ("bash", "scripts/maintain-workers.sh", "--upgrade"), config_required=True, workers=True),
        Action("Synkroniser Garmin og kalendere nå", "Start den eksisterende synkroniseringstjenesten.",
               ("sudo", "systemctl", "start", "pi-display-integrations.service"), venv_required=True),
        Action("Reinstaller nåværende cluster-oppsett", "Bruk lokal konfigurasjon og eksisterende nøkler i veiviseren.",
               ("bash", "scripts/setup-cluster.sh", "--action", "reinstall"), config_required=True),
        Action("Full programoppdatering / reparasjon", "Hent siste Git-versjon og kjør full installasjon.",
               ("bash", "scripts/update.sh", "--full"), reload_after=True),
    )),
    "3": ("Status og feilsøking", (
        Action("Vis lokalt oppsett", "Vis controller, registrerte workers og skjermoppsett uten hemmeligheter."),
        Action("Kontroller hele clusteret", "Kontroller tjenester, API, SSH, versjoner og TLS.",
               ("bash", "scripts/verify-cluster.sh"), config_required=True, venv_required=True),
        Action("Vis tjenestestatus", "Vis også om tjenester er stoppet eller ikke installert.",
               ("systemctl", "--no-pager", "--full", "status", "pi-display-lab.service",
                "cluster-coordinator.service", "deskdisplay-secure-peer.service", "pi-display-integrations.timer")),
        Action("Vis siste logger", "Velg tjeneste og vis de siste 60 logglinjene."),
    )),
}

LOG_SERVICES = (
    ("Controller", "pi-display-lab.service"),
    ("Cluster-koordinator", "cluster-coordinator.service"),
    ("DeskDisplay-forbindelse", "deskdisplay-secure-peer.service"),
    ("Garmin / kalendersynk", "pi-display-integrations.service"),
)


class Menu:
    def __init__(self, project: Path, *, input_fn=input, runner=subprocess.run, restart=None, revision_reader=None):
        self.project = project.resolve()
        self.input = input_fn
        self.runner = runner
        self.restart = restart or self._restart
        self.revision = revision_reader or self._revision

    def _revision(self) -> str | None:
        try:
            result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.project,
                                    capture_output=True, text=True, check=False)
            return result.stdout.strip() if result.returncode == 0 else None
        except OSError:
            return None

    def _restart(self):
        # The updater may have replaced this menu. Load the fetched version.
        os.execv(sys.executable, [sys.executable, str(self.project / "meny.py")])

    def _python(self) -> str:
        bundled = self.project / ".venv/bin/python"
        return str(bundled) if bundled.is_file() else sys.executable

    def _choose(self, title: str, labels: list[str], *, top=False) -> int:
        while True:
            print(f"\n{'=' * 52}\n{title}\n{'=' * 52}")
            for index, label in enumerate(labels, 1):
                print(f"  {index}. {label}")
            print("  0. " + ("Avslutt" if top else "Tilbake"))
            answer = self.input("Velg: ").strip()
            if answer.isascii() and answer.isdigit() and 0 <= int(answer) <= len(labels):
                return int(answer)
            print("Velg et av numrene i menyen.")

    def choose_workers(self) -> list[str] | None:
        workers = load_config(self.project / "config.local.json").worker_hosts
        if not workers:
            print("Ingen workers er registrert. Bruk Konfigurasjon → Cluster-oppsett først.")
            return None
        print("\nRegistrerte workers:")
        for index, host in enumerate(workers, 1):
            print(f"  {index}. {host}")
        print("Skriv nummer med mellomrom/komma, a for alle, eller 0 for å avbryte.")
        while True:
            answer = self.input("Velg workers: ").strip().lower()
            if answer == "0":
                return None
            if answer in {"a", "alle"}:
                return list(workers)
            parts = answer.replace(",", " ").split()
            if parts and all(p.isascii() and p.isdigit() and 1 <= int(p) <= len(workers) for p in parts):
                return list(dict.fromkeys(workers[int(p) - 1] for p in parts))
            print("Velg gyldige nummer, a for alle eller 0 for å avbryte.")

    def show_config(self):
        if not (self.project / "config.local.json").is_file():
            print("Clusteret er ikke konfigurert. Velg Konfigurasjon → Cluster-oppsett.")
            return
        settings = load_config(self.project / "config.local.json")
        print(f"\nRolle: {settings.node_role}\nController: {settings.controller_host}")
        print(f"SSH-bruker: {settings.ssh_user or 'ikke valgt'}")
        print(f"Workers ({len(settings.worker_hosts)}):")
        for host in settings.worker_hosts:
            print(f"  - {host}")
        print("DeskDisplay: " + ("aktivert" if settings.deskdisplay.enabled else "deaktivert"))
        print("USB-vert: " + (settings.deskdisplay.display_host or "ikke valgt"))
        print("OTA: " + ("klargjort" if settings.deskdisplay.display_ota_ready else "ikke klargjort"))

    def execute(self, section: str, index: int, action: Action):
        print(f"\n{action.label}\n{action.description}")
        if action.config_required and not (self.project / "config.local.json").is_file():
            print("Lokal cluster-konfigurasjon mangler. Velg Konfigurasjon → Cluster-oppsett først.")
            return
        if action.venv_required and not (self.project / ".venv/bin/python").is_file():
            print("Controlleren er ikke installert. Velg Konfigurasjon → Cluster-oppsett først.")
            return
        command = list(action.command)
        if section == "3" and index == 1:
            self.show_config()
            return
        if section == "3" and index == 4:
            selected = self._choose("Logger", [name for name, _ in LOG_SERVICES])
            if not selected:
                return
            command = ["sudo", "journalctl", "--no-pager", "-n", "60", "-u", LOG_SERVICES[selected - 1][1]]
        if action.workers:
            workers = self.choose_workers()
            if workers is None:
                return
            for host in workers:
                command.extend(["--worker", host])
            print("Valgte workers: " + ", ".join(workers))
        if command[0] == "@python":
            command[0] = self._python()
        print("\nKjører: " + shlex.join(command), flush=True)
        before = self.revision() if action.reload_after else None
        try:
            result = self.runner(command, cwd=self.project, check=False)
            returncode = result.returncode
        except KeyboardInterrupt:
            print("\nHandlingen ble avbrutt.")
            returncode = 130
        except OSError as error:
            print(f"Kunne ikke starte handlingen: {error}")
            return
        if returncode:
            print(f"\nHandlingen avsluttet med kode {returncode}. Se meldingen over.")
        if action.reload_after:
            after = self.revision()
            if returncode == 0 or (before is not None and after is not None and before != after):
                if returncode:
                    self.input("\nNy kode ble hentet før handlingen stoppet. Trykk Enter for å laste menyen på nytt ...")
                print("\nLaster menyen fra den oppdaterte versjonen ...", flush=True)
                self.restart()
        else:
            if not returncode:
                print("\nFerdig. Du kan velge en ny handling i menyen.")

    def run(self) -> int:
        while True:
            section_number = self._choose("PI DISPLAY LAB", [title for title, _ in SECTIONS.values()], top=True)
            if not section_number:
                return 0
            section = str(section_number)
            title, actions = SECTIONS[section]
            while True:
                index = self._choose(title, [action.label for action in actions])
                if not index:
                    break
                self.execute(section, index, actions[index - 1])
                self.input("\nTrykk Enter for å gå tilbake til menyen ...")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if not sys.platform.startswith("linux"):
        print("Menyen skal kjøres på Pi-controlleren med Linux: python3 meny.py")
        return 2
    if os.geteuid() == 0:
        print("Start menyen som vanlig controller-bruker, uten sudo. Handlingene ber om sudo ved behov.")
        return 2
    try:
        return Menu(Path(__file__).resolve().parent).run()
    except (EOFError, KeyboardInterrupt):
        print("\nMenyen er avsluttet.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
