"""State choice of the Abaqus D-4 tangent gate (G10; Vera A5, Curie item 5).

States are chosen from the ORIGINAL history, on one integration point's own
records (activation found there, not on the flattened list of every point),
before anything is compared; each is matched to the transformed record of the
same (increment, element, point). A state with no transformed match stays in
the denominator.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.unit


@pytest.fixture()
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "tools"))
    sys.modules.pop("verify_store_in_abaqus", None)
    import verify_store_in_abaqus
    return verify_store_in_abaqus


def _history(points=(1, 2), increments=12, activate=None, transformed=False):
    out = []
    for inc in range(1, increments + 1):
        for point in points:
            moved = activate is not None and point in activate and inc >= activate[point]
            record = {"increment": inc, "element": 1, "point": point,
                      "STRESS": [float(inc)], "STATEV": [1.0 if moved else 0.0],
                      "DDSDDE": [100.0], "DSTRAN": [1e-3]}
            if transformed:
                record["entry"] = {"DSTRAN": [1e-3]}
            out.append(record)
    return out


def test_activation_is_read_on_one_point_and_states_straddle_it(tool):
    # point 1 activates at increment 6; point 2 at increment 2 (the flattened
    # list would put the transition at point 2's second increment)
    original = _history(activate={1: 6, 2: 2})
    chosen, selection = tool.choose_gate_states(original, _history(transformed=True))
    assert selection["selected_from"] == "original"
    assert selection["point"] == {"element": 1, "point": 1}
    assert selection["activation_increment"] == 6
    increments = [s["increment"] for s in selection["states"]]
    assert len(increments) == 4
    assert all(i < 5 or i > 7 for i in increments)
    assert sum(i < 6 for i in increments) == 2 and sum(i > 6 for i in increments) == 2
    for _pos, _records, original_record, transformed_record in chosen:
        assert transformed_record["increment"] == original_record["increment"]
        assert transformed_record["point"] == 1


def test_without_activation_four_states_are_spread_over_the_matched_records(tool):
    original = _history(points=(1,), activate=None)
    transformed = [r for r in _history(points=(1,), transformed=True) if r["increment"] != 12]
    chosen, selection = tool.choose_gate_states(original, transformed)
    assert len(chosen) == 4 and all(t is not None for *_x, t in chosen)
    assert selection["rule"].startswith("4 states spread")
    assert 12 not in [s["increment"] for s in selection["states"]]


def test_a_chosen_state_without_a_replay_counts_against_the_row(tool):
    from umat_oti.abaqus import tangent_gate as G
    from umat_oti.corpus_features import fd
    good = G.StateJudgement(increment=1, ntens=1, entry_codes={(1, 1): fd.PASS})
    ok, why = G.row_verdict([good, good, None, None, None], 5, coverage_ok=True,
                            coverage_reason="")
    assert not ok and "2 of 5" in why


def test_states_pair_on_step_as_well_as_increment(tool):
    """Vera G10 review B1: Abaqus restarts the increment count each step."""
    def two_steps(transformed=False):
        out = []
        for step in (1, 2):
            for record in _history(points=(1,), increments=6, transformed=transformed):
                record = dict(record, step=step)
                record["STRESS"] = [float(10 * step + record["increment"])]
                out.append(record)
        return out
    original = two_steps()
    transformed = two_steps(transformed=True)
    chosen, selection = tool.choose_gate_states(original, transformed)
    for _pos, _records, orig, trans in chosen:
        assert (trans["step"], trans["increment"]) == (orig["step"], orig["increment"])
        assert trans["STRESS"] == orig["STRESS"]
    keys = [(s["step"], s["increment"]) for s in selection["states"]]
    assert len(keys) == len(set(keys)) and {k[0] for k in keys} == {1, 2}


def test_an_early_activation_still_gives_two_states_before_it(tool):
    """pass21: activation at the third increment left one pre-activation state
    clear of it, and the row lost on its own coverage rule."""
    original = _history(points=(1,), increments=12, activate={1: 3})
    chosen, selection = tool.choose_gate_states(original, _history(points=(1,),
                                                                   transformed=True))
    before = [s["increment"] for s in selection["states"] if s["increment"] < 3]
    assert before == [1, 2]
    assert all(s["increment"] != 3 for s in selection["states"])
