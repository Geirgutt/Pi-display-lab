"""Statiske sikkerhetsnett for den beginner-vennlige installasjonen."""

import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent


class InstallationWorkflowTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (PROJECT_DIR / relative_path).read_text(encoding="utf-8")

    def test_installer_handles_local_and_worker_sudo_without_weakening_ssh(self) -> None:
        installer = self.read("scripts/install-cluster.sh")
        preflight = self.read("scripts/preflight-cluster.py")
        self.assertIn("sudo -v", installer)
        self.assertIn("--ask-become-pass", installer)
        self.assertIn("StrictHostKeyChecking=yes", preflight)
        self.assertNotIn("StrictHostKeyChecking=no", installer + preflight)
        self.assertNotIn("ANSIBLE_HOST_KEY_CHECKING", installer + preflight)

    def test_workers_are_pinned_and_receive_no_admin_token(self) -> None:
        installer = self.read("scripts/install-cluster.sh")
        playbook = self.read("ansible/install-workers.yml")
        self.assertIn('REVISION="$(git rev-parse HEAD)"', installer)
        self.assertIn('version: "{{ project_version }}"', playbook)
        self.assertIn("worker_revision.stdout == project_version", playbook)
        self.assertNotIn("admin_token", playbook)
        self.assertIn("no_log: true", playbook)

    def test_services_are_non_root_and_have_low_risk_hardening(self) -> None:
        playbook = self.read("ansible/install-workers.yml")
        controller_units = "".join(
            self.read(path)
            for path in (
                "scripts/install-service.sh",
                "scripts/install-coordinator-service.sh",
            )
        )
        self.assertIn("ansible_user_uid | int != 0", playbook)
        self.assertIn("NoNewPrivileges=true", playbook)
        self.assertIn("User=$RUN_USER", controller_units)
        self.assertIn("NoNewPrivileges=true", controller_units)

    def test_verification_uses_no_become_for_read_only_service_checks(self) -> None:
        verify = self.read("scripts/verify-cluster.sh")
        self.assertNotIn("--become", verify)
        self.assertNotIn(" -b ", verify)
        self.assertIn("verify-controller-api.py", verify)

    def test_update_remains_explicit_and_fast_forward_only(self) -> None:
        update = self.read("scripts/update.sh")
        self.assertIn("git merge --ff-only", update)
        self.assertIn("git ls-files --others --exclude-standard", update)
        self.assertIn("bash scripts/install-cluster.sh", update)


if __name__ == "__main__":
    unittest.main()
