from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from umat_oti.validation.actual_legacy_higher_order import run_code_imp_higher_order_evidence
from umat_oti.validation.actual_umat_higher_order import run_actual_j2_higher_order_evidence


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is required")
def test_actual_transformed_j2_orders_two_to_four_match_independent_reference(tmp_path: Path):
    evidence = run_actual_j2_higher_order_evidence(
        REPO_ROOT / "examples" / "j2_actual_higher_order.json",
        tmp_path / "evidence",
    )

    assert evidence["status"] == "verified_from_generic_transformed_source"
    assert evidence["comparison"]["rows"] == 108
    assert evidence["comparison"]["passed_rows"] == 108
    assert evidence["comparison"]["failed_rows"] == 0
    assert evidence["comparison"]["max_relative_error_when_absolute_tolerance_exceeded"] < 1.0e-7
    assert [row["yielded"] for row in evidence["branch_history"]] == [False, True, True]
    assert evidence["branch_history"][2]["eqplas_before"] > 0.0
    assert evidence["branch_history"][2]["eqplas_after"] > evidence["branch_history"][2]["eqplas_before"]
    assert {tuple(direction) for direction in evidence["directions"]} >= {
        (1, 1),
        (1, 2),
        (1, 1, 1),
        (1, 1, 2),
        (1, 1, 1, 1),
        (1, 1, 2, 2),
    }
    assert all(record["sha256"] for record in evidence["artifacts"])
    manifest = json.loads(Path(evidence["canonical_manifest"]).read_text(encoding="utf-8"))
    assert manifest["execution"]["status"] == "compiled"
    assert manifest["derivatives"][0]["order"] == 4


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is required")
def test_actual_transformed_code_imp_orders_two_to_four_match_original_umat_fd(tmp_path: Path):
    evidence = run_code_imp_higher_order_evidence(
        REPO_ROOT / "examples" / "code_imp_actual_higher_order.json",
        tmp_path / "evidence",
    )

    assert evidence["status"] == "verified_from_generic_transformed_source"
    assert evidence["comparison"]["rows"] == 96
    assert evidence["comparison"]["passed_rows"] == 96
    assert evidence["comparison"]["failed_rows"] == 0
    assert evidence["comparison"]["max_relative_error_when_absolute_tolerance_exceeded"] < 2.0e-5
    assert [row["branch"] for row in evidence["branch_history"]] == [
        "elastic",
        "plastic",
        "plastic",
        "plastic",
    ]
    assert evidence["branch_history"][3]["effective_plastic_strain"] > evidence["branch_history"][1]["effective_plastic_strain"]
    assert {tuple(direction) for direction in evidence["directions"]} >= {
        (1, 1),
        (1, 2),
        (1, 1, 1),
        (1, 1, 2),
        (1, 1, 1, 1),
        (1, 1, 2, 2),
    }
    assert all(record["sha256"] for record in evidence["artifacts"])
    assert "independently compiled original code_imp UMAT" in evidence["reference"]["method"]
    manifest = json.loads(Path(evidence["canonical_manifest"]).read_text(encoding="utf-8"))
    assert manifest["execution"]["status"] == "compiled"
    assert manifest["derivatives"][0]["order"] == 4
