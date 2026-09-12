"""The named target, taken apart: three defects, none of them each other.

``Jeff97__General-shape-control-of-shell/Abaqus_Files/2Dto2D/From-2D-to-2D-Axe.for``
is finite throughout, its primal history AGREES between the two builds, and
only its tangent failed. pass9 reported that as "the closest step agreed only
to 1.196e-06, against a tolerance of 1e-06; and the converted build differs
from the author's own DDSDDE by 1.251e+00, so there are two candidate tangents
and the difference is not close enough to either to choose between them" --
one sentence covering three unrelated things.

They are:

1. THE REFERENCE was not the matrix Abaqus asks for. It added the transform's
   own DFGRD1 seed onto DFGRD1, so it measured the same quantity the converted
   build measured and could not falsify it. Fixed; see
   :mod:`umat_oti.validation.finite_strain_tangent`.

2. THE AUTHOR'S OWN DDSDDE is inconsistent with the author's own stress. The
   source computes ``BA1B(k) = DETBA1**(-TWO/THREE)*BA1(k)`` with
   ``DETBA1 = det(b) = J^2``, so its b-bar is ``J^(-4/3) b``; its DDSDDE is the
   Abaqus manual's formula, which is the consistent Jacobian for
   ``b-bar = J^(-2/3) b``. That mismatch is the 7.4% the earlier investigation
   saw, and it is the author's, not the transform's.

3. THE CONVERTED DDSDDE is still not the Abaqus Jacobian after (1) is fixed,
   and the residual is the Kirchhoff term the seed does not carry.

MEASURED, offline, replaying pass9's recorded states through a driver built
from the published source, and again through one with only the six
``DETBA1**(-TWO/THREE)`` occurrences changed to ``DETA1**(-TWO/THREE)``.
Worst componentwise relative error against the corrected reference:

    h                  1e-1      1e-2      1e-3      1e-4      1e-5      1e-6
    author, published  2.0000    2.0000    2.0000    2.0000    2.0000    2.0000
    author, repaired   3.05e-07  6.07e-06  2.77e-08  2.49e-06  3.02e-03  3.06e-02
    converted build    0.7500    0.7500    0.7500    0.7500    0.7500    0.7500

and in relative Frobenius, for the repaired source: 1.44e-11, 8.80e-12,
5.50e-11, 7.30e-10, 7.00e-09, 8.11e-08 -- a four-decade plateau bottoming at
h=1e-2. At the second state (increment 2, point 5) the repaired source reaches
4.74e-09 worst component and 4.68e-12 relative Frobenius.

Two of those three rows do not move with the step at all. A quantity that is
the same to five figures over five decades of step size is not a truncation
error, and the harness's "the closest step agreed only to ..." described both
of them as though a finer ladder would have helped.

So: the answer to "does From-2D-to-2D-Axe pass now that the reference is
corrected" is NO, and it gets slightly worse rather than better -- the
converted tangent's relative Frobenius residual goes from 8.03e-03 against the
old reference to 2.54e-02 against the corrected one, which is
``|sigma|/|DDSDDE| = 2.66e-02`` at that state.

This file tests (2) and (3) with no compiler and no corpus, by writing the
author's own algebra out in Python and asking which deviatoric split his
published DDSDDE is the Jacobian of.
"""
import pytest

from umat_oti.validation.finite_strain_tangent import (
    corotational_perturbation, kirchhoff_correction)


SEED = {1: [(1, 1, 1.0)], 2: [(2, 2, 1.0)], 3: [(3, 3, 1.0)],
        4: [(1, 2, 0.5), (2, 1, 0.5)],
        5: [(1, 3, 0.5), (3, 1, 0.5)],
        6: [(2, 3, 0.5), (3, 2, 0.5)]}

#: The author's own constants: PROPS(1)=906512, PROPS(2)=0.4995, and
#: C10 = E/(4(1+nu)), D1 = 6(1-2nu)/E, exactly as the source computes them.
EMOD, ENU = 906512.0, 0.4995
C10 = EMOD / (4.0 * (1.0 + ENU))
D1 = 6.0 * (1.0 - 2.0 * ENU) / EMOD

#: A state with shear in it, so DDSDDE(4,k) is not a structural zero. The
#: corpus state has b_12 of order 1e-3 of b_11 and the same conclusion.
GRADIENT = [[1.06, 0.04, 0.0], [0.02, 0.97, 0.0], [0.0, 0.0, 1.01]]


def _determinant(f):
    return (f[0][0] * (f[1][1] * f[2][2] - f[1][2] * f[2][1])
            - f[0][1] * (f[1][0] * f[2][2] - f[1][2] * f[2][0])
            + f[0][2] * (f[1][0] * f[2][1] - f[1][1] * f[2][0]))


def _state(f, *, exponent):
    """The author's BA1, BA1B and stress, with his split or the correct one.

    ``exponent`` is what the source raises ``DETBA1 = det(b)`` to. The
    published text uses -2/3, which makes b-bar ``J^(-4/3) b``; -1/3 is the
    split the manual's tangent belongs to and the one Trachea.for uses.
    """
    deta = _determinant(f)                     # DETA1, the author's det(A)
    b = [[sum(f[i][k] * f[j][k] for k in range(3)) for j in range(3)]
         for i in range(3)]
    detb = (b[0][0] * (b[1][1] * b[2][2] - b[1][2] * b[2][1])
            - b[0][1] * (b[1][0] * b[2][2] - b[1][2] * b[2][0])
            + b[0][2] * (b[1][0] * b[2][1] - b[1][1] * b[2][0]))
    scale = detb ** exponent
    bbar = [[scale * b[i][j] for j in range(3)] for i in range(3)]
    trace = bbar[0][0] + bbar[1][1] + bbar[2][2]
    shear = 2.0 * C10 / deta
    pressure = 2.0 / D1 * (deta - 1.0)
    stress = [shear * (bbar[i][i] - trace / 3.0) + pressure for i in range(3)]
    stress += [shear * bbar[0][1], shear * bbar[0][2], shear * bbar[1][2]]
    return stress, bbar, trace, deta


def _authors_tangent(f, *, exponent):
    """DDSDDE exactly as From-2D-to-2D-Axe.for writes it, on whatever b-bar
    the routine computed."""
    _stress, bbar, trace, deta = _state(f, exponent=exponent)
    shear = 2.0 * C10 / deta
    eg23 = shear * 2.0 / 3.0
    ek = 2.0 / D1 * (2.0 * deta - 1.0)
    b = [bbar[0][0], bbar[1][1], bbar[2][2],
         bbar[0][1], bbar[0][2], bbar[1][2]]
    d = [[0.0] * 6 for _ in range(6)]
    d[0][0] = eg23 * (b[0] + trace / 3.0) + ek
    d[0][1] = -eg23 * (b[0] + b[1] - trace / 3.0) + ek
    d[0][2] = -eg23 * (b[0] + b[2] - trace / 3.0) + ek
    d[0][3] = eg23 * b[3] / 2.0
    d[1][1] = eg23 * (b[1] + trace / 3.0) + ek
    d[1][2] = -eg23 * (b[1] + b[2] - trace / 3.0) + ek
    d[1][3] = eg23 * b[3] / 2.0
    d[2][2] = eg23 * (b[2] + trace / 3.0) + ek
    d[2][3] = -eg23 * b[3]
    d[3][3] = shear * (b[0] + b[1]) / 2.0
    d[0][4] = eg23 * b[4] / 2.0
    d[0][5] = -eg23 * b[5]
    d[1][4] = -eg23 * b[4]
    d[1][5] = eg23 * b[5] / 2.0
    d[2][4] = eg23 * b[4] / 2.0
    d[2][5] = eg23 * b[5] / 2.0
    d[3][4] = shear * b[5] / 2.0
    d[3][5] = shear * b[4] / 2.0
    d[4][4] = shear * (b[0] + b[2]) / 2.0
    d[4][5] = shear * b[3] / 2.0
    d[5][5] = shear * (b[1] + b[2]) / 2.0
    # The author's own symmetrisation loop, which is where the wrong split
    # shows: with it, DDSDDE(4,1) is forced to equal DDSDDE(1,4).
    for i in range(6):
        for j in range(i):
            d[i][j] = d[j][i]
    return d


def _corrected_reference(f, step, *, exponent):
    """The Jacobian Abaqus defines, by centred difference of that stress."""
    columns = []
    for direction in range(1, 7):
        plus = corotational_perturbation(SEED[direction], step, f)
        minus = corotational_perturbation(SEED[direction], -step, f)
        high = [[f[r][c] + plus[r * 3 + c] for c in range(3)] for r in range(3)]
        low = [[f[r][c] + minus[r * 3 + c] for c in range(3)] for r in range(3)]
        above, _b, _t, _j = _state(high, exponent=exponent)
        below, _b, _t, _j = _state(low, exponent=exponent)
        columns.append([(a - b) / (2.0 * step) for a, b in zip(above, below)])
    matrix = [[columns[j][i] for j in range(6)] for i in range(6)]
    stress, _b, _t, _j = _state(f, exponent=exponent)
    return kirchhoff_correction(matrix, stress, 3)


def _worst(exact, other):
    scale = max(abs(v) for row in exact for v in row)
    floor = 1.0e-8 * scale
    worst, where = 0.0, None
    for i, row in enumerate(exact):
        for j, value in enumerate(row):
            denominator = abs(value) if abs(value) > floor else scale
            error = abs(value - other[i][j]) / denominator
            if error > worst:
                worst, where = error, (i + 1, j + 1)
    return worst, where


PUBLISHED = -2.0 / 3.0          # DETBA1**(-TWO/THREE), what the source says
REPAIRED = -1.0 / 3.0           # det(b)**(-1/3) == J**(-2/3), the manual's
STEPS = (1e-3, 1e-4, 1e-5)


def test_the_authors_tangent_is_the_jacobian_of_the_split_he_did_not_use():
    errors = [_worst(_authors_tangent(GRADIENT, exponent=REPAIRED),
                     _corrected_reference(GRADIENT, h, exponent=REPAIRED))[0]
              for h in STEPS]
    assert min(errors) < 1e-6, errors
    assert sum(1 for e in errors if e < 1e-4) >= 2, errors


def test_with_the_split_he_did_use_his_tangent_is_a_factor_out():
    errors = [_worst(_authors_tangent(GRADIENT, exponent=PUBLISHED),
                     _corrected_reference(GRADIENT, h, exponent=PUBLISHED))[0]
              for h in STEPS]
    assert min(errors) > 1.0, errors
    # And it does not move with the step: a factor, not a truncation error.
    assert (max(errors) - min(errors)) / max(errors) < 1e-3, errors


def test_the_defect_is_in_the_shear_rows_and_is_a_sign():
    """DDSDDE(4,1) comes out +280 where the author's symmetrisation puts -280.

    With the published split the shear row of the true Jacobian is not the
    transpose of the shear column, so forcing ``DDSDDE(K1,K2)=DDSDDE(K2,K1)``
    writes the wrong number into three entries. At the pass9 state (increment
    2, element 1, point 5) the author has -2.804459e+02 at both (1,4) and
    (4,1), while the corrected reference gives -2.804459e+02 at (1,4) and
    +2.804459e+02 at (4,1).
    """
    exact = _authors_tangent(GRADIENT, exponent=PUBLISHED)
    reference = _corrected_reference(GRADIENT, 1e-4, exponent=PUBLISHED)
    _worst_value, where = _worst(exact, reference)
    assert where[0] in (4, 5, 6), where
    assert where[1] in (1, 2, 3), where
    # the column is right even though the row is not
    assert exact[0][3] == pytest.approx(reference[0][3], rel=1e-4)


def test_the_repaired_split_makes_the_matrix_symmetric_again():
    reference = _corrected_reference(GRADIENT, 1e-4, exponent=REPAIRED)
    for i in range(6):
        for j in range(6):
            scale = max(abs(reference[i][j]), abs(reference[j][i]), 1.0)
            assert abs(reference[i][j] - reference[j][i]) / scale < 1e-5, (i, j)


def test_the_published_split_makes_it_unsymmetric():
    reference = _corrected_reference(GRADIENT, 1e-4, exponent=PUBLISHED)
    gaps = [abs(reference[i][j] - reference[j][i])
            / max(abs(reference[i][j]), abs(reference[j][i]), 1.0)
            for i in range(6) for j in range(i)]
    assert max(gaps) > 1.0, max(gaps)


def test_both_splits_give_a_stress_neither_build_disputes():
    """Which is why the primal agreed and only the tangent failed.

    The split is wrong in the same way in both builds -- the transform carries
    the author's expression through unchanged -- so the stress histories are
    identical and the disagreement lives entirely in DDSDDE.
    """
    published, _b, _t, _j = _state(GRADIENT, exponent=PUBLISHED)
    repaired, _b, _t, _j = _state(GRADIENT, exponent=REPAIRED)
    assert published != pytest.approx(repaired), "the split does change the stress"
    # but each is a perfectly definite function of F, which is all a primal
    # comparison between two builds of the SAME source can ask.
    again, _b, _t, _j = _state(GRADIENT, exponent=PUBLISHED)
    assert published == pytest.approx(again, rel=0, abs=0)
