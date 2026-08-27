"""Sharpening the reference, rather than widening what is asked of the value.

Five m6_fcc entries had the generated derivative and the centred-difference
reference agreeing to about 3e-6 relative, while the reference's own residual
was the same size as the gap between them. The reference could neither confirm
nor deny those entries. The only honest way to settle such a row is to make the
reference better; loosening the tolerance would settle it by assumption.
"""
from __future__ import annotations

import random

import pytest

from umat_oti.validation.reference_resolution import (
    ResolutionLadder, converged_value, richardson,
)

TRUE = 2.0


def _ladder(steps, factory) -> ResolutionLadder:
    ladder = ResolutionLadder(props_index=1, array="DSIGMA_DP", steps=tuple(steps))
    ladder.values[(1, 1)] = tuple(factory(h) for h in steps)
    return ladder


def _halving(count: int = 7, start: float = 1e-2):
    return [start / 2 ** k for k in range(count)]


def test_it_removes_the_leading_truncation_term():
    """A pure h^2 error is exactly what Richardson cancels."""
    ladder = _ladder(_halving(), lambda h: TRUE + 0.37 * h * h)
    value, step, residual = richardson(ladder, 1, 1)
    assert value == pytest.approx(TRUE, abs=1e-12)
    assert residual < 1e-12
    assert step > 0


def test_it_beats_the_plain_estimate_when_round_off_is_present():
    random.seed(7)

    def sampled(h):
        return (TRUE + 0.37 * h * h
                + random.uniform(-1, 1) * 2.2e-16 * 5.0 / (2 * h))

    ladder = _ladder(_halving(), sampled)
    bounds = ladder.window(1, 1)
    series = ladder.values[(1, 1)]
    chunk = series[bounds[0]:bounds[1]]
    plain_residual = max(chunk) - min(chunk)

    value, _step, residual = richardson(ladder, 1, 1)
    assert abs(value - TRUE) < 1e-10
    assert residual < plain_residual


def test_the_chosen_estimate_is_whichever_pins_the_value_down_better():
    """Never taken unconditionally: cancelling truncation amplifies round-off."""
    ladder = _ladder(_halving(), lambda h: TRUE + 0.37 * h * h)
    chosen = converged_value(ladder, 1, 1)
    extrapolated = richardson(ladder, 1, 1)
    assert chosen[2] <= extrapolated[2]


def test_a_ladder_dominated_by_noise_falls_back_to_the_plain_estimate():
    random.seed(3)
    # Steps far below the cancellation floor: nothing to extrapolate from.
    ladder = _ladder([1e-13 / 2 ** k for k in range(5)],
                     lambda h: TRUE + random.uniform(-1, 1) * 1e-3)
    chosen = converged_value(ladder, 1, 1)
    extrapolated = richardson(ladder, 1, 1)
    assert chosen[2] <= extrapolated[2], \
        "a worse extrapolation was taken over the plain estimate"


@pytest.mark.parametrize("steps", [(), (1e-2,), (1e-2, 5e-3)])
def test_a_ladder_too_short_to_extrapolate_returns_nothing(steps):
    ladder = _ladder(steps, lambda h: TRUE + h * h)
    assert richardson(ladder, 1, 1) is None


def test_a_non_monotone_ladder_is_refused_rather_than_extrapolated():
    """The formula assumes each step is finer than the one before it."""
    ladder = _ladder([1e-3, 1e-2, 1e-4], lambda h: TRUE + h * h)
    assert richardson(ladder, 1, 1) is None


def test_an_absent_entry_returns_nothing():
    ladder = _ladder(_halving(), lambda h: TRUE + h * h)
    assert richardson(ladder, 9, 9) is None
    assert converged_value(ladder, 9, 9) is None


def test_it_never_invents_a_value_for_an_empty_ladder():
    ladder = ResolutionLadder(props_index=1, array="DSIGMA_DP", steps=())
    assert converged_value(ladder, 1, 1) is None
