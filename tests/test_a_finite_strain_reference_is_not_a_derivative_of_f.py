"""DDSDDE under nlgeom is not the derivative of the stress with respect to F.

The finite difference this repository checked a converted tangent against
added the transform's own seed direction straight onto DFGRD1 and called the
result the tangent. Two things are wrong with that, and neither is small.

A perturbation of the deformation gradient produces a velocity gradient
``l = dF . F^-1``. Asking for the strain increment ``eps`` therefore asks for
``dF = eps . F``. And the matrix Abaqus calls DDSDDE is the Jacobian of the
Jaumann rate of the KIRCHHOFF stress divided by J, which is
``d sigma_ij / d eps_kl + sigma_ij delta_kl`` -- so a difference of Cauchy
stresses is one term short.

MEASURED HERE, with no compiler, on the compressible neo-Hookean UMAT from the
Abaqus manual, whose analytic DDSDDE the manual publishes, at
``F = [[1.18, .07, .02], [.03, .93, -.05], [-.01, .04, 1.07]]``. Worst
componentwise relative error of the centred difference against that analytic
tangent:

    reference built as              h=1e-3     h=1e-4     h=1e-5     h=1e-6
    dF = eps            (shipped)   1.360e+01  1.360e+01  1.360e+01  1.360e+01
    dF = eps,     + sigma.delta     1.170e+01  1.170e+01  1.170e+01  1.170e+01
    dF = eps . F                    3.000e+00  3.000e+00  3.000e+00  3.000e+00
    dF = eps . F, + sigma.delta     4.07e-06   4.07e-08   3.17e-09   9.13e-08

Three of the four rows do not move over three decades of step size. That is
what a wrong definition looks like; a truncation error falls as h^2.

MEASURED AGAIN on real Fortran, offline, replaying pass9's own recorded state
through pass9's own compiled replay driver for
``Jeff97__growth-of-shell/.../Example3/Trachea.for`` -- a source whose analytic
DDSDDE is the manual's and whose deviatoric split is the correct one. Against
the author's own DDSDDE: 3.000 at every step for the shipped reference;
7.12e-06 and 2.40e-06 at h=1e-1 and 1e-2 for the corrected one, a relative
Frobenius residual of 2.33e-12 against ``||DDSDDE||_F = 2.82e+09``.

pass9 recorded that state as "tangent not verified".
"""
import math

import pytest

from umat_oti.validation.finite_strain_tangent import (
    as_matrix, corotational_perturbation, kirchhoff_correction, matrix_product,
    strain_direction)


#: The seed the transform injects for a three-dimensional continuum source:
#: a direct component onto one diagonal entry, an engineering shear split in
#: half over the two symmetric off-diagonal entries.
SEED = {1: [(1, 1, 1.0)], 2: [(2, 2, 1.0)], 3: [(3, 3, 1.0)],
        4: [(1, 2, 0.5), (2, 1, 0.5)],
        5: [(1, 3, 0.5), (3, 1, 0.5)],
        6: [(2, 3, 0.5), (3, 2, 0.5)]}

#: Far enough from the identity that the two definitions cannot coincide by
#: accident, and still a state a growth model reaches.
GRADIENT = [[1.18, 0.07, 0.02], [0.03, 0.93, -0.05], [-0.01, 0.04, 1.07]]
C10, D1 = 1.2e5, 4.0e-6


def _determinant(f):
    return (f[0][0] * (f[1][1] * f[2][2] - f[1][2] * f[2][1])
            - f[0][1] * (f[1][0] * f[2][2] - f[1][2] * f[2][0])
            + f[0][2] * (f[1][0] * f[2][1] - f[1][1] * f[2][0]))


def _neo_hookean(f):
    """The Abaqus manual's compressible neo-Hookean Cauchy stress, and b-bar."""
    volume = _determinant(f)
    scale = volume ** (-1.0 / 3.0)
    distorted = [[scale * f[i][j] for j in range(3)] for i in range(3)]
    bbar = [[sum(distorted[i][k] * distorted[j][k] for k in range(3))
             for j in range(3)] for i in range(3)]
    trace = bbar[0][0] + bbar[1][1] + bbar[2][2]
    shear = 2.0 * C10 / volume
    pressure = 2.0 / D1 * (volume - 1.0)
    stress = [shear * (bbar[i][i] - trace / 3.0) + pressure for i in range(3)]
    stress += [shear * bbar[0][1], shear * bbar[0][2], shear * bbar[1][2]]
    return stress, bbar, volume


def _manual_tangent(f):
    """DDSDDE exactly as the Abaqus manual's neo-Hookean UMAT writes it."""
    _stress, bbar, volume = _neo_hookean(f)
    trace = bbar[0][0] + bbar[1][1] + bbar[2][2]
    shear = 2.0 * C10 / volume
    two_thirds = shear * 2.0 / 3.0
    bulk = 2.0 / D1 * (2.0 * volume - 1.0)
    b = [bbar[0][0], bbar[1][1], bbar[2][2],
         bbar[0][1], bbar[0][2], bbar[1][2]]
    d = [[0.0] * 6 for _ in range(6)]
    d[0][0] = two_thirds * (b[0] + trace / 3.0) + bulk
    d[0][1] = -two_thirds * (b[0] + b[1] - trace / 3.0) + bulk
    d[0][2] = -two_thirds * (b[0] + b[2] - trace / 3.0) + bulk
    d[0][3] = two_thirds * b[3] / 2.0
    d[0][4] = two_thirds * b[4] / 2.0
    d[0][5] = -two_thirds * b[5]
    d[1][1] = two_thirds * (b[1] + trace / 3.0) + bulk
    d[1][2] = -two_thirds * (b[1] + b[2] - trace / 3.0) + bulk
    d[1][3] = two_thirds * b[3] / 2.0
    d[1][4] = -two_thirds * b[4]
    d[1][5] = two_thirds * b[5] / 2.0
    d[2][2] = two_thirds * (b[2] + trace / 3.0) + bulk
    d[2][3] = -two_thirds * b[3]
    d[2][4] = two_thirds * b[4] / 2.0
    d[2][5] = two_thirds * b[5] / 2.0
    d[3][3] = shear * (b[0] + b[1]) / 2.0
    d[3][4] = shear * b[5] / 2.0
    d[3][5] = shear * b[4] / 2.0
    d[4][4] = shear * (b[0] + b[2]) / 2.0
    d[4][5] = shear * b[3] / 2.0
    d[5][5] = shear * (b[1] + b[2]) / 2.0
    for i in range(6):
        for j in range(i):
            d[i][j] = d[j][i]
    return d


def _difference(step, *, push_forward, kirchhoff):
    """The centred difference, built the way the flags say."""
    columns = []
    for direction in range(1, 7):
        base = GRADIENT if push_forward else None
        plus = corotational_perturbation(SEED[direction], step, base)
        minus = corotational_perturbation(SEED[direction], -step, base)
        high = [[GRADIENT[r][c] + plus[r * 3 + c] for c in range(3)]
                for r in range(3)]
        low = [[GRADIENT[r][c] + minus[r * 3 + c] for c in range(3)]
               for r in range(3)]
        above, _b, _j = _neo_hookean(high)
        below, _b, _j = _neo_hookean(low)
        columns.append([(a - b) / (2.0 * step) for a, b in zip(above, below)])
    matrix = [[columns[j][i] for j in range(6)] for i in range(6)]
    if kirchhoff:
        stress, _bbar, _volume = _neo_hookean(GRADIENT)
        matrix = kirchhoff_correction(matrix, stress, 3)
    return matrix


def _worst_relative(exact, other):
    """compare_tangent's measure: worst component, near-zero entries floored."""
    scale = max(abs(value) for row in exact for value in row)
    floor = 1.0e-8 * scale
    worst = 0.0
    for i, row in enumerate(exact):
        for j, value in enumerate(row):
            denominator = abs(value) if abs(value) > floor else scale
            worst = max(worst, abs(value - other[i][j]) / denominator)
    return worst


STEPS = (1e-3, 1e-4, 1e-5, 1e-6)


def test_both_corrections_together_recover_the_published_tangent():
    exact = _manual_tangent(GRADIENT)
    errors = [_worst_relative(exact, _difference(h, push_forward=True,
                                                 kirchhoff=True))
              for h in STEPS]
    assert min(errors) < 1e-7, errors
    # A plateau, not one lucky step: at least three of the four agree to
    # better than a part in a hundred thousand.
    assert sum(1 for error in errors if error < 1e-5) >= 3, errors


def test_the_shipped_additive_reference_is_a_different_matrix():
    exact = _manual_tangent(GRADIENT)
    errors = [_worst_relative(exact, _difference(h, push_forward=False,
                                                 kirchhoff=False))
              for h in STEPS]
    assert min(errors) > 1.0, errors
    # And it does not improve with the step, which is how a wrong definition
    # tells itself apart from a truncation error.
    assert (max(errors) - min(errors)) / max(errors) < 1e-3, errors


def test_neither_correction_is_enough_on_its_own():
    exact = _manual_tangent(GRADIENT)
    for push_forward, kirchhoff in ((True, False), (False, True)):
        errors = [_worst_relative(
            exact, _difference(h, push_forward=push_forward,
                               kirchhoff=kirchhoff)) for h in STEPS]
        assert min(errors) > 1.0, (push_forward, kirchhoff, errors)


def test_the_kirchhoff_term_touches_only_the_direct_columns():
    matrix = [[1.0] * 6 for _ in range(6)]
    stress = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    corrected = kirchhoff_correction(matrix, stress, ndi=3)
    for i in range(6):
        for j in range(3):
            assert corrected[i][j] == pytest.approx(1.0 + stress[i])
        for j in range(3, 6):
            assert corrected[i][j] == pytest.approx(1.0)


def test_a_plane_strain_shape_corrects_its_own_direct_columns():
    # NDI=3, NSHR=1: four columns, of which three carry a trace.
    matrix = [[1.0] * 4 for _ in range(4)]
    corrected = kirchhoff_correction(matrix, [7.0, 8.0, 9.0, 0.5], ndi=3)
    assert [row[3] for row in corrected] == [1.0, 1.0, 1.0, 1.0]
    assert [row[0] for row in corrected] == [8.0, 9.0, 10.0, 1.5]


def test_the_push_forward_is_the_seed_direction_times_the_gradient():
    terms = SEED[4]
    step = 3.0e-4
    direction = strain_direction(terms, step)
    expected = matrix_product(direction, as_matrix(GRADIENT))
    got = corotational_perturbation(terms, step, GRADIENT)
    assert got == pytest.approx([v for row in expected for v in row])


def test_without_a_gradient_the_perturbation_is_the_bare_seed():
    # The shipped behaviour is still reachable, and is what a caller with no
    # deformation gradient to hand gets -- never a half-applied correction.
    got = corotational_perturbation(SEED[4], 2.0, None)
    assert got == pytest.approx([0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])


def test_at_the_identity_the_two_perturbations_agree():
    # Which is why the defect was invisible: every synthetic tangent case in
    # this repository drives a gradient that starts at I and advances by
    # additive increments of order 1e-4.
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for direction in range(1, 7):
        bare = corotational_perturbation(SEED[direction], 1e-4, None)
        pushed = corotational_perturbation(SEED[direction], 1e-4, identity)
        assert pushed == pytest.approx(bare)


def test_the_reader_takes_a_gradient_in_either_shape():
    flat = [v for row in GRADIENT for v in row]
    assert as_matrix(flat) == GRADIENT
    assert as_matrix(GRADIENT) == GRADIENT
    assert all(math.isfinite(v) for row in as_matrix([1.0, 2.0]) for v in row)
