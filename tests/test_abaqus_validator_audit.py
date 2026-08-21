from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from umat_oti.reports.aggregate_abaqus_results import aggregate_abaqus_results
from umat_oti.reports.run_softwarex_evidence import _build_claim_matrix_from_results
from umat_oti.validation.compare_results import compare_validation_results


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_ddsdde_perturbation_fails_and_identifies_component(tmp_path: Path):
    validation_report = {
        "comparison_settings": {
            "compare_outputs": ["STRESS", "DDSDDE"],
            "absolute_tolerance": 1.0e-12,
            "relative_tolerance": 1.0e-12,
            "ddsdde_absolute_tolerance": 1.0e-12,
            "ddsdde_relative_tolerance": 1.0e-12,
        },
        "ddsdde_validation": {"enabled": True, "status": "configured"},
    }
    original = {"final_stress": [1.0, 2.0], "increments": [{"ddsdde": [[10.0, 2.0], [3.0, 20.0]]}]}
    transformed = json.loads(json.dumps(original))
    transformed["increments"][0]["ddsdde"][1][0] += 1.0
    _write_json(tmp_path / "validation_report.json", validation_report)
    _write_json(tmp_path / "original_results.json", original)
    _write_json(tmp_path / "otis_results.json", transformed)

    result = compare_validation_results(tmp_path)

    assert result.passed is False
    report = json.loads((tmp_path / "comparison_report.json").read_text(encoding="utf-8"))
    mismatch = report["ddsdde_comparison"]["worst_increment"]
    assert mismatch["worst_component"] == "(2,1)"
    assert mismatch["worst_original_value"] == 3.0
    assert mismatch["worst_otis_value"] == 4.0


def test_aggregate_preserves_nonzero_ddsdde_metrics(tmp_path: Path):
    arc_dir = tmp_path / "arc_123"
    case_dir = arc_dir / "paired_batch" / "validation" / "code_imp"
    case_dir.mkdir(parents=True)
    _write_json(
        case_dir / "validation_report.json",
        {
            "status": "passed",
            "final_pass": True,
            "stress_comparison": {"status": "passed", "max_abs_difference": 1.0e-6, "max_rel_difference": 2.0e-8},
            "state_variable_comparison": {"status": "passed"},
            "ddsdde_comparison": {"status": "passed", "max_abs_difference": 0.015625, "max_rel_difference": 8.2e-8},
            "convergence_comparison": {"status": "passed"},
        },
    )

    output_json = tmp_path / "aggregate.json"
    aggregate_abaqus_results(arc_dir, output_csv=tmp_path / "aggregate.csv", output_json=output_json)

    row = json.loads(output_json.read_text(encoding="utf-8"))["rows"][0]
    assert row["ddsdde_max_abs_diff"] == 0.015625
    assert row["ddsdde_max_rel_diff"] == 8.2e-8


def test_claim_matrix_does_not_promote_reference_fixtures():
    claims = _build_claim_matrix_from_results(
        env=SimpleNamespace(abaqus_ok=True),
        oti_j2={"status": "verified"},
        oti_ho={"status": "verified"},
    )
    by_id = {claim["id"]: claim for claim in claims}

    assert by_id["higher_order_direction_and_factorial_reference_fixture"]["status"] == "verified"
    assert by_id["higher_order_from_real_UMAT_stress_update"]["status"] == "not_implemented"
    assert by_id["residual_assembler_synthetic_B_bridge"]["status"] == "verified"
    assert by_id["residual_assembler_C3D8_structural_sensitivity"]["status"] == "not_implemented"
    assert by_id["abaqus_paired_18_case_collection"]["status"] == "18_pass_1_original_case_execution_failure"