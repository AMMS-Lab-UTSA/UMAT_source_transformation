"""A finite-difference reference has an accuracy of its own, and it is measured.

``fd_noise_floor`` models cancellation only. A centred difference also carries
truncation error of order ``h^2 f'''``, and for a stiff model that term dominates
wherever cancellation is still small. Judging against the cancellation term alone
reports disagreements the reference cannot actually adjudicate.
"""

from __future__ import annotations

import pytest

from umat_oti.validation.reference_resolution import (
    DEFAULT_LADDER,
    ResolutionLadder,
    converged_value,
    select_reference_step,
)


def _ladder(values, steps=(1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7)):
    ladder = ResolutionLadder(props_index=1, array="DSIGMA_DP", steps=tuple(steps))
    ladder.values[(1, 1)] = tuple(values)
    return ladder


#: The measured m6_fcc curve for d(SDV9)/d(C11): textbook h^2 convergence onto
#: the OTI value, then cancellation.
M6_FCC_SERIES = (
    1.9614371681501020e-06, 1.9873162345095723e-06, 1.9875864462408619e-06,
    1.9875891495965994e-06, 1.9875891773880570e-06, 1.9875891863249805e-06,
)
M6_FCC_OTI = 1.9875891768692679e-06


def test_default_ladder_spans_truncation_and_cancellation():
    assert DEFAULT_LADDER[0] > DEFAULT_LADDER[-1]
    assert len(DEFAULT_LADDER) >= 4


def test_ladder_spacing_samples_the_turning_point():
    """The ladder has to land on the turn, not step over it.

    Every estimate in this module is read off consecutive ladder entries, so
    the spacing decides whether the turning point is ever evaluated. Between
    two rungs a ratio ``r`` apart a centred difference changes its truncation
    by ``r**2`` and its round-off by ``r``; once Richardson has removed the
    leading term those become ``r**4`` and ``r``. At the decade spacing this
    module used to ship, ``r**4`` is 1e4 per rung: the minimum of the
    extrapolated sequence falls between two rungs and is never evaluated, the
    flattest pair straddles it, and the gap between two straddling entries
    reports how far apart they are without saying which one is nearer.

    Too fine is its own failure and the bound below is two-sided. As ``r``
    approaches 1 consecutive answers separate by less than the round-off
    between them, and the closest pair becomes a coincidence down in the
    cancellation region rather than a plateau -- exactly what ``resolution``
    exists to avoid.
    """
    ratios = {round(DEFAULT_LADDER[i] / DEFAULT_LADDER[i + 1], 9)
              for i in range(len(DEFAULT_LADDER) - 1)}
    assert len(ratios) == 1, (
        f"richardson() extrapolates only on a constant ratio; got {sorted(ratios)}")
    ratio = ratios.pop()
    assert ratio ** 4 <= 100.0 + 1e-6, (
        f"ratio {ratio:g} moves the extrapolated truncation by {ratio ** 4:g} per "
        "rung, which steps over the turning point instead of sampling it")
    assert ratio >= 3.0, (
        f"ratio {ratio:g} is fine enough that consecutive answers differ by less "
        "than their own round-off, and the flattest pair becomes a coincidence")


def test_ladder_refines_the_decade_rungs_rather_than_moving_them():
    """Refining the spacing must add evidence, not relocate the measurement.

    Keeping every decade rung means the finer ladder cannot reach a different
    answer by having looked somewhere else; it can only reach one by having
    looked in more places.
    """
    for decade in (1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7):
        assert any(abs(step / decade - 1.0) < 1e-9 for step in DEFAULT_LADDER), \
            f"the decade rung {decade:g} is no longer evaluated"


def test_converged_value_beats_the_default_step_on_the_measured_curve():
    """Regression: 71 rows were reported as disagreements that were not.

    At the fixed relative step of 1e-4 this derivative carries 1.4e-6 of
    truncation error, enough to fail a 1e-6 comparison. The same derivative
    agrees with the OTI value far better once the step is chosen by convergence.
    """
    ladder = _ladder(M6_FCC_SERIES)
    at_default = abs(M6_FCC_SERIES[2] - M6_FCC_OTI) / abs(M6_FCC_OTI)
    assert at_default > 1e-6, "the fixture no longer reproduces the failure"

    value, step, uncertainty = converged_value(ladder, 1, 1)
    assert abs(value - M6_FCC_OTI) / abs(M6_FCC_OTI) < at_default
    assert step < 1e-4
    assert uncertainty > 0.0


def test_selection_ignores_an_accidental_coincidence_in_the_noise():
    """Two steps deep in cancellation can coincide and look perfectly converged.

    What must not happen is that the coincident pair down in the noise is
    mistaken for convergence. The assertion is therefore about which part of
    the ladder the estimate comes from, not about a particular arithmetic:
    a plain midpoint and a Richardson extrapolation of the same plateau give
    slightly different numbers, and both are correct answers to this question.
    """
    series = (1.0, 0.5, 0.30, 0.3000001, 0.9, 0.9)   # last pair identical by chance
    ladder = _ladder(series)
    value, step, uncertainty = converged_value(ladder, 1, 1)
    assert 0.28 < value < 0.32, f"the estimate came from the noise, not the plateau: {value}"
    assert not (0.85 < value < 0.95), "the coincident noise pair was taken as converged"
    assert uncertainty > 0.0, "a zero uncertainty would claim infinite precision"


def test_selection_does_not_stop_on_an_early_wobble():
    """Breaking at the first non-decreasing gap returns a far too coarse step.

    That failure left one m6_fcc row judged at a relative step of 1e-3 with a
    3e-3 relative error and called a disagreement.
    """
    series = (5.0, 4.0, 4.5, 4.02, 4.010, 4.0105)
    ladder = _ladder(series)
    _value, step, _uncertainty = converged_value(ladder, 1, 1)
    assert step <= 1e-4, f"stopped early and chose {step:g}"


def test_a_short_ladder_reports_nothing_rather_than_guessing():
    ladder = _ladder((1.0,), steps=(1e-4,))
    assert converged_value(ladder, 1, 1) is None
    assert select_reference_step(ladder) is None


def test_group_selection_aggregates_over_entries():
    ladder = ResolutionLadder(props_index=1, array="DSIGMA_DP",
                              steps=(1e-2, 1e-3, 1e-4, 1e-5))
    ladder.values[(1, 1)] = (1.0, 0.5, 0.30, 0.3001)
    ladder.values[(1, 2)] = (2.0, 1.0, 0.60, 0.6002)
    assert select_reference_step(ladder) in (1e-4, 1e-5)
