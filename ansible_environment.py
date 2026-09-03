"""Check Ansible imports and rebuild an identified corrupt local bytecode cache."""

from __future__ import annotations

import importlib.util
import json
import py_compile
import subprocess
import sys
from pathlib import Path


PROBE = '''
import importlib, json, sys, traceback
try:
    for name in json.loads(sys.argv[1]):
        importlib.import_module(name)
except (ValueError, EOFError) as error:
    frame = error.__traceback__
    while frame:
        if frame.tb_frame.f_code.co_name == '_compile_bytecode':
            values = frame.tb_frame.f_locals
            print(json.dumps({'source': values.get('source_path'), 'cache': values.get('bytecode_path')}))
            traceback.print_exc()
            sys.exit(10)
        frame = frame.tb_next
    raise
'''


def check_environment(environment: Path, modules=("ansible.plugins.connection.ssh",)):
    # Linux workers require SSH. Optional Windows plugins must not gate rollout.
    environment = environment.resolve()
    repaired = set()
    while True:
        result = subprocess.run([sys.executable, "-c", PROBE, json.dumps(modules)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print("Ansible: påkrevde moduler kan lastes.", flush=True)
            return len(repaired)
        if result.returncode != 10:
            raise RuntimeError("Ansible-kontrollen feilet:\n" + result.stderr)
        try:
            details = json.loads(result.stdout)
            source = Path(details["source"]).resolve()
            cache = Path(details["cache"]).resolve()
        except (ValueError, TypeError, KeyError):
            raise RuntimeError("Kunne ikke identifisere cachefilen:\n" + result.stderr) from None
        # Never rewrite source, system packages, symlink targets outside the venv,
        # or arbitrary files mentioned by an unrelated import exception.
        expected = Path(importlib.util.cache_from_source(str(source))).resolve()
        if (not source.is_relative_to(environment) or not cache.is_relative_to(environment)
                or source.suffix != ".py" or not source.is_file() or cache != expected):
            raise RuntimeError("Cachefeilen ligger utenfor prosjektmiljøet eller mangler gyldig kildefil; "
                               "ingen systemfiler ble endret:\n" + result.stderr)
        if cache in repaired or len(repaired) >= 3:
            raise RuntimeError("Bytecode-feilen vedvarer etter reparasjon; kontroller lagring og Python-miljø:\n" + result.stderr)
        print(f"Bygger skadet Python-cache på nytt: {cache.relative_to(environment)}", flush=True)
        py_compile.compile(str(source), cfile=str(cache), doraise=True)
        repaired.add(cache)


def main():
    environment = Path(__file__).resolve().parent / ".ansible-venv"
    if sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() != environment.resolve():
        raise RuntimeError("Kjør kontrollen med .ansible-venv/bin/python ansible_environment.py")
    check_environment(environment)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError, py_compile.PyCompileError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
