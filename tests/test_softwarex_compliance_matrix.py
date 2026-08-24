from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "paper_results" / "softwarex_claim_matrix.json"
DOC_PATH = ROOT / "docs" / "SOFTWAREX_COMPLIANCE_MATRIX.md"

ALLOWED_STATUSES = {
    "verified_from_generic_transformed_source",
    "verified_from_real_abaqus_execution",
    "verified_reference_fixture_only",
    "implemented_offline_not_abaqus_verified",
    "partially_implemented",
    "not_implemented",
    "blocked_by_external_environment",
    "failed",
}


def _matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def test_claim_matrix_has_complete_schema_and_allowed_statuses():
    matrix = _matrix()
    assert set(matrix["allowed_statuses"]) == ALLOWED_STATUSES
    claims = matrix["claims"]
    assert len(claims) >= 15
    assert len({claim["id"] for claim in claims}) == len(claims)
    required = {
        "id",
        "manuscript_location",
        "required_capability",
        "implementation",
        "source_case",
        "executable_test",
        "evidence",
        "status",
        "blocker",
    }
    for claim in claims:
        assert set(claim) == required
        assert claim["status"] in ALLOWED_STATUSES
        assert claim["blocker"] is not None or claim["status"].startswith("verified_")


def test_narrow_evidence_does_not_promote_broad_claims():
    by_id = {claim["id"]: claim for claim in _matrix()["claims"]}
    assert by_id["higher_order_direction_factorial_fixture"]["status"] == "verified_reference_fixture_only"
    assert by_id["higher_orders_from_actual_umat_models"]["status"] != "verified_reference_fixture_only"
    assert by_id["focused_j2_parameter_sensitivity"]["status"] == "verified_reference_fixture_only"
    assert by_id["generic_source_parameter_sensitivity"]["status"] != "verified_from_generic_transformed_source"
    assert by_id["public_corpus_round_1"]["status"] == "implemented_offline_not_abaqus_verified"
    assert by_id["public_corpus_numerical_ladder_and_round_2"]["status"] == "not_implemented"


def test_abaqus_collection_and_failed_nineteenth_case_are_separate():
    by_id = {claim["id"]: claim for claim in _matrix()["claims"]}
    assert by_id["abaqus_paired_18_manuscript_cases"]["status"] == "verified_from_real_abaqus_execution"
    assert by_id["nineteenth_VPDCL_R_case"]["status"] == "failed"


def test_human_matrix_exists_and_mentions_machine_source():
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "paper_results/softwarex_claim_matrix.json" in text
    assert "UMAT_OTI_SoftwareX_V4.docx" in text