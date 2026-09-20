"""Tests for conservative automatic update selection."""

import unittest

from update_policy import classify_paths


class UpdatePolicyTests(unittest.TestCase):
    def test_display_code_with_docs_and_tests_is_display_only(self) -> None:
        self.assertEqual(
            classify_paths(("deskdisplay/src/ui.cpp", "deskdisplay/docs/ui.md", "tests/test_installation.py")),
            ("display", True, ()),
        )

    def test_runtime_changes_use_quick_update(self) -> None:
        self.assertEqual(
            classify_paths(("app.py", "static/app.js", "README.md")),
            ("quick", False, ()),
        )

    def test_security_install_and_dependency_changes_require_full_update(self) -> None:
        for path in ("cluster_pki.py", "requirements.txt", "ansible/install-workers.yml", "scripts/update.sh"):
            with self.subTest(path=path):
                self.assertEqual(classify_paths((path,))[0], "full")

    def test_unknown_path_requires_operator_choice(self) -> None:
        self.assertEqual(
            classify_paths(("new-component/data.bin",)),
            ("ask", False, ("new-component/data.bin",)),
        )

    def test_no_changes_does_nothing(self) -> None:
        self.assertEqual(classify_paths(()), ("none", False, ()))


if __name__ == "__main__":
    unittest.main()
