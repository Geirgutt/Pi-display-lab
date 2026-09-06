"""Reproduce an inherited distro Ansible package using local, synthetic wheels."""

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent


def wheel(directory, name, version, dependency=""):
    metadata_dir = f"{name}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    if dependency:
        metadata += f"Requires-Dist: {dependency}\n"
    files = {
        f"{metadata_dir}/METADATA": metadata,
        f"{metadata_dir}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = io.StringIO()
    csv.writer(record).writerows((path, "", "") for path in [*files, f"{metadata_dir}/RECORD"])
    files[f"{metadata_dir}/RECORD"] = record.getvalue()
    path = directory / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    return path


class AnsibleDependencyTests(unittest.TestCase):
    def test_upgrade_resolves_distro_ansible_and_core_together_without_changing_system(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheels = root / "wheels"
            wheels.mkdir()
            system_site = root / "system-site"
            system_site.mkdir()
            # This is the combination from Raspberry Pi OS, outside the new venv.
            old = [wheel(wheels, "ansible", "12.0.0", "ansible-core~=2.19.1"),
                   wheel(wheels, "ansible_core", "2.19.4")]
            for path in old:
                with zipfile.ZipFile(path) as archive:
                    archive.extractall(system_site)
            before = {str(p.relative_to(system_site)): p.read_bytes() for p in system_site.rglob("*") if p.is_file()}
            wheel(wheels, "ansible", "14.0.0", "ansible-core~=2.21.0")
            wheel(wheels, "ansible_core", "2.21.3")

            environment = root / "env"
            venv.EnvBuilder(with_pip=False).create(environment)
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            # Only the fake distro packages are exposed; no actual system package is touched.
            site_dir = subprocess.check_output(
                [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True,
            ).strip()
            (Path(site_dir) / "distro-test.pth").write_text(str(system_site) + "\n", encoding="utf-8")
            pip = [sys.executable, "-m", "pip", "--python", str(python), "--isolated", "--disable-pip-version-check"]
            command = [*pip, "install", "--no-index", "--find-links", str(wheels), "--upgrade",
                       "-r", str(PROJECT_DIR / "requirements-ansible.txt")]
            first = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            check = subprocess.run([*pip, "check"], capture_output=True, text=True, timeout=30)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertNotIn("dependency conflicts", first.stderr)
            versions = json.loads(subprocess.check_output([
                str(python), "-c", "import importlib.metadata as m, json; print(json.dumps([m.version('ansible'), m.version('ansible-core')]))",
            ], text=True))
            self.assertEqual(versions, ["14.0.0", "2.21.3"])
            second = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertNotIn("Installing collected packages", second.stdout)
            self.assertEqual(before, {str(p.relative_to(system_site)): p.read_bytes() for p in system_site.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
