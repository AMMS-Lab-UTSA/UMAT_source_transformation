"""The reproduction entry point and its guarantees."""

from __future__ import annotations

import json
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


def test_environment_capture_names_the_toolchain():
    environment = capture_environment()
    assert environment["python"]
    assert "gfortran" in environment and "abaqus" in environment


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
