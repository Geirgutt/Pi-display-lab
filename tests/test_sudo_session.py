"""Exercise sudo refresh and child behavior with a fake sudo, never real privileges."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


@unittest.skipIf(os.name == "nt", "Requires a Unix shell; run in Linux/WSL")
class SudoSessionTests(unittest.TestCase):
    def run_session(self, body: str, reject_initial: bool = False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sudo = root / "sudo"
            sudo.write_text(
                '#!/usr/bin/env bash\n'
                'printf "%s\\n" "$*" >> "$SUDO_TEST_DIR/calls"\n'
                '[[ ! -f "$SUDO_TEST_DIR/reject" ]]\n', encoding="utf-8",
            )
            sudo.chmod(0o700)
            if reject_initial:
                (root / "reject").touch()
            environment = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"], SUDO_TEST_DIR=directory)
            script = (
                'set -Eeuo pipefail\n'
                'source "$1/scripts/sudo-session.sh"\n'
                "trap 'sudo_session_stop' EXIT\n"
                # Accelerate the refresh timer, keeping the real background loop.
                'sleep() { command sleep 0.02; }\n'
                + body
            )
            result = subprocess.run(
                ["bash", "-c", script, "session-test", str(PROJECT_DIR)],
                env=environment, capture_output=True, text=True, timeout=10,
            )
            return result, (root / "calls").read_text(encoding="utf-8").splitlines()

    def test_refresh_child_noninteractive_sudo_and_cleanup(self):
        result, calls = self.run_session('''
sudo_session_start
bash -c 'sudo /usr/bin/true'
for attempt in {1..100}; do
  if grep -q -- '^-n -v$' "$SUDO_TEST_DIR/calls"; then break; fi
  command sleep 0.02
done
sudo_session_stop
if kill -0 "$SUDO_SESSION_PID" 2>/dev/null; then exit 3; fi
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0], "-v")
        self.assertIn("-n -v", calls)
        self.assertIn("-n /usr/bin/true", calls)
        self.assertEqual(calls.count("-v"), 1)

    def test_initial_denial_stops_without_starting_refresh(self):
        result, calls = self.run_session("sudo_session_start\n", reject_initial=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ["-v"])

    def test_expired_access_fails_in_child_without_another_prompt(self):
        result, calls = self.run_session('''
sudo_session_start
touch "$SUDO_TEST_DIR/reject"
bash -c 'sudo /usr/bin/true'
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("-n /usr/bin/true", calls)
        self.assertEqual(calls.count("-v"), 1)


if __name__ == "__main__":
    unittest.main()
