"""``umat-oti --version`` and ``umat-oti doctor`` (Nico, B11: the ``umat-oti`` on
PATH was an old install that said ``invalid choice: 'all'`` and nothing about
being old; the working route needed an undocumented PYTHONPATH).
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import umat_oti
from umat_oti.app import front_door as door

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "umat-oti"


def _run(*args, env=None, cwd=None):
    environment = dict(os.environ if env is None else env)
    return subprocess.run([sys.executable, str(LAUNCHER), *args], capture_output=True, text=True,
                          env=environment, cwd=cwd, timeout=120)


def _without_pythonpath():
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def test_version_says_which_code_runs_and_where():
    done = _run("--version", env=_without_pythonpath(), cwd="/")
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith(f"umat-oti {umat_oti.__version__} (checkout {ROOT}")
    assert door.version_line().startswith(f"umat-oti {umat_oti.__version__}")


def test_the_launcher_runs_from_any_directory_without_pythonpath_or_an_install():
    done = _run("all", "--help", env=_without_pythonpath(), cwd="/")
    assert done.returncode == 0, done.stderr
    assert "usage: umat-oti all" in done.stdout
    helped = _run("--help", env=_without_pythonpath(), cwd="/")
    assert "umat-oti check UMAT.for" in helped.stdout and "umat-oti doctor" in helped.stdout


def test_the_pipeline_children_import_this_code_not_another(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else" + os.pathsep + str(door.import_root()))
    door.make_this_code_visible_to_children()
    parts = os.environ["PYTHONPATH"].split(os.pathsep)
    assert parts[0] == str(door.import_root()) and parts.count(str(door.import_root())) == 1
    assert "/somewhere/else" in parts


def _fake_install(tmp_path, *, package_file, version, commands):
    """A ``umat-oti`` script whose interpreter reports a package and commands."""
    python = tmp_path / "fakepython"
    python.write_text("#!/bin/sh\n"
                      'if [ "$1" = "-c" ]; then\n'
                      f"  echo '{json.dumps({'file': str(package_file), 'version': version})}'\n"
                      "else\n"
                      f"  echo 'usage: umat-oti [-h] {{{','.join(commands)}}} ...'\n"
                      "fi\n")
    command = tmp_path / "bin" / "umat-oti"
    command.parent.mkdir(exist_ok=True)
    command.write_text(f"#!{python}\n")
    for path in (python, command):
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return command


def _on_path(monkeypatch, command):
    monkeypatch.setenv("PATH", str(command.parent) + os.pathsep + os.environ["PATH"])


def test_doctor_warns_when_the_installed_command_is_older_than_the_checkout(tmp_path, monkeypatch):
    stale = _fake_install(tmp_path, package_file=tmp_path / "old" / "src" / "umat_oti" / "__init__.py",
                          version="0.9.0", commands=["transform", "config"])
    _on_path(monkeypatch, stale)
    findings = door.diagnose()
    warned = [text for status, text in findings if status == "warn"]
    assert len(warned) == 1
    text = warned[0]
    assert "older than this checkout" in text and str(tmp_path / "old") in text
    assert "no `all` or `jacobian` command" in text and "version 0.9.0 is older" in text
    assert "pip install -e" in text or "umat-oti ..." in text


def test_doctor_is_quiet_when_the_installed_command_runs_this_code(tmp_path, monkeypatch):
    current = _fake_install(tmp_path, package_file=Path(umat_oti.__file__).resolve(),
                            version=umat_oti.__version__,
                            commands=["all", "jacobian", "transform", "config", "check"])
    _on_path(monkeypatch, current)
    findings = door.diagnose()
    assert not [f for f in findings if f[0] == "warn"] or all(
        "gfortran" in t for s, t in findings if s == "warn")
    assert any("runs this code" in text for _, text in findings)


def test_doctor_says_so_when_no_command_is_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(door, "_installed_command", lambda name="umat-oti": None)
    findings = door.diagnose()
    assert any(s == "info" and "No `umat-oti` command is installed" in t for s, t in findings)


def test_doctor_exit_code_follows_its_warnings(tmp_path, monkeypatch, capsys):
    stale = _fake_install(tmp_path, package_file=tmp_path / "x" / "umat_oti" / "__init__.py",
                          version="0.1.0", commands=["transform"])
    _on_path(monkeypatch, stale)
    assert door.doctor() == 1
    assert "WARN" in capsys.readouterr().out
