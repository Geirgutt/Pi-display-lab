"""Exercise menu navigation and subprocess boundaries without touching the lab."""

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock

from meny import Menu, SECTIONS


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "lab with spaces"
        self.project.mkdir()
        self.runner = Mock(return_value=subprocess.CompletedProcess([], 0))
        self.restart = Mock()
        self.revision = Mock(return_value="unchanged")

    def menu(self, answers=()):
        choices = iter(answers)
        return Menu(self.project, input_fn=lambda _: next(choices), runner=self.runner,
                    restart=self.restart, revision_reader=self.revision)

    def config(self):
        (self.project / "config.local.json").write_text(json.dumps({
            "node_role": "controller", "controller_host": "controller.example", "ssh_user": "lab",
            "worker_hosts": ["one.example", "two.example"], "client_secret": "must-not-print",
        }))

    def test_navigation_and_invalid_choices_do_not_execute_commands(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.menu(["bad", "9", "1", "0", "0"]).run(), 0)
        self.runner.assert_not_called()

    def test_spotify_uses_current_python_and_project_directory(self):
        menu = self.menu(["1", "1", "", "0", "0"])
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(menu.run(), 0)
        args, kwargs = self.runner.call_args
        self.assertEqual(args[0][1:], ["scripts/configure-spotify.py"])
        self.assertEqual(kwargs, {"cwd": self.project.resolve(), "check": False})
        self.assertIn("ssh -L 8888:127.0.0.1:8888", output.getvalue())

    def test_missing_config_does_not_start_cluster_action(self):
        with redirect_stdout(io.StringIO()):
            self.menu().execute("1", 3, SECTIONS["1"][1][2])
        self.runner.assert_not_called()

    def test_add_workers_enters_the_existing_wizard_directly(self):
        self.config()
        with redirect_stdout(io.StringIO()):
            self.menu().execute("1", 3, SECTIONS["1"][1][2])
        self.assertEqual(self.runner.call_args.args[0], ["bash", "scripts/setup-cluster.sh", "--action", "add"])
        self.assertNotIn("input", self.runner.call_args.kwargs)

    def test_worker_selection_is_explicit_validated_and_deduplicated(self):
        self.config()
        with redirect_stdout(io.StringIO()):
            self.menu(["", "99", "2, 2"]).execute("2", 4, SECTIONS["2"][1][3])
        self.assertEqual(self.runner.call_args.args[0], [
            "bash", "scripts/maintain-workers.sh", "--upgrade", "--worker", "two.example"])

    def test_cancelled_selection_never_falls_back_to_all_workers(self):
        self.config()
        with redirect_stdout(io.StringIO()):
            self.menu(["0"]).execute("2", 4, SECTIONS["2"][1][3])
        self.runner.assert_not_called()

    def test_all_workers_are_still_passed_as_explicit_arguments(self):
        self.config()
        with redirect_stdout(io.StringIO()):
            self.menu(["a"]).execute("2", 3, SECTIONS["2"][1][2])
        self.assertEqual(self.runner.call_args.args[0][-4:], ["--worker", "one.example", "--worker", "two.example"])

    def test_successful_update_reloads_and_failed_unchanged_update_does_not(self):
        with redirect_stdout(io.StringIO()):
            self.menu().execute("2", 1, SECTIONS["2"][1][0])
        self.restart.assert_called_once()
        self.restart.reset_mock()
        self.runner.return_value.returncode = 1
        with redirect_stdout(io.StringIO()) as output:
            self.menu().execute("2", 1, SECTIONS["2"][1][0])
        self.restart.assert_not_called()
        self.assertIn("kode 1", output.getvalue())

    def test_failed_or_interrupted_update_reloads_if_git_already_changed(self):
        for interrupted in (False, True):
            self.restart.reset_mock()
            self.revision.side_effect = ["old-commit", "new-commit"]
            self.runner.side_effect = KeyboardInterrupt if interrupted else None
            self.runner.return_value.returncode = 2
            with redirect_stdout(io.StringIO()) as output:
                self.menu([""]).execute("2", 1, SECTIONS["2"][1][0])
            self.restart.assert_called_once()
            self.assertIn("kode 130" if interrupted else "kode 2", output.getvalue())

    def test_interrupted_or_missing_tool_returns_to_menu(self):
        for error in (KeyboardInterrupt, FileNotFoundError("missing")):
            self.runner.side_effect = error
            with redirect_stdout(io.StringIO()):
                self.menu().execute("2", 1, SECTIONS["2"][1][0])
        self.restart.assert_not_called()

    def test_config_summary_does_not_dump_private_config_fields(self):
        self.config()
        with redirect_stdout(io.StringIO()) as output:
            self.menu().execute("3", 1, SECTIONS["3"][1][0])
        self.assertIn("controller.example", output.getvalue())
        self.assertNotIn("must-not-print", output.getvalue())
        self.runner.assert_not_called()

    def test_log_selection_uses_only_known_service_names(self):
        with redirect_stdout(io.StringIO()):
            self.menu(["bad", "3"]).execute("3", 4, SECTIONS["3"][1][3])
        self.assertEqual(self.runner.call_args.args[0], [
            "sudo", "journalctl", "--no-pager", "-n", "60", "-u", "deskdisplay-secure-peer.service"])


if __name__ == "__main__":
    unittest.main()
