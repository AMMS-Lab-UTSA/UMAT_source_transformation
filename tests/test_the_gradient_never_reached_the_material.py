"""UMAT_OTI_EVAL_TOTAL_F: the provider entry point that forwards the gradient.

Every small-strain entry point the provider publishes hard-sets
``DFGRD0 = DFGRD1 = I`` and drives the UMAT through STRAN/DSTRAN. A UMAT that
reads its kinematics from the deformation gradient -- every large-deformation
UMAT -- then sees no deformation at all and returns zero stress for every
increment: a run that looks converged and means nothing. Nothing in the
repository could catch that, because every shipped fixture reads DSTRAN.

``tests/fixtures/provider_finite_strain`` is a compressible neo-Hookean that
reads DFGRD1 and never touches DSTRAN, so it can. The references here are
central differences of the ORIGINAL UMAT compiled into the same provider; no
constitutive mathematics is restated in Python.
"""

import ctypes
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from umat_oti.provider import build_provider

ROOT = Path(__file__).resolve().parents[1]
FINITE = ROOT / "tests" / "fixtures" / "provider_finite_strain" / "contract_v2.json"
SMALL = ROOT / "tests" / "fixtures" / "provider_total_strain" / "contract_v2.json"

PROPS = [80000.0, 120000.0, 0.4]

SHIM = r"""
subroutine c_total_f(props, nprops, ntens, nstatv, nparam, stress, statev, ddsdde, &
    stran, dstran, dtime, dsig, dstv, dsig_in, dstv_in, e0_dp, de_dp, dstv_de, &
    f0, f1, drot, f0_dp, f1_dp, pnewdt) bind(C, name="c_total_f")
  use iso_c_binding
  implicit none
  integer(c_int), value :: nprops, ntens, nstatv, nparam
  real(c_double) :: props(nprops), stress(ntens), statev(nstatv), ddsdde(ntens, ntens)
  real(c_double) :: stran(ntens), dstran(ntens), dsig(ntens, nparam), dstv(nstatv, nparam)
  real(c_double) :: dsig_in(ntens, nparam), dstv_in(nstatv, nparam), e0_dp(ntens, nparam)
  real(c_double) :: de_dp(ntens, nparam), dstv_de(nstatv, ntens), pnewdt
  real(c_double) :: f0(3, 3), f1(3, 3), drot(3, 3)
  real(c_double) :: f0_dp(3, 3, nparam), f1_dp(3, 3, nparam)
  real(c_double), value :: dtime
  real(8) :: time(2), coords(3)
  time = 0.0d0; coords = 0.0d0
  call umat_oti_eval_total_f(stress, statev, ddsdde, stran, dstran, time, dtime, &
      0.0d0, 0.0d0, props, nprops, ntens, nstatv, nparam, dsig, dstv, dsig_in, &
      dstv_in, e0_dp, de_dp, dstv_de, coords, 1.0d0, 1, 1, 1, 1, pnewdt, &
      f0, f1, drot, f0_dp, f1_dp)
end subroutine

subroutine c_total(props, nprops, ntens, nstatv, nparam, stress, statev, ddsdde, stran, &
    dstran, dtime, dsig, dstv, dsig_in, dstv_in, e0_dp, de_dp, dstv_de, pnewdt) &
    bind(C, name="c_total")
  use iso_c_binding
  implicit none
  integer(c_int), value :: nprops, ntens, nstatv, nparam
  real(c_double) :: props(nprops), stress(ntens), statev(nstatv), ddsdde(ntens, ntens)
  real(c_double) :: stran(ntens), dstran(ntens), dsig(ntens, nparam), dstv(nstatv, nparam)
  real(c_double) :: dsig_in(ntens, nparam), dstv_in(nstatv, nparam), e0_dp(ntens, nparam)
  real(c_double) :: de_dp(ntens, nparam), dstv_de(nstatv, ntens), pnewdt
  real(c_double), value :: dtime
  real(8) :: time(2), coords(3)
  time = 0.0d0; coords = 0.0d0
  call umat_oti_eval_total(stress, statev, ddsdde, stran, dstran, time, dtime, 0.0d0, &
      0.0d0, props, nprops, ntens, nstatv, nparam, dsig, dstv, dsig_in, dstv_in, &
      e0_dp, de_dp, dstv_de, coords, 1.0d0, 1, 1, 1, 1, pnewdt)
end subroutine

subroutine c_umat_f(props, nprops, ntens, nstatv, stress, statev, stran, dstran, &
    dtime, f0, f1, pnewdt) bind(C, name="c_umat_f")
  use iso_c_binding
  implicit none
  integer(c_int), value :: nprops, ntens, nstatv
  real(c_double) :: props(nprops), stress(ntens), statev(nstatv), stran(ntens)
  real(c_double) :: dstran(ntens), f0(3, 3), f1(3, 3), pnewdt
  real(c_double), value :: dtime
  real(8) :: dd(ntens, ntens), sse, spd, scd, rpl, ddsddt(ntens), drplde(ntens), drpldt
  real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3, 3)
  character(len=80) :: cmname
  integer :: k
  sse = 0; spd = 0; scd = 0; rpl = 0; drpldt = 0; ddsddt = 0; drplde = 0; dd = 0
  time = 0; predef = 0; dpred = 0; coords = 0; drot = 0
  do k = 1, 3
    drot(k, k) = 1
  end do
  pnewdt = 1.0d0
  cmname = 'MATERIAL'
  call umat(stress, statev, dd, sse, spd, scd, rpl, ddsddt, drplde, drpldt, stran, &
      dstran, time, dtime, 0.0d0, 0.0d0, predef, dpred, cmname, 3, 3, ntens, nstatv, &
      props, nprops, coords, drot, pnewdt, 1.0d0, f0, f1, 1, 1, 1, 1, 1, 1)
end subroutine
"""

P = ctypes.c_void_p


def _f(array):
    return np.asfortranarray(np.array(array, dtype=float))


class Provider:
    """ctypes view of one built provider: both TOTAL entry points and the original."""

    def __init__(self, contract_path, directory):
        built = build_provider(contract_path, directory / "provider")
        self.meta = json.loads(Path(built["contract"]).read_text())
        shim = directory / "shim.f90"
        shim.write_text(SHIM)
        subprocess.run(["gfortran", "-fPIC", "-c", str(shim), "-o", str(directory / "shim.o")],
                       check=True)
        library = directory / "finite.so"
        subprocess.run(["gfortran", "-shared", str(directory / "shim.o"), built["object"],
                        "-o", str(library)], check=True)
        self.lib = ctypes.CDLL(str(library))
        dims = self.meta["dimensions"]
        self.nt, self.np_ = dims["ntens"], dims["nprops"]
        self.ns, self.npar = dims["nstatev"], dims["nparam"]

    def _blank(self):
        return (np.zeros((self.nt, self.npar), order="F"),
                np.zeros((self.ns, self.npar), order="F"))

    def total_f(self, props, stress, state, f0, f1, *, dtime=1.0, drot=None,
                stran=None, dstran=None, dsig_in=None, dstv_in=None,
                f0_dp=None, f1_dp=None):
        dsig_z, dstv_z = self._blank()
        s, v = _f(stress), _f(state)
        dd = np.zeros((self.nt, self.nt), order="F")
        dsig = np.zeros((self.nt, self.npar), order="F")
        dstv = np.zeros((self.ns, self.npar), order="F")
        dve = np.zeros((self.ns, self.nt), order="F")
        pnewdt = ctypes.c_double(0.0)
        arrays = [_f(props), s, v, dd,
                  _f(stran if stran is not None else np.zeros(self.nt)),
                  _f(dstran if dstran is not None else np.zeros(self.nt))]
        seeds = [_f(dsig_in if dsig_in is not None else dsig_z),
                 _f(dstv_in if dstv_in is not None else dstv_z),
                 _f(np.zeros((self.nt, self.npar))), _f(np.zeros((self.nt, self.npar)))]
        grads = [_f(f0), _f(f1), _f(drot if drot is not None else np.eye(3)),
                 _f(f0_dp if f0_dp is not None else np.zeros((3, 3, self.npar))),
                 _f(f1_dp if f1_dp is not None else np.zeros((3, 3, self.npar)))]
        self.lib.c_total_f(arrays[0].ctypes.data_as(P), self.np_, self.nt, self.ns, self.npar,
                           *(a.ctypes.data_as(P) for a in arrays[1:]), ctypes.c_double(dtime),
                           dsig.ctypes.data_as(P), dstv.ctypes.data_as(P),
                           *(a.ctypes.data_as(P) for a in seeds), dve.ctypes.data_as(P),
                           *(a.ctypes.data_as(P) for a in grads), ctypes.byref(pnewdt))
        return s, v, dd, dsig, dstv, dve

    def total(self, props, stress, state, stran, dstran, *, dtime=1.0,
              dsig_in=None, dstv_in=None):
        dsig_z, dstv_z = self._blank()
        s, v = _f(stress), _f(state)
        dd = np.zeros((self.nt, self.nt), order="F")
        dsig = np.zeros((self.nt, self.npar), order="F")
        dstv = np.zeros((self.ns, self.npar), order="F")
        dve = np.zeros((self.ns, self.nt), order="F")
        pnewdt = ctypes.c_double(0.0)
        arrays = [_f(props), s, v, dd, _f(stran), _f(dstran)]
        seeds = [_f(dsig_in if dsig_in is not None else dsig_z),
                 _f(dstv_in if dstv_in is not None else dstv_z),
                 _f(np.zeros((self.nt, self.npar))), _f(np.zeros((self.nt, self.npar)))]
        self.lib.c_total(arrays[0].ctypes.data_as(P), self.np_, self.nt, self.ns, self.npar,
                         *(a.ctypes.data_as(P) for a in arrays[1:]), ctypes.c_double(dtime),
                         dsig.ctypes.data_as(P), dstv.ctypes.data_as(P),
                         *(a.ctypes.data_as(P) for a in seeds), dve.ctypes.data_as(P),
                         ctypes.byref(pnewdt))
        return s, v, dd, dsig, dstv, dve

    def original_f(self, props, stress, state, f0, f1, *, dtime=1.0):
        s, v = _f(stress), _f(state)
        pnewdt = ctypes.c_double(0.0)
        arrays = [_f(props), s, v, _f(np.zeros(self.nt)), _f(np.zeros(self.nt))]
        self.lib.c_umat_f(arrays[0].ctypes.data_as(P), self.np_, self.nt, self.ns,
                          *(a.ctypes.data_as(P) for a in arrays[1:]),
                          ctypes.c_double(dtime), _f(f0).ctypes.data_as(P),
                          _f(f1).ctypes.data_as(P), ctypes.byref(pnewdt))
        return s, v


@pytest.fixture(scope="module")
def finite(tmp_path_factory):
    return Provider(FINITE, tmp_path_factory.mktemp("finite"))


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    return Provider(SMALL, tmp_path_factory.mktemp("small"))


#: A gradient with stretch, compression and shear, far enough from the identity
#: that `dF = eps` and `dF = eps . F` are not the same question.
F1 = np.array([[1.08, 0.04, 0.02],
               [0.00, 0.95, 0.03],
               [0.01, 0.00, 1.06]])
F0 = np.eye(3)

#: The strain-increment directions the seed stands for, in Abaqus Voigt order:
#: a one on the diagonal for a direct direction, a half on each off-diagonal
#: position for an engineering shear.
def _voigt_strain(direction):
    eps = np.zeros((3, 3))
    if direction < 3:
        eps[direction, direction] = 1.0
    else:
        row, column = ((0, 1), (0, 2), (1, 2))[direction - 3]
        eps[row, column] = eps[column, row] = 0.5
    return eps


def test_the_contract_says_which_entry_point_to_drive(finite, small):
    assert finite.meta["kinematics"] == "finite_strain"
    assert finite.meta["drive"] == "umat_oti_eval_total_f_"
    assert small.meta["kinematics"] == "small_strain"
    assert small.meta["drive"] == "umat_oti_eval_total_"


def test_the_small_strain_entry_point_sees_no_deformation_at_all(finite):
    """Why this entry point exists, stated as a measurement.

    The same material, the same gradient: through UMAT_OTI_EVAL_TOTAL the
    gradient never arrives, and the model reports zero stress rather than
    failing.
    """
    blind, _, _, _, _, _ = finite.total(PROPS, np.zeros(6), np.zeros(1),
                                        np.zeros(6), np.zeros(6))
    assert np.allclose(blind, 0.0), "expected the small-strain entry point to see F = I"
    seeing, _, _, _, _, _ = finite.total_f(PROPS, np.zeros(6), np.zeros(1), F0, F1)
    assert np.abs(seeing).max() > 1.0e3, "the finite-strain entry point returned no stress"


def test_the_stress_matches_the_original_umat_under_the_same_gradient(finite):
    oti, state, _, _, _, _ = finite.total_f(PROPS, np.zeros(6), np.zeros(1), F0, F1)
    reference, reference_state = finite.original_f(PROPS, np.zeros(6), np.zeros(1), F0, F1)
    assert np.allclose(oti, reference, rtol=0, atol=1.0e-9)
    assert np.allclose(state, reference_state, rtol=0, atol=1.0e-12)


@pytest.mark.parametrize("step", [1.0e-5, 1.0e-6])
def test_the_tangent_is_the_kirchhoff_one_abaqus_asks_for(finite, step):
    """DDSDDE(ij,kl) = d sigma_ij / d eps_kl + sigma_ij delta_kl, by central difference.

    The perturbation is ``dF = eps . F``, which is what asking for a velocity
    gradient ``l = eps`` means; the Kirchhoff term rides on the direct columns.
    Two step sizes so a passing number has to be a plateau rather than a
    coincidence.
    """
    stress, _, ddsdde, _, _, _ = finite.total_f(PROPS, np.zeros(6), np.zeros(1), F0, F1)
    reference = np.zeros((6, 6))
    for direction in range(6):
        eps = _voigt_strain(direction)
        plus, _ = finite.original_f(PROPS, np.zeros(6), np.zeros(1), F0,
                                    (np.eye(3) + step * eps) @ F1)
        minus, _ = finite.original_f(PROPS, np.zeros(6), np.zeros(1), F0,
                                     (np.eye(3) - step * eps) @ F1)
        reference[:, direction] = (plus - minus) / (2.0 * step)
        if direction < 3:
            reference[:, direction] += stress
    scale = np.abs(reference).max()
    worst = np.abs(ddsdde - reference).max() / scale
    assert worst < 5.0e-6, f"worst scaled tangent error {worst:.3e} at h={step:g}"


@pytest.mark.parametrize("step", [1.0e-4, 1.0e-5])
def test_the_parameter_derivatives_hold_through_a_history(finite, step):
    """Three increments, the carry chained as a consumer would chain it.

    The fixture's state feeds its own stress, so the last increment's
    dSTRESS/dp is only right if the previous increments' dSTATEV/dp came
    forward. The reference re-runs the WHOLE path with a perturbed parameter.
    """
    path = [np.eye(3) + t * (F1 - np.eye(3)) for t in (0.4, 0.7, 1.0)]

    def march(props):
        stress, state = np.zeros(6), np.zeros(1)
        previous = np.eye(3)
        for gradient in path:
            stress, state = finite.original_f(props, stress, state, previous, gradient)
            previous = gradient
        return stress

    stress, state = np.zeros(6), np.zeros(1)
    dsig_in = np.zeros((6, finite.npar))
    dstv_in = np.zeros((1, finite.npar))
    previous = np.eye(3)
    for gradient in path:
        stress, state, _, dsig_in, dstv_in, _ = finite.total_f(
            PROPS, stress, state, previous, gradient,
            dsig_in=dsig_in, dstv_in=dstv_in)
        previous = gradient

    reference = np.zeros((6, finite.npar))
    for index in range(finite.npar):
        plus, minus = list(PROPS), list(PROPS)
        h = step * abs(PROPS[index])
        plus[index] += h
        minus[index] -= h
        reference[:, index] = (march(plus) - march(minus)) / (2.0 * h)
    scale = np.abs(reference).max()
    worst = np.abs(dsig_in - reference).max() / scale
    assert worst < 1.0e-6, f"worst scaled dSTRESS/dp error {worst:.3e} at h={step:g}"


def test_a_gradient_that_moves_with_the_parameter_is_carried(finite):
    """DFGRD1_DP is not decoration: seeding it must change dSTRESS/dp.

    A consumer whose geometry responds to the parameter -- which is the whole
    point of a residual sensitivity -- passes a nonzero dF/dp. The reference
    is a central difference of the original UMAT along the SAME gradient
    direction, so a wrong seed shows up as a wrong number rather than as an
    ignored argument.
    """
    direction = np.zeros((3, 3, finite.npar))
    direction[:, :, 0] = np.array([[0.30, 0.05, 0.00],
                                   [0.00, -0.20, 0.02],
                                   [0.01, 0.00, 0.15]])
    _, _, _, dsig, _, _ = finite.total_f(PROPS, np.zeros(6), np.zeros(1), F0, F1,
                                         f1_dp=direction)
    plain, _, _, dsig_plain, _, _ = finite.total_f(PROPS, np.zeros(6), np.zeros(1), F0, F1)
    assert not np.allclose(dsig[:, 0], dsig_plain[:, 0]), "DFGRD1_DP was ignored"

    step = 1.0e-6
    moved = direction[:, :, 0]
    plus, _ = finite.original_f(PROPS, np.zeros(6), np.zeros(1), F0, F1 + step * moved)
    minus, _ = finite.original_f(PROPS, np.zeros(6), np.zeros(1), F0, F1 - step * moved)
    # Direction 0 carries the unit PROPS(1) seed as well, so subtract its part.
    geometry_only = dsig[:, 0] - dsig_plain[:, 0]
    reference = (plus - minus) / (2.0 * step)
    worst = np.abs(geometry_only - reference).max() / np.abs(reference).max()
    assert worst < 1.0e-6, f"worst scaled dF/dp contribution error {worst:.3e}"


def test_at_the_identity_it_reduces_to_the_small_strain_entry_point(small):
    """A small-strain UMAT must not notice which entry point it came through.

    At F = I with no gradient seed the two differ by exactly the Kirchhoff
    term, on the direct columns and nowhere else -- so the small-strain
    contract keeps its meaning and the finite-strain one is a strict
    extension rather than a second, divergent definition.
    """
    props = [70000.0, 0.25, 0.0005, 400.0, 0.05]
    stran = np.zeros(6)
    dstran = np.array([6.0e-4, -1.0e-4, -1.0e-4, 8.0e-4, 1.0e-4, -2.0e-4])

    sa, va, dda, dsa, dva, dvea = small.total(props, np.zeros(6), np.zeros(small.ns),
                                              stran, dstran)
    sb, vb, ddb, dsb, dvb, dveb = small.total_f(props, np.zeros(6), np.zeros(small.ns),
                                                np.eye(3), np.eye(3),
                                                stran=stran, dstran=dstran)
    assert np.allclose(sa, sb, rtol=0, atol=1.0e-10), "stress differs between entry points"
    assert np.allclose(va, vb, rtol=0, atol=1.0e-12)
    assert np.allclose(dsa, dsb, rtol=0, atol=1.0e-10)
    assert np.allclose(dva, dvb, rtol=0, atol=1.0e-12)
    assert np.allclose(dvea, dveb, rtol=0, atol=1.0e-12)

    kirchhoff = np.zeros((6, 6))
    kirchhoff[:, :3] = np.tile(sa.reshape(6, 1), (1, 3))
    assert np.allclose(ddb, dda + kirchhoff, rtol=0, atol=1.0e-8)
