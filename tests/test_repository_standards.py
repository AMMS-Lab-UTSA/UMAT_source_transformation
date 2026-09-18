"""Repository-standards and documentation audits, run as tests.

These also run as CI steps. Having them here means `make test` catches a
regression before it reaches CI.
"""

from __future__ import annotations

import json
import re
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


def test_historical_inventory_paths_are_not_local_but_commands_and_links_are(
        tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import audit_documentation_commands as audit_module

    (tmp_path / "examples").mkdir()
    (tmp_path / "docs").mkdir()
    historical = tmp_path / "docs" / "BRANCH_IMPLEMENTATION_AUDIT.md"
    historical.write_text(
        "`examples/from_another_repository`\n"
        "[missing link](missing.md)\n"
        "```bash\npython tools/missing.py\n```\n", encoding="utf-8")
    current = tmp_path / "docs" / "CURRENT.md"
    current.write_text("`examples/missing_local_example`\n", encoding="utf-8")
    monkeypatch.setattr(audit_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(audit_module, "doc_files", lambda: [historical, current])

    assert audit_module.audit() == [
        {"doc": "docs/BRANCH_IMPLEMENTATION_AUDIT.md", "kind": "broken_link",
         "detail": "missing.md"},
        {"doc": "docs/BRANCH_IMPLEMENTATION_AUDIT.md", "kind": "missing_script",
         "detail": "tools/missing.py"},
        {"doc": "docs/CURRENT.md", "kind": "stale_path_reference",
         "detail": "examples/missing_local_example"},
    ]


def test_companion_links_use_explicit_checkout_and_still_check_targets(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import audit_documentation_commands as audit_module

    root = tmp_path / "arbitrary-producer"
    companion = tmp_path / "arbitrary-consumer"
    doc = root / "docs/CURRENT.md"
    doc.parent.mkdir(parents=True)
    companion.mkdir()
    (companion / "README.md").write_text("reference")
    doc.write_text("[valid](../../Residual_Assembler/README.md)\n"
                   "[broken](../../Residual_Assembler/absent.md)\n")
    monkeypatch.setattr(audit_module, "REPO_ROOT", root)
    monkeypatch.setattr(audit_module, "doc_files", lambda: [doc])
    monkeypatch.setenv("RESASM_REPO", str(companion))
    assert audit_module.audit() == [{"doc": "docs/CURRENT.md", "kind": "broken_link",
                                     "detail": "../../Residual_Assembler/absent.md"}]


def test_every_machine_path_fixture_marker_states_a_reason():
    """A marker with nothing after it is a hole, not an exemption.

    The line-level marker exists so the filter's own tests can hold paths
    shaped like real ones. It is worth having only while every use of it says
    which fixture it excuses, and only while it stays confined to the files
    that handle machine paths -- one appearing in evidence or documentation
    would mean a real path was marked rather than removed.
    """
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from audit_repository_standards import FIXTURE_MARKER

    # A marker is a comment, so look for one -- matching the bare token would
    # match this test's own search for it, and the pattern's own definition.
    looks_like_a_marker = re.compile(r"#\s*machine-path-fixture:")
    allowed = ("tests/", "tools/")
    found = 0
    for path in REPO_ROOT.rglob("*.py"):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        relative = str(path.relative_to(REPO_ROOT))
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if not looks_like_a_marker.search(line):
                continue
            found += 1
            where = f"{relative}:{number}"
            assert FIXTURE_MARKER.search(line), f"{where} states no reason"
            reason = line.split("machine-path-fixture:", 1)[1].strip()
            assert len(reason) > 20, f"{where} states only {reason!r}"
            assert relative.startswith(allowed), f"{where} is outside {allowed}"
    assert found, "the marker is unused; delete it rather than leaving it armed"


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

    leaked = "as shipped: /tmp/claude-1000/-home-someone/abc/work/u.for:3: Error"  # machine-path-fixture: a fabricated path, proving this audit's own patterns match it
    assert not HOME_PATH.search(leaked), "the old pattern really did miss it"
    assert SCRATCH_PATH.search(leaked)

    for path in ("/tmp/tmp.J8e353cPrO/out/",  # machine-path-fixture: a fabricated path, proving this audit's own patterns match it
                 "/tmp/pytest-of-someone/pytest-1/",  # machine-path-fixture: a fabricated path, proving this audit's own patterns match it
                 "/var/folders/kx/T/build/"):  # machine-path-fixture: a fabricated path, proving this audit's own patterns match it
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
