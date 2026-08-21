"""Lesende versjonssjekk mot prosjektets konfigurerte Git-remote."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any


class UpdateManager:
    """Sjekker om origin/main har en nyere fast-forward-commit."""

    BUSY_STATES = {"checking"}

    def __init__(self, project_dir: Path | None = None) -> None:
        self.project_dir = (project_dir or Path(__file__).resolve().parent).resolve()
        self._lock = threading.Lock()
        worktree_status = self._git_optional("status", "--porcelain")
        self._state: dict[str, Any] = {
            "status": "idle",
            "message": "Oppdateringsstatus er ikke sjekket",
            "current_commit": self._git_optional("rev-parse", "--short", "HEAD"),
            "available_commit": None,
            "commit_url": None,
            "worktree_clean": worktree_status == "",
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def check_async(self) -> bool:
        if not self._begin("checking", "Sjekker GitHub for ny versjon ..."):
            return False
        threading.Thread(target=self._check, daemon=True, name="update-check").start()
        return True

    def _begin(self, status: str, message: str) -> bool:
        with self._lock:
            if self._state["status"] in self.BUSY_STATES:
                return False
            self._state.update(status=status, message=message)
        return True

    def _check(self) -> None:
        try:
            branch = self._git("branch", "--show-current")
            if branch != "main":
                raise RuntimeError(f"Versjonssjekk krever main, ikke {branch or 'detached HEAD'}")

            self._git("fetch", "origin", "main")
            current = self._git("rev-parse", "HEAD")
            remote = self._git("rev-parse", "origin/main")
            clean = not bool(self._git("status", "--porcelain"))
            if current == remote:
                self._finish(
                    "current",
                    "Appen er oppdatert",
                    current_commit=current[:8],
                    available_commit=None,
                    commit_url=None,
                    worktree_clean=clean,
                )
                return

            ancestor = subprocess.run(
                ["git", "merge-base", "--is-ancestor", current, remote],
                cwd=self.project_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if ancestor.returncode != 0:
                raise RuntimeError("Lokal historikk avviker fra origin/main; sjekk via SSH")

            origin = self._git_optional("remote", "get-url", "origin")
            self._finish(
                "available",
                "Ny versjon tilgjengelig; kontroller endringen og oppdater via SSH",
                current_commit=current[:8],
                available_commit=remote[:8],
                commit_url=self._github_commit_url(origin, remote),
                worktree_clean=clean,
            )
        except (OSError, subprocess.SubprocessError, RuntimeError) as error:
            self._finish("error", str(error), commit_url=None)

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.project_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
        return result.stdout.strip()

    def _git_optional(self, *args: str) -> str | None:
        try:
            return self._git(*args)
        except (OSError, subprocess.SubprocessError):
            return None

    def _finish(self, status: str, message: str, **values: Any) -> None:
        with self._lock:
            self._state.update(status=status, message=message, **values)

    @staticmethod
    def _github_commit_url(remote: str | None, commit: str) -> str | None:
        """Lag en nettleserlenke bare for kjente GitHub-remote-formater."""

        if not remote:
            return None
        repository: str | None = None
        if remote.startswith("https://github.com/"):
            repository = remote.removeprefix("https://github.com/")
        elif remote.startswith("git@github.com:"):
            repository = remote.removeprefix("git@github.com:")
        if not repository:
            return None
        repository = repository.removesuffix(".git").strip("/")
        if repository.count("/") != 1:
            return None
        return f"https://github.com/{repository}/commit/{commit}"
