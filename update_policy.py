"""Conservative classification of repository updates.

The updater may only choose a reduced deployment when every changed path is
known to be safe for that deployment. Unknown paths are deliberately returned
as ``ask`` so the operator can choose a full update or stop.
"""

from __future__ import annotations

from collections.abc import Iterable


QUICK_FILES = {
    "ansible/update-workers.yml",
    "ansible/verify-workers.yml",
    "app.py",
    "cluster_client.py",
    "cluster_coordinator.py",
    "cluster_install.py",
    "cluster_jobs.py",
    "cluster_worker.py",
    "display_state.py",
    "node_agent.py",
    "scripts/check-cluster-pki.py",
    "scripts/classify-update.py",
    "scripts/install-cluster.sh",
    "scripts/quick-update-controller.sh",
    "scripts/update.sh",
    "training.py",
    "transports.py",
    "update_policy.py",
    "updates.py",
}
QUICK_PREFIXES = ("static/", "templates/")
NEUTRAL_FILES = {"LICENSE", "README.md", "SECURITY.md"}
NEUTRAL_PREFIXES = ("tests/",)
FULL_FILES = {
    "cluster_auth.py",
    "cluster_bootstrap.py",
    "cluster_pki.py",
    "cluster_ssh.py",
    "cluster_tls.py",
    "config.py",
    "config.example.json",
    "requirements.txt",
    "requirements-ansible.txt",
    "requirements-test.txt",
    "setup_cluster.py",
}
FULL_PREFIXES = ("ansible/", "scripts/")
DISPLAY_NEUTRAL_PREFIXES = ("deskdisplay/docs/",)


def _matches(path: str, files: set[str], prefixes: tuple[str, ...]) -> bool:
    return path in files or path.startswith(prefixes)


def classify_paths(paths: Iterable[str]) -> tuple[str, bool, tuple[str, ...]]:
    """Return ``(mode, display_changed, unknown_paths)``.

    ``mode`` is one of none, display, quick, full or ask. Display changes can
    accompany quick/full changes; an otherwise display-only revision gets the
    dedicated display mode.
    """

    changed = tuple(dict.fromkeys(path for path in paths if path))
    if not changed:
        return "none", False, ()

    display_changed = any(
        path.startswith("deskdisplay/")
        and not path.startswith(DISPLAY_NEUTRAL_PREFIXES)
        for path in changed
    )
    non_display = tuple(
        path
        for path in changed
        if not path.startswith("deskdisplay/")
        and not _matches(path, NEUTRAL_FILES, NEUTRAL_PREFIXES)
    )
    if display_changed and not non_display:
        return "display", True, ()

    if any(
        _matches(path, FULL_FILES, FULL_PREFIXES)
        and not _matches(path, QUICK_FILES, QUICK_PREFIXES)
        for path in non_display
    ):
        return "full", display_changed, ()

    unknown = tuple(
        path
        for path in non_display
        if not _matches(path, QUICK_FILES, QUICK_PREFIXES)
    )
    if unknown:
        return "ask", display_changed, unknown
    return "quick", display_changed, ()
