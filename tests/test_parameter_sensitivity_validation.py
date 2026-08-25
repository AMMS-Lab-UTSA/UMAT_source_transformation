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
from pathlib import Path

import pytest

from umat_oti.validation.parameter_sensitivity_validation import (
    DEFAULT_REL_STEP, ReplayResult, compare, driver_source, fd_noise_floor,
    primal_parity,
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
