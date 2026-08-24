"""Stages 11-13: execution, primal parity and derivative verification.

The rules these pin down:

  * a contract with no validation block yields ``not_requested``, never a
    fabricated load path;
  * a primal divergence within the model's own local Newton tolerance is a
    convergence artefact -- the stage succeeds but names the branches whose
    derivatives are bounded by it;
  * a divergence beyond that tolerance is a transformation defect and fails;
  * when parity fails, no derivative row counts as verified however cleanly the
    reference resolved it;
  * a contract whose reference is an independent implementation has no
    build-to-build parity to wait for, and says so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.pipeline.engine import RunContext
from umat_oti.pipeline.manifest import RunManifest, StageRecord
from umat_oti.pipeline.stages import (
    _material_point_execution, _primal_parity, _reference_kind,
)
from umat_oti.pipeline.status import StageStatus
from umat_oti.validation.actual_umat_higher_order_generic import ModelSpec

REPO_ROOT = Path(__file__).resolve().parents[1]


def _ctx(contract, tmp_path, results=None, options=None, manifest=None):
    manifest = manifest or RunManifest.create(run_id="t", contract=contract,
                                              repo_root=REPO_ROOT)
    return RunContext(contract=contract, work_dir=tmp_path, repo_root=REPO_ROOT,
                      manifest=manifest, results=dict(results or {}),
                      options=dict(options or {"compile": True}))


def _check(increment, branch, agrees, ratio):
    return {"increment": increment, "branch": branch, "agrees": agrees,
            "max_absolute_difference": 0.0 if agrees else 1e-5,
            "max_relative_difference": 0.0 if agrees else 1e-8,
            "divergence_over_model_solver_tolerance": ratio,
            "model_solver_tolerance": 1e-5,
            "transformed_stress": [], "original_stress": []}


# --------------------------------------------------------------------------- #
# Contract-driven specs
# --------------------------------------------------------------------------- #
def test_a_contract_without_a_validation_block_is_not_requested(tmp_path):
    ctx = _ctx({"name": "x"}, tmp_path, results={"source_acquisition": {"sources": []}})
    outcome = _material_point_execution(ctx)
    assert outcome.status is StageStatus.NOT_REQUESTED
    assert "no 'validation' block" in outcome.reason


def test_a_validation_block_without_a_load_path_is_refused():
    with pytest.raises(ValueError, match="increments"):
        ModelSpec.from_contract({"validation": {"stress_scale": 1.0}},
                                key="k", config="c", source="s")


def test_the_shipped_contracts_round_trip_into_specs():
    """The registry is known-good data, not the mechanism."""
    for name in ("code_imp", "UMAT_PCL", "UMAT_PCLK", "visco_imp"):
        path = REPO_ROOT / "examples" / f"{name}_actual_higher_order.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        spec = ModelSpec.from_contract(contract, key=name, config=str(path), source="s")
        assert spec.increments, name
        assert spec.base_step > 0, name


# --------------------------------------------------------------------------- #
# Primal parity
# --------------------------------------------------------------------------- #
def test_parity_succeeds_when_every_increment_agrees(tmp_path):
    results = {"material_point_execution": {
        "primal_check": [_check(1, "elastic", True, 0.0)], "primal_agrees": True}}
    outcome = _primal_parity(_ctx({}, tmp_path, results))
    assert outcome.status is StageStatus.SUCCEEDED
    assert outcome.outputs["parity_limited_branches"] == []


def test_a_divergence_within_the_solver_tolerance_is_not_called_a_defect(tmp_path):
    """Two builds stopping at different admissible points is a model property."""
    results = {"material_point_execution": {
        "primal_check": [_check(1, "elastic", True, 0.0),
                         _check(2, "inelastic", False, 1.4)],
        "primal_agrees": False}}
    outcome = _primal_parity(_ctx({}, tmp_path, results))
    assert outcome.status is StageStatus.SUCCEEDED
    assert outcome.outputs["parity_limited_branches"] == ["inelastic"]
    assert outcome.diagnostics, "the limitation must still be reported"


def test_a_divergence_beyond_the_solver_tolerance_fails(tmp_path):
    results = {"material_point_execution": {
        "primal_check": [_check(4, "inelastic", False, 5.9e6)], "primal_agrees": False}}
    outcome = _primal_parity(_ctx({}, tmp_path, results))
    assert outcome.status is StageStatus.FAILED
    assert "beyond what the model's own local Newton tolerance can explain" in outcome.reason


def test_an_unexplained_divergence_with_no_stated_tolerance_fails(tmp_path):
    """A model that states no tolerance cannot use one as an excuse."""
    check = _check(2, "inelastic", False, None)
    check["model_solver_tolerance"] = None
    results = {"material_point_execution": {"primal_check": [check],
                                            "primal_agrees": False}}
    assert _primal_parity(_ctx({}, tmp_path, results)).status is StageStatus.FAILED


def test_an_independent_reference_has_no_build_to_build_parity(tmp_path):
    contract = {"validation": {"reference_kind": "extended_precision_model"}}
    assert _reference_kind(_ctx(contract, tmp_path)) == "extended_precision_model"
    outcome = _primal_parity(_ctx(contract, tmp_path))
    assert outcome.status is StageStatus.NOT_REQUESTED
    assert "different implementation, not a different build" in outcome.reason


# --------------------------------------------------------------------------- #
# The parity gate on derivative verification
# --------------------------------------------------------------------------- #
def test_generated_evidence_reflects_the_parity_gate():
    """PCLK: parity failed, so no row may count however it classified."""
    path = (REPO_ROOT / "paper_results" / "higher_order_convergence" / "UMAT_PCLK"
            / "convergence_evidence.json")
    if not path.exists():
        pytest.skip("UMAT_PCLK convergence dataset not generated")
    data = json.loads(path.read_text(encoding="utf-8"))
    primal = data.get("primal_consistency", {})
    assert primal.get("agrees") is False
    assert data["summary"]["verified"] is False


def test_reference_kind_defaults_to_a_compiled_original(tmp_path):
    assert _reference_kind(_ctx({"validation": {}}, tmp_path)) == "compiled_original"
    assert _reference_kind(_ctx({}, tmp_path)) == "none"
