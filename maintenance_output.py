"""Terminal output for the OS maintenance playbook."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
from collections import deque
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
                   "after": None, "available": None, "remaining": None, "reboot": None}
            for host in self.workers
        }
        self._pulse_stop = threading.Event()
        self._pulse_thread: threading.Thread | None = None
        self._active: dict[str, tuple[str, float]] = {}
        self._finished = False
        self._dashboard = (
            self._is_tty() and os.environ.get("TERM") != "dumb"
            and os.environ.get("PI_DISPLAY_MAINTENANCE_UI") != "plain"
        )
        self._panel_lines = 0
        self._phase = "Kontrollerer workers"
        self._status = {host: "venter" for host in self.workers}
        self._recent = deque(maxlen=3)
        self._details = []

    def phase(self, message: str) -> None:
        with self._lock:
            self._phase = message
            self._write(message)

    def checking(self, host: str, message: str) -> None:
        with self._lock:
            self._status[host] = message
            self._write(f"{host}: {message}")

    def start(self, host: str, stage: str) -> None:
        self._check_host_stage(host, stage)
        with self._pulse_lifecycle_lock:
            with self._lock:
                pulse_was_idle = not self._has_active_pulse()
            if pulse_was_idle:
                # Reap an exited timer before reusing its Event for a new run.
                self._stop_pulse()
            with self._lock:
                started = time.monotonic()
                self._active[host] = (stage, started)
                self._status[host] = STAGE_LABELS[stage]
                progress = self._node_progress(host)
                self._write(f"{host}: {STAGE_LABELS[stage]} ({progress}).")
                if (self._dashboard or stage in ("refresh", "upgrade")) and self._is_tty() and self._pulse_thread is None:
                    # The previous pulse thread was joined before this shared Event was reset.
                    self._pulse_stop.clear()
                    self._pulse_thread = threading.Thread(
                        target=self._pulse, daemon=True,
                        name="maintenance-progress",
                    )
                    self._pulse_thread.start()

    def result(self, host: str, stage: str, result: dict, skipped: bool = False) -> None:
        self._check_host_stage(host, stage)
        with self._pulse_lifecycle_lock:
            with self._lock:
                node = self._nodes[host]
                node["completed"].add(stage)
                self._active.pop(host, None)
                self._status[host] = "ferdig" if len(node["completed"]) == len(STAGES) else "venter på neste trinn"
                if skipped and stage == "upgrade":
                    self._write(f"{host}: pakkeoppgraderingen ble ikke kjørt.")
                elif skipped:
                    self._write(f"{host}: {STAGE_LABELS[stage]} – hoppet over.")
                else:
                    self._render_result(host, stage, result or {}, node)
                self._write_progress(host)
                pulse_remains_active = self._has_active_pulse()
            if not pulse_remains_active:
                self._stop_pulse()

    def fail(self, host: str, message: str) -> None:
        if host not in self._nodes:
            raise ValueError(f"Ukjent worker: {host}")
        with self._pulse_lifecycle_lock:
            with self._lock:
                self._active.pop(host, None)
                self._nodes[host]["failed"] = True
                self._status[host] = "FEIL"
                self._write(f"{host}: FEIL – {message.strip() or 'vedlikeholdet feilet'}")
                self._write_progress(host)
                pulse_remains_active = self._has_active_pulse()
            if not pulse_remains_active:
                self._stop_pulse()

    def finish(self) -> None:
        with self._pulse_lifecycle_lock:
            with self._lock:
                if self._finished:
                    return
                self._active.clear()
                self._finished = True
                if self._dashboard:
                    self._clear_panel()
                    self._dashboard = False
                    self._write("Detaljer fra vedlikeholdet:")
                    for message in self._details:
                        self._write(message)
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
            self._stop_pulse()

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
            packages = self._parse_upgradable(result.get("stdout", ""), node["before"])
            node["available"] = len(packages)
            if not self.upgrade:
                node["remaining"] = packages
            self._write(f"{host}: {len(packages)} oppgraderinger tilgjengelig.")
            for name, old, new in packages:
                self._write(f"  {name}: {old} → {new}")
        elif stage == "remaining":
            packages = self._parse_upgradable(result.get("stdout", ""), node["after"] or node["before"])
            node["remaining"] = packages
            self._write(f"{host}: {len(packages)} oppgraderinger gjenstår.")
            for name, _old, new in packages:
                self._write(f"  {name}: {new}")
        elif stage == "reboot":
            stat = result.get("stat", {})
            exists = stat.get("exists") if isinstance(stat, dict) else None
            if "stdout" in result:
                try:
                    exists = json.loads(result["stdout"]).get("reboot_required")
                except (ValueError, AttributeError):
                    exists = None
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
                installed.setdefault(fields[1], set()).add(fields[2])
        return {name: ", ".join(sorted(versions)) for name, versions in installed.items()}

    @staticmethod
    def _parse_upgradable(stdout: str, installed: dict | None = None) -> list[tuple[str, str, str]]:
        packages = []
        for line in stdout.splitlines():
            fields = line.split("\t")
            if len(fields) == 3 and fields[0] == "pi-update":
                packages.append((fields[1], (installed or {}).get(fields[1], "ukjent"), fields[2]))
                continue
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

    def _has_active_pulse(self) -> bool:
        return bool(self._active) if self._dashboard else any(
            stage in ("refresh", "upgrade") for stage, _started in self._active.values()
        )

    def _pulse(self) -> None:
        while not self._pulse_stop.wait(1 if self._dashboard else 5):
            now = time.monotonic()
            with self._lock:
                active = [
                    (host, stage, started)
                    for host, (stage, started) in self._active.items()
                    if self._dashboard or stage in ("refresh", "upgrade")
                ]
                if not active:
                    return
                lines = [
                    f"{host}: {STAGE_LABELS[stage]} … {int(now - started)}s"
                    for host, stage, started in active
                ]
                if self._dashboard:
                    self._draw_panel(now)
                else:
                    self._write("Pågår: " + "; ".join(lines) + ".")

    def _stop_pulse(self) -> None:
        self._pulse_stop.set()
        thread = self._pulse_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()
        self._pulse_thread = None

    def _write(self, message: str) -> None:
        # Remote output must never inject terminal controls into the panel/log.
        message = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", message)
        if self._dashboard:
            if not message.startswith("Fremdrift:"):
                self._details.append(message)
                self._recent.append(message.strip().splitlines()[0] if message.strip() else "")
            self._draw_panel()
            return
        self.stream.write(message + "\n")
        self.stream.flush()

    def _clear_panel(self) -> None:
        if self._panel_lines:
            self.stream.write(f"\x1b[{self._panel_lines}A\r\x1b[J")
            self._panel_lines = 0

    def _draw_panel(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        columns, rows = shutil.get_terminal_size((100, 24))
        completed = sum(not n["failed"] and len(n["completed"]) == len(STAGES) for n in self._nodes.values())
        failed = sum(n["failed"] for n in self._nodes.values())
        lines = ["WORKER-VEDLIKEHOLD | " + self._phase,
                 f"[{self._bar(completed, len(self.workers))}] {completed}/{len(self.workers)} fullført | {failed} feilet",
                 "Fremdrift = fullførte trinn; ventetid gjelder aktivt trinn.", ""]
        capacity = max(1, (rows - 10) // 2)
        visible = self.workers
        if len(visible) > capacity:
            visible = sorted(visible, key=lambda h: (h not in self._active, not self._nodes[h]["failed"]))[:capacity]
        for host in visible:
            node = self._nodes[host]
            active = self._active.get(host)
            elapsed = f" ({int(now - active[1])}s)" if active else ""
            available = "?" if node["available"] is None else str(node["available"])
            remaining = "?" if node["remaining"] is None else str(len(node["remaining"]))
            lines.append(f"{host}: {self._node_progress(host)} | tilgjengelig {available}, gjenstår {remaining}")
            reboot = " | OMSTART KREVES" if node["reboot"] else ""
            lines.append(f"  {self._status[host]}{elapsed}{reboot}")
        if len(visible) < len(self.workers):
            lines.append(f"+ {len(self.workers) - len(visible)} øvrige workers (alle i sluttrapporten)")
        lines += ["", "Siste hendelser:", *self._recent]
        self._clear_panel()
        # Leave one column spare to avoid automatic terminal wrapping.
        self.stream.write("".join(line[:max(1, columns - 1)] + "\n" for line in lines[:max(1, rows - 1)]))
        self._panel_lines = min(len(lines), max(1, rows - 1))
        self.stream.flush()

    def _check_host_stage(self, host: str, stage: str) -> None:
        if host not in self._nodes:
            raise ValueError(f"Ukjent worker: {host}")
        if stage not in STAGES:
            raise ValueError(f"Ukjent vedlikeholdstrinn: {stage}")
