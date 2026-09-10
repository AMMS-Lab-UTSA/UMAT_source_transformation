"""A state variable moving is not a material yielding.

STATEV can hold a plastic strain -- or time, temperature, a total strain, a
stretch, an orientation, a copied input, or iteration bookkeeping. Measured on
From-2D-to-2D-Axe.for: STATEV(9) rises to 1.05885 under load and falls back to
1.00583 the moment the strain is removed. It is a deformation measure. A rule
that read its movement as "this material has activated and has no elastic
branch" would have called a reversible response irreversible, and then asked
LESS evidence of it than a reversible response deserves.

So the question asked is reversibility, which is observable: when the strain
comes back toward where it started, does the stress come back too?

And where the evidence does not settle it, the answer is
`unknown_state_semantics` -- which gets the FULL requirement, not a reduced
one. Not knowing is not a reason to ask for less.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.state_regime import (IRREVERSIBLE,  # noqa: E402
                                          LINEAR_REVERSIBLE,
                                          NONLINEAR_REVERSIBLE, Regime,
                                          SMOOTH_ELASTIC, SMOOTH_INELASTIC,
                                          UNKNOWN_STATE_SEMANTICS, coverage,
                                          response_character)


def path(strains, stresses, states=None):
    states = states or [[0.0]] * len(strains)
    return [{"STRAN": [s] + [0.0] * 5, "STRESS": [t] + [0.0] * 5,
             "STATEV": list(v)}
            for s, t, v in zip(strains, stresses, states)]


OUT_AND_BACK = (0.0, 1e-4, 2e-4, 1e-4, 0.0)


def test_a_state_that_moves_and_comes_back_is_reversible():
    """The From-2D-to-2D-Axe case: STATEV tracks the stretch."""
    stretches = [[1.0 + s * 100] for s in OUT_AND_BACK]
    character, why = response_character(
        path(OUT_AND_BACK, [1e6 * s for s in OUT_AND_BACK], stretches))
    assert character == LINEAR_REVERSIBLE
    assert "reversible" in why


def test_a_nonlinear_response_that_returns_is_still_reversible():
    stresses = [1e6 * s - 2e9 * s * s for s in OUT_AND_BACK]
    assert response_character(path(OUT_AND_BACK, stresses))[0] == NONLINEAR_REVERSIBLE


def test_stress_left_over_when_the_strain_returns_is_irreversible():
    """This is what a plastic strain looks like, and STATEV is not consulted
    to see it."""
    character, why = response_character(
        path(OUT_AND_BACK, [0.0, 1e5, 2e5, 8e4, 6e4]))
    assert character == IRREVERSIBLE
    assert "kept something" in why


def test_a_path_that_never_returns_settles_nothing():
    """A monotonic ramp cannot show reversibility either way, and saying so
    is the honest answer."""
    ramp = (0.0, 1e-4, 2e-4, 3e-4, 4e-4)
    character, why = response_character(path(ramp, [1e6 * s for s in ramp]))
    assert character == UNKNOWN_STATE_SEMANTICS
    assert "cannot tell them apart" in why


def test_a_small_monotonic_path_is_not_mistaken_for_a_return():
    """The gap is measured against the path's OWN excursion. Against a fixed
    scale, every strain on a small ramp looks like the origin."""
    tiny = (0.0, 1e-9, 2e-9, 3e-9)
    assert response_character(
        path(tiny, [1e6 * s for s in tiny]))[0] == UNKNOWN_STATE_SEMANTICS


def test_too_few_increments_settles_nothing():
    assert response_character(path((0.0, 1e-4), (0.0, 1e2)))[0] == \
        UNKNOWN_STATE_SEMANTICS


# ---- what the character may and may not buy -----------------------------
def _r(kind, increment):
    return Regime(increment=increment, regime=kind, reason="")


def test_unknown_semantics_gets_the_full_requirement_not_a_reduced_one():
    """Not knowing whether a material is irreversible is not a reason to ask
    for less evidence about it."""
    states = [_r(SMOOTH_INELASTIC, 4), _r(SMOOTH_INELASTIC, 7)]
    ok, why = coverage(states, nonlinear=True,
                       character=UNKNOWN_STATE_SEMANTICS)
    assert not ok and "before activation" in why


def test_an_irreversible_material_must_span_both_sides():
    states = [_r(SMOOTH_INELASTIC, 4), _r(SMOOTH_INELASTIC, 7)]
    assert not coverage(states, nonlinear=True, character=IRREVERSIBLE)[0]


def test_a_reversible_nonlinear_material_has_no_branch_to_cross():
    """There is no irreversible regime to reach, so demanding two states
    before one would make it permanently unverifiable -- and that would be a
    limitation of this pipeline, not a property of the model."""
    ok, why = coverage([_r(SMOOTH_INELASTIC, 4), _r(SMOOTH_INELASTIC, 7)],
                       nonlinear=True, character=NONLINEAR_REVERSIBLE)
    assert ok and "REVERSIBLE" in why


def test_even_a_reversible_material_needs_more_than_one_state():
    assert not coverage([_r(SMOOTH_INELASTIC, 4)], nonlinear=True,
                        character=NONLINEAR_REVERSIBLE)[0]
