"""The three integrity audits of tools/audit_integrity.py, run as tests.

``t12`` compares the audited commit with the baseline commit the completion
work started from: deleted or renamed tests, new skips and deselections,
changed tolerances and removed checks, new warning filters, broad exception
handlers, mocks, deleted examples, changed support metadata and changed
reference data. Every finding must be reviewed in
docs/evidence/integrity_review.json, as justified (with a reason whose quoted
evidence the audit finds where the entry says it is) or as a violation.

``t11`` selects the fix commits since the baseline by the rule in
docs/evidence/bug_fix_regression_map.json; each must be mapped to regression
tests that exist, excluded with a reason, or listed as a fix without a test.

``ci3`` checks that every step of the clean-clone run in
docs/evidence/clean_clone_commands.json still rests on the quoted instruction,
and, in Residual_Assembler, that the list matches what the clean-install gate
and the examples phase really run.

What fails here is a finding nobody reviewed, a review entry that matches
nothing any more, or a quoted passage that is not where it is said to be. A
recorded violation, fix without a test or undocumented step does not fail
these tests: the audit reports it, exits 2 while it is open, and the
completion ledger names it. The audits need the full git history; a shallow
clone fails them with a message saying so.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "audit_integrity.py"


def _audit(check: str, tmp_path: Path) -> tuple[dict, int]:
    report = tmp_path / f"{check}.json"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--check", check, "--report", str(report)],
                               cwd=REPO_ROOT, capture_output=True, text=True)
    assert completed.returncode in (0, 2), completed.stdout + completed.stderr
    return json.loads(report.read_text(encoding="utf-8")), completed.returncode


def _assert_explained(report: dict, returncode: int) -> None:
    assert report["unexplained"] == [], "not reviewed:\n" + "\n".join(report["unexplained"])
    assert report["stale"] == [], "stale entries:\n" + "\n".join(report["stale"])
    assert report["problems"] == [], "\n".join(report["problems"])
    # exit 2 exactly when something reviewed is still open
    assert (returncode == 2) == bool(report["violations"])


def test_t12_every_change_since_the_baseline_is_reviewed(tmp_path):
    report, returncode = _audit("t12", tmp_path)
    _assert_explained(report, returncode)
    assert report["unparsed_python"] == {"base": [], "head": []}
    review = json.loads((REPO_ROOT / "docs/evidence/integrity_review.json").read_text(encoding="utf-8"))
    recorded = sorted(key for key, entry in review["findings"].items() if entry["verdict"] == "violation")
    assert sorted(report["violations"]) == recorded


def test_t11_every_fix_since_the_baseline_names_existing_regression_tests(tmp_path):
    report, returncode = _audit("t11", tmp_path)
    _assert_explained(report, returncode)
    fixes = [row for row in report["rows"] if row["status"].startswith("fix")]
    assert fixes and all(row["bug"] for row in fixes)
    without = sorted(row["commit"] for row in fixes if not row["tests"])
    assert sorted(entry.split(":")[0][:7] for entry in report["violations"]) == without


def test_ci3_every_clean_clone_step_rests_on_a_quoted_instruction(tmp_path):
    report, returncode = _audit("ci3", tmp_path)
    _assert_explained(report, returncode)
    here = report["repository"]
    checked = [row for row in report["steps"] if here in row["checked"]]
    assert checked and all(row["checked"][here] == "quotes found"
                           for row in checked if row["status"] == "documented")
    if here == "RA":
        # the step list is the gate's and the examples phase's real command list
        assert report["coverage"]["gate_calls"].endswith("compared with scripts/clean_install_gate.py")
        assert report["coverage"]["example_calls"].endswith("compared with scripts/audit_recovery_usage.py")


# -- the scanner itself, on a repository made for it --------------------------

BASE_FILES = {
    "pyproject.toml": ('[project]\nname = "sample"\nclassifiers = [\n'
                       '\t"Operating System :: OS Independent",\n]\n'
                       '[tool.pytest.ini_options]\naddopts = "-ra"\n'),
    "codemeta.json": '{"operatingSystem": ["Linux", "Windows"]}\n',
    "examples/demo/run.py": "print('demo')\n",
    "src/sample/verify.py": ("TOLERANCE = 1e-8\n\n\ndef check(error):\n"
                             "    if error > TOLERANCE:\n        raise ValueError(error)\n"),
    "tests/test_sample.py": ("import numpy as np\n\n\ndef test_kept():\n"
                             "    assert abs(1.0 - 1.0) < 1e-12\n"
                             "    np.testing.assert_allclose(1.0, 1.0, rtol=1e-10)\n\n\n"
                             "def test_dropped():\n    assert 1 == 1\n"),
}

HEAD_FILES = {
    "pyproject.toml": ('[project]\nname = "sample"\nclassifiers = [\n'
                       '\t"Operating System :: POSIX :: Linux",\n]\n'
                       '[tool.pytest.ini_options]\naddopts = "-ra -p no:warnings"\n'
                       'filterwarnings = ["ignore::DeprecationWarning"]\n'),
    "codemeta.json": '{"operatingSystem": ["Linux"]}\n',
    "src/sample/verify.py": ("TOLERANCE = 1e-8\n\n\ndef check(error):\n    try:\n        return error\n"
                             "    except Exception:\n        pass\n"),
    "tests/test_sample.py": ("import warnings\n\nimport numpy as np\nimport pytest\n\n\ndef test_kept(monkeypatch):\n"
                             "    assert abs(1.0 - 1.0) < 1e-6\n"
                             "    np.testing.assert_allclose(1.0, 1.0, rtol=1e-12)\n"
                             "    monkeypatch.setattr(np.linalg, 'solve', lambda a, b: b)\n"
                             "    warnings.simplefilter('ignore')\n\n\n"
                             "@pytest.mark.skip(reason='not today')\ndef test_new():\n"
                             "    pytest.importorskip('nothing_of_the_kind')\n"),
}


def _commit(root: Path, files: dict, message: str) -> str:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git = ["git", "-c", "user.name=audit", "-c", "user.email=audit@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run(git + ["add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(git + ["commit", "-q", "-m", message], cwd=root, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


def test_the_scanner_finds_each_kind_of_change(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import audit_integrity as audit

    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    base = _commit(root, BASE_FILES, "baseline")
    (root / "examples/demo/run.py").unlink()
    _commit(root, HEAD_FILES, "the changes the audit must see")
    findings = audit.T12(audit.Revision(base, root=root), audit.Revision("HEAD", root=root)).run()
    by_category: dict[str, list] = {}
    for finding in findings:
        by_category.setdefault(finding["category"], []).append(finding)

    assert [f["id"] for f in by_category["deleted_test"]] == [
        "deleted_test:tests/test_sample.py::test_dropped"]
    kinds = sorted(f["summary"] for f in by_category["skip"])
    assert kinds == ["call:importorskip added", "mark.skip added"]
    changes = {f["qualname"] + " " + f["summary"].split(":")[0]: f["change"] for f in by_category["tolerance"]}
    assert changes == {"test_kept assert abs(1.0 - 1.0) <": "loosened",
                       "test_kept kwarg np.testing.assert_allclose": "tightened"}
    assert [f["text"] for f in by_category["removed_check"]] == ["error > TOLERANCE"]
    assert sorted(f["text"] for f in by_category["warning_filter"]) == [
        "addopts -p no:warnings", "filterwarnings ignore::DeprecationWarning", "warnings.simplefilter('ignore')"]
    assert [f["summary"] for f in by_category["broad_except"]] == ["except Exception added"]
    assert [f["path"] for f in by_category["deleted_example"]] == ["examples/demo/run.py"]
    assert sorted(f["id"] for f in by_category["metadata"]) == [
        "metadata:codemeta.json:operatingSystem[1]",
        "metadata:pyproject.toml:classifier:+Operating System :: POSIX :: Linux",
        "metadata:pyproject.toml:classifier:-Operating System :: OS Independent"]
    assert [f["summary"] for f in by_category["mock"]] == ["monkeypatch.setattr added"]
    # every finding names the commit that made the change
    assert all(finding["commits"] for finding in findings), [f["id"] for f in findings if not f["commits"]]


def test_a_quote_that_is_not_where_it_is_said_to_be_is_a_problem(tmp_path):
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import audit_integrity as audit

    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    base = _commit(root, {"notes.txt": "the tolerance was tightened\n"}, "baseline")
    _commit(root, {"notes.txt": "the tolerance was loosened\n"}, "head")
    revisions = audit.Revision(base, root=root), audit.Revision("HEAD", root=root)
    assert audit.check_evidence({"evidence": [{"in": "notes.txt", "text": "was loosened"},
                                              {"in": "BASE:notes.txt", "text": "was tightened"}]},
                                *revisions) == []
    assert audit.check_evidence({"quote": "was tightened", "quote_source": "notes.txt"}, *revisions) == [
        "text not found in notes.txt: 'was tightened'"]
