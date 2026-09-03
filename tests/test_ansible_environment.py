"""Use real malformed .pyc files to exercise the repair and its boundaries."""

import json
import os
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ansible_environment import check_environment
from setup_cluster import build_controller_config, write_local_config


class AnsibleEnvironmentTests(unittest.TestCase):
    def corrupt(self, root):
        source = root / "cache_test_module.py"
        source.write_text("VALUE = 42\n", encoding="utf-8")
        cache = Path(py_compile.compile(str(source), doraise=True))
        # A valid cache header with an invalid marshal reference reproduces the log.
        cache.write_bytes(cache.read_bytes()[:16] + b"r\xff\xff\xff\x7f")
        return source, cache

    def test_repairs_only_the_corrupt_cache_and_rechecks_in_a_fresh_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, cache = self.corrupt(root)
            before = source.read_bytes()
            with patch.dict(os.environ, {"PYTHONPATH": str(root)}):
                self.assertEqual(check_environment(root, (source.stem,)), 1)
                self.assertEqual(check_environment(root, (source.stem,)), 0)
            self.assertEqual(source.read_bytes(), before)
            self.assertGreater(cache.stat().st_size, 21)

    def test_does_not_modify_a_cache_outside_the_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / "venv"
            local.mkdir()
            source, cache = self.corrupt(root)
            before = cache.read_bytes()
            with patch.dict(os.environ, {"PYTHONPATH": str(root)}):
                with self.assertRaisesRegex(RuntimeError, "utenfor prosjektmilj"):
                    check_environment(local, (source.stem,))
            self.assertEqual(cache.read_bytes(), before)

    def test_does_not_rewrite_cache_for_an_unrelated_module_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "cache_test_module.py"
            source.write_text("raise ValueError('bad marshal data from module code')\n", encoding="utf-8")
            cache = Path(py_compile.compile(str(source), doraise=True))
            before = cache.read_bytes()
            with patch.dict(os.environ, {"PYTHONPATH": str(root)}):
                with self.assertRaisesRegex(RuntimeError, "Ansible-kontrollen feilet"):
                    check_environment(root, (source.stem,))
            self.assertEqual(cache.read_bytes(), before)

    def test_stops_if_repair_does_not_resolve_the_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _ = self.corrupt(root)
            with patch.dict(os.environ, {"PYTHONPATH": str(root)}), patch("ansible_environment.py_compile.compile") as compile_cache:
                with self.assertRaisesRegex(RuntimeError, "vedvarer"):
                    check_environment(root, (source.stem,))
                compile_cache.assert_called_once()

    def test_inventory_pins_the_python_used_by_preflight(self):
        project = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            write_local_config(config, build_controller_config("controller.example", "labuser", ["worker.example"]))
            subprocess.run([sys.executable, str(project / "scripts/prepare-ansible.py"), str(config), str(root),
                            "--revision", "a" * 40], check=True, capture_output=True)
            variables = json.loads((root / "vars.json").read_text())
            self.assertEqual(variables["ansible_python_interpreter"], "/usr/bin/python3")


if __name__ == "__main__":
    unittest.main()
