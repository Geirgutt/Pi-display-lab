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
        session = self.read("scripts/sudo-session.sh")
        runner = self.read("cluster_install.py")
        transport = self.read("cluster_ssh.py")
        self.assertIn("sudo_session_start", installer)
        self.assertIn("sudo -v", session)
        self.assertIn("sudo -n -v", session)
        self.assertIn("cluster_install.py", installer)
        self.assertIn('"--forks"', runner)
        self.assertIn("StrictHostKeyChecking=yes", transport)
        self.assertNotIn("StrictHostKeyChecking=no", installer + preflight + runner + transport)
        self.assertNotIn("ANSIBLE_HOST_KEY_CHECKING", installer + preflight + runner + transport)

    def test_workers_are_pinned_and_receive_no_admin_token(self) -> None:
        installer = self.read("scripts/install-cluster.sh")
        playbook = self.read("ansible/install-workers.yml")
        self.assertIn('REVISION="$(git rev-parse HEAD)"', installer)
        self.assertIn('version: "{{ project_version }}"', playbook)
        self.assertIn("worker_revision.stdout == project_version", playbook)
        self.assertNotIn("admin_token", playbook)
        self.assertIn("no_log: true", playbook)
        self.assertIn('"https://{{ controller_host }}:{{ coordinator_port }}"', playbook)
        self.assertIn('"worker_slots": {{ ansible_facts[\'processor_vcpus\']', playbook)
        self.assertNotIn("ca.key", playbook)

    def test_deskdisplay_gateway_is_installed_on_controller(self) -> None:
        playbook = self.read("ansible/install-workers.yml")
        config = self.read("config.py")
        controller_service = self.read("scripts/install-deskdisplay-service.sh")
        installer = self.read("scripts/install-cluster.sh")
        display_provisioner = self.read("scripts/provision-deskdisplay.sh")
        display_config = self.read("scripts/ensure-display-config.py")
        self.assertIn("deskdisplay/tools/secure_peer.c", controller_service)
        self.assertIn("/api/deskdisplay/state", controller_service)
        self.assertIn('SERVICE_NAME="deskdisplay-secure-peer"', controller_service)
        self.assertIn("openssl rand -hex 32", controller_service)
        self.assertIn("--display-port", installer)
        self.assertIn("secure key $PSK", display_provisioner)
        self.assertIn("--controller-ssh", display_provisioner)
        self.assertIn("sudo -n cat", display_provisioner)
        self.assertIn("display_attached", display_config)
        self.assertIn("--reset", display_config)
        self.assertIn("--display-no-flash", installer)
        self.assertIn(".display-venv/", self.read(".gitignore"))
        self.assertIn("Stopp gammel DeskDisplay-tjeneste", playbook)
        self.assertIn("service_facts", playbook)
        self.assertIn("DEFAULT_DESKDISPLAY_PSK_FILE", config)

    def test_deskdisplay_ota_consumes_each_received_control_frame(self) -> None:
        transport = self.read("deskdisplay/src/secure_transport.cpp")
        control_branch = transport.split(
            "if (frame[3] >= secure_protocol::controlTypeBase)", 1
        )[1].split("uint64_t sequence", 1)[0]
        self.assertIn("if (processed) clearFrame();", control_branch)

    def test_services_are_non_root_and_have_low_risk_hardening(self) -> None:
        playbook = self.read("ansible/install-workers.yml")
        controller_units = "".join(
            self.read(path)
            for path in (
                "scripts/install-service.sh",
                "scripts/install-coordinator-service.sh",
                "scripts/install-deskdisplay-service.sh",
            )
        )
        self.assertIn("ansible_facts['user_uid'] | int != 0", playbook)
        self.assertIn("NoNewPrivileges=true", playbook)
        self.assertIn("User=$RUN_USER", controller_units)
        self.assertIn("NoNewPrivileges=true", controller_units)

    def test_verification_uses_no_become_for_read_only_service_checks(self) -> None:
        verify = self.read("scripts/verify-cluster.sh")
        self.assertNotIn("--become", verify)
        self.assertNotIn(" -b ", verify)
        self.assertIn("verify-controller-api.py", verify)
        self.assertIn("ansible/verify-workers.yml", verify)

    def test_beginner_wizard_is_primary_orchestrator(self) -> None:
        wizard = self.read("scripts/setup-cluster.py")
        logic = self.read("setup_cluster.py")
        self.assertIn("run_wizard", wizard)
        self.assertIn("Fortsette installasjonen?", logic)
        self.assertIn("scripts/install-cluster.sh", logic)
        self.assertIn("config.local.json", logic)

    def test_update_remains_explicit_and_fast_forward_only(self) -> None:
        update = self.read("scripts/update.sh")
        self.assertIn("git merge --ff-only", update)
        self.assertIn("git ls-files --others --exclude-standard", update)
        self.assertIn("bash scripts/install-cluster.sh", update)


if __name__ == "__main__":
    unittest.main()
