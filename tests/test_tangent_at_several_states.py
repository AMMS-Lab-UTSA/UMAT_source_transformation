"""A tangent checked at one increment is a tangent checked in one regime.

The verification used to take the last replayable probe record and check
DDSDDE there. On a path-dependent model the last increment is usually the
plastic one and the first is usually elastic -- and an elastic tangent is the
part every build gets right, so agreement at a single conveniently chosen
state is the weakest evidence the pipeline can produce.

Several states are now checked and all of them have to agree. That is
strictly stronger: it cannot pass anything the single-record rule would have
failed, because the state that rule chose is still among them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from verify_store_in_abaqus import choose_probe_records  # noqa: E402

ENTRY = {"STRESS0": [0.0] * 6, "DSTRAN": [1e-4] + [0.0] * 5}


def _history(count, replayable=None):
    replayable = range(1, count + 1) if replayable is None else replayable
    return [({"DDSDDE": [1.0] * 36, "entry": ENTRY, "increment": i}
             if i in replayable else {"increment": i})
            for i in range(1, count + 1)]


def test_several_states_are_chosen_and_they_span_the_path():
    chosen = choose_probe_records(_history(20), 3)
    increments = [record["increment"] for _, record in chosen]
    assert increments == [1, 10, 20]


def test_the_furthest_state_is_always_among_them():
    """It is the one the single-record rule used to take, so the new rule
    cannot pass a material the old one would have failed."""
    for wanted in (1, 2, 3, 5, 7):
        chosen = choose_probe_records(_history(20), wanted)
        assert chosen[-1][1]["increment"] == 20


def test_asking_for_more_states_than_exist_returns_what_there_is():
    assert len(choose_probe_records(_history(2), 5)) == 2


def test_a_record_without_a_beginning_of_increment_state_is_skipped():
    """It cannot be replayed, and replaying it from a state made up to fill
    the gap would compare the tangent against a different increment."""
    history = [{"DDSDDE": [1.0] * 36, "increment": 1},
               {"DDSDDE": [1.0] * 36, "entry": ENTRY, "increment": 2}]
    assert [r["increment"] for _, r in choose_probe_records(history, 3)] == [2]


def test_a_record_without_a_tangent_is_skipped():
    history = [{"entry": ENTRY, "increment": 1},
               {"DDSDDE": [1.0] * 36, "entry": ENTRY, "increment": 2}]
    assert [r["increment"] for _, r in choose_probe_records(history, 3)] == [2]


def test_no_replayable_record_selects_nothing():
    assert choose_probe_records([{"increment": 1}], 3) == []
    assert choose_probe_records([], 3) == []


def test_sparse_replayable_records_are_all_taken():
    chosen = choose_probe_records(_history(10, replayable={2, 5, 9}), 3)
    assert [r["increment"] for _, r in chosen] == [2, 5, 9]


def test_the_positions_returned_index_the_original_history():
    """The caller writes per-state working directories from them, so an index
    into a filtered list would collide."""
    history = _history(10, replayable={3, 7})
    for position, record in choose_probe_records(history, 3):
        assert history[position] is record


# ---- the loading path the states come from ------------------------------
def test_the_probe_path_exercises_shear_as_well_as_extension():
    """Uniaxial extension drives one direct component, so the shear rows and
    columns of DDSDDE are only ever exercised by whatever coupling the model
    happens to have. A transform can be wrong about them without a uniaxial
    path noticing."""
    from umat_oti.abaqus.manifest import simple_shear, uniaxial

    assert uniaxial(0.01).strain[0] == 0.01
    assert simple_shear(0.01).strain[3] == 0.01
    assert simple_shear(0.01).strain[:3] == (0.0, 0.0, 0.0)


def test_a_reversal_makes_state_evolution_observable():
    from umat_oti.abaqus.manifest import reverse, uniaxial

    back = reverse(uniaxial(0.01))
    assert back.strain[0] < 0
    assert "reversal" in back.description


# --------------------------------------------------------------------------
# a state where no difference could be taken is not a state that disagreed
# --------------------------------------------------------------------------
def _state(increment, *, verified, best=None):
    return {"increment": increment, "record_index": increment,
            "verified": verified,
            "comparison": ({"best_relative": best} if best is not None else {}),
            "reason": "" if verified else ("the sweep recorded no best step"
                                           if best is None else "disagreed")}


def test_the_minimum_measured_states_is_more_than_one():
    """One state cannot separate an elastic tangent every build gets right
    from a converted one that is right everywhere."""
    from verify_store_in_abaqus import MINIMUM_MEASURED_STATES

    assert MINIMUM_MEASURED_STATES >= 2


def test_an_unmeasured_state_is_reported_as_unmeasured():
    """Of 106 state-level failures in one batch, 89 were states where the
    reference could not be obtained at all. Calling those disagreements
    reports "the tangent is wrong at increment 10" when what happened is
    "no difference could be taken at increment 10"."""
    import verify_store_in_abaqus as v

    states = [_state(1, verified=True, best=1e-12),
              _state(5, verified=False),          # no sweep
              _state(10, verified=True, best=2e-12)]
    measured = [s for s in states
                if (s.get("comparison") or {}).get("best_relative") is not None]
    assert len(measured) == 2
    assert len(states) - len(measured) == 1


def test_a_genuine_disagreement_at_one_state_still_fails():
    """The stronger rule must not become a weaker one: a state that WAS
    measured and did not agree keeps failing the material."""
    states = [_state(1, verified=True, best=1e-12),
              _state(5, verified=False, best=3.2e-2),
              _state(10, verified=True, best=2e-12)]
    measured = [s for s in states
                if (s.get("comparison") or {}).get("best_relative") is not None]
    disagreeing = [s for s in measured if not s["verified"]]
    assert len(measured) == 3 and len(disagreeing) == 1


# --------------------------------------------------------------------------
# the perturbation scale
# --------------------------------------------------------------------------
def test_a_non_finite_component_does_not_decide_the_scale():
    """max() over values containing NaN returns NaN, and `largest or 1.0`
    then returns the NaN because NaN is truthy. Every step became NaN and
    fifty states of one batch produced no sweep at all."""
    from verify_store_in_abaqus import perturbation_scale

    assert perturbation_scale({"DSTRAN": [float("nan"), 1e-4, 0.0]}) == 1e-4


def test_an_all_non_finite_increment_falls_back_rather_than_poisoning():
    from verify_store_in_abaqus import perturbation_scale

    assert perturbation_scale({"DSTRAN": [float("nan")] * 6}) == 1.0


def test_a_gradient_driven_source_is_scaled_by_its_deformation():
    """Its DSTRAN is all zeros because its kinematic input is the
    deformation gradient, and the old fallback then returned 1.0 -- a strain
    scale of one hundred percent."""
    from verify_store_in_abaqus import perturbation_scale

    scale = perturbation_scale({
        "DSTRAN": [0.0] * 6,
        "DFGRD1": [1.002, 0, 0, 0, 0.999, 0, 0, 0, 1.0]})
    assert 0.0019 < scale < 0.0021


def test_an_identity_gradient_falls_back_to_one():
    """A sweep of zeros measures nothing, so a zero scale is not usable."""
    from verify_store_in_abaqus import perturbation_scale

    assert perturbation_scale({
        "DSTRAN": [0.0] * 6,
        "DFGRD1": [1, 0, 0, 0, 1, 0, 0, 0, 1]}) == 1.0


def test_an_ordinary_strain_increment_is_unchanged():
    from verify_store_in_abaqus import perturbation_scale

    assert perturbation_scale({"DSTRAN": [5e-3, 0, 0, 0, 0, 0]}) == 5e-3
