"""The front door of the ``umat-oti`` command: ``--version``, ``doctor`` and ``check``.

Everything else is handed to :mod:`umat_oti.cli` unchanged. The door lives here
because ``umat_oti/cli.py`` is part of the transform fingerprint and a new verb
for a person is not a change to the transform.

Why ``doctor`` exists. The ``umat-oti`` on a user's PATH is a small script that
imports whichever ``umat_oti`` its own Python can see, and that is not always
the checkout the user is reading about: a virtual environment installed from an
older checkout keeps running that older code, which says
``invalid choice: 'all'`` and nothing about being old. ``--version`` names the
code that is running and where it is, and ``doctor`` compares it with the
command on PATH.

``python umat-oti ...`` (the launcher in the checkout's root) runs this module
with the checkout's own ``src`` on the path -- no PYTHONPATH, no install.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

import umat_oti

#: Commands a current ``umat-oti`` answers to. A command on PATH that lacks one
#: of these is older than this checkout.
CURRENT_COMMANDS = ("all", "jacobian", "transform", "config")

MINIMUM_PYTHON = (3, 10)

_PROBE = ("import json, umat_oti; "
          "print(json.dumps({'file': umat_oti.__file__, 'version': umat_oti.__version__}))")


def package_dir() -> Path:
    """The directory of the ``umat_oti`` package that is running."""
    return Path(umat_oti.__file__).resolve().parent


def import_root() -> Path:
    """The directory that has to be on ``sys.path`` for this package (its parent)."""
    return package_dir().parent


def checkout_root() -> Optional[Path]:
    """The source checkout this package sits in (``<root>/src/umat_oti``), or None
    when it is an ordinary installed copy."""
    root = import_root()
    if root.name == "src" and (root.parent / "pyproject.toml").is_file():
        return root.parent
    return None


def commit_of(checkout: Optional[Path]) -> str:
    if checkout is None or shutil.which("git") is None:
        return ""
    try:
        done = subprocess.run(["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def version_line() -> str:
    """``umat-oti 1.1.0 (checkout /path at commit abc1234)`` -- which code runs."""
    checkout = checkout_root()
    where = (f"checkout {checkout}" + (f" at commit {commit_of(checkout)}"
                                       if commit_of(checkout) else "")
             if checkout else f"installed at {package_dir()}")
    return f"umat-oti {umat_oti.__version__} ({where})"


def make_this_code_visible_to_children() -> None:
    """Put this package's import root first on PYTHONPATH.

    The pipeline starts its own Python processes (``python -m
    umat_oti.abaqus.trial_deck`` and others). Unless they can import THIS
    ``umat_oti`` they either fail or, worse, import another one.
    """
    root = str(import_root())
    existing = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p and p != root]
    os.environ["PYTHONPATH"] = os.pathsep.join([root, *existing])


def _tuple(version: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", version)[:3])


def _installed_command(name: str = "umat-oti") -> Optional[Path]:
    found = shutil.which(name)
    return Path(found) if found else None


def _interpreter_of(script: Path) -> Optional[str]:
    try:
        first = script.read_text(errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return None
    if not first.startswith("#!"):
        return None
    parts = first[2:].strip().split()
    if parts and Path(parts[0]).name == "env" and len(parts) > 1:
        return shutil.which(parts[1])
    return parts[0] if parts else None


def _clean_environment() -> dict:
    """The environment a user's shell gives the installed command: no PYTHONPATH
    of ours, so what it imports is what the install says."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def probe_installed(command: Path, *, timeout: int = 60) -> dict:
    """What the ``umat-oti`` at ``command`` runs: its package file, version and commands."""
    interpreter = _interpreter_of(command)
    answer: dict = {"command": str(command), "interpreter": interpreter}
    if interpreter is None:
        answer["error"] = "its first line names no Python interpreter"
        return answer
    try:
        done = subprocess.run([interpreter, "-c", _PROBE], capture_output=True, text=True,
                              timeout=timeout, env=_clean_environment(), check=False)
        if done.returncode == 0:
            answer.update(json.loads(done.stdout.strip().splitlines()[-1]))
        else:
            answer["error"] = (done.stderr.strip().splitlines() or ["did not import umat_oti"])[-1]
        helped = subprocess.run([str(command), "--help"], capture_output=True, text=True,
                                timeout=timeout, env=_clean_environment(), check=False)
        found = re.search(r"\{([a-z0-9_,\-]+)\}", helped.stdout + helped.stderr)
        answer["commands"] = sorted(found.group(1).split(",")) if found else []
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as error:
        answer["error"] = f"{type(error).__name__}: {error}"
    return answer


def diagnose(*, installed: Optional[dict] = None) -> list:
    """The doctor's findings: ``[(status, sentence), ...]`` with status ok / warn / info."""
    findings: list = []
    findings.append(("info", "Running " + version_line() + "."))
    if sys.version_info[:2] < MINIMUM_PYTHON:
        findings.append(("warn", f"Python {sys.version_info[0]}.{sys.version_info[1]} is older than "
                                 f"{MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]}, which umat-oti needs."))
    else:
        findings.append(("ok", f"Python {sys.version_info[0]}.{sys.version_info[1]}."))
    if shutil.which("gfortran") is None:
        findings.append(("warn", "gfortran is not on PATH; it is needed to compile the converted routine "
                                 "and to check it. Install it (for example `apt install gfortran`)."))
    else:
        findings.append(("ok", "gfortran found."))
    for tool, why in (("ifort", "Abaqus's own compiler, for the Abaqus checks"),
                      ("abaqus", "the solver, for the optional Abaqus runs")):
        if shutil.which(tool) is None:
            findings.append(("info", f"{tool} not found ({why}); not needed for `umat-oti check`."))
    command = _installed_command()
    checkout = checkout_root()
    hint = (f"Run `python {checkout / 'umat-oti'} ...` from this checkout, or install it in a "
            f"fresh virtual environment with `pip install -e {checkout}`."
            if checkout else "Reinstall umat-oti from the checkout you are reading about.")
    if command is None:
        findings.append(("info", "No `umat-oti` command is installed on PATH. " + hint))
        return findings
    if installed is None:
        installed = probe_installed(command)
    if installed.get("error") and not installed.get("file"):
        findings.append(("warn", f"The `umat-oti` on PATH ({command}) does not run: "
                                 f"{installed['error']}. " + hint))
        return findings
    problems = []
    here = package_dir()
    theirs = Path(installed["file"]).resolve().parent if installed.get("file") else None
    if theirs is not None and theirs != here:
        problems.append(f"it runs the code in {theirs} (version {installed.get('version', '?')}), "
                        f"not the code running now ({here}, version {umat_oti.__version__})")
    missing = [c for c in CURRENT_COMMANDS if installed.get("commands") and c not in installed["commands"]]
    if missing:
        problems.append("it has no `" + "` or `".join(missing) + "` command")
    if installed.get("version") and _tuple(installed["version"]) < _tuple(umat_oti.__version__):
        problems.append(f"its version {installed['version']} is older than {umat_oti.__version__}")
    if problems:
        findings.append(("warn", f"The `umat-oti` on PATH ({command}) is older than this checkout: "
                                 + "; ".join(problems) + ". " + hint))
    else:
        findings.append(("ok", f"The `umat-oti` on PATH ({command}) runs this code."))
    return findings


def doctor(argv: Sequence[str] = ()) -> int:
    findings = diagnose()
    marks = {"ok": "ok  ", "warn": "WARN", "info": "    "}
    for status, text in findings:
        print(f"[{marks[status]}] {text}")
    warned = any(status == "warn" for status, _ in findings)
    print("\nEverything needed is in place." if not warned else
          "\nFix the WARN lines above, then run `umat-oti doctor` again.")
    return 1 if warned else 0


_DOOR_HELP = """\
umat-oti: derivatives of a UMAT with respect to its parameters, checked.

  umat-oti check UMAT.for [DECK.inp | FOLDER]   check one UMAT (start here)
  umat-oti doctor                               is this install the one you think it is?
  umat-oti --version                            which code is running, and where

The commands below are the lower-level steps `check` is built from.
"""


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] in (["--version"], ["-V"], ["version"]):
        print(version_line())
        return 0
    if args[:1] == ["doctor"]:
        return doctor(args[1:])
    if args[:1] == ["check"]:
        from umat_oti.app.check_command import main as check_main

        make_this_code_visible_to_children()
        return check_main(args[1:])
    if not args or args[0] in ("-h", "--help"):
        print(_DOOR_HELP)
    from umat_oti.cli import main as cli_main

    make_this_code_visible_to_children()
    return cli_main(args or None)


if __name__ == "__main__":
    raise SystemExit(main())
