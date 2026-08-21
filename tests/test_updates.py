"""Tester at appens oppdateringssjekk er lesende og lager trygge lenker."""

import unittest

from updates import UpdateManager


class UpdateManagerTests(unittest.TestCase):
    def test_status_does_not_offer_installation(self) -> None:
        updater = UpdateManager()
        status = updater.status()
        self.assertNotIn("can_apply", status)
        self.assertFalse(hasattr(updater, "apply_async"))

    def test_busy_manager_rejects_another_check(self) -> None:
        updater = UpdateManager()
        updater._state["status"] = "checking"
        self.assertFalse(updater.check_async())

    def test_github_commit_urls_support_https_and_ssh(self) -> None:
        commit = "a" * 40
        expected = f"https://github.com/example/project/commit/{commit}"
        self.assertEqual(
            UpdateManager._github_commit_url("https://github.com/example/project.git", commit),
            expected,
        )
        self.assertEqual(
            UpdateManager._github_commit_url("git@github.com:example/project.git", commit),
            expected,
        )
        self.assertIsNone(
            UpdateManager._github_commit_url("https://git.example/project.git", commit)
        )


if __name__ == "__main__":
    unittest.main()
