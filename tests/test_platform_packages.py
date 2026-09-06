"""Execute the remote apt/dnf scripts using fake package managers on Linux."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cluster_bootstrap import prerequisite_script


@unittest.skipIf(os.name == "nt", "Requires Linux/WSL")
class PlatformPackageTests(unittest.TestCase):
    def exercise(self, distro, installed):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("apt-get", "dnf", "dpkg-query", "rpm"):
                command = root / name
                if name == "dpkg-query":
                    body = "printf 'install ok installed'\n" if installed else "exit 1\n"
                elif name == "rpm":
                    body = "exit 0\n" if installed else "exit 1\n"
                else:
                    body = 'printf "%s %s\\n" "${0##*/}" "$*" >> "$PACKAGE_TEST_LOG"\n'
                command.write_text("#!/bin/sh\n" + body, encoding="utf-8")
                command.chmod(0o700)
            log = root / "calls"
            environment = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"], PACKAGE_TEST_LOG=str(log))
            result = subprocess.run(["sh", "-c", prerequisite_script(distro)], env=environment,
                                    text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return log.read_text() if log.exists() else ""

    def test_missing_packages_are_installed_with_the_right_manager(self):
        apt = self.exercise("ubuntu", False)
        self.assertIn("apt-get update", apt)
        self.assertIn("python3-venv", apt)
        dnf = self.exercise("fedora", False)
        self.assertIn("dnf --refresh -y install", dnf)
        self.assertIn("python3-libdnf5", dnf)
        self.assertNotIn("python3-venv", dnf)

    def test_rerun_does_not_reinstall_existing_packages(self):
        for distro in ("ubuntu", "fedora"):
            self.assertEqual(self.exercise(distro, True), "")


if __name__ == "__main__":
    unittest.main()
