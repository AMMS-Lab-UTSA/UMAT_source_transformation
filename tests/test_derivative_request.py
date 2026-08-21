"""Tests for the unified derivative-request canonical model.

The tests verify that:
* the 19 completed benchmark contracts all normalize into at least one
  DerivativeRequest with the expected material-tangent shape;
* legacy contract shapes (compact, extra_jacobian_contracts, advanced) all
  normalize to the same canonical model;
* the new unified contract (schema_version 1.1) loads into equivalent
  DerivativeRequest values;
* validation catches duplicate ids, unsupported orders, bad PROPS indices,
  duplicate PROPS/STATEV indices, and empty seeds/targets.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from umat_oti.core.config_loader import load_project_config_json
from umat_oti.core.derivative_request import (
    DerivativeRequest,
    DerivativeRequestError,
    KIND_LOCAL_JACOBIAN,
    KIND_MATERIAL_TANGENT,
    KIND_PARAMETER_SENSITIVITY,
    KIND_STATE_SENSITIVITY,
    UNIFIED_SCHEMA_VERSION,
    load_project_derivative_requests,
    load_unified_contract,
    validate_derivative_requests,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = REPO_ROOT / "benchmarks"


def _load_config(path: Path) -> dict:
    return load_project_config_json(path.read_bytes(), origin_path=path)


def test_material_tangent_from_compact_contract():
    config = {
        "name": "elastic",
        "source": "elastic.for",
        "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
        "ntens": 4,
        "order": 1,
    }
    requests = load_project_derivative_requests(config)
    assert len(requests) == 1
    tangent = requests[0]
    assert tangent.id == "material_tangent"
    assert tangent.kind == KIND_MATERIAL_TANGENT
    assert tangent.target == "DDSDDE"
    assert tangent.seed == ("DSTRAN",)
    assert tangent.response == "STRESS"
    assert tangent.order == 1
    assert tangent.output_shape == (4, 4)
    assert tangent.source_contract == "compact"


def test_extra_jacobian_contracts_emit_deprecation_and_normalize():
    config = {
        "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
        "ntens": 6,
        "order": 1,
        "extra_jacobian_contracts": [
            {
                "id": "local_return_mapping",
                "seed": {"variable": "DGAMMA"},
                "output": {"variable": "RESID"},
                "replace_variable": "FJAC",
                "selected_umat": "UMAT",
            }
        ],
    }
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        requests = load_project_derivative_requests(config)
    assert any("legacy alias" in str(w.message) for w in captured)
    assert [r.id for r in requests] == ["material_tangent", "local_return_mapping"]
    local = requests[1]
    assert local.kind == KIND_LOCAL_JACOBIAN
    assert local.seed == ("DGAMMA",)
    assert local.response == "RESID"
    assert local.target == "FJAC"
    assert local.scope == "UMAT"
    assert local.source_contract == "extra_jacobian_contracts"


def test_constitutive_jacobians_normalize_without_deprecation():
    config = {
        "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
        "constitutive_jacobians": [
            {
                "id": "detdg",
                "seed": {"variable": "DG"},
                "output": {"variable": "DET"},
                "replace_variable": "DETDG",
            }
        ],
    }
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        requests = load_project_derivative_requests(config)
    # No 'legacy alias' warning should have been raised for the modern name.
    assert not any("legacy alias" in str(w.message) for w in captured)
    assert [r.id for r in requests] == ["material_tangent", "detdg"]
    assert requests[1].source_contract == "constitutive_jacobians"


def test_advanced_block_produces_one_request_per_extract_entry():
    config = {
        "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"},
        "advanced": {
            "seed": "DSTRAN",
            "output": "STRESS",
            "extract": [
                {"order": 2, "target": "DDSDDE2", "layout": "hessian_voigt_sym"},
                {"order": 3, "target": "DDSDDE3", "layout": "third_voigt"},
                {"order": 4, "target": "DDSDDE4", "layout": "third_voigt"},
            ],
        },
    }
    requests = load_project_derivative_requests(config)
    ids = [r.id for r in requests]
    assert ids == [
        "material_tangent",
        "advanced_extract_1",
        "advanced_extract_2",
        "advanced_extract_3",
    ]
    higher = requests[1:]
    assert [r.order for r in higher] == [2, 3, 4]
    assert [r.target for r in higher] == ["DDSDDE2", "DDSDDE3", "DDSDDE4"]


def test_unified_contract_round_trips_j2_example():
    payload = {
        "schema_version": UNIFIED_SCHEMA_VERSION,
        "name": "j2_all_derivatives",
        "source": "umat_j2.for",
        "entry_routine": "UMAT",
        "parameters": [
            {"name": "E", "props_index": 1},
            {"name": "NU", "props_index": 2},
            {"name": "SIGY0", "props_index": 3},
            {"name": "H", "props_index": 4},
        ],
        "state_variables": [{"name": "EQPLAS", "statev_index": 1}],
        "derivatives": [
            {
                "id": "material_tangent",
                "target": "DDSDDE",
                "seed": "DSTRAN",
                "response": "STRESS",
                "order": 1,
            },
            {
                "id": "local_return_mapping",
                "target": "FJAC",
                "seed": "DGAMMA",
                "response": "RESID",
                "order": 1,
                "scope": "NEWTON",
            },
            {
                "id": "stress_parameter_sensitivity",
                "target": "DSIGMA_DP",
                "seed": ["E", "NU", "SIGY0", "H"],
                "response": "STRESS",
                "order": 1,
            },
            {
                "id": "state_parameter_sensitivity",
                "target": "DSTATEV_DP",
                "seed": ["E", "NU", "SIGY0", "H"],
                "response": "STATEV",
                "order": 1,
            },
        ],
    }
    data = load_unified_contract(json.dumps(payload))
    requests = load_project_derivative_requests(data)
    assert [r.id for r in requests] == [
        "material_tangent",
        "local_return_mapping",
        "stress_parameter_sensitivity",
        "state_parameter_sensitivity",
    ]
    tangent, local, dsigma, dstate = requests
    assert tangent.kind == KIND_MATERIAL_TANGENT
    assert local.kind == KIND_LOCAL_JACOBIAN
    assert local.scope == "NEWTON"
    assert dsigma.kind == KIND_PARAMETER_SENSITIVITY
    assert dsigma.parameter_map == (
        ("E", 1),
        ("NU", 2),
        ("SIGY0", 3),
        ("H", 4),
    )
    assert dstate.kind == KIND_STATE_SENSITIVITY
    assert dstate.state_map == (("EQPLAS", 1),)


def test_load_unified_contract_rejects_wrong_schema_version():
    with pytest.raises(DerivativeRequestError):
        load_unified_contract({"schema_version": "9.9", "derivatives": []})


def test_load_unified_contract_rejects_empty_derivatives():
    payload = {"schema_version": UNIFIED_SCHEMA_VERSION, "derivatives": []}
    with pytest.raises(DerivativeRequestError):
        load_project_derivative_requests(payload)


def test_validate_catches_common_mistakes():
    requests = [
        DerivativeRequest(
            id="material_tangent",
            target="DDSDDE",
            seed=("DSTRAN",),
            response="STRESS",
            order=1,
        ),
        # Duplicate id.
        DerivativeRequest(
            id="material_tangent",
            target="DDSDDE",
            seed=("DSTRAN",),
            response="STRESS",
            order=1,
        ),
        # Unsupported order (default supported set is 1..4).
        DerivativeRequest(
            id="tenth_order",
            target="D10",
            seed=("DSTRAN",),
            response="STRESS",
            order=10,
        ),
        # Missing seed.
        DerivativeRequest(
            id="no_seed",
            target="DDSDDE",
            seed=(),
            response="STRESS",
            order=1,
        ),
        # Duplicate PROPS index.
        DerivativeRequest(
            id="dup_props",
            target="DSIGMA_DP",
            seed=("E", "NU"),
            response="STRESS",
            order=1,
            parameter_map=(("E", 1), ("NU", 1)),
        ),
        # Non-1-based STATEV index.
        DerivativeRequest(
            id="bad_statev",
            target="DSTATEV_DP",
            seed=("H",),
            response="STATEV",
            order=1,
            state_map=(("EQPLAS", 0),),
        ),
    ]
    errors = validate_derivative_requests(requests)
    joined = "\n".join(errors)
    assert "duplicate derivative-request id" in joined
    assert "tenth_order" in joined
    assert "no_seed" in joined
    assert "dup_props" in joined
    assert "bad_statev" in joined


@pytest.mark.parametrize(
    "config_path",
    sorted(BENCHMARKS.glob("*.json")),
    ids=lambda p: p.stem,
)
def test_every_benchmark_contract_normalizes_to_material_tangent(config_path: Path):
    """All 19 completed benchmark contracts must yield a material-tangent request.

    This guarantees the unified schema does not break any historical contract.
    """
    if config_path.name.endswith("_report.json"):
        pytest.skip("report artefact, not a contract")
    config = _load_config(config_path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        requests = load_project_derivative_requests(config)
    assert requests, f"no requests loaded from {config_path.name}"
    tangent = next((r for r in requests if r.id == "material_tangent"), None)
    assert tangent is not None
    assert tangent.target == "DDSDDE"
    assert tangent.seed == ("DSTRAN",)
    assert tangent.response == "STRESS"
    ntens = config.get("transformation_settings", {}).get("ntens") or config.get("ntens")
    if isinstance(ntens, int):
        assert tangent.output_shape == (ntens, ntens)


def test_benchmark_batch_normalized_count_matches_19_files():
    contracts = [p for p in BENCHMARKS.glob("*.json") if not p.name.endswith("_report.json")]
    assert len(contracts) == 19
    total_requests = 0
    for path in contracts:
        config = _load_config(path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            total_requests += len(load_project_derivative_requests(config))
    # Every contract has at least a material-tangent request; some also
    # carry legacy constitutive-jacobian entries, so the total >= 19.
    assert total_requests >= 19
