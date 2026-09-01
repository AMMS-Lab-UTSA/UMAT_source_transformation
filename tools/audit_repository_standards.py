#!/usr/bin/env python
"""Audit the repository against the standards a SoftwareX reviewer expects.

Every check reports the exact offending paths rather than a pass/fail count, so
a failure is actionable without rerunning anything. Exits non-zero if any
required check fails, which is what makes it usable as a CI gate.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "README.md", "START_HERE.md", "LICENSE.txt", "CITATION.cff", "codemeta.json",
    ".zenodo.json", "CHANGELOG.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
    "SECURITY.md", "AUTHORS.md", "THIRD_PARTY_NOTICES.md", ".gitignore",
    ".gitattributes", "pyproject.toml",
)

#: Generated build products that must never be tracked.
BINARY_SUFFIXES = {".o", ".mod", ".so", ".obj", ".a", ".pyc", ".exe"}

#: A tracked file naming someone's home directory cannot be reproduced by anyone
#: else. Evidence is exempt only where it records where a run happened, and even
#: then the path must not be required to re-run anything.
HOME_PATH = re.compile(r"/home/[a-z][-a-z0-9_]*/|/Users/[A-Za-z][-A-Za-z0-9_]*/")

#: Scratch directories are as machine-specific as a home directory and are not
#: caught by the pattern above -- a run whose work directory was under
#: /tmp/claude-<uid>/ wrote three of those absolute paths into a published
#: blocker column, and the audit passed because the string never said /home/.
#: Named prefixes only: the bare word /tmp is legitimate in prose and in
#: documented commands, and banning it would make this check unusable.
SCRATCH_PATH = re.compile(
    r"/tmp/(?:claude|tmp|pytest-of-|pyright-|scratch)[-a-zA-Z0-9_.]*/"
    r"|/var/folders/[a-zA-Z0-9_]+/")

SECRET_PATTERNS = (
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"), "GitHub token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key)\s*[:=]\s*['\"][^'\"\s]{8,}"),
     "hardcoded credential"),
)

TEXT_SUFFIXES = {
    ".py", ".md", ".json", ".toml", ".cfg", ".ini", ".yml", ".yaml", ".sh",
    ".txt", ".for", ".f", ".f90", ".csv", ".cff",
}


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True)
    return [REPO_ROOT / name for name in out.stdout.split("\0") if name]


def check_required_files(files: list[Path]) -> dict:
    present = {str(p.relative_to(REPO_ROOT)) for p in files}
    missing = [name for name in REQUIRED_FILES if name not in present]
    return {"name": "required_project_files", "required": True,
            "ok": not missing, "offenders": missing}


def check_no_tracked_binaries(files: list[Path]) -> dict:
    offenders = [str(p.relative_to(REPO_ROOT)) for p in files
                 if p.suffix.lower() in BINARY_SUFFIXES]
    return {"name": "no_tracked_build_products", "required": True,
            "ok": not offenders, "offenders": offenders}


def check_no_pycache(files: list[Path]) -> dict:
    offenders = [str(p.relative_to(REPO_ROOT)) for p in files
                 if "__pycache__" in p.parts]
    return {"name": "no_tracked_pycache", "required": True,
            "ok": not offenders, "offenders": offenders}


def _text_files(files: list[Path]) -> list[Path]:
    return [p for p in files if p.suffix.lower() in TEXT_SUFFIXES and p.is_file()]


def _exemptions() -> list[dict]:
    config = REPO_ROOT / "tools" / "repository_standards.json"
    if not config.is_file():
        return []
    return json.loads(config.read_text(encoding="utf-8"))["absolute_path_exemptions"]


def check_no_absolute_home_paths(files: list[Path]) -> dict:
    """Reviewer-facing files must not name anyone's home directory.

    Archived run records are exempt by path prefix, each with a stated reason:
    rewriting a Slurm log's working directory would falsify the record. The
    exemption never covers anything a reproduction reads as input, and the
    authoritative proof of independence is the clean-clone acceptance script.

    A scratch directory counts as a machine path for the same reason a home
    directory does. It did not count until a triage run put its own /tmp work
    directory into the published blocker column and this check passed anyway.
    """
    exempt = tuple(e["prefix"] for e in _exemptions())
    offenders = []
    exempted = 0
    for path in _text_files(files):
        relative = str(path.relative_to(REPO_ROOT))
        if relative.startswith(exempt):
            exempted += 1
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if HOME_PATH.search(line) or SCRATCH_PATH.search(line):
                offenders.append(f"{relative}:{number}")
    return {"name": "no_absolute_home_paths_outside_archived_records",
            "required": True, "ok": not offenders, "offenders": offenders[:80],
            "total": len(offenders), "exempted_files": exempted}


def check_no_secrets(files: list[Path]) -> dict:
    offenders = []
    for path in _text_files(files):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern, label in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                line = text[:match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line} ({label})")
    return {"name": "no_secrets", "required": True,
            "ok": not offenders, "offenders": offenders}


def check_gitignore_covers_build_output() -> dict:
    path = REPO_ROOT / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    needed = ["__pycache__", "*.o", "*.mod", "build/", "*.so"]
    missing = [entry for entry in needed if entry not in text]
    return {"name": "gitignore_covers_build_output", "required": True,
            "ok": not missing, "offenders": missing}


def check_pyproject_declares_packaging() -> dict:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    missing = [key for key in ("[project]", "name =", "version =", "dependencies",
                               "[tool.pytest.ini_options]", "markers")
               if key not in text]
    return {"name": "pyproject_declares_packaging_and_markers", "required": True,
            "ok": not missing, "offenders": missing}


CHECKS = (
    check_required_files, check_no_tracked_binaries, check_no_pycache,
    check_no_absolute_home_paths, check_no_secrets,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    files = tracked_files()
    results = [check(files) for check in CHECKS]
    results.append(check_gitignore_covers_build_output())
    results.append(check_pyproject_declares_packaging())

    failed = [r for r in results if r["required"] and not r["ok"]]
    report = {"tracked_files": len(files), "checks": results,
              "failed": [r["name"] for r in failed]}

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for result in results:
            mark = "PASS" if result["ok"] else "FAIL"
            count = result.get("total", len(result["offenders"]))
            print(f"[{mark}] {result['name']}"
                  + (f"  ({count} offending)" if not result["ok"] else ""))
            for offender in result["offenders"][:20]:
                print(f"         {offender}")
            if len(result["offenders"]) > 20:
                print(f"         ... and {count - 20} more")
        print(f"\n{len(files)} tracked files, {len(failed)} failing checks")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
