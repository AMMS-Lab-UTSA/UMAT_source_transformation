"""Primal cells from the D-15 gate, path portability, and the D-11 family.

Synthetic pass records shaped like corpus_run/pass19 store_verification.jsonl
(primal_gate, routine_primal, jacobian_matched_primal, undefined_in_original).
"""

from __future__ import annotations


import pytest

from umat_oti.corpus_features import manifest as M
from umat_oti.corpus_features.manifest import (
    TOLERANCE_RULES,
    WORKSPACE_TOKEN,
    expand_roots,
    portable_roots,
    primal_gate_verdict,
    reported_family,
    validate_cell,
)

GATES_TRUE = {"abaqus_job_completed": True, "complete_history_finite": True,
              "primal_agreed": True, "mechanically_informative": True}


def _comp(over=0.1, state=0.0, calls=100, **kw):
    return {"agrees": over <= 1, "calls": calls, "tolerance": 1e-10,
            "worst_stress_over_bound": over, "worst_state_relative": state,
            "non_finite_mismatches": 0, "reason": f"{calls} paired calls", **kw}


def _rec(agrees, decided_by, routine=None, jm=None, jm_completed=True, jm_ran=True,
         reason="r", init=True, fe_worst=0.5):
    rec = {"primal_gate": {"agrees": agrees, "decided_by": decided_by,
                           "init_variants_established": init,
                           "undefined_outputs_excluded": []},
           "routine_primal": {"ran": routine is not None, "agrees": agrees,
                              **({"comparison": routine} if routine else {})},
           "jacobian_matched_primal": {"ran": jm_ran, "completed": jm_completed,
                                       **({"comparison": jm} if jm else {})},
           "undefined_in_original": {"established": init, "undefined": {}},
           "primal": {"agrees": True, "worst_stress_relative": fe_worst,
                      "worst_state_relative": 0.0, "informational_only": True},
           "reason": reason, "stage": "x"}
    return rec


def _ev(agreed):
    return {**GATES_TRUE, "primal_agreed": agreed}


def test_the_gate_rule_is_registered_for_primal_cells():
    rule = TOLERANCE_RULES["routine_primal_gate/1"]
    assert rule["accepted"] and rule["applies_to"] == ("primal",)


def test_agreement_on_both_comparisons_is_verified_with_the_larger_ratio():
    c = primal_gate_verdict(_rec(True, "routine_level+jacobian_matched",
                                 _comp(0.2), _comp(0.6)), _ev(True))
    assert c["status"] == "verified"
    assert c["tolerance_rule_id"] == "routine_primal_gate/1"
    assert c["max_error"] == pytest.approx(0.6) and c["tolerance"] == 1.0
    assert c["decided_by"] == "routine_level+jacobian_matched"
    # the measured block carries the gate's numbers; FE only as informational
    assert c["measured"]["jacobian_matched"]["ratio"] == pytest.approx(0.6)
    assert "worst_stress_relative" not in c["measured"]
    assert c["measured"]["fe_comparison_informational"]["worst_stress_relative"] == 0.5
    assert validate_cell("primal_stress_state",
                         {**c, "evidence": "", "build": None},
                         check_evidence=False) == []


def test_state_difference_enters_the_ratio_over_rtol():
    c = primal_gate_verdict(_rec(False, "routine_level", _comp(1e-6, state=0.25)),
                            _ev(False))
    assert c["status"] == "failed" and c["values_disagree"] is True
    assert c["max_error"] == pytest.approx(0.25 / 1e-10)


def test_a_jacobian_matched_disagreement_carries_the_controls_ratio():
    # pass19 bcfe0f80: routine level 0.12, control 2.68x its bound
    c = primal_gate_verdict(_rec(False, "jacobian_matched", _comp(0.124), _comp(2.683)),
                            _ev(False))
    assert c["status"] == "failed"
    assert c["max_error"] == pytest.approx(2.683)
    assert c["decided_by"] == "jacobian_matched"
    assert c["measured"]["routine_level"]["ratio"] == pytest.approx(0.124)
    assert validate_cell("primal_stress_state", {**c, "evidence": ""},
                         check_evidence=False) == []


@pytest.mark.parametrize("rec, status, kind", [
    # control job never completed (pass19 cf192d29): routine level measured
    (_rec(False, "jacobian_matched", _comp(1e-4), None, jm_completed=False),
     "inconclusive", "jacobian_matched_job_incomplete"),
    # control ran but over zero paired calls (pass19 91aa363f)
    (_rec(False, "jacobian_matched", _comp(0.0), _comp(0.0, calls=0)),
     "inconclusive", "replay_mismatch"),
    # routine replay paired no calls and nothing else ran (pass19 3c834cf1)
    (_rec(False, "routine_level", _comp(0.0, calls=0), None, jm_ran=False,
          jm_completed=None),
     "not_attempted", "replay_mismatch"),
    # no init build set could be built (pass19 8e59ba46)
    (_rec(False, "undefined_in_original_check", None, None, jm_ran=False,
          jm_completed=None, init=False),
     "not_attempted", "no_init_build"),
])
def test_process_failures_are_not_failures(rec, status, kind):
    c = primal_gate_verdict(rec, _ev(False))
    assert c["status"] == status and c["process_failure"] == kind
    assert c["max_error"] is None and "values_disagree" not in c


def test_a_gate_that_agreed_without_its_comparison_is_inconclusive_not_fe_ruled():
    rec = _rec(True, "routine_level+jacobian_matched", _comp(0.1), None)
    c = primal_gate_verdict(rec, _ev(True))
    assert c["status"] == "inconclusive"
    assert c["process_failure"] == "gate_comparison_missing"
    assert c["tolerance_rule_id"] == "routine_primal_gate/1"


def test_undefined_in_original_has_its_own_status_and_names_the_outputs():
    rec = {"primal_gate": None, "routine_primal": None,
           "undefined_in_original": {"established": True,
                                     "undefined": {"STRESS": [1, 2], "DDSDDE": [],
                                                   "STATEV": [3]}},
           "primal": {"agrees": True, "worst_stress_relative": 0.0},
           "reason": "undefined_in_original (D-12): STRESS(1) differs"}
    c = primal_gate_verdict(rec, {**GATES_TRUE, "primal_agreed": False,
                                  "mechanically_informative": False})
    assert c["status"] == "undefined_in_original"
    assert "values disagree" not in c["reason"]
    assert c["undefined_outputs"] == ["STRESS(1)", "STRESS(2)", "STATEV(3)"]
    assert c["stress_and_ddsdde_fully_defined"] is False
    assert c["max_error"] is None
    assert validate_cell("primal_stress_state", {**c, "evidence": ""},
                         check_evidence=False) == []


def test_records_from_before_the_gate_keep_the_fe_rule():
    rec = {"primal": {"worst_stress_relative": 5e-11, "worst_state_relative": 0.0}}
    c = primal_gate_verdict(rec, _ev(True))
    assert c["status"] == "verified"
    assert c["tolerance_rule_id"] == "abaqus_primal_history_floor/1"
    assert c["max_error"] == pytest.approx(0.5)


def test_a_nonfinite_mismatch_is_an_infinite_ratio():
    c = primal_gate_verdict(_rec(False, "routine_level",
                                 _comp(0.0, non_finite_mismatches=2)), _ev(False))
    assert c["status"] == "failed" and M._is_inf(c["max_error"])


# ---- portability ------------------------------------------------------------

@pytest.fixture
def ws(monkeypatch, tmp_path):
    w = str(tmp_path / "softwarex_work")
    monkeypatch.setenv("UMAT_OTI_WORKSPACE", w)
    return w


def test_portable_replaces_only_whole_paths(ws):
    v = M._portable({"a": f"{ws}/corpus_run/x.json",
                     "b": [f"cd {ws} && ls {ws}2/y", f"{ws}_old/z", ws],
                     "c": 3})
    assert v["a"] == f"{WORKSPACE_TOKEN}/corpus_run/x.json"
    assert v["b"][0] == f"cd {WORKSPACE_TOKEN} && ls {ws}2/y"
    assert v["b"][1] == f"{ws}_old/z"
    assert v["b"][2] == WORKSPACE_TOKEN and v["c"] == 3


def test_portable_uses_the_environment_workspace_not_the_checkout(ws):
    other = str(M._WS_DEFAULT) + "/corpus_run"
    if other.startswith(ws):
        pytest.skip("checkout lies under the temporary workspace")
    assert M._portable(other) == other


def test_roots_round_trip_and_checkout_roots_follow_the_clone(ws):
    roots = {"corpus_run": f"{ws}/corpus_run", "campaign": f"{ws}/corpus_campaign",
             "repo": f"{ws}/final-umat", "umat": f"{ws}/final-umat",
             "elsewhere": "/data/x", "near": f"{ws}2/x"}
    p = portable_roots(roots)
    assert p["corpus_run"] == f"{WORKSPACE_TOKEN}/corpus_run"
    assert p["elsewhere"] == "/data/x" and p["near"] == f"{ws}2/x"
    back = expand_roots(p)
    assert back["corpus_run"] == f"{ws}/corpus_run"
    assert back["campaign"] == f"{ws}/corpus_campaign"
    # a manifest naming another checkout never overrides this one
    assert back["repo"] == back["umat"] == str(M._REPO_DEFAULT)
    assert expand_roots({"repo": "$UMAT_OTI_WORKSPACE/renamed-clone"})["repo"] == \
        str(M._REPO_DEFAULT)


# ---- D-11 family --------------------------------------------------------------

def test_reported_family_is_b3_with_identity_growth_scaffolds_as_growth():
    b3 = {"family": "hyperelasticity", "disagreement_kind": "definitional",
          "confidence": "medium"}
    r = reported_family("Jeff97__plates/umat.for", b3, {"family": "growth / morphoelasticity"})
    assert r["family"] == "growth" and r["identity_growth_scaffold"] is True
    assert r["source"] == "B3_identity_growth_as_growth"
    r = reported_family("other__x/umat.f", b3, None)
    assert r["family"] == "hyperelasticity"
    assert r["reporting_family"] == "other_incl_hyperelasticity"
    r = reported_family("e_only/u.f", None, {"family": "plasticity"})
    assert r["family"] == "rate_independent_plasticity" and r["source"] == "E_fallback"
