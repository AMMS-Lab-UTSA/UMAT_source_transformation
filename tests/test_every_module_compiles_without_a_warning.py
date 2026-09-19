"""Every module of the package compiles without a warning.

A docstring in ``umat_oti/abaqus/data_files.py`` quoted a Windows path in an
ordinary string, so its backslash was an invalid escape: a
DeprecationWarning on Python 3.10 and 3.11 and a SyntaxWarning from 3.12,
printed to every user whose interpreter compiled the module (c43e0e7). Each
module is compiled here by an interpreter that turns warnings into errors.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "umat_oti"

PROBE = r'''
import pathlib, sys
# the interpreter does turn an invalid escape into an error, or nothing below means anything
try:
    compile('"C:\\Temp\\job"', "<invalid escape>", "exec")
    sys.exit("an invalid escape compiled without a warning; -W error is not in effect")
except SyntaxError:
    pass
compiled, failures = [], []
for path in sorted(pathlib.Path(sys.argv[1]).rglob("*.py")):
    try:
        compile(path.read_bytes(), str(path), "exec")
        compiled.append(path.relative_to(sys.argv[1]).as_posix())
    except SyntaxError as error:
        failures.append(f"{path}: {error}")
print("\n".join(failures or compiled))
sys.exit(1 if failures else 0)
'''


def test_every_module_compiles_with_warnings_as_errors():
    completed = subprocess.run([sys.executable, "-W", "error", "-c", PROBE, str(PACKAGE)],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    compiled = completed.stdout.split()
    assert "abaqus/data_files.py" in compiled
    assert len(compiled) == len(list(PACKAGE.rglob("*.py")))
