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
