"""What DDSDDE means when the kinematic input is the deformation gradient.

A UMAT run under ``nlgeom`` is handed ``DFGRD1`` and asked for ``DDSDDE``.
``DDSDDE`` is not the derivative of the stress with respect to ``DFGRD1``. It is
the Jacobian associated with the Jaumann rate of the Kirchhoff stress divided
by J, expressed on the corotational logarithmic strain increment::

    DDSDDE(ij,kl) = d sigma_ij / d eps_kl  +  sigma_ij * delta_kl

and the strain increment ``eps`` is related to a perturbation of the
deformation gradient by ``dF = eps . F``, not by ``dF = eps``.

Both halves of that statement were missing from the finite difference this
repository checked converted tangents against, and both are measurable.

MEASURED, offline, by replaying pass9's own recorded states through pass9's
own compiled replay driver
(``corpus_run/pass9/work/b3cadd7c558a0603f5000dff/replay/state{0,1}``,
``Jeff97__growth-of-shell/.../Example3/Trachea.for``, whose analytic DDSDDE is
the Abaqus manual's neo-Hookean tangent and whose deviatoric split is the
correct one). Worst-component relative error of the centred difference against
that author's own analytic DDSDDE, at ``h`` relative to the increment:

    reference built as              h=1e-1     h=1e-2     h=1e-3
    dF = eps            (shipped)   3.000      3.000      3.000
    dF = eps,     + sigma.delta     7.97e-03   7.97e-03   7.97e-03
    dF = eps . F                    3.000      3.000      3.000
    dF = eps . F, + sigma.delta     7.12e-06   2.40e-06   9.74e-04

Neither correction works alone: each leaves the same hard factor of three,
unmoved by four decades of step size, which is what a wrong definition looks
like and what a truncation error does not. Together they reproduce a tangent
nobody in this repository wrote to 2.40e-06 on the worst component and to
6.56e-03 in Frobenius against ``||DDSDDE||_F = 2.82e+09`` -- a relative
Frobenius residual of 2.33e-12, at a state the harness had recorded as
"tangent not verified".

Confirmed at a second state of the same source (1.26e-05 worst component,
1.42e-11 relative Frobenius) and on a second source: From-2D-to-2D-Axe.for
with its deviatoric split repaired agrees to 4.74e-09.

And confirmed by an author who wrote the same perturbation into his own UMAT.
``keisuke58__pde-fem-biofilm/umat_biofilm_visco_phase2.f`` computes its own
tangent by differences and builds the perturbed gradient as
``F_pert(II,K) = F(II,K) + h*F(II,K)`` for a direct component and as the
half-weighted symmetric pair for an engineering shear -- ``dF = eps . F``,
written out by hand. That source's shear tangent is reproduced by the
reference here to 4.03e-11; its direct block sits 3.9e-03 away, which is
``|sigma|/|DDSDDE|`` at that state, because the author left the Kirchhoff term
out.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence


def matrix_product(left: Sequence[Sequence[float]],
                   right: Sequence[Sequence[float]]) -> list[list[float]]:
    """The 3x3 product ``left . right``."""
    return [[sum(left[i][k] * right[k][j] for k in range(3)) for j in range(3)]
            for i in range(3)]


def as_matrix(nine: Sequence) -> list[list[float]]:
    """A 3x3, from either nine numbers row-major or three rows of three.

    Both shapes are in circulation here: the replay driver's state file holds
    the gradient flat, and a caller that has already split it holds rows. A
    reader that accepted only one of them would raise on the other at the
    moment it was asked to correct a perturbation, which is the moment it must
    not fail quietly or loudly.
    """
    rows = list(nine)
    if rows and isinstance(rows[0], (list, tuple)):
        flat = [float(value) for row in rows for value in row]
    else:
        flat = [float(value) for value in rows]
    if len(flat) < 9:
        flat = flat + [0.0] * (9 - len(flat))
    return [flat[row * 3:row * 3 + 3] for row in range(3)]


def strain_direction(terms: Iterable[tuple], step: float) -> list[list[float]]:
    """One seeded direction as a 3x3 strain increment, at a finite size.

    ``terms`` are the ``(row, column, coefficient)`` triples the transform
    seeded for this Voigt direction, one-based. The half-weights the seed
    carries on the two off-diagonal positions are what makes an engineering
    shear an engineering shear, and they are used exactly as seeded.
    """
    matrix = [[0.0] * 3 for _ in range(3)]
    for row, column, coefficient in terms:
        matrix[int(row) - 1][int(column) - 1] += float(coefficient) * float(step)
    return matrix


def corotational_perturbation(terms: Iterable[tuple], step: float,
                              gradient: Optional[Sequence[float]] = None,
                              ) -> list[float]:
    """``dF`` for one direction, row-major, as Abaqus's strain increment means it.

    With no ``gradient`` this is the seed matrix itself -- the shipped
    behaviour, kept so a caller that has no deformation gradient to hand still
    gets something rather than nothing.

    With one, the answer is ``eps . F``. The velocity gradient a perturbation
    of the deformation gradient produces is ``l = dF . F^-1``; asking for
    ``l = eps`` therefore asks for ``dF = eps . F``. Adding ``eps`` straight
    onto ``F`` instead asks for ``l = eps . F^-1``, which is the same thing
    only when ``F`` is the identity -- an error of order ``||F - I||``, 0.2%
    at the state measured in this module's docstring and growing with the
    deformation.
    """
    direction = strain_direction(terms, step)
    if gradient is None:
        return [value for row in direction for value in row]
    product = matrix_product(direction, as_matrix(gradient))
    return [value for row in product for value in row]


def kirchhoff_correction(matrix: Sequence[Sequence[float]],
                         stress: Sequence[float], ndi: int = 3,
                         ) -> list[list[float]]:
    """``d sigma_ij / d eps_kl`` raised to the Jacobian Abaqus asks for.

    ``C_ijkl = d sigma_ij / d eps_kl + sigma_ij delta_kl``. In Voigt storage
    ``delta_kl`` is one for the ``ndi`` direct columns and zero for the shear
    columns, so the whole correction is: add the stress component of the row
    to every direct column of that row.

    It is not a small term. It is ``|sigma|/|DDSDDE|`` on the direct block --
    1.3% at the state in this module's docstring -- and on the shear rows,
    where the derivative of the shear stress with respect to a direct strain
    is itself of order the shear stress, it is the difference between
    ``+280.4`` and ``-280.4``.
    """
    rows = [list(row) for row in matrix]
    direct = max(0, int(ndi))
    for i, row in enumerate(rows):
        if i >= len(stress):
            continue
        shift = float(stress[i])
        for j in range(min(direct, len(row))):
            row[j] += shift
    return rows


def is_step_independent(sweep: dict, *, tolerance: float = 1.0e-3,
                        minimum_steps: int = 3) -> bool:
    """Does the error refuse to move when the step size does?

    ``sweep`` maps a step size to an error. A centred difference that is
    measuring something has an error that FALLS as the step shrinks until
    cancellation takes over and it rises again. An error that is the same
    number at every step size is not a truncation error at all: it is a fixed
    disagreement the difference cannot see past, and reporting its smallest
    value as "the closest step agreed only to X" describes it as though a
    smaller step might have helped.

    MEASURED on ``keisuke58__pde-fem-biofilm/umat_biofilm_visco_phase2.f``,
    pass9 row ``0eb82e2b175e1d50122acefb``: worst-component relative error
    3.2003e-02 at every one of the eight step sizes from 1e-1 to 1e-8, the
    same to five figures. The converted build returns a DDSDDE whose three
    shear rows are identically zero, and 3.2e-02 is the shear stiffness
    divided by the size of the matrix. The row was recorded as "the closest
    step agreed only to 3.200e-02", which reads as a convergence failure.

    Compared against the four Jeff97 rows in the same batch, whose errors move
    over four decades across the same ladder, this separates the two cleanly.
    """
    values = [float(value) for value in sweep.values()
              if value is not None and math.isfinite(float(value))]
    if len(values) < max(2, int(minimum_steps)):
        return False
    largest, smallest = max(values), min(values)
    if largest <= 0.0:
        return False
    return (largest - smallest) / largest <= float(tolerance)


def plateau_steps(sweep: dict, *, width: float = 10.0) -> list[float]:
    """The step sizes whose error is within ``width`` of the smallest.

    The shape of the sweep, not the value of any one point in it. A tangent
    that agrees at one step and nowhere near it has not been measured; the
    caller decides how many steps it wants, this says which ones qualify.
    """
    usable = {float(step): float(value) for step, value in sweep.items()
              if value is not None and math.isfinite(float(value))}
    if not usable:
        return []
    best = min(usable.values())
    if best <= 0.0:
        return sorted(step for step, value in usable.items() if value <= 0.0)
    return sorted(step for step, value in usable.items()
                  if value <= width * best)
