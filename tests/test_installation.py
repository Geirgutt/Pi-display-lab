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

    def test_deskdisplay_ota_hides_unreliable_rgb_scanout_and_restores_after_failure(self) -> None:
        transport = self.read("deskdisplay/src/secure_transport.cpp")
        app = self.read("deskdisplay/src/app.cpp")
        ui_header = self.read("deskdisplay/src/ui.h")
        self.assertIn('"SYSTEM UPDATE"', self.read("deskdisplay/src/ui.cpp"))
        self.assertIn("prepareOtaDisplay();", transport)
        self.assertIn("hardware::setBacklight(false)", transport)
        self.assertIn("hardware::setBacklight(true)", transport)
        self.assertIn("if (otaDisplayIsSuppressed && otaRebootAt == 0)", transport)
        self.assertIn("if (secure_transport::takeDisplayRestoreRequest()) ui::page(model);", app)
        self.assertIn("if (secure_transport::displaySuppressed()) return;", app)
        self.assertIn("void showSystemUpdate();", ui_header)

    def test_deskdisplay_ota_waits_for_rebooted_tls_reconnect(self) -> None:
        gateway = self.read("deskdisplay/tools/secure_peer.c")
        protocol = self.read("deskdisplay/src/secure_protocol.h")
        staging = self.read("scripts/stage-deskdisplay-ota.sh")
        self.assertIn("DeskDisplay reconnected after OTA reboot", gateway)
        self.assertIn("OTA_LEGACY_CHUNK_SIZE 96", gateway)
        self.assertIn("OTA_FAST_CHUNK_SIZE 4096", gateway)
        self.assertIn("ota_fast_path", gateway)
        self.assertIn("otaChunkDataSize = 4096", protocol)
        self.assertIn("OTA_RESULT", staging)
        self.assertIn("PI_DISPLAY_OTA_TIMEOUT", staging)
        self.assertIn("OTA fullført", staging)
        self.assertIn("bash scripts/install-deskdisplay-service.sh", staging)
        self.assertIn("--resume-staged", staging)

    def test_gateway_build_recovers_from_compiler_crash_without_replacing_live_binary(self) -> None:
        installer = self.read("scripts/install-deskdisplay-service.sh")
        self.assertIn("compile_gateway -O2", installer)
        self.assertIn("internal compiler error", installer)
        self.assertIn("compile_gateway -O0", installer)
        self.assertIn('TEMP_INSTALLED="$(sudo mktemp', installer)
        self.assertIn('sudo mv -f -- "$TEMP_INSTALLED" "$BINARY"', installer)

    def test_deskdisplay_home_prioritizes_clock_and_primary_pages(self) -> None:
        state = self.read("deskdisplay/src/app_state.h")
        app = self.read("deskdisplay/src/app.cpp")
        ui = self.read("deskdisplay/src/ui.cpp")
        self.assertIn("Page::Home", app)
        self.assertIn("configTzTime", app)
        for caption in ("Cluster", "Training", "Calendar", "System"):
            self.assertIn(f'button(', ui)
            self.assertIn(f'"{caption}"', ui)
        self.assertNotIn("Touch Test", ui)
        self.assertNotIn("Page::TouchTest", state + app + ui)
        self.assertNotIn('button(1, "Wi-Fi"', ui)
        self.assertIn("strcmp(lastClockText, model.clockText)", ui)
        self.assertIn("TOMORROW", ui)
        self.assertIn("NEXT 7 DAYS", ui)
        self.assertIn("Rest / no workout", ui)
        self.assertIn("trainingDayCount = 7", self.read("deskdisplay/src/ui_layout.h"))
        self.assertIn("trainingItemMax = 7", self.read("deskdisplay/src/secure_protocol.h"))
        self.assertIn("Page::TrainingDetail", state + app + ui)
        self.assertIn("display().setFont(&fonts::Font0);\n        uint8_t clockSize = 11;", ui)
        self.assertIn("(width - display().textWidth(model.clockText)) / 2, 86);", ui)
        self.assertIn("uint8_t dateSize = 4;", ui)
        self.assertIn("display().fillRect(20, 272, 440, 42, homeBackground);", ui)
        self.assertIn("? 278 : 283);", ui)
        hardware = self.read("deskdisplay/src/hardware.cpp")
        hardware_header = self.read("deskdisplay/src/hardware.h")
        self.assertIn("putUChar(brightnessKey", hardware)
        self.assertIn("putBool(nightModeKey", hardware)
        self.assertIn("constexpr uint32_t backlightFrequency = 1000", hardware)
        self.assertIn("constexpr uint8_t minimumBrightness = 20", hardware_header)
        self.assertIn("constexpr uint8_t maximumBrightness = 100", hardware_header)
        self.assertIn("analogWriteFrequency(backlightFrequency)", hardware)
        self.assertIn("analogWrite(backlightPin, duty)", hardware)
        self.assertIn("previewBrightness", app + hardware)
        self.assertIn("brightnessSlider", ui)
        layout = self.read("deskdisplay/src/ui_layout.h")
        self.assertIn("brightnessSliderX = 48", layout)
        self.assertIn("brightnessSliderWidth = 384", layout)
        self.assertIn("brightnessSliderHitPadding = 12", layout)
        self.assertIn("brightnessSliderX - ui_layout::brightnessSliderHitPadding", app)
        self.assertIn('"Night ON"', ui)

    def test_deskdisplay_home_counts_online_nodes_and_hides_offline_metrics(self) -> None:
        ui = self.read("deskdisplay/src/ui.cpp")
        protocol = self.read("deskdisplay/src/secure_protocol.h")
        gateway = self.read("deskdisplay/tools/secure_peer.c")
        self.assertIn("Cluster: %u/%u online", ui)
        self.assertIn("model.clusterTelemetry.onlineNodes", ui)
        self.assertIn('"CPU N/A"', ui)
        self.assertIn('"RAM N/A"', ui)
        self.assertIn("const bool online = streamLive && node.online", ui)
        self.assertIn("if (!online)", ui)
        self.assertIn("constexpr uint16_t homeBackground = TFT_BLACK", ui)
        self.assertIn("fillRect(20, 272, 440, 42, homeBackground)", ui)
        self.assertIn("? 278 : 283);", ui)
        self.assertNotIn('header("Home"', ui)
        self.assertIn("model.page == app_state::Page::Home ? homeBackground : background", ui)
        self.assertNotIn("fillRoundRect(12, 68, 456, 272, 10, card)", ui)
        self.assertIn("clusterMetadataSize = 7", protocol)
        self.assertIn("CLUSTER_METADATA_SIZE 7", gateway)
        self.assertIn("put16(payload + 4, online_nodes)", gateway)

    def test_services_are_non_root_and_have_low_risk_hardening(self) -> None:
        playbook = self.read("ansible/install-workers.yml")
        controller_units = "".join(
            self.read(path)
            for path in (
                "scripts/install-service.sh",
                "scripts/install-coordinator-service.sh",
                "scripts/install-deskdisplay-service.sh",
                "scripts/install-integrations-service.sh",
            )
        )
        self.assertIn("ansible_facts['user_uid'] | int != 0", playbook)
        self.assertIn("NoNewPrivileges=true", playbook)
        self.assertIn("User=$RUN_USER", controller_units)
        self.assertIn("NoNewPrivileges=true", controller_units)

    def test_integrations_keep_private_addresses_outside_the_repository(self) -> None:
        installer = self.read("scripts/install-integrations-service.sh")
        configure = self.read("scripts/configure-integrations.py")
        synchronizer = self.read("scripts/sync-integrations.py")
        self.assertIn("/etc/pi-display-lab/integrations.json", configure)
        self.assertIn("0600", configure)
        self.assertIn("getpass", configure)
        self.assertIn("/var/lib/pi-display-lab/integrations", installer)
        self.assertIn("ProtectSystem=strict", installer)
        self.assertNotIn("GARMIN_PASSWORD", installer + configure + synchronizer)

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
        self.assertIn("scripts/classify-update.py", update)
        self.assertIn("scripts/check-cluster-pki.py", update)
        self.assertIn("--quick", update)
        self.assertIn("--full", update)

    def test_quick_worker_update_skips_bootstrap_secrets_and_pki(self) -> None:
        playbook = self.read("ansible/update-workers.yml")
        self.assertIn("gather_facts: false", playbook)
        self.assertIn("ansible.builtin.git", playbook)
        self.assertIn("state: restarted", playbook)
        self.assertNotIn("ansible.builtin.package", playbook)
        self.assertNotIn("cluster_ca_certificate", playbook)
        self.assertNotIn("worker_credentials", playbook)


if __name__ == "__main__":
    unittest.main()
