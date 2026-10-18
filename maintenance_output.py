"""Terminal output for the OS maintenance playbook."""

from __future__ import annotations

import re
import sys
import threading
import time
from typing import TextIO


STAGES = ("refresh", "before", "available", "upgrade", "after", "remaining", "reboot")
STAGE_LABELS = {
    "refresh": "oppdaterer pakkelister",
    "before": "leser installerte pakker før vedlikehold",
    "available": "finner tilgjengelige oppgraderinger",
    "upgrade": "oppgraderer pakker",
    "after": "leser installerte pakker etter vedlikehold",
    "remaining": "kontrollerer gjenstående oppgraderinger",
    "reboot": "kontrollerer omstart",
}
_UPGRADABLE_RE = re.compile(r"^([^/]+)/\S+\s+(\S+)\s+\S+\s+\[upgradable from: (.+)]$")


class MaintenanceOutput:
    """Render measured node and package progress without inventing percentages."""

    def __init__(self, workers: list[str], upgrade: bool, stream: TextIO | None = None):
        self.workers = list(workers)
        self.upgrade = upgrade
        self.stream = stream if stream is not None else sys.stdout
        self._lock = threading.RLock()
        self._pulse_lifecycle_lock = threading.Lock()
        self._nodes = {
            host: {"completed": set(), "failed": False, "before": None,
                   "after": None, "remaining": None, "reboot": None}
            for host in self.workers
        }
        self._pulse_stop = threading.Event()
        self._pulse_thread: threading.Thread | None = None
        self._pulse_started = 0.0
        self._active: tuple[str, str] | None = None
        self._finished = False

    def start(self, host: str, stage: str) -> None:
        self._check_host_stage(host, stage)
        with self._pulse_lifecycle_lock:
            self._stop_pulse()
            with self._lock:
                self._active = (host, stage)
                progress = self._node_progress(host)
                self._write(f"{host}: {STAGE_LABELS[stage]} ({progress}).")
                if stage in ("refresh", "upgrade") and self._is_tty():
                    # The previous pulse thread is joined before this shared Event is reset.
                    self._pulse_stop.clear()
                    self._pulse_started = time.monotonic()
                    self._pulse_thread = threading.Thread(
                        target=self._pulse, args=(host, stage), daemon=True,
                        name="maintenance-progress",
                    )
                    self._pulse_thread.start()

    def result(self, host: str, stage: str, result: dict, skipped: bool = False) -> None:
        self._check_host_stage(host, stage)
        with self._pulse_lifecycle_lock:
            self._stop_pulse()
            with self._lock:
                node = self._nodes[host]
                node["completed"].add(stage)
                self._active = None
                if skipped and stage == "upgrade":
                    self._write(f"{host}: pakkeoppgraderingen ble ikke kjørt.")
                elif skipped:
                    self._write(f"{host}: {STAGE_LABELS[stage]} – hoppet over.")
                else:
                    self._render_result(host, stage, result or {}, node)
                self._write_progress(host)

    def fail(self, host: str, message: str) -> None:
        if host not in self._nodes:
            raise ValueError(f"Ukjent worker: {host}")
        with self._pulse_lifecycle_lock:
            self._stop_pulse()
            with self._lock:
                self._active = None
                self._nodes[host]["failed"] = True
                self._write(f"{host}: FEIL – {message.strip() or 'vedlikeholdet feilet'}")
                self._write_progress(host)

    def finish(self) -> None:
        with self._pulse_lifecycle_lock:
            self._stop_pulse()
            with self._lock:
                if self._finished:
                    return
                self._active = None
                self._finished = True
                failed = sum(node["failed"] for node in self._nodes.values())
                completed = sum(
                    not node["failed"] and len(node["completed"]) == len(STAGES)
                    for node in self._nodes.values()
                )
                pending = len(self._nodes) - completed - failed
                self._write(
                    f"Vedlikehold ferdig: {completed} fullført, {failed} feilet, "
                    f"{pending} ufullstendig av {len(self._nodes)} workers."
                )
                for host in self.workers:
                    node = self._nodes[host]
                    before = node["before"]
                    after = node["after"]
                    if not self.upgrade:
                        installed = upgraded = 0
                    else:
                        changes = self._package_changes(before, after) if before is not None and after is not None else None
                        installed = sum(old is None for _name, old, _new in changes) if changes is not None else None
                        upgraded = sum(old is not None for _name, old, _new in changes) if changes is not None else None
                    remaining = node["remaining"]
                    reboot = node["reboot"]
                    installed_text = "ukjent" if installed is None else str(installed)
                    upgraded_text = "ukjent" if upgraded is None else str(upgraded)
                    remaining_text = "ukjent" if remaining is None else str(len(remaining))
                    reboot_text = "ukjent" if reboot is None else ("kreves" if reboot else "ikke meldt")
                    status = "feilet" if node["failed"] else (
                        "ufullstendig" if len(node["completed"]) < len(STAGES) else "ferdig"
                    )
                    self._write(
                        f"  {host}: {status}; {installed_text} nye pakker; {upgraded_text} oppgradert; "
                        f"{remaining_text} oppgraderinger gjenstår; omstart {reboot_text}."
                    )

    def _render_result(self, host: str, stage: str, result: dict, node: dict) -> None:
        if stage in ("before", "after", "available", "remaining") and "stdout" not in result:
            self._write(f"{host}: pakkedata er ikke tilgjengelig for dette trinnet.")
            return
        if stage in ("before", "after"):
            node[stage] = self._parse_installed(result.get("stdout", ""))
            if stage == "before":
                self._write(f"{host}: {len(node['before'])} installerte pakker funnet.")
            elif node["before"] is not None:
                changes = self._package_changes(node["before"], node["after"])
                if changes:
                    self._write(f"{host}: {len(changes)} installerte pakker endret:")
                    for name, old, new in changes:
                        if old is None:
                            self._write(f"  + {name} {new} (ny installasjon)")
                        else:
                            self._write(f"  ~ {name} {old} → {new}")
                else:
                    self._write(f"{host}: ingen installerte pakker ble endret.")
        elif stage == "available":
            packages = self._parse_upgradable(result.get("stdout", ""))
            if not self.upgrade:
                node["remaining"] = packages
            self._write(f"{host}: {len(packages)} oppgraderinger tilgjengelig.")
            for name, old, new in packages:
                self._write(f"  {name}: {old} → {new}")
        elif stage == "remaining":
            packages = self._parse_upgradable(result.get("stdout", ""))
            node["remaining"] = packages
            self._write(f"{host}: {len(packages)} oppgraderinger gjenstår.")
            for name, _old, new in packages:
                self._write(f"  {name}: {new}")
        elif stage == "reboot":
            stat = result.get("stat", {})
            exists = stat.get("exists") if isinstance(stat, dict) else None
            node["reboot"] = exists if isinstance(exists, bool) else None
            if exists is True:
                self._write(f"{host}: omstart kreves.")
            elif exists is False:
                self._write(f"{host}: operativsystemet melder ikke behov for omstart.")
            else:
                self._write(f"{host}: omstartsstatus ukjent.")
        elif stage == "upgrade":
            self._write(f"{host}: pakkeoppgraderingen er ferdig.")
        elif stage == "refresh":
            self._write(f"{host}: pakkelistene er oppdatert.")

    @staticmethod
    def _parse_installed(stdout: str) -> dict[str, str]:
        installed = {}
        for line in stdout.splitlines():
            fields = line.split("\t", 2)
            if len(fields) == 3 and fields[0] == "installed":
                installed[fields[1]] = fields[2]
        return installed

    @staticmethod
    def _parse_upgradable(stdout: str) -> list[tuple[str, str, str]]:
        packages = []
        for line in stdout.splitlines():
            match = _UPGRADABLE_RE.match(line.strip())
            if match:
                name, new, old = match.groups()
                packages.append((name, old, new))
        return packages

    @staticmethod
    def _package_changes(before: dict[str, str], after: dict[str, str]) -> list[tuple[str, str | None, str]]:
        changes = []
        for name in sorted(after):
            old = before.get(name)
            new = after[name]
            if old != new:
                changes.append((name, old, new))
        return changes

    def _node_progress(self, host: str) -> str:
        done = len(self._nodes[host]["completed"])
        return f"[{self._bar(done, len(STAGES))}] trinn {done}/{len(STAGES)}"

    def _write_progress(self, host: str) -> None:
        completed = sum(
            not node["failed"] and len(node["completed"]) == len(STAGES)
            for node in self._nodes.values()
        )
        failed = sum(node["failed"] for node in self._nodes.values())
        pending = len(self._nodes) - completed - failed
        self._write(
            f"Fremdrift: [{self._bar(completed, len(self._nodes))}] "
            f"{completed} fullført, {failed} feilet, {pending} ufullstendig; "
            f"{host} {self._node_progress(host)}."
        )

    @staticmethod
    def _bar(done: int, total: int, width: int = 20) -> str:
        if total <= 0:
            return "-" * width
        filled = round(width * done / total)
        return "#" * filled + "-" * (width - filled)

    def _is_tty(self) -> bool:
        try:
            return bool(self.stream.isatty())
        except (AttributeError, OSError):
            return False

    def _pulse(self, host: str, stage: str) -> None:
        while not self._pulse_stop.wait(5):
            elapsed = int(time.monotonic() - self._pulse_started)
            with self._lock:
                if self._active != (host, stage):
                    return
                self.stream.write(f"\r{host}: {STAGE_LABELS[stage]} … {elapsed}s")
                self.stream.flush()

    def _stop_pulse(self) -> None:
        self._pulse_stop.set()
        thread = self._pulse_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()
            if self._is_tty():
                self.stream.write("\r" + " " * 100 + "\r")
                self.stream.flush()
        self._pulse_thread = None

    def _write(self, message: str) -> None:
        self.stream.write(message + "\n")
        self.stream.flush()

    def _check_host_stage(self, host: str, stage: str) -> None:
        if host not in self._nodes:
            raise ValueError(f"Ukjent worker: {host}")
        if stage not in STAGES:
            raise ValueError(f"Ukjent vedlikeholdstrinn: {stage}")
