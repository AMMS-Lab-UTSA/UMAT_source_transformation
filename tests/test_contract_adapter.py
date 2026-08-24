"""The v2 -> canonical contract adapter must never guess.

Eighteen contracts written against another schema are converted by a tested
function rather than by hand-editing JSON, so the originals stay authoritative
and the conversion is reviewable. These tests pin the two behaviours that make
it safe: nothing is silently dropped, and a contract that cannot be expressed
canonically is refused rather than approximated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.core.derivative_request import (
    load_project_derivative_requests, validate_derivative_requests,
)
from umat_oti.services.contract_adapter import (
    ContractAdaptationError, V2_SCHEMA, adapt_v2_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS = REPO_ROOT / "parameter_sensitivity" / "models"

REQUIRED_18 = {
    "m1_elastic", "m2_cubic", "m3_j2", "m5_cpflow", "m6_fcc",
    "sweep_aniso_ortho", "sweep_damage_elastic", "sweep_eco",
    "sweep_j2_bilinear", "sweep_j2_combined", "sweep_j2_kinematic",
    "sweep_lame_elastic", "sweep_maxwell_ve", "sweep_mooney_small",
    "sweep_real_ECL_TEMP", "sweep_real_PCO", "sweep_thermoelastic",
    "sweep_transiso",
}


def _v2(model: str) -> dict:
    return json.loads((MODELS / model / "contract_v2.json").read_text(encoding="utf-8"))


def _adapt(model: str):
    return adapt_v2_contract(_v2(model), model=model,
                             source_path=f"parameter_sensitivity/models/{model}/umat.for")


@pytest.mark.skipif(not MODELS.is_dir(), reason="model set not imported")
def test_all_eighteen_required_models_are_present():
    present = {p.name for p in MODELS.iterdir() if p.is_dir()}
    assert REQUIRED_18 <= present, f"missing: {sorted(REQUIRED_18 - present)}"


@pytest.mark.skipif(not MODELS.is_dir(), reason="model set not imported")
@pytest.mark.parametrize("model", sorted(REQUIRED_18))
def test_every_required_model_adapts_and_normalizes(model):
    """Adapting must produce a contract the canonical loader actually accepts."""
    adapted = _adapt(model)
    contract = adapted.contract
    assert contract["schema_version"] == "1.1"
    assert contract["ntens"], model
    assert contract["parameters"], model
    assert contract["derivatives"], model

    requests = load_project_derivative_requests(contract, emit_deprecations=False)
    assert requests, f"{model}: canonical loader produced no requests"
    errors = validate_derivative_requests(requests)
    assert not errors, f"{model}: {errors}"


@pytest.mark.skipif(not MODELS.is_dir(), reason="model set not imported")
def test_parameter_props_indices_and_values_survive():
    adapted = _adapt("sweep_transiso")
    params = adapted.contract["parameters"]
    assert [p["props_index"] for p in params] == [1, 2, 3, 4, 5]
    assert [p["name"] for p in params] == ["EP", "ET", "XNUP", "XNUPT", "GT"]
    # validation.props_values must land on the matching parameter
    assert params[0]["value"] == 150000.0 and params[4]["value"] == 5000.0


@pytest.mark.skipif(not MODELS.is_dir(), reason="model set not imported")
def test_a_parameter_derivative_seeds_props_not_dstran():
    """DSIGMA_DP differentiates with respect to PROPS; seeding DSTRAN would be wrong."""
    adapted = _adapt("m1_elastic")
    request = adapted.contract["derivatives"][0]
    assert request["target"] == "DSIGMA_DP"
    assert request["seed"] == "PROPS"
    assert request["response"] == "STRESS"
    assert adapted.contract["provenance"]["seed_selected"] == "PROPS"


@pytest.mark.skipif(not MODELS.is_dir(), reason="model set not imported")
def test_the_explicit_request_variant_is_handled():
    adapted = _adapt("m2_elastic3d")
    assert any("explicit derivative_requests" in n for n in adapted.notes)
    assert [r["target"] for r in adapted.contract["derivatives"]][0] == "DSIGMA_DP"


@pytest.mark.skipif(not MODELS.is_dir(), reason="model set not imported")
def test_nothing_is_silently_dropped():
    """Unmapped v2 keys are reported, with a reason, not discarded."""
    adapted = _adapt("m2_elastic3d")
    assert adapted.unmapped, "this contract has keys with no canonical home"
    for key, record in adapted.unmapped.items():
        assert record["reason"], f"{key} dropped without a reason"


@pytest.mark.skipif(not MODELS.is_dir(), reason="model set not imported")
def test_state_requests_are_not_invented_for_path_dependent_models():
    """m3_j2 has state and path dependence but declares no state export."""
    adapted = _adapt("m3_j2")
    targets = [r["target"] for r in adapted.contract["derivatives"]]
    assert "DSTATEV_DP" not in targets
    assert any("no state export" in n or "declares no state export" in n
               for n in adapted.notes)


def test_finite_strain_is_refused_rather_than_seeded_with_dstran():
    """The failure mode that would silently differentiate the wrong quantity."""
    v2 = {
        "schema": V2_SCHEMA,
        "source": {"entry_point": "UMAT", "main_file": "umat.for"},
        "kinematics": "finite_strain",
        "dimensions": {"ntens": 6, "nprops": 2, "nstatev": 0},
        "parameters": [{"name": "E", "props_index": 1}],
        "derivative": {"of": "STRESS", "wrt": "DSTRAN", "order": 1},
        "history": {"state": "STATEV"},
    }
    with pytest.raises(ContractAdaptationError, match="deformation-gradient"):
        adapt_v2_contract(v2, model="fake", source_path="umat.for")


def test_an_unknown_kinematics_is_refused():
    v2 = {"schema": V2_SCHEMA, "source": {}, "kinematics": "hypoelastic_corotational",
          "dimensions": {"ntens": 6}, "parameters": [], "derivative": {}}
    with pytest.raises(ContractAdaptationError, match="unrecognised kinematics"):
        adapt_v2_contract(v2, model="fake", source_path="umat.for")


def test_a_foreign_schema_is_refused():
    with pytest.raises(ContractAdaptationError, match="expected schema"):
        adapt_v2_contract({"schema": "something_else"}, model="x", source_path="s")


def test_a_contract_with_no_derivative_is_refused():
    v2 = {"schema": V2_SCHEMA, "source": {}, "kinematics": "small_strain",
          "dimensions": {"ntens": 6}, "parameters": []}
    with pytest.raises(ContractAdaptationError, match="neither"):
        adapt_v2_contract(v2, model="x", source_path="s")


@pytest.mark.skipif(not MODELS.is_dir(), reason="model set not imported")
def test_props_values_are_indexed_by_props_index_not_list_position():
    """m5_cpflow lists its parameters out of PROPS order; the trap is real.

    Its `parameters` array is [tau0@3, dG@4, q@6, p@5, gam0@7, H@8]: `q` is third
    in the list but PROPS(6). Assigning values by list position would give `q` the
    value of PROPS(3) and silently mis-parameterise the model.
    """
    adapted = _adapt("m5_cpflow")
    by_name = {p["name"]: p for p in adapted.contract["parameters"]}
    # cross-checked against umat.for: TAU0=PROPS(3), PEXP=PROPS(5), QEXP=PROPS(6)
    assert by_name["tau0"]["props_index"] == 3 and by_name["tau0"]["value"] == 1500.0
    assert by_name["p"]["props_index"] == 5 and by_name["p"]["value"] == 0.4
    assert by_name["q"]["props_index"] == 6 and by_name["q"]["value"] == 1.6
    assert by_name["H"]["props_index"] == 8 and by_name["H"]["value"] == 60000.0


@pytest.mark.skipif(not MODELS.is_dir(), reason="model set not imported")
def test_properties_that_are_not_parameters_are_still_supplied():
    """A model may declare more PROPS than it differentiates.

    m5_cpflow seeds PROPS(3..8) and leaves E and nu fixed at PROPS(1..2). Without
    the full static vector the driver would run with E = 0.
    """
    from tools.run_parameter_sensitivity_sweep import generate_contract

    _path, contract = generate_contract("m5_cpflow")
    static = contract["material_point_driver"]["static_props"]
    assert len(static) == 8, "the full PROPS vector must be supplied, not just the seeded ones"
    assert static[0] == 200000.0 and static[1] == 0.3, "E and nu must not default to zero"
