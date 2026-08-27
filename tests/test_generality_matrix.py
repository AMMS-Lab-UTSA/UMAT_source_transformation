"""The generality matrix must report evidence, never assert capability."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX = REPO_ROOT / "paper_results" / "generality" / "generality_matrix.csv"
SUMMARY = REPO_ROOT / "paper_results" / "generality" / "generality_summary.json"
ROUND = (REPO_ROOT / "paper_results" / "parameter_sensitivity"
         / "parameter_sensitivity_round.json")
JACOBIANS = (REPO_ROOT / "paper_results" / "internal_jacobians"
             / "internal_jacobian_round.json")

REQUIRED_COLUMNS = {
    "identity", "provenance", "license", "source_form", "file_layout",
    "helper_routines", "include_files", "kinematics", "ntens", "nstatv",
    "nprops", "path_dependent", "constitutive_class", "existing_tangent",
    "derivative_families_requested", "highest_stage_reached", "transformation",
    "compilation", "primal_parity", "numerical_verification",
    "internal_jacobian", "abaqus", "failure_category_and_blocker",
}


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    if not MATRIX.is_file():
        pytest.skip("generality matrix has not been generated")
    return list(csv.DictReader(MATRIX.open(encoding="utf-8")))


def test_matrix_carries_every_required_column(rows):
    assert REQUIRED_COLUMNS.issubset(set(rows[0]))


def test_every_verified_row_traces_to_an_executed_round(rows):
    """A 'succeeded' in the matrix must exist in the round that produced it.

    The matrix joins several rounds, so each origin is checked against its own
    source of truth. It must never be the only place a result lives.
    """
    payload = json.loads(ROUND.read_text(encoding="utf-8"))
    sweep_verified = {m["model"] for m in payload["models"]
                      if m["stages"].get("derivatives_verified", {}).get("status")
                      == "succeeded"}
    # Rows are merged on canonical identity, so a sweep model that also appears
    # elsewhere carries several aliases. Compare on the aliases rather than on a
    # single label.
    from_sweep = {alias for r in rows
                  if r["numerical_verification"] == "succeeded"
                  and "parameter_sensitivity benchmark set" in r["origin"]
                  for alias in r["aliases"].split(";")}
    assert sweep_verified <= from_sweep

    corpus_file = (REPO_ROOT / "paper_results" / "corpus" / "corpus_round.json")
    if corpus_file.is_file():
        corpus = json.loads(corpus_file.read_text(encoding="utf-8"))
        corpus_verified = {c["id"] for c in corpus["candidates"]
                           if c.get("furthest_stage") == "derivatives_verified"}
        from_corpus = {alias for r in rows
                       if r["numerical_verification"] == "succeeded"
                       and "external corpus" in r["origin"]
                       for alias in r["aliases"].split(";")}
        assert corpus_verified <= from_corpus


def test_internal_jacobian_column_matches_the_jacobian_round(rows):
    """Every verified extraction must be reachable from some canonical row."""
    matrix = {alias for r in rows if r["internal_jacobian"] == "succeeded"
              for alias in r["aliases"].split(";")}
    payload = json.loads(JACOBIANS.read_text(encoding="utf-8"))
    executed = {r["id"] for r in payload["records"] if r["bucket"] == "verified"}
    assert executed <= matrix, executed - matrix


def test_abaqus_is_blocked_unless_an_executed_job_says_otherwise(rows):
    """No row may claim an Abaqus result without an executed job behind it.

    The point has always been that an Abaqus verdict is traceable to a run
    that happened, not that the run happened on a cluster. There are now two
    places one can come from -- the archived cluster round, which names its
    Slurm job, and the local paired round, which writes
    paper_results/abaqus_paired/. Both name themselves in the cell. Anything
    else is a verdict with nothing behind it.
    """
    allowed_provenance = ("slurm", "local paired round")
    for row in rows:
        value = row["abaqus"]
        assert (value == "blocked_by_external_dependency"
                or any(token in value for token in allowed_provenance)), (
            f"{row['identity']}: abaqus={value!r} names no executed job")


def test_every_local_abaqus_claim_is_backed_by_a_row_in_that_round(rows):
    """And the run it points at has to actually say it passed."""
    round_path = (REPO_ROOT / "paper_results" / "abaqus_paired"
                  / "abaqus_paired_round.json")
    claiming = [r for r in rows if "local paired round" in r["abaqus"]]
    if not claiming:
        pytest.skip("no row claims the local paired round")
    assert round_path.is_file(), (
        "rows cite the local paired round but its results are not published")
    passed = {r["model"] for r in json.loads(round_path.read_text(encoding="utf-8"))["rows"]
              if r["status"] == "passed"}
    for row in claiming:
        aliases = set(row["aliases"].split(";")) | {row["identity"]}
        assert aliases & passed, (
            f"{row['identity']} claims a local Abaqus pass, but that round "
            f"records no passing row for it")


def test_summary_states_the_benchmark_set_structural_limits():
    """Breadth of constitutive class is not breadth of source structure.

    Every parameter-sensitivity benchmark is single-file fixed-form small-strain,
    and the summary has to say so rather than let a headline count imply wider
    coverage than was demonstrated.
    """
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert summary["structural_diversity_caveat"]
    assert summary["by_source_form"].keys() == {"fixed"}


@pytest.mark.slow
def test_matrix_regenerates_identically_and_leaves_published_evidence_alone(tmp_path):
    """Regression: this test used to regenerate straight into paper_results/.

    A test that rewrites published evidence to check it can be reproduced is
    indistinguishable from one that quietly replaces it, so the tool now takes
    an explicit output directory and the published copy must be untouched.
    """
    before = MATRIX.read_text(encoding="utf-8")
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "build_generality_matrix.py"),
         "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT, check=True, capture_output=True)
    assert MATRIX.read_text(encoding="utf-8") == before, \
        "the published matrix was modified by a test"
    regenerated = (tmp_path / "generality_matrix.csv").read_text(encoding="utf-8")
    assert regenerated == before
