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

INDEPENDENTLY CONFIRMED
-----------------------

The definition above was implemented in the transform by another agent. What
follows checks that implementation against sources it was not developed on,
spanning different constitutive kinds, with both binaries built offline by
gfortran and sharing no code: the reference is the author's own file compiled
as it stands, the value under test is the transform store's emitted Fortran,
and the only thing in common is a driver that contains no constitutive law.

Relative Frobenius residual of the converted DDSDDE against a centred
difference of the ORIGINAL compiled routine, over a ladder of absolute step
sizes from 1e-2 to 1e-8. The three ablations are computed from the same stress
evaluations, so a residual that does not move between them is a statement
about the definition rather than about the arithmetic::

  source                                     kind          dF=eps   dF=eps    dF=eps.F  dF=eps.F  minimum at  plateau
                                                           no K     +K        no K      +K
  AlexanderJFDR/NeoHookean_umat.for          hyperelastic  1.15e-01 5.03e-02  7.95e-02  9.69e-11  h=1e-5      1e-5,1e-6
  mholla/umat_iso_stretch.f  (no growth)     growth        1.06e-01 5.17e-02  6.97e-02  1.11e-10  h=1e-6      1e-5,1e-6
  mholla/umat_iso_stretch.f  (growing)       growth        2.74e-01 7.11e-02  2.09e-01  3.79e-11  h=1e-5      1e-5,1e-6
  abuganza/UMAT_Tissue_3d.f                  damage        9.10e-02 5.25e-02  5.47e-02  8.27e-11  h=1e-6      1e-6
  abuganza/UMAT_Tissue_2d_plane_strain.f     2D, NTENS=4   8.52e-02 6.10e-02  4.38e-02  8.98e-11  h=1e-6      1e-5..1e-7
  keisuke58/umat_biofilm_visco_phase2.f      viscoelastic  8.78e-02 5.07e-02  5.36e-02  2.52e-11  h=1e-5      1e-5
  mholla/umat_transverse.f   (growing)       anisotropic   7.99e-01 1.22e-01  5.73e-01  6.25e-11  h=1e-5      1e-5,1e-6
  mholla__BMMB24/umat_transverseIsotropicStretch.f
                                             anisotropic   9.19e-02 5.05e-02  5.85e-02  1.36e-10  h=1e-6      1e-5,1e-6

Nine states of eight sources across six constitutive kinds. In every one the
three wrong definitions are flat to four significant figures over six decades
of step size, and the right one falls as ``h^2`` for three decades, turns at a
genuine minimum, and rises again as cancellation takes over. The converted
stress is unchanged throughout: worst relative difference from the original
ranges from exactly 0 to 1.06e-09.

That the three wrong columns are FLAT is the whole point. A step-independent
residual is a different function, not a truncation error, and reporting its
smallest value as "the closest step agreed only to X" describes a wrong
formula as a convergence failure. See :func:`is_step_independent`.

WHERE THE STATES CAME FROM, AND WHY THEY ARE SMOOTH
---------------------------------------------------

A centred difference across a yield surface, a damage onset or any other
corner returns the slope of a chord, which is not a derivative of anything and
which no step size makes converge. Every state above was established smooth by
measurement, not by assumption, on two independent signatures:

* The forward and backward one-sided slopes of a C^1 function differ by O(h)
  and so fall by ten per decade of h. Reported as
  ``||D+ - D-|| / ||D_centred||`` per direction; across all nine states above
  the largest decay ratio is 0.100, i.e. exactly one decade per decade.
* Any internal variable that is a discrete decision is identical either side
  of the state. A continuous one differs by O(h); dividing the two-sided gap
  by h separates them, with a floor at 1e-10 of the variable's own size so
  that a variable whose two sides agree to the last bit -- for a pure shear,
  ``det(F +/- h eps.F) = det(F)(1 - h^2/4 ...)`` -- is not flagged.

The growth and damage laws were run on BOTH sides of their criteria where
they have one: ``umat_iso_stretch.f`` at ``phi_g = detF/theta_g - tcr`` equal
to -4.32e-02 and to +8.87e-02, and ``umat_transverse.f`` with both its area
and fibre criteria active. ``UMAT_Tissue_3d.f`` has two branches -- the
recruitment cut-off at ``lam < gama = 0.66`` and the memory update at
``lam > lam_m`` -- and at the state used every fibre stretch is near 1, while
the memory enters the stress only through the OLD ``lam_m``, a frozen input.

A smoothness test that never fires proves nothing, so it was run on a corner.
``umat_iso_stretch.f`` at ``det F = 1.1000``, which puts ``phi_g`` exactly on
zero::

  direction                1   2   3   (cross the branch)    4   5   6   (do not)
  ||D+ - D-||/||D_c||   5.81e-01                          6.16e-04
  at h ten times smaller 5.80e-01                          6.16e-05
  and ten times smaller  5.79e-01                          6.16e-06

The three directions that change ``det F`` straddle the corner and their
one-sided slopes stay a fixed distance apart over three decades; the three
shears do not change ``det F`` to first order, stay on one branch, and decay
by exactly ten per decade. The residual ladder at that state is flat at
2.63e-01 with a ratio of 1.01 between its largest and smallest entry -- no
minimum anywhere in it. The test localises the corner to the directions that
cross it.

WHAT NTENS=3 MEANS, AND WHAT THE SEED ASSUMES IT MEANS
------------------------------------------------------

Two of the eight sources above are not three-dimensional, and the tensor size
alone does not say which Voigt components a UMAT is being handed. NTENS=4 is
plane strain: NDI=3, NSHR=1, components 11, 22, 33, 12. NTENS=3 is plane
stress: NDI=2, NSHR=1, components 11, 22, 12 -- there is no 33 column.

The seed the transform emits maps directions 1..3 onto the three diagonal
positions whenever ``min(ntens, 3)`` allows, so at NTENS=3 it seeds direction
3 as ``E33``. For plane stress the third direction is the engineering shear,
which wants half on ``(1,2)`` and half on ``(2,1)``. Read back from the only
NTENS=3 entry in the corpus,
``abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_stress.f`` (store key
368b46da86f02422635ea06e), the emitted seed is::

    {1: ((1, 1, 1.0),), 2: ((2, 2, 1.0),), 3: ((3, 3, 1.0),)}

and that source's own author wrote, at the line that packs its answer for
Abaqus, "I am treating sigma(3) as sigma12". So column 3 of that converted
tangent is a derivative with respect to an out-of-plane stretch where the
solver asked for one with respect to an in-plane shear.

The two halves of the correction disagree with each other about this: the
Kirchhoff term asks ``direct_component_count_expression`` for the number of
direct components and gets ``NDI``, which is 2 at run time and right, while
the seed has already assumed 3. Nothing here is measured against a run,
because that entry is blocked at ``derivative_truncated`` before any tangent
comparison happens -- 42 assignments take the real part of an expression that
carries a seed -- so the seed defect has never reached a verdict and is
recorded rather than demonstrated.

NTENS=4 is not affected: ``(1,1), (2,2), (3,3)`` and a half-weighted ``(1,2)``
pair is exactly plane strain, and the plane-strain row of the table above
confirms it at 8.98e-11.
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

    A row is anything that is not a number, rather than a ``list`` or a
    ``tuple`` specifically. The narrower test passed the corpus, which hands
    this a flat list of nine, and failed on a caller holding the gradient as
    rows of some other sequence type: those rows fell through to
    ``float(row)``, which raises "only 0-dimensional arrays can be converted
    to Python scalars" from inside a perturbation, several frames from
    anything that names a deformation gradient.
    """
    rows = list(nine)
    if rows and not isinstance(rows[0], (int, float)):
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
