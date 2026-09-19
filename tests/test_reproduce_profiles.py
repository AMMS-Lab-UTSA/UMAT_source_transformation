"""The reproduction entry point and its guarantees."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from umat_oti.reproduce import PROFILES, build_steps, capture_environment

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ARTIFACTS = (
    "run_manifest.json", "environment.json", "claim_matrix.json",
    "artifact_checksums.sha256", "reproduction_summary.md",
)


def test_every_profile_builds_a_non_empty_step_list():
    for profile in PROFILES:
        assert build_steps(profile, allow_network=False), profile


def test_environment_capture_records_provenance_and_toolchain():
    """A reproduction must say what it ran on and from what.

    Repository URL, exact commit and dirty state all change results, so a
    record without them cannot be audited.
    """
    environment = capture_environment()
    assert environment["python"]
    repository = environment["repository"]
    for key in ("url", "commit", "branch", "worktree_dirty"):
        assert key in repository, key
    toolchain = environment["toolchain"]
    for tool in ("gfortran", "make", "abaqus"):
        assert tool in toolchain, tool
        report = toolchain[tool]
        assert "available" in report and "executable" in report
        # Unavailable is only meaningful with a reason attached.
        if not report["available"]:
            assert report.get("reason")


def test_abaqus_detection_does_not_mistake_the_launcher_banner_for_a_version():
    """Regression: the version was read as "Abaqus JOB abaqus".

    Taking the first line of `abaqus information=release` picks up the
    launcher's banner. A string like that is not evidence that a usable Abaqus
    exists, and reporting it as the version made an unusable installation look
    fine.
    """
    from umat_oti.environment import detect_abaqus

    report = detect_abaqus()
    if report.version is not None:
        assert "JOB" not in report.version
        assert re.match(r"^\d{4}", report.version), report.version
    if report.available:
        # Available means a job could actually be submitted, so the licence
        # check must have found a feature to use.
        assert report.details.get("licences_issued", 0) > 0
    else:
        assert report.reason


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_smoke_profile_succeeds_and_writes_every_artifact(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "umat_oti.reproduce", "--profile", "smoke",
         "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for name in REQUIRED_ARTIFACTS:
        assert (tmp_path / name).is_file(), name
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["counts"]["failed"] == 0
    assert manifest["counts"]["succeeded"] == manifest["counts"]["total"]


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_subset_round_does_not_overwrite_published_evidence(tmp_path):
    """A one-model round must not replace the full Table 6 evidence.

    Regression: the smoke profile ran the sweep with --model m3_j2 and the sweep
    wrote unconditionally to paper_results/, so a four-second smoke test silently
    replaced an eighteen-model round with a one-model round that still looked
    complete.
    """
    published = (REPO_ROOT / "paper_results" / "parameter_sensitivity"
                 / "parameter_sensitivity_round.json")
    before = published.read_text(encoding="utf-8")
    subprocess.run(
        [sys.executable, "tools/run_parameter_sensitivity_sweep.py",
         "--model", "m3_j2", "--work-dir", str(tmp_path / "work"),
         "--results-dir", str(tmp_path / "results")],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    assert published.read_text(encoding="utf-8") == before
    assert (tmp_path / "results" / "parameter_sensitivity_round.json").is_file()


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_subset_round_defaults_away_from_the_published_location(tmp_path):
    """Even without --results-dir, a --model subset must not land on the round."""
    published = (REPO_ROOT / "paper_results" / "parameter_sensitivity"
                 / "parameter_sensitivity_round.json")
    before = published.read_text(encoding="utf-8")
    subprocess.run(
        [sys.executable, "tools/run_parameter_sensitivity_sweep.py",
         "--model", "m1_elastic", "--work-dir", str(tmp_path / "work")],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    assert published.read_text(encoding="utf-8") == before


def test_repository_discovery_finds_this_checkout():
    from umat_oti.reproduce import find_repository_root

    root = find_repository_root()
    assert root is not None
    assert (root / "tools").is_dir() and (root / "parameter_sensitivity").is_dir()


def test_repository_discovery_reports_absence_rather_than_guessing(monkeypatch, tmp_path):
    """Regression: an installed wheel resolved REPO_ROOT into site-packages.

    Reproduction reads benchmark models and round runners that are repository
    content and are deliberately not shipped in the wheel. Walking up from the
    module file found them for an editable install and silently pointed at
    site-packages for a real one, where the step died with
    "can't open file .../lib/python3.11/tools/run_parameter_sensitivity_sweep.py".
    """
    import umat_oti.reproduce as reproduce

    monkeypatch.delenv("UMAT_OTI_REPO_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(reproduce, "__file__", str(tmp_path / "pkg" / "umat_oti" / "reproduce.py"))
    assert reproduce.find_repository_root() is None


def test_an_unsupported_step_is_not_reported_as_an_external_blocker():
    """Unimplemented is not the same as blocked by someone else.

    The corpus step used to claim blocked_by_external_dependency because a live
    round needs the network. The network is a real dependency of such a round,
    but it is not what stops this entry point: no round is wired in at all.
    """
    from umat_oti.reproduce import step_corpus
    from umat_oti.pipeline.status import StageStatus
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        result = step_corpus(Path(tmp))
    assert result.status == StageStatus.UNSUPPORTED.value
    assert "not an external blocker" in result.reason


def _summary_for(directory: Path, environment: dict) -> str:
    from umat_oti.reproduce import ProfileRun, write_outputs

    out = directory / "out"
    out.mkdir(parents=True)
    write_outputs(ProfileRun(profile="smoke", out_dir=out), environment)
    return (out / "reproduction_summary.md").read_text(encoding="utf-8")


def _git_reads_only(monkeypatch, tree: Path, ceiling: Path) -> None:
    """Point the environment capture at ``tree``, with no repository above ``ceiling``."""
    import umat_oti.reproduce as reproduce

    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(ceiling))
    monkeypatch.setattr(reproduce, "REPO_ROOT", tree)


def test_a_tree_git_cannot_read_is_not_reported_clean(tmp_path, monkeypatch):
    """Regression: a copied tree that is not a checkout was summarised "(clean)".

    git fails there, and its failure and a clean tree's empty status both came
    back as nothing, so the record said clean. The state is unknown, and the
    record and the summary say so.
    """
    from umat_oti.reproduce import capture_environment

    copied = tmp_path / "copied_tree"
    copied.mkdir()
    _git_reads_only(monkeypatch, copied, tmp_path)

    environment = capture_environment()
    repository = environment["repository"]
    assert repository["commit"] is None
    assert repository["worktree_dirty"] is None
    summary = _summary_for(tmp_path, environment)
    assert "- Commit: not a git checkout (worktree state unknown" in summary
    assert "(clean)" not in summary


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_a_checkout_git_can_read_is_still_reported_clean_or_dirty(tmp_path, monkeypatch):
    from umat_oti.reproduce import capture_environment

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git_reads_only(monkeypatch, checkout, tmp_path)

    def git(*args: str) -> None:
        subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.org",
                        *args], cwd=checkout, check=True, capture_output=True)

    git("init", "-q")
    (checkout / "file.txt").write_text("one\n", encoding="utf-8")
    git("add", "file.txt")
    git("commit", "-q", "-m", "one")

    clean = capture_environment()
    assert clean["repository"]["worktree_dirty"] is False
    assert " (clean)" in _summary_for(tmp_path / "clean", clean)

    (checkout / "file.txt").write_text("two\n", encoding="utf-8")
    dirty = capture_environment()
    assert dirty["repository"]["worktree_dirty"] is True
    assert dirty["repository"]["dirty_paths"]
    assert " (worktree dirty)" in _summary_for(tmp_path / "dirty", dirty)
