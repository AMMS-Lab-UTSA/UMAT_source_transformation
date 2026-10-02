"""The regression-case comparators reject what they must and accept what they must.

Pure-Python: synthetic observations against a synthetic frozen reference.
Covers every failure kind of ``tools/corpus_cases.py check``: tolerance
breach (tangent and primal), coverage shrink, drift, hidden state, and the
mutant canaries (a canary that passes is a failure of the tier).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("corpus_cases", REPO / "tools" / "corpus_cases.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

pytestmark = pytest.mark.unit

E = 1000.0


class Run:
    """A RealOutput stand-in: linear elastic 2x2 'material', 3 increments."""

    def __init__(self, scale=1.0, hidden_at=None):
        self.base, self.local, self.replay = {}, {}, {}
        for inc in (1, 2, 3):
            stress = np.array([E * 1e-3 * inc, 0.5 * E * 1e-3 * inc])
            statev = np.array([1e-3 * inc])
            ddsdde = np.array([[E, 0.3 * E], [0.3 * E, E]]) * scale
            self.base[inc] = dict(stress=stress, statev=statev, ddsdde=ddsdde)
            replay_stress = stress * (1 + 1e-9) if hidden_at == inc else stress
            self.local[(inc, 1, 1)] = (replay_stress, statev, 1.0)
            self.local[(inc, 1, -1)] = (replay_stress, statev, 1.0)
            self.replay[inc] = dict(stress=replay_stress, statev=statev, ddsdde=ddsdde)


def path_ref(tau_rel=1e-6):
    run = Run()
    states = [{"inc": inc, "entries": [[i, j, float(run.base[inc]["ddsdde"][i - 1, j - 1]),
                                        tau_rel * abs(float(run.base[inc]["ddsdde"][i - 1, j - 1])),
                                        "pass"] for i in (1, 2) for j in (1, 2)]}
              for inc in (1, 2, 3)]
    return {"name": "p", "ntens": 2, "nstatv": 1, "n_inc": 3, "statev_defined": None,
            "original": {"stress": [run.base[k]["stress"].tolist() for k in (1, 2, 3)],
                         "statev": [run.base[k]["statev"].tolist() for k in (1, 2, 3)]},
            "judged": states, "frozen_error": {"primal": 0.0, "tangent": 0.0}}


def test_the_unchanged_build_passes_every_comparator():
    v = cc.judge_path(path_ref(), Run())
    assert v["primal"]["agrees"] and v["tangent"]["agrees"] and v["hidden_state"]["agrees"]
    assert v["coverage"]["judged"] == v["coverage"]["frozen"] == 3
    assert cc.failures_of({"p": v}, {"p": {"primal": 0.0, "tangent": 0.0}}) == []


def test_a_tangent_outside_its_frozen_tolerance_is_a_tolerance_failure():
    v = cc.judge_path(path_ref(), Run(scale=1 + 1e-4))
    kinds = {f["kind"] for f in cc.failures_of({"p": v}, {})}
    assert "tolerance" in kinds and not v["tangent"]["agrees"]


def test_a_non_finite_tangent_fails_and_shrinks_coverage():
    run = Run()
    run.base[2]["ddsdde"] = run.base[2]["ddsdde"].copy()
    run.base[2]["ddsdde"][0, 0] = np.nan
    v = cc.judge_path(path_ref(), run)
    kinds = {f["kind"] for f in cc.failures_of({"p": v}, {})}
    assert {"tolerance", "coverage_shrank"} <= kinds
    assert "2" in v["coverage"]["lost"]


def test_a_primal_difference_fails_and_unjudges_every_later_state():
    run = Run()
    run.base[2]["stress"] = run.base[2]["stress"] * (1 + 1e-8)
    v = cc.judge_path(path_ref(), run)
    assert not v["primal"]["agrees"]
    assert sorted(v["coverage"]["lost"]) == ["2", "3"]


def test_hidden_state_is_detected_and_shrinks_coverage_from_where_it_starts():
    v = cc.judge_path(path_ref(), Run(hidden_at=2))
    assert v["hidden_state"]["differs_at"] == [2]
    kinds = {f["kind"] for f in cc.failures_of({"p": v}, {})}
    assert {"hidden_state", "coverage_shrank"} <= kinds


def test_an_original_that_no_longer_reproduces_its_history_shrinks_coverage():
    original = Run()
    original.base[3]["stress"] = original.base[3]["stress"] * 1.01
    v = cc.judge_path(path_ref(), Run(), original)
    assert v["coverage"]["lost"] == {"3": ["the ORIGINAL no longer reproduces its frozen history"]}


def test_error_growth_beyond_ten_times_the_frozen_error_is_drift_even_inside_tolerance():
    ref = path_ref(tau_rel=1e-3)
    v = cc.judge_path(ref, Run(scale=1 + 1e-4))          # error/tau = 0.1: inside tolerance
    assert v["tangent"]["agrees"]
    fails = cc.failures_of({"p": v}, {"p": {"primal": 0.0, "tangent": 1e-3}})
    assert [f["kind"] for f in fails] == ["drift"]
    assert cc.failures_of({"p": v}, {"p": {"primal": 0.0, "tangent": 0.05}}) == []


def test_every_data_canary_is_rejected_on_a_resolving_reference():
    ref = {"paths": [path_ref()]}
    results = cc.data_canaries(ref, {"p": Run()})
    assert len(results) == 3 and all(r["rejected"] for r in results)


def test_a_canary_that_slips_through_a_loose_reference_is_reported_as_not_rejected():
    # tau = 1e-2 |D|: a 1e-4 column error is inside it, so that canary PASSES -> tier failure
    results = cc.data_canaries({"paths": [path_ref(tau_rel=1e-2)]}, {"p": Run()})
    column = next(r for r in results if "column" in r["canary"])
    assert column["rejected"] is False


def test_the_frozen_capture_refuses_a_state_with_an_unresolved_entry():
    capture = {"judged": [1], "states": {"1": {"strain_1": {
        "names": ["DDSDDE(1,1)"], "D": [1.0], "tau": [1e-6], "codes": ["unresolved_spread"],
        "oti": [1.0]}}}}
    with pytest.raises(ValueError):
        cc.frozen_states_from_capture(capture)


def test_the_rule_id_is_stable_and_names_its_version():
    assert cc.rule_id() == cc.rule_id()
    assert cc.rule_id().startswith("case-rule/1-")
