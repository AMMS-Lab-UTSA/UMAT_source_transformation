"""Repository-standards and documentation audits, run as tests.

These also run as CI steps. Having them here means `make test` catches a
regression before it reaches CI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, f"tools/{script}", "--json"],
                          cwd=REPO_ROOT, capture_output=True, text=True)


def test_repository_standards_audit_passes():
    proc = _run("audit_repository_standards.py")
    report = json.loads(proc.stdout)
    assert report["failed"] == [], json.dumps(report["checks"], indent=2)


def test_documented_commands_and_links_resolve():
    proc = _run("audit_documentation_commands.py")
    problems = json.loads(proc.stdout)["problems"]
    assert problems == [], json.dumps(problems, indent=2)


def test_every_absolute_path_exemption_states_a_reason():
    """An exemption without a reason is an unexamined hole in the check."""
    config = json.loads(
        (REPO_ROOT / "tools" / "repository_standards.json").read_text(encoding="utf-8"))
    for entry in config["absolute_path_exemptions"]:
        assert entry["prefix"] and len(entry["reason"]) > 40, entry


def test_exemptions_never_cover_source_or_tests():
    """Code a reviewer executes must never be exempt from the path check."""
    config = json.loads(
        (REPO_ROOT / "tools" / "repository_standards.json").read_text(encoding="utf-8"))
    for entry in config["absolute_path_exemptions"]:
        assert not entry["prefix"].startswith(("src/", "tests/", "scripts/", "examples/"))
        assert entry["prefix"] not in {"", "."}


def test_a_scratch_directory_counts_as_a_machine_path():
    """A /tmp work directory is as machine-specific as a home directory.

    It did not count until a triage run wrote its own scratch path into the
    published blocker column and this audit passed anyway -- the string never
    said /home/, so nothing objected. Three rows of committed evidence named
    a directory that exists on exactly one computer.
    """
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from audit_repository_standards import HOME_PATH, SCRATCH_PATH

    leaked = "as shipped: /tmp/claude-1000/-home-someone/abc/work/u.for:3: Error"
    assert not HOME_PATH.search(leaked), "the old pattern really did miss it"
    assert SCRATCH_PATH.search(leaked)

    for path in ("/tmp/tmp.J8e353cPrO/out/",
                 "/tmp/pytest-of-someone/pytest-1/",
                 "/var/folders/kx/T/build/"):
        assert SCRATCH_PATH.search(path), path


def test_the_word_tmp_is_still_allowed_in_prose():
    """The check names scratch prefixes, not the bare directory.

    Documented commands and prose legitimately say /tmp, and a check that
    banned it would be turned off rather than obeyed.
    """
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from audit_repository_standards import SCRATCH_PATH

    for benign in ("write it to /tmp if you like",
                   "--work-dir /tmp/umat-oti-work",
                   "export TMPDIR=/tmp"):
        assert not SCRATCH_PATH.search(benign), benign
