"""What a tangent comparison may conclude from one entry, and what it may not.

The store verification scores a converted tangent by its worst component at a
single step common to the whole matrix, with an entry below 1e-8 of the largest
entry scored against that largest entry instead of against itself. Two things
go wrong with that, and both were measured offline with gfortran against the
ORIGINAL compiled UMAT rather than argued:

* An entry just ABOVE the floor is scored against itself even when the centred
  difference cannot determine it. On ``Jeff97__Programming-Plane-Strain-Plates-
  through-Growth-Under-Body-Forces/.../ArcDown/Th01/BodyForce-Growth-2Stages
  .for`` at pass10's own recorded state, DDSDDE(3,4) = 3.609726e+02 is
  1.803e-08 of a matrix whose largest entry is 2.0023e+10. It decides a verdict
  of 1.772e-05 while the relative Frobenius residual of the same pair is
  2.268e-12.

* The step that determines one entry does not determine another. Entries of
  that tangent span eight decades; the stiff block is best at a relative step
  of 1e-3 and DDSDDE(3,4) is best at 1e-1.

``adjudicate_entries`` reads the same sweep entry by entry and says, for each,
how tightly the ladder pins its own answer down. Nothing here moves a
tolerance, and the tests below pin that: a tangent that is actually wrong is
still caught, at the same tolerance, with the same sweep.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.compare import (  # noqa: E402
    adjudicate_entries,
    compare_tangent,
)
from umat_oti.validation.finite_strain_tangent import as_matrix  # noqa: E402


def _diagonal(value: float, small: float, steps, noise):
    """A sweep over a 2x2: a stiff diagonal and one small off-diagonal entry.

    The small entry carries a fixed absolute noise divided by the step, which
    is what a stress evaluation short of its own precision produces.
    """
    return {step: [[value, small + noise / step], [0.0, value]] for step in steps}


STEPS = (1e-1, 1e-2, 1e-3, 1e-4)


# ---------------------------------------------------------------------------
# The guard: this must not become a way to pass
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a_tangent_that_is_wrong_is_still_wrong():
    """A stiff entry off by 1% is caught, and the resolution does not excuse it.

    The whole risk of adjudicating by resolution is that it becomes a tolerance
    in disguise. It cannot excuse this: the ladder agrees with ITSELF to the
    last bit here, so its resolution is zero and the gap is judged on its own.
    """
    steps = {step: [[100.0, 0.0], [0.0, 100.0]] for step in STEPS}
    oti = [[101.0, 0.0], [0.0, 100.0]]
    verdicts = {(v.row, v.column): v for v in adjudicate_entries(oti, steps)}
    wrong = verdicts[(1, 1)]
    assert wrong.within_resolution is False
    assert wrong.resolution == 0.0
    assert wrong.relative == pytest.approx(1.0 / 101.0, rel=1e-12)

    comparison = compare_tangent(oti, steps)
    assert comparison.resolved_relative == pytest.approx(1.0 / 101.0, rel=1e-12)
    assert comparison.resolved_relative > 1e-6
    assert comparison.resolved_worst_entry == (1, 1)


@pytest.mark.unit
def test_the_worst_component_at_one_step_is_still_reported():
    """The existing verdict is untouched; the new number sits beside it."""
    steps = {step: [[100.0, 0.0], [0.0, 100.0]] for step in STEPS}
    oti = [[101.0, 0.0], [0.0, 100.0]]
    comparison = compare_tangent(oti, steps)
    assert comparison.best.relative == pytest.approx(1.0 / 101.0, rel=1e-12)
    assert "best_relative" in comparison.as_dict()
    assert comparison.as_dict()["resolved_relative"] == pytest.approx(
        1.0 / 101.0, rel=1e-12)


# ---------------------------------------------------------------------------
# What it does excuse
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_an_entry_the_ladder_cannot_pin_down_is_reported_as_unresolved():
    """A small entry whose ladder answers scatter is not evidence of error.

    The ladder's own answers for the off-diagonal entry move by more than the
    gap being scored, so the difference cannot say the OTI value is wrong. It
    is counted as unresolved; the stiff entries, which the ladder does pin
    down, still decide the verdict.
    """
    noisy = _diagonal(100.0, 1.0e-4, STEPS, noise=1.0e-8)
    oti = [[100.0, 1.0e-4], [0.0, 100.0]]
    verdicts = {(v.row, v.column): v for v in adjudicate_entries(oti, noisy)}
    assert verdicts[(1, 2)].within_resolution is True
    assert verdicts[(1, 1)].within_resolution is True

    comparison = compare_tangent(oti, noisy)
    assert comparison.unresolved_entries >= 1
    assert comparison.adjudicated_entries == 4
    # and the single-step reading still sees the scatter
    assert comparison.best.relative > comparison.resolved_relative


@pytest.mark.unit
def test_a_structural_zero_is_not_a_relative_error_of_one():
    """Two rounding residues divided by each other say nothing about either.

    Without the structural-zero rule every entry that is a zero of the matrix
    reports a relative error of 1.000, and the worst-component verdict becomes
    a statement about round-off. The floor is a property of the REFERENCE, so
    that a large bogus value cannot escape the zero test by being large.
    """
    steps = {step: [[1.0e9, 1.0e-9], [1.0e-9, 1.0e9]] for step in STEPS}
    oti = [[1.0e9, -3.0e-9], [2.0e-9, 1.0e9]]
    verdicts = {(v.row, v.column): v for v in adjudicate_entries(oti, steps)}
    zero = verdicts[(1, 2)]
    assert zero.structural_zero is True
    assert zero.within_resolution is True
    assert zero.relative < 1.0e-15

    comparison = compare_tangent(oti, steps)
    assert comparison.resolved_relative < 1.0e-15


@pytest.mark.unit
@pytest.mark.regression
def test_a_large_value_does_not_escape_the_zero_test_by_being_large():
    """The floor is set by the reference, not by max(|reference|,|value|).

    An OTI entry of 1e6 where the reference says zero is a defect. Scoring it
    against max(|reference|,|value|) would divide 1e6 by 1e6 and call the
    relative error 1.0 -- correct here by luck -- but scoring it against the
    reference's own magnitude would divide by 1e-9 and overflow the reading.
    What must not happen is that it is filed as a structural zero and excused.
    """
    steps = {step: [[1.0e9, 1.0e-9], [1.0e-9, 1.0e9]] for step in STEPS}
    oti = [[1.0e9, 1.0e6], [1.0e-9, 1.0e9]]
    verdicts = {(v.row, v.column): v for v in adjudicate_entries(oti, steps)}
    intruder = verdicts[(1, 2)]
    assert intruder.structural_zero is True
    assert intruder.within_resolution is False, (
        "an entry the reference places at zero but the tangent places at 1e6 "
        "is a defect, not a rounding residue")
    comparison = compare_tangent(oti, steps)
    assert comparison.resolved_relative > 1e-6


@pytest.mark.unit
def test_a_ladder_of_fewer_than_two_steps_adjudicates_nothing():
    """One step is not a ladder: it cannot say how well it determined anything."""
    steps = {1e-2: [[100.0, 0.0], [0.0, 100.0]]}
    assert adjudicate_entries([[101.0, 0.0], [0.0, 100.0]], steps) == []
    comparison = compare_tangent([[101.0, 0.0], [0.0, 100.0]], steps)
    assert comparison.adjudicated_entries == 0
    assert comparison.resolved_relative == 0.0


@pytest.mark.unit
def test_a_step_whose_matrix_is_not_finite_is_not_adjudicated():
    """A NaN rung must not become the pair that looks flattest."""
    steps = {1e-1: [[100.0, 0.0], [0.0, 100.0]],
             1e-2: [[100.0, 0.0], [0.0, 100.0]],
             1e-3: [[math.nan, 0.0], [0.0, 100.0]]}
    verdicts = {(v.row, v.column): v for v in adjudicate_entries(
        [[101.0, 0.0], [0.0, 100.0]], steps)}
    assert verdicts[(1, 1)].resolution == 0.0
    assert verdicts[(1, 1)].within_resolution is False


# ---------------------------------------------------------------------------
# The gradient a caller hands in
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.regression
def test_a_gradient_given_as_rows_of_any_sequence_is_read():
    """``as_matrix`` tested for ``list``/``tuple`` and nothing else.

    The corpus hands it a flat list of nine and so never saw this. A caller
    holding the gradient as rows of some other sequence type fell through to
    ``float(row)``, which raises "only 0-dimensional arrays can be converted to
    Python scalars" from inside a perturbation, several frames from anything
    that names a deformation gradient.
    """
    class Row:
        def __init__(self, values):
            self._values = list(values)

        def __iter__(self):
            return iter(self._values)

    rows = [Row([1.0, 2.0, 3.0]), Row([4.0, 5.0, 6.0]), Row([7.0, 8.0, 9.0])]
    assert as_matrix(rows) == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    assert as_matrix([1, 2, 3, 4, 5, 6, 7, 8, 9]) == as_matrix(rows)
    assert as_matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == as_matrix(rows)


@pytest.mark.unit
def test_a_short_gradient_is_padded_rather_than_raising():
    assert as_matrix([1.0, 2.0]) == [[1.0, 2.0, 0.0], [0.0, 0.0, 0.0],
                                     [0.0, 0.0, 0.0]]


# ---------------------------------------------------------------------------
# The reference must not quietly fall back to the seed map
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.regression
def test_a_gradient_driven_reference_is_not_the_seed_map_difference():
    """A reference that shares the seed's definition cannot falsify the seed.

    pass10 recorded ``best_relative`` 8.432916579511807e-10 for
    ``AlexanderJFDR__Hyperelastic_phase_field/umat/NeoHookean_umat.for`` (store
    key b02211fef691bb6a2b174039) and 1.8013861063013595e-06 for
    ``Jeff97/.../From-2D-to-2D-Axe.for`` (key c14b3e1b76081216b57abbf8). Both
    stored conversions predate the finite-strain fix; their emitted seed is the
    additive ``DFGRD1_OTI(i,j) += Ek`` and they carry no Kirchhoff term.

    Built offline with gfortran at pass10's own recorded replay states, those
    two numbers are reproduced to every digit by scoring the stale conversion
    against a reference with NEITHER correction -- 8.4329e-10 and 1.8014e-06.
    Against the corrected reference the same conversions sit at 3.7456e-02 and
    7.5000e-01, and their re-transforms agree to 8.1285e-10 and 2.7275e-08.

    So a verdict was taken on a reference that had neither correction. Running
    ``difference_tangent`` today over those same replay directories applies
    both, so the artifacts do not say which line dropped them -- and the sweep
    field that would have said, ``reference_definition``, is set but never
    serialised into the record.

    What is pinned here is the invariant: with a deformation gradient in hand,
    the assembled reference differs from the raw seed-map difference by exactly
    the Kirchhoff term, on the direct columns and nowhere else. When they are
    equal, the reference has fallen back to differentiating what the seed
    differentiates, and the comparison has lost its power to falsify.
    """
    from umat_oti.abaqus.replay import _as_the_solver_defines_it

    raw = [[10.0, 2.0, 3.0, 0.5], [2.0, 11.0, 4.0, 0.25],
           [3.0, 4.0, 12.0, 0.75], [0.5, 0.25, 0.75, 6.0]]
    stress = [1.0, -2.0, 0.5, 0.125]
    ndi = 3

    corrected = _as_the_solver_defines_it(raw, stress, ndi, correct=True)
    uncorrected = _as_the_solver_defines_it(raw, stress, ndi, correct=False)

    assert uncorrected == raw
    assert corrected != uncorrected, (
        "with a gradient in hand the reference must carry sigma_ij delta_kl; "
        "equal to the seed-map difference means it differentiates whatever the "
        "seed differentiated and cannot falsify it")
    for i in range(4):
        for j in range(4):
            expected = raw[i][j] + (stress[i] if j < ndi else 0.0)
            assert corrected[i][j] == pytest.approx(expected, rel=1e-15)


@pytest.mark.unit
def test_half_a_correction_is_not_applied():
    """Without the push-forward the Kirchhoff term is withheld too.

    Each half alone leaves a residual of the same order as doing nothing, and
    of the opposite sign on the shear rows: applying one would move the
    reference away from both definitions rather than towards either.
    """
    from umat_oti.abaqus.replay import _as_the_solver_defines_it

    raw = [[10.0, 2.0, 0.0], [2.0, 11.0, 0.0], [0.0, 0.0, 6.0]]
    assert _as_the_solver_defines_it(raw, [1.0, 1.0, 1.0], 2, correct=False) == raw
