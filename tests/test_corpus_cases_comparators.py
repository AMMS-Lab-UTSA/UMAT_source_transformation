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


# ---------------------------------------------------------------------------
# the capture records the verdict the harness used (judge_binary32 judges a
# column three times and returns a fourth)
# ---------------------------------------------------------------------------
class _V:
    """A ColumnVerdict stand-in: the three fields the capture reads."""

    def __init__(self, tag, codes, reference, tolerance):
        self.tag, self.codes = tag, list(codes)
        self.reference, self.tolerance = np.asarray(reference, float), np.asarray(tolerance, float)


def _binary32_stand_in(stack):
    """judge_binary32 as fd defines it: three calls through the (wrapped)
    module-level judge_column, then the per-entry verdict it returns."""
    holder = {}

    def judge_column(*_a, **_k):
        calls = holder["calls"]
        holder["calls"] = calls + 1
        return (_V("normal", ["pass"], [2.0], [1e-9]),
                _V("wide", ["unresolved_spread"], [2.5], [1e-1]),     # unresolved under the noise
                _V("variant", ["pass"], [2.0], [1e-9]))[calls]

    def judge_binary32(*args, **kwargs):
        for _ in range(3):
            holder["wrapped"](*args, **kwargs)
        return _V("returned", ["pass_b32"], [2.0], [3e-4])
    judge, judge_b32 = cc._capturing_judges(judge_column, judge_binary32, stack)
    holder["wrapped"], holder["calls"] = judge, 0
    return judge, judge_b32


def test_the_capture_takes_the_verdict_judge_binary32_returns_not_its_last_inner_call():
    stack = [[]]
    _judge, judge_b32 = _binary32_stand_in(stack)
    returned = judge_b32("column")
    assert [v.tag for v in stack[0]] == ["returned"] and stack[0][0] is returned
    assert stack[0][0].codes == ["pass_b32"]


def test_a_plain_column_is_recorded_once_and_outside_a_judgement_nothing_is():
    stack = [[]]
    judge, _ = cc._capturing_judges(lambda *a, **k: _V("plain", ["pass"], [1.0], [1e-9]),
                                    lambda *a, **k: None, stack)
    judge("column")
    assert [v.tag for v in stack[0]] == ["plain"]
    empty: list = []
    judge2, _ = cc._capturing_judges(lambda *a, **k: _V("plain", ["pass"], [1.0], [1e-9]),
                                     lambda *a, **k: None, empty)
    judge2("column")
    assert empty == []


def test_the_capture_of_the_old_wrapper_would_have_kept_the_unresolved_wide_call():
    """What the old capture (judge_column only, last call kept) recorded."""
    stack = [[]]
    judge, _ = cc._capturing_judges(
        lambda *a, **k: _V("wide", ["unresolved_spread"], [2.5], [1e-1]),
        lambda *a, **k: None, stack)
    judge("column")
    capture = {"judged": [1], "states": {"1": {"strain_1": {
        "names": ["DDSDDE(1,1)"], "D": [2.5], "tau": [1e-1], "codes": ["unresolved_spread"],
        "oti": [2.0]}}}}
    with pytest.raises(ValueError):
        cc.frozen_states_from_capture(capture)


def test_a_binary32_pass_freezes_with_its_own_tolerance_and_is_judged_like_a_pass():
    capture = {"judged": [1], "states": {"1": {"strain_1": {
        "names": ["DDSDDE(1,1)", "DDSDDE(2,1)"], "D": [2.0, 0.0], "tau": [3e-4, 1e-9],
        "codes": ["pass_b32", "zero_pass_b32"], "oti": [2.0, 0.0]}}}}
    (state,) = cc.frozen_states_from_capture(capture)
    assert state["entries"] == [[1, 1, 2.0, 3e-4, "pass_b32"], [2, 1, 0.0, 1e-9, "zero_pass_b32"]]
    good = cc.compare_tangent({1: np.array([[2.0, 0.0], [0.0, 0.0]])}, [state])
    assert good["agrees"]
    off = cc.compare_tangent({1: np.array([[2.0 + 1e-3, 0.0], [0.0, 0.0]])}, [state])
    assert not off["agrees"]                              # outside tau
    moved = cc.compare_tangent({1: np.array([[2.0, 0.0], [1e-3, 0.0]])}, [state])
    assert not moved["agrees"]                            # a frozen zero moved off zero
    for code in ("unresolved_binary32", "fail", "unresolved_zero_scale"):
        bad = {"judged": [1], "states": {"1": {"s": {"names": ["DDSDDE(1,1)"], "D": [1.0],
                                                    "tau": [1e-6], "codes": [code], "oti": [1.0]}}}}
        with pytest.raises(ValueError):
            cc.frozen_states_from_capture(bad)


def test_a_stray_staging_directory_is_never_read_as_a_case(tmp_path, monkeypatch):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "case.json").write_text("{}")
    (tmp_path / ".freeze-real-4242").mkdir()
    (tmp_path / ".freeze-real-4242" / "case.json").write_text("{}")
    monkeypatch.setattr(cc, "CASES", tmp_path)
    assert [p.parent.name for p in cc.case_jsons()] == ["real"]
    loaded = cc.load_cases(None, ())
    assert [d.name for d, _case in loaded] == ["real"]
