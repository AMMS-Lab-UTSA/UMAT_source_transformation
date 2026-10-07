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
import textwrap
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
                                 + "; ".join(problems) + "."))
        findings.append(("fix", hint))
    else:
        findings.append(("ok", f"The `umat-oti` on PATH ({command}) runs this code."))
    return findings


def doctor(argv: Sequence[str] = ()) -> int:
    findings = diagnose()
    marks = {"ok": "ok  ", "warn": "WARN", "info": "    ", "fix": "fix "}
    warnings = [text for status, text in findings if status == "warn"]
    if warnings and all("on PATH" in text for text in warnings):
        # exit code stays 1 (the install on PATH is not this checkout), but the user is told first that nothing else is wrong
        print("All else is fine: the tools umat-oti needs are in place. One thing to put right, below.")
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


_ONE_LINE = {
    "check": "Check one UMAT: read its files, convert it, verify it and give the verdict (start here).",
    "doctor": "Say which umat-oti code is running and whether the command on your PATH is the same.",
}


def _lower_level_help() -> str:
    """The pipeline's own ``--help`` with ``check`` and ``doctor`` added to its usage line and its command list."""
    import contextlib
    import io

    from umat_oti.cli import main as cli_main

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            cli_main(["--help"])
        except SystemExit:
            pass
    text = buffer.getvalue()
    text = text.replace("{all,transform,config,jacobian}", "{check,doctor,all,transform,config,jacobian}")
    lines, added = [], False
    for line in text.splitlines():
        if line.startswith("    all ") and not added:
            for name, sentence in _ONE_LINE.items():
                wrapped = textwrap.wrap(sentence, 50)
                lines.append(f"    {name:<19} {wrapped[0]}")
                lines += [" " * 24 + w for w in wrapped[1:]]
            added = True
        lines.append(line)
    return "\n".join(lines)


def _plain_usage_error(text: str) -> str:
    """The message of an argparse failure, without its usage block or its prefix."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    errors = [l for l in lines if "error:" in l]
    message = errors[-1] if errors else (lines[-1] if lines else "the command line was not understood")
    return message.rsplit("error: ", 1)[-1]


def _out_of(args: Sequence[str]) -> Optional[Path]:
    for index, token in enumerate(args):
        if token == "--out" and index + 1 < len(args):
            return Path(args[index + 1])
        if token.startswith("--out="):
            return Path(token.split("=", 1)[1])
    return None


def run_with_cards(command: str, args: Sequence[str]) -> int:
    """Run ``umat-oti all`` or ``umat-oti jacobian`` and, when it is refused or fails,
    print the plain card (:mod:`umat_oti.app.refusal_cards`) instead of the raw JSON
    error or an internal script's usage text. The raw output is kept in a file; on
    success the command's output passes through unchanged."""
    import contextlib
    import io

    from umat_oti.cli import main as cli_main

    out_text, err_text = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_text), contextlib.redirect_stderr(err_text):
        try:
            code = cli_main([command, *args])
        except SystemExit as stop:
            code = stop.code if isinstance(stop.code, int) else (0 if stop.code in (None, 0) else 2)
    printed, errors = out_text.getvalue(), err_text.getvalue()
    if code == 0:
        sys.stdout.write(printed)
        sys.stderr.write(errors)
        return 0
    if "usage:" in errors and not printed.strip():
        print(f"umat-oti {command}: {_plain_usage_error(errors)}", file=sys.stderr)
        print("The one-command route is: umat-oti check my_umat.for [my_deck.inp]   "
              "(umat-oti check --help)", file=sys.stderr)
        return int(code)
    from umat_oti.app.check_command import clean_reason, failure_state, print_card
    from umat_oti.app.check_preflight import normalise, refusal_from_summary

    summary = None
    try:
        summary = json.loads(printed) if printed.lstrip().startswith("{") else None
    except ValueError:
        summary = None
    if command == "all" and isinstance(summary, dict):
        state, reason = failure_state(summary)
    elif isinstance(summary, dict):
        found = refusal_from_summary(summary, exit_code=int(code), succeeded=False)
        state, reason = found if found else ("transform_refused", "the transformation did not complete")
    else:
        state = "transform_refused"
        reason = normalise(clean_reason(printed or errors))
    destination = _out_of(args)
    where = None
    try:
        folder = destination if destination is not None and destination.is_dir() else Path.cwd()
        where = folder / f"umat-oti-{command}-output.json"
        where.write_text(printed or errors, encoding="utf-8")
    except OSError:
        where = None
    print_card(state, reason)
    if summary is None and (printed or errors).strip():
        print("The program said: " + clean_reason(printed or errors).strip().splitlines()[0][:300])
    if where is not None:
        print(f"Everything the program recorded is in {where}")
    return int(code)


def guard_all(args: Sequence[str]) -> Optional[int]:
    """Before ``all`` asks for material data, ask whether the routine can be converted
    at all, so the first refusal is the real one. Returns an exit code to stop, or None."""
    import argparse
    import tempfile

    from umat_oti.app.check_command import print_card
    from umat_oti.app.check_intake import scan_source
    from umat_oti.app.check_preflight import preflight

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("--dependency-root", type=Path, action="append", default=[])
    known, _ = parser.parse_known_args(list(args))
    if known.source is None or not known.source.is_file():
        return None
    source = known.source.expanduser().resolve()
    work = Path(tempfile.mkdtemp(prefix="umat-oti-preflight-"))
    blocked = preflight(source, scan_source(source),
                        [p.expanduser().resolve() for p in known.dependency_root], work)
    if blocked is None:
        return None
    print_card(*blocked)
    print(f"Everything the program recorded is in {work}")
    return 2


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
    if args[:1] in (["all"], ["jacobian"]):
        make_this_code_visible_to_children()
        if args[0] == "all" and "-h" not in args and "--help" not in args:
            stop = guard_all(args[1:])
            if stop is not None:
                return stop
        if "-h" in args or "--help" in args:
            from umat_oti.cli import main as cli_main

            return cli_main(args)
        return run_with_cards(args[0], args[1:])
    if not args or args[0] in ("-h", "--help"):
        print(_DOOR_HELP)
        print(_lower_level_help())
        return 0
    from umat_oti.cli import main as cli_main

    make_this_code_visible_to_children()
    return cli_main(args or None)


if __name__ == "__main__":
    raise SystemExit(main())
