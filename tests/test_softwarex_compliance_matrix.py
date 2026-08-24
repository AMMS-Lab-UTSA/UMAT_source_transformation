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


def test_reference_quality_section_never_counts_an_unsupported_row():
    """Higher-order rows are carried by a resolved reference, not by a tolerance."""
    matrix = _matrix()
    section = matrix["reference_quality"]
    assert section["applies_to_claim"] == "higher_orders_from_actual_umat_models"
    assert set(section["supporting_classifications"]) == {
        "resolved",
        "expected_zero_independently_supported",
    }
    # Everything else is reported but never counted. In particular a zero that
    # rests only on sampled equality is not evidence.
    assert set(section["classifications"]) - set(section["supporting_classifications"]) == {
        "empirically_zero_over_stencil",
        "cancellation_limited",
        "reference_unresolved",
    }
    for name, model in section["models"].items():
        assert name in section["models_verified"], name
        counted = model["resolved"] + model["expected_zero_independently_supported"]
        withheld = (
            model["empirically_zero_over_stencil"]
            + model["cancellation_limited"]
            + model["reference_unresolved"]
        )
        assert counted + withheld == model["rows"], name
        assert withheld == 0, f"{name} still has {withheld} rows without a usable reference"
        assert model["rows_disagreeing_with_resolved_reference"] == 0, name
        assert model["rows_supporting_verification"] == model["rows"], name
        assert model["max_relative_error_on_resolved_rows"] < 1.0e-4, name


def test_sampled_equality_is_never_recorded_as_proof_of_an_exact_zero():
    section = _matrix()["reference_quality"]
    policy = section["zero_support_policy"]
    assert set(policy["weak"]) == {
        "empirical_stencil_invariance", "empirical_affine_probe",
    }
    assert "high_precision" in policy["strong"]
    # the two must not overlap: a support cannot be both proof and sampling
    assert not set(policy["strong"]) & set(policy["weak"])
    assert "empirically_zero_over_stencil" not in section["supporting_classifications"]


def test_models_that_did_not_verify_are_never_listed_as_verified():
    section = _matrix()["reference_quality"]
    unverified = section["models_studied_not_verified"]
    assert set(unverified) == {
        "UMAT_PCL", "UMAT_PCLK", "visco_imp", "code_imp_legacy_umat",
    }
    assert not set(section["models_verified"]) & set(unverified)
    assert not set(section["models"]) & set(unverified)
    for name, entry in unverified.items():
        assert entry["outcome"] != "verified", name
        if entry.get("rows_disagreeing_with_resolved_reference"):
            # a disagreement with a resolved reference is a discrepancy, never a
            # reference-quality gap
            assert entry["outcome"] != "reference_quality_limited", name
        if "rows_supporting_verification" in entry:
            assert entry["rows_supporting_verification"] < entry["rows"], name
    assert section["primal_consistency_gate"]
    assert section["branch_admissibility"]


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