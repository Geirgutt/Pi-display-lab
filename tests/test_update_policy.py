"""Tests for conservative automatic update selection."""

import unittest

from update_policy import classify_paths


class UpdatePolicyTests(unittest.TestCase):
    def test_terminal_menu_update_does_not_redeploy_workers(self) -> None:
        self.assertEqual(classify_paths(("meny.py", "README.md", "tests/test_menu.py")), ("controller", False, ()))

    def test_maintenance_tools_only_update_controller(self) -> None:
        paths = (
            "cluster_maintenance.py", "maintenance_output.py",
            "scripts/maintain-workers.sh", "scripts/fedora-reboot-status.py",
            "ansible/maintain-workers.yml", "ansible/maintenance-debian.yml",
            "ansible/maintenance-fedora.yml", "ansible/callback_plugins/pi_maintenance.py",
            "README.md", "tests/test_maintenance_output.py",
        )
        self.assertEqual(classify_paths(paths), ("controller", False, ()))
        self.assertEqual(classify_paths(paths + ("cluster_worker.py",)), ("quick", False, ()))
        self.assertEqual(classify_paths(paths + ("ansible/install-workers.yml",)), ("full", False, ()))

    def test_display_code_with_docs_and_tests_is_display_only(self) -> None:
        self.assertEqual(
            classify_paths((
                "deskdisplay/src/ui.cpp",
                "scripts/stage-deskdisplay-ota.sh",
                "deskdisplay/docs/ui.md",
                "tests/test_installation.py",
            )),
            ("display", True, ()),
        )

    def test_runtime_changes_use_quick_update(self) -> None:
        self.assertEqual(
            classify_paths(("app.py", "static/app.js", "README.md")),
            ("quick", False, ()),
        )

    def test_test_only_dependencies_do_not_reinstall_cluster(self) -> None:
        self.assertEqual(classify_paths(("requirements-test.txt",)), ("none", False, ()))
        self.assertEqual(classify_paths(("README.md", "tests/test_training.py")), ("none", False, ()))
        self.assertEqual(
            classify_paths(("requirements-test.txt", "deskdisplay/src/ui.cpp")),
            ("display", True, ()),
        )

    def test_controller_and_display_changes_skip_workers(self) -> None:
        self.assertEqual(
            classify_paths((
                "app.py",
                "integration_sync.py",
                "spotify.py",
                "garmin_data.py",
                "deskdisplay/src/ui.cpp",
                "scripts/stage-deskdisplay-ota.sh",
                "scripts/update.sh",
            )),
            ("controller", True, ()),
        )

    def test_security_install_and_dependency_changes_require_full_update(self) -> None:
        for path in (
            "cluster_pki.py",
            "requirements.txt",
            "ansible/install-workers.yml",
            "scripts/install-service.sh",
        ):
            with self.subTest(path=path):
                self.assertEqual(classify_paths((path,))[0], "full")

    def test_integration_dependencies_are_controller_only(self) -> None:
        paths = ("requirements-integrations.txt", "garmin_charts.py", "deskdisplay/src/ui.cpp")
        self.assertEqual(classify_paths(paths), ("controller", True, ()))
        self.assertEqual(classify_paths(paths + ("cluster_worker.py",)), ("quick", True, ()))
        self.assertEqual(classify_paths(paths + ("requirements.txt",)), ("full", True, ()))

    def test_update_engine_changes_can_bootstrap_through_quick_path(self) -> None:
        paths = (
            "cluster_install.py",
            "update_policy.py",
            "scripts/update.sh",
            "scripts/install-cluster.sh",
            "ansible/update-workers.yml",
            "ansible/verify-workers.yml",
        )
        self.assertEqual(classify_paths(paths), ("quick", False, ()))

    def test_unknown_path_requires_operator_choice(self) -> None:
        self.assertEqual(
            classify_paths(("new-component/data.bin",)),
            ("ask", False, ("new-component/data.bin",)),
        )

    def test_no_changes_does_nothing(self) -> None:
        self.assertEqual(classify_paths(()), ("none", False, ()))


if __name__ == "__main__":
    unittest.main()
