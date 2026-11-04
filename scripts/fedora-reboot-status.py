"""Read Fedora reboot hints without installing plugins or changing packages."""

import json
import shutil
import subprocess


def reboot_status():
    dnf5 = shutil.which("dnf5")
    command = [dnf5 or shutil.which("dnf") or "dnf", "needs-restarting"]
    if not dnf5:
        command.append("-r")
    try:
        # Missing plugins often return 1 too; don't mistake that for a reboot hint.
        probe = subprocess.run(command + ["--help"], capture_output=True, text=True)
        if probe.returncode:
            return {"reboot_required": None, "reason": "needs-restarting er ikke tilgjengelig"}
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError:
        return {"reboot_required": None, "reason": "dnf kunne ikke kjøres"}
    if result.returncode not in (0, 1) or result.stderr.strip():
        return {"reboot_required": None, "reason": "needs-restarting kunne ikke avgjøre omstartsstatus"}
    return {"reboot_required": result.returncode == 1}


if __name__ == "__main__":
    print(json.dumps(reboot_status()))
