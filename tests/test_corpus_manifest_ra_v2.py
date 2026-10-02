"""RA records that carry the merge contract's fields are folded, not downgraded.

``ra-corpus-residual/1`` records used a vector max-norm tolerance and a
plateau taken where FD agreed with OTI, so the adapter turned their
``verified`` into ``inconclusive``. ``/2`` records (B2) state an entrywise
rule, an FD-only plateau, a per-record error/tolerance ratio and the build;
applying the /1 downgrade to them turned every verified RA result into
inconclusive. The fold is the harness's coverage rule.
"""
from __future__ import annotations

import pytest

from umat_oti.corpus_features.manifest import (
    RA_SCHEMA_V2,
    _ra_v2_cell,
    ra_records_to_cells,
)


def _record(problem: str, status: str, **extra) -> dict:
    base = {
        "schema": RA_SCHEMA_V2, "source_id": "a/b.f", "feature": "residual_sens",
        "problem": problem, "status": status, "reference": "fd",
        "tolerance_rule_id": "entrywise/1", "rtol": 1e-6, "plateau_basis": "fd_only",
        "min_plateau_observed": 4, "max_error": 0.2, "tolerance": 1.0,
        "quantity": "R", "wrt": "PROPS(1)", "held_fixed": "u_n", "scope": "local",
        "evidence": "campaign:batches/x.json", "build": {"kind": "provider", "sha256": "f" * 64},
    }
    base.update(extra)
    return base


@pytest.mark.unit
def test_two_verified_problems_make_a_verified_cell_with_the_worst_numbers():
    cell = _ra_v2_cell("a/b.f", "residual_sens",
                       [_record("p1", "verified", max_error=0.3, min_plateau_observed=5),
                        _record("p2", "verified", max_error=0.7, min_plateau_observed=3)],
                       {}, "test")
    assert cell["status"] == "verified"
    assert cell["max_error"] == 0.7 and cell["min_plateau_observed"] == 3
    assert cell["tolerance_rule_id"] == "entrywise/1" and cell["plateau_basis"] == "fd_only"


@pytest.mark.unit
def test_one_verified_problem_of_three_is_not_enough():
    cell = _ra_v2_cell("a/b.f", "residual_sens",
                       [_record("p1", "verified"), _record("p2", "unresolved"),
                        _record("p3", "unresolved")], {}, "test")
    assert cell["status"] == "not_attempted"
    assert "insufficient coverage" in cell["reason"]


@pytest.mark.unit
def test_a_single_evaluated_problem_may_verify_alone():
    cell = _ra_v2_cell("a/b.f", "residual_sens",
                       [_record("p1", "verified"), _record("p2", "unsupported")], {}, "test")
    assert cell["status"] == "verified"


@pytest.mark.unit
def test_any_failed_problem_fails_the_cell():
    cell = _ra_v2_cell("a/b.f", "residual_sens",
                       [_record("p1", "verified"), _record("p2", "verified"),
                        _record("p3", "failed")], {}, "test")
    assert cell["status"] == "failed"


@pytest.mark.unit
def test_v2_records_are_routed_to_the_v2_fold_and_v1_are_not():
    cells, report = ra_records_to_cells(
        [_record("p1", "verified"), _record("p2", "verified")])
    assert [c["status"] for c in cells] == ["verified"]
    assert not report["mismatches"]
    v1 = dict(_record("p1", "verified"), schema="ra-corpus-residual/1")
    cells, _ = ra_records_to_cells([v1])
    assert cells[0]["status"] == "inconclusive"


@pytest.mark.unit
def test_a_cell_whose_original_is_not_fully_defined_is_shown_not_counted():
    from umat_oti.corpus_features.manifest import _gate_on_definedness

    cells = {"ddsdde": {"status": "verified", "stress_and_ddsdde_fully_defined": False,
                        "undefined_outputs": ["DDSDDE(1,1)"], "evidence": "x"},
             "primal_stress_state": {"status": "verified",
                                     "stress_and_ddsdde_fully_defined": True}}
    _gate_on_definedness(cells)
    assert cells["ddsdde"]["status"] == "inconclusive"
    assert "DDSDDE(1,1)" in cells["ddsdde"]["reason"]
    assert cells["ddsdde"]["withheld_verified"]["status"] == "verified"
    assert cells["primal_stress_state"]["status"] == "verified"
