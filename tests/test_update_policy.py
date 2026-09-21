"""Tests for conservative automatic update selection."""

import unittest

from update_policy import classify_paths


class UpdatePolicyTests(unittest.TestCase):
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
            "requirements-integrations.txt",
            "ansible/install-workers.yml",
            "scripts/install-service.sh",
        ):
            with self.subTest(path=path):
                self.assertEqual(classify_paths((path,))[0], "full")

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
