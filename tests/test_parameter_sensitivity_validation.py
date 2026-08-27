"""DSIGMA_DP / DSTATEV_DP must be checked against the original UMAT.

The reference is a separate compilation of the author's own Fortran, replayed
with perturbed properties. A Python re-implementation would share every
modelling assumption with the thing being checked, so agreement would prove only
that two transcriptions match.

Three outcomes, not two: a row can agree, disagree, or be beyond what a centred
difference can resolve. Collapsing the third into either of the others would
either inflate the verified count or blame the transformation for the
reference's limits.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from umat_oti.validation.parameter_sensitivity_validation import (
    DEFAULT_REL_STEP, ReplayResult, build_original_driver, compare,
    driver_source, fd_noise_floor, primal_parity, replay, replay_reproducibly,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUND = REPO_ROOT / "paper_results" / "parameter_sensitivity" / "parameter_sensitivity_round.json"


def _params():
    return [{"name": "E", "props_index": 1, "oti_direction": 1},
            {"name": "H", "props_index": 2, "oti_direction": 2}]


def _reference(dsigma_e, dsigma_h, step=1.0):
    return {1: {"step": step, "dsigma": dsigma_e, "dstatev": [[0.0]]},
            2: {"step": step, "dsigma": dsigma_h, "dstatev": [[0.0]]}}


def test_the_driver_declares_the_contract_dimensions():
    source = driver_source(ntens=6, nstatv=3, nprops=4)
    assert "NTENS=6" in source and "NSTATV=3" in source and "NPROPS=4" in source
    assert "CALL UMAT(" in source
    # a model that aborts must stop the run, not silently return
    assert "SUBROUTINE XIT" in source and "STOP 3" in source


def test_a_model_with_no_state_still_gets_a_valid_statev_array():
    """NSTATV=0 is illegal in Fortran; the driver must size at least one slot."""
    assert "NSTATV=1" in driver_source(ntens=6, nstatv=0, nprops=2)


def test_the_noise_floor_grows_as_the_step_shrinks():
    """Halving the step doubles the round-off amplification."""
    assert fd_noise_floor(100.0, 1.0) == pytest.approx(2 * fd_noise_floor(100.0, 2.0))
    assert fd_noise_floor(100.0, 0.0) == float("inf")


def test_agreement_is_measured_against_the_references_own_resolution():
    """Values differing by less than the FD can distinguish agree."""
    floor = fd_noise_floor(500.0, 1.0)
    oti = {(1, 1): {"E": 1.0e-13 + 0.4 * floor, "H": 0.0}}
    rows = compare(oti, _reference([[1.0e-13]], [[0.0]]), array="DSIGMA_DP",
                   parameters=_params(), branches=["elastic"], response_scale=500.0)
    e_row = next(r for r in rows if r.parameter == "E")
    assert e_row.agrees is True
    assert e_row.judged_by == "within_reference_resolution"


def test_a_row_at_the_noise_floor_that_disagrees_is_unresolved_not_failed():
    floor = fd_noise_floor(500.0, 1.0)
    oti = {(1, 1): {"E": 3.0 * floor, "H": 0.0}}
    rows = compare(oti, _reference([[1.0 * floor]], [[0.0]]), array="DSIGMA_DP",
                   parameters=_params(), branches=["elastic"], response_scale=500.0)
    e_row = next(r for r in rows if r.parameter == "E")
    assert e_row.agrees is None, "neither verified nor failed"
    assert e_row.judged_by == "reference_unresolved"


def test_a_substantive_disagreement_is_reported_as_a_disagreement():
    oti = {(1, 1): {"E": 2.0, "H": 0.0}}
    rows = compare(oti, _reference([[1.0]], [[0.0]]), array="DSIGMA_DP",
                   parameters=_params(), branches=["elastic"], response_scale=1.0)
    e_row = next(r for r in rows if r.parameter == "E")
    assert e_row.agrees is False and e_row.judged_by == "relative"
    assert e_row.relative_error == pytest.approx(1.0)


def test_every_row_carries_its_direction_and_props_index():
    """A column of DSIGMA_DP must be traceable to a parameter without guessing."""
    oti = {(1, 1): {"E": 1.0, "H": 2.0}}
    rows = compare(oti, _reference([[1.0]], [[2.0]]), array="DSIGMA_DP",
                   parameters=_params(), branches=["elastic"], response_scale=1.0)
    assert {(r.parameter, r.props_index, r.oti_direction) for r in rows} == {
        ("E", 1, 1), ("H", 2, 2)}


def test_primal_parity_detects_a_stress_difference(tmp_path):
    csv_path = tmp_path / "primal.csv"
    csv_path.write_text(
        "increment,method,stress_1,stress_2,EQPLAS\n"
        "1,oti,1.0,2.0,0.0\n2,oti,9.9,2.0,0.0\n", encoding="utf-8")
    original = ReplayResult(stress=[[1.0, 2.0], [3.0, 2.0]], statev=[[0.0], [0.0]])
    result = primal_parity(original, csv_path, ntens=2, nstatv=1)
    assert result["agrees"] is False
    assert result["per_increment"][0]["agrees"] is True
    assert result["per_increment"][1]["agrees"] is False


def test_primal_parity_passes_on_identical_responses(tmp_path):
    csv_path = tmp_path / "primal.csv"
    csv_path.write_text(
        "increment,method,stress_1,stress_2,EQPLAS\n1,oti,1.0,2.0,0.0\n", encoding="utf-8")
    original = ReplayResult(stress=[[1.0, 2.0]], statev=[[0.0]])
    assert primal_parity(original, csv_path, ntens=2, nstatv=1)["agrees"] is True


# --------------------------------------------------------------------------- #
# The executed round
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not ROUND.exists(), reason="sweep not executed")
def test_the_round_reports_a_funnel_not_a_single_number():
    payload = json.loads(ROUND.read_text(encoding="utf-8"))
    funnel = payload["funnel"]
    for stage in ("attempted", "contract_complete", "transformed", "compiled_oti",
                  "executed_oti", "executed_original", "primal_parity",
                  "reference_resolved", "derivatives_verified"):
        assert stage in funnel, stage
    # each stage can only be reached through the previous one
    assert funnel["derivatives_verified"] <= funnel["primal_parity"]
    assert funnel["primal_parity"] <= funnel["executed_original"]
    assert funnel["executed_oti"] <= funnel["compiled_oti"] <= funnel["transformed"]
    # verified directions can never exceed declared ones
    assert funnel["parameter_directions_verified"] <= funnel["parameter_directions_declared"]


@pytest.mark.skipif(not ROUND.exists(), reason="sweep not executed")
def test_no_model_claims_verification_without_primal_parity():
    payload = json.loads(ROUND.read_text(encoding="utf-8"))
    for model in payload["models"]:
        stages = model["stages"]
        if (stages.get("derivatives_verified") or {}).get("status") == "succeeded":
            assert (stages.get("primal_parity") or {}).get("status") == "succeeded", (
                f"{model['model']} claims verified derivatives without primal parity")


@pytest.mark.skipif(not ROUND.exists(), reason="sweep not executed")
def test_a_model_with_unverified_rows_reports_no_verified_directions_for_them():
    payload = json.loads(ROUND.read_text(encoding="utf-8"))
    for model in payload["models"]:
        verified = model.get("verified_parameter_directions", [])
        assert len(verified) <= model.get("parameter_count", 0), model["model"]


# --------------------------------------------------------------------------
# What the reference build has to be before anything may be measured against
# it. Each of these is checked by compiling Fortran that misbehaves in the
# specific way and running it, because the failures they describe are ones that
# produce plausible-looking numbers rather than an error.
# --------------------------------------------------------------------------

_UMAT_HEAD = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      IMPLICIT REAL*8(A-H,O-Z)
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
"""

_UMAT_TAIL = """      STRESS(1)=STRESS(1)+PROPS(1)*DSTRAN(1)
      STATEV(1)=STRAN(1)+DSTRAN(1)
      DDSDDE(1,1)=PROPS(1)
      RETURN
      END
"""

#: Stops part way through the path the way a real local solver does: it prints
#: why and calls EXIT, which leaves the process with status 0.
ABORTING_UMAT = _UMAT_HEAD + """      IF (KINC.GT.3) THEN
        WRITE(*,*)
        WRITE(*,*) 'LOCAL SOLVE DID NOT CONVERGE'
        WRITE(*,*) 'AFTER=',10,' ITERATIONS'
        CALL EXIT
      END IF
""" + _UMAT_TAIL

#: Prints a warning on one increment and carries on to the end of the path.
CHATTY_UMAT = _UMAT_HEAD + """      IF (KINC.EQ.2) WRITE(*,*) 'WARNING: SMALL PIVOT, CONTINUING'
""" + _UMAT_TAIL


def _nondeterministic_umat(counter_file) -> str:
    """A UMAT that answers differently in every process.

    A source that reads an uninitialised variable behaves like this, but
    uninitialised memory is undefined rather than guaranteed to differ, so the
    run-to-run change is driven by a counter on disk instead. What matters to
    the code under test is only that identical input produces different output.
    """
    return _UMAT_HEAD + f"""      IF (KINC.EQ.1) THEN
        NRUN=0
        OPEN(71,FILE='{counter_file}',STATUS='OLD',IOSTAT=IOS)
        IF (IOS.EQ.0) THEN
          READ(71,*,IOSTAT=IOS) NRUN
          IF (IOS.NE.0) NRUN=0
          CLOSE(71)
        END IF
        OPEN(72,FILE='{counter_file}',STATUS='REPLACE')
        WRITE(72,*) NRUN+1
        CLOSE(72)
        STATEV(2)=DBLE(NRUN)
      END IF
      STRESS(1)=STRESS(1)+PROPS(1)*DSTRAN(1)+STATEV(2)*1.0D-2
      STATEV(1)=STRAN(1)+DSTRAN(1)
      DDSDDE(1,1)=PROPS(1)
      RETURN
      END
"""


def _build(tmp_path, text, name, *, nstatv=1):
    source = tmp_path / f"{name}.for"
    source.write_text(text, encoding="utf-8")
    return build_original_driver(source, tmp_path / name, ntens=1,
                                 nstatv=nstatv, nprops=1)


@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_model_that_stops_part_way_is_reported_as_stopping_not_as_bad_data(tmp_path):
    """A UMAT can abort without XIT and without a non-zero exit status.

    CALL EXIT leaves the process at status 0 with the rows it already wrote
    still on stdout, so nothing but the row count establishes that the path was
    never finished. Reporting the model's own message with the count is the
    difference between naming the abort and blaming the parser.
    """
    driver = _build(tmp_path, ABORTING_UMAT, "abort")
    with pytest.raises(RuntimeError) as excinfo:
        replay(driver, [1000.0], [[1e-4]] * 5, ntens=1, nstatv=1)
    message = str(excinfo.value)
    assert "completed 3 of 5 increments" in message
    assert "LOCAL SOLVE DID NOT CONVERGE" in message


@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_warning_printed_mid_path_does_not_destroy_the_replay(tmp_path):
    """A model is allowed to talk. Only the row count decides completeness."""
    driver = _build(tmp_path, CHATTY_UMAT, "chatty")
    result = replay(driver, [1000.0], [[1e-4]] * 5, ntens=1, nstatv=1)
    assert result.increments == 5
    assert result.stress[-1][0] == pytest.approx(5 * 1000.0 * 1e-4)


@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_build_that_answers_differently_each_run_is_refused_as_a_reference(tmp_path):
    """The precondition every later stage depends on and none of them checks.

    Primal parity compares one evaluation against another build's; a centred
    difference divides the gap between two evaluations by a step of order 1e-5.
    Both are meaningless unless the same PROPS reproduce the same response, and
    a single replay cannot tell -- each run on its own looks like a complete,
    well-formed answer.
    """
    driver = _build(tmp_path, _nondeterministic_umat(tmp_path / "count.txt"),
                    "drift", nstatv=2)
    path = [[1e-4]] * 5

    # Each run on its own is a full, plausible replay: the defect is invisible
    # to any single evaluation.
    first = replay(driver, [1000.0], path, ntens=1, nstatv=2)
    second = replay(driver, [1000.0], path, ntens=1, nstatv=2)
    assert first.increments == second.increments == 5
    assert first.stress[0][0] != second.stress[0][0]

    with pytest.raises(RuntimeError) as excinfo:
        replay_reproducibly(driver, [1000.0], path, ntens=1, nstatv=2)
    assert "not reproducible" in str(excinfo.value)


@pytest.mark.fortran
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_reproducible_build_passes_the_check_and_returns_its_response(tmp_path):
    """The gate must not cost a well-behaved model anything."""
    driver = _build(tmp_path, _UMAT_HEAD + _UMAT_TAIL, "steady")
    result = replay_reproducibly(driver, [1000.0], [[1e-4]] * 5, ntens=1, nstatv=1)
    assert result.increments == 5
    assert result.stress[-1][0] == pytest.approx(5 * 1000.0 * 1e-4)
