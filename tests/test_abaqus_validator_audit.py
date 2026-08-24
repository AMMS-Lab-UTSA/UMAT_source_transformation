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
    aggregate_abaqus_results(
        arc_dir,
        output_csv=tmp_path / "aggregate.csv",
        output_json=output_json,
        commit_sha="audit-sha",
        execution_commit_sha="execution-sha",
    )

    row = json.loads(output_json.read_text(encoding="utf-8"))["rows"][0]
    assert row["ddsdde_max_abs_diff"] == 0.015625
    assert row["ddsdde_max_rel_diff"] == 8.2e-8
    assert row["execution_commit_sha"] == "execution-sha"
    assert row["audit_commit_sha"] == "audit-sha"


def test_aggregate_uses_independent_observable_denominators(tmp_path: Path):
    arc_dir = tmp_path / "arc_123"
    validation_dir = arc_dir / "paired_batch" / "validation"
    for name, compare_outputs, final_pass, run_status, ddsdde_status in (
        ("regular", ["STRESS", "STATEV", "DDSDDE", "CONVERGENCE"], True, "completed", "passed"),
        ("spin_elas_def", ["STRESS", "STATEV", "CONVERGENCE"], True, "completed", "not_requested"),
        ("failed_case", ["STRESS", "STATEV", "DDSDDE", "CONVERGENCE"], False, "failed", "failed"),
    ):
        case_dir = validation_dir / name
        case_dir.mkdir(parents=True)
        _write_json(
            case_dir / "validation_report.json",
            {
                "status": "passed" if final_pass else "failed_execution",
                "final_pass": final_pass,
                "comparison_settings": {"compare_outputs": compare_outputs},
                "original_run_status": {"status": run_status},
                "transformed_run_status": {"status": run_status},
                "stress_comparison": {"pass": final_pass, "max_abs_difference": 0.0},
                "state_variable_comparison": {"status": "passed" if final_pass else "failed"},
                "ddsdde_comparison": {"status": ddsdde_status, "max_abs_difference": 3000.0 if not final_pass else 0.0},
                "convergence_comparison": {"status": "passed" if final_pass else "failed"},
            },
        )

    output_json = tmp_path / "aggregate.json"
    aggregate_abaqus_results(arc_dir, output_csv=tmp_path / "aggregate.csv", output_json=output_json)
    aggregate = json.loads(output_json.read_text(encoding="utf-8"))
    ddsdde = aggregate["summary"]["observables"]["DDSDDE"]

    assert ddsdde == {
        "requested": 2,
        "available": 1,
        "compared": 1,
        "passed": 1,
        "failed": 0,
        "not_requested": 1,
        "unavailable": 1,
    }
    failed = next(row for row in aggregate["rows"] if row["case_name"] == "failed_case")
    assert failed["ddsdde_status"] == "unavailable"
    assert failed["ddsdde_max_abs_diff"] is None
    assert failed["audit"]["original_final_ddsdde"] is None
    assert failed["audit"]["transformed_final_ddsdde"] is None
    assert failed["audit"]["increments"] == []
    assert not (ddsdde["passed"] == 2 and aggregate["summary"]["total"] == 3)
    assert aggregate["summary"]["observables"]["STRESS"]["passed"] == 2


def test_aggregate_archives_source_and_increment_provenance(tmp_path: Path):
    arc_dir = tmp_path / "arc_123"
    case_dir = arc_dir / "paired_batch" / "validation" / "code_imp"
    case_dir.mkdir(parents=True)
    original_source = case_dir / "original.f"
    transformed_source = case_dir / "transformed.f90"
    original_source.write_text("      DDSDDE(1,1) = 10.0D0\n", encoding="utf-8")
    transformed_source.write_text(
        "      DSTRAN_OTI(1) = DSTRAN_OTI(1) + OTI_E1\n"
        "! OTIS-SKIP: DDSDDE(1,1) = 10.0D0\n"
        "      DDSDDE(1,1) = GETIM(STRESS_OTI(1),1)\n"
        "      STATEV(2) = DDSDDE(1,1)\n",
        encoding="utf-8",
    )
    original_results = {
        "ddsdde_component_count": 1,
        "ddsdde_statev_start_index": 2,
        "ddsdde_statev_end_index": 2,
        "increments": [{"frame_index": 1, "increment_number": 1, "ddsdde": [[10.0]]}],
    }
    transformed_results = {
        **original_results,
        "increments": [{"frame_index": 1, "increment_number": 1, "ddsdde": [[10.25]]}],
    }
    original_results_path = case_dir / "original_results.json"
    transformed_results_path = case_dir / "otis_results.json"
    _write_json(original_results_path, original_results)
    _write_json(transformed_results_path, transformed_results)
    _write_json(
        case_dir / "validation_report.json",
        {
            "status": "passed",
            "final_pass": True,
            "original_umat_path": str(original_source),
            "transformed_umat_path": str(transformed_source),
            "generated_files": {
                "instrumented_original_user": str(original_source),
                "combined_oti_user": str(transformed_source),
                "original_results_json": str(original_results_path),
                "otis_results_json": str(transformed_results_path),
            },
            "ddsdde_comparison": {
                "status": "passed",
                "max_abs_difference": 0.25,
                "max_rel_difference": 0.025,
            },
        },
    )

    output_json = tmp_path / "aggregate.json"
    aggregate_abaqus_results(
        arc_dir, output_csv=tmp_path / "aggregate.csv", output_json=output_json
    )

    audit = json.loads(output_json.read_text(encoding="utf-8"))["rows"][0]["audit"]
    checks = audit["transformed_source_checks"]
    assert checks["oti_seeding_lines"][0]["line"] == 1
    assert checks["original_ddsdde_assignment_span"] == {
        "start_line": 1,
        "end_line": 1,
        "statement_count": 1,
    }
    assert checks["bypassed_ddsdde_assignment_span"]["start_line"] == 2
    assert checks["compiled_ddsdde_extraction_span"]["start_line"] == 3
    assert audit["increments"][0]["absolute_difference"] == [[0.25]]
    assert audit["increments"][0]["max_rel_difference"] == 0.25 / 10.25
    assert audit["result_extraction_layout"]["original"]["ddsdde_statev_start_index"] == 2
    assert "job=original_umat_validation" in audit["jobs"]["original"]["command"]


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


def test_claim_matrix_promotes_only_observed_corpus_stages():
    claims = _build_claim_matrix_from_results(
        env=SimpleNamespace(abaqus_ok=False),
        oti_j2={"status": "verified"},
        oti_ho={"status": "verified"},
        corpus_metrics={
            "cumulative_stage_counts": {"generated_source_compiled": 14},
            "provenance": {
                "acquired_source_count": 148,
                "unique_source_count": 133,
                "unique_umat_count": 46,
            },
        },
    )
    by_id = {claim["id"]: claim for claim in claims}

    assert by_id["corpus_compile_success"]["status"] == "verified"
    assert by_id["corpus_compile_success"]["observed_compile_success"] == 14
    assert by_id["corpus_regression_round_metrics"]["status"] == "verified"
    assert by_id["corpus_primal_parity"]["status"] == "pending"
    assert by_id["corpus_derivative_verification"]["status"] == "pending"