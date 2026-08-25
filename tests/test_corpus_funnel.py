"""The external-corpus funnel: honest stages, and the guards that keep it honest."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from umat_oti.corpus.funnel import (
    STAGES, Candidate, MaterialData, run_funnel,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO_ROOT / "parameter_sensitivity" / "corpus_snapshot.json"
CORPUS = (REPO_ROOT.parent / "Residual_Assembler" / "sources" / "permissive"
          / "jgomezc1_ABAQUS-US")

TRIVIAL = """\
      SUBROUTINE UMAT(STRESS, STATEV, DDSDDE, SSE, SPD, SCD, RPL,
     1 DDSDDT, DRPLDE, DRPLDT, STRAN, DSTRAN, TIME, DTIME, TEMP,
     2 DTEMP, PREDEF, DPRED, CMNAME, NDI, NSHR, NTENS, NSTATV, PROPS,
     3 NPROPS, COORDS, DROT, PNEWDT, CELENT, DFGRD0, DFGRD1, NOEL,
     4 NPT, LAYER, KSPT, KSTEP, KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS), STATEV(NSTATV), DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS), DRPLDE(NTENS), STRAN(NTENS), DSTRAN(NTENS),
     2 TIME(2), PREDEF(1), DPRED(1), PROPS(NPROPS), COORDS(3),
     3 DROT(3,3), DFGRD0(3,3), DFGRD1(3,3)
      EMOD=PROPS(1)
      DO K1=1,NTENS
        STRESS(K1)=STRESS(K1)+EMOD*DSTRAN(K1)
      END DO
      STATEV(1)=EMOD
      RETURN
      END
"""


def test_stage_order_is_a_real_funnel():
    assert STAGES[0] == "discovered"
    assert STAGES[-1] == "derivatives_verified"
    assert STAGES.index("primal_parity") < STAGES.index("derivatives_verified")
    assert STAGES.index("original_compiled") < STAGES.index("original_executed")


def test_snapshot_pins_commits_not_branches():
    """A moving ref makes an offline replay depend on when it ran."""
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert snapshot["repositories"]
    for repository in snapshot["repositories"]:
        sha = repository["commit_sha"]
        assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), repository
        assert repository["license_spdx"]
        assert repository["license_source"]


def test_every_candidate_declares_provenance_and_material_or_a_blocker():
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    repositories = {r["id"] for r in snapshot["repositories"]}
    for candidate in snapshot["candidates"]:
        assert candidate["repository"] in repositories
        if candidate.get("material") is None:
            assert candidate.get("material_blocker"), candidate["id"]
        else:
            assert candidate["material"]["provenance"], candidate["id"]


def test_a_non_redistributable_licence_is_classified_not_executed(tmp_path):
    source = tmp_path / "x.for"
    source.write_text(TRIVIAL, encoding="utf-8")
    candidate = Candidate(
        id="restricted", source_path=source, repository_url="https://example.invalid",
        commit_sha="0" * 40, license_spdx="NOASSERTION",
        license_source="no LICENSE file", ntens=6, nstatv=1)
    record = run_funnel(candidate, tmp_path / "work")
    assert record["stages"]["entry_detected"]["status"] == "blocked_by_license"
    assert record["furthest_stage"] == "license_classified"


def test_missing_material_data_is_its_own_blocker(tmp_path):
    """Absent upstream material must stop the funnel, never be invented."""
    source = tmp_path / "x.for"
    source.write_text(TRIVIAL, encoding="utf-8")
    candidate = Candidate(
        id="nomaterial", source_path=source, repository_url="https://example.invalid",
        commit_sha="0" * 40, license_spdx="MIT", license_source="LICENSE",
        ntens=6, nstatv=1, material=None)
    record = run_funnel(candidate, tmp_path / "work")
    stage = record["stages"]["contract_constructed"]
    assert stage["status"] == "blocked_by_missing_material_data"
    assert "may be invented" in stage["reason"]


def test_declared_dimensions_are_checked_against_the_source(tmp_path):
    """Regression: too small an NSTATV produced 1e222 derivatives.

    The source read past the end of the state array. The real part it found
    there was zero, so primal parity passed and the failure looked like a
    transformation defect rather than a contract error.
    """
    source = tmp_path / "x.for"
    source.write_text(TRIVIAL.replace(
        "      STATEV(1)=EMOD",
        "      DO K1=10,2*NTENS+5\n        STATEV(K1)=EMOD\n      END DO"),
        encoding="utf-8")
    candidate = Candidate(
        id="toosmall", source_path=source, repository_url="https://example.invalid",
        commit_sha="0" * 40, license_spdx="MIT", license_source="LICENSE",
        ntens=4, nstatv=9,
        material=MaterialData(props=(1.0,), dstran_per_increment=(1e-4, 0, 0, 0),
                              n_increments=2, provenance="test"))
    record = run_funnel(candidate, tmp_path / "work")
    stage = record["stages"]["contract_constructed"]
    assert stage["status"] == "dimension_inference_conflict"
    assert stage["required_nstatv"] == 13


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
@pytest.mark.skipif(not (CORPUS / "UMATS" / "UMAT_PCO.for").is_file(),
                    reason="pinned external corpus snapshot is not checked out")
def test_a_real_external_multi_file_umat_reaches_numerical_verification(tmp_path):
    """End to end on genuinely external, non-curated, MIT-licensed source.

    UMAT_PCO defines none of the seven helpers it calls, so this exercises
    dependency resolution, transformation, both builds, primal parity and the
    derivative comparison together.
    """
    candidate = Candidate(
        id="jgomezc1_UMAT_PCO", source_path=CORPUS / "UMATS" / "UMAT_PCO.for",
        repository_url="https://github.com/jgomezc1/ABAQUS-US.git",
        commit_sha="54181407aa7aa23055e33d354d0b2a3abc266365",
        license_spdx="MIT", license_source="LICENSE.md",
        ntens=6, nstatv=14, ndi=3, nshr=3,
        dependency_roots=(CORPUS / "UMATS",),
        material=MaterialData(
            props=(220000.0, 0.3, 0.005, 900000.0, 56.0, 0.0, 343.5, 0.25),
            dstran_per_increment=(1e-4, 0, 0, 0, 0, 0), n_increments=6,
            provenance="INPUT_FILES/UNIUSER_COS.inp",
            parameters=(("EMOD", 1), ("ENU", 2))))
    record = run_funnel(candidate, tmp_path / "work")
    assert record["furthest_stage"] == "derivatives_verified", record.get("blocker")
    assert record["dependency_graph"]["multi_file"] is True
    assert record["comparison"]["disagreeing"] == 0
    assert record["comparison"]["substantive_rows"] > 0
    assert record["stages"]["primal_parity"]["worst_relative_difference"] < 1e-12
