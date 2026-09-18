"""UMAT_OTI_EVAL_TOTAL: the total-derivative provider entry point.

Every check compares the transformed (OTI) object against the ORIGINAL UMAT
compiled into the same provider, through central finite differences with two
step sizes (a plateau), or against the existing UMAT_OTI_EVAL bit for bit.
No constitutive mathematics is reimplemented in Python.

Models: m3_j2 (radial return, one state), m6_fcc (explicit sub-stepped
crystal plasticity, twelve states, rate dependent) and a test-fixture
total-strain damage model that reads STRAN, has a history maximum and asks
for a cut-back (PNEWDT<1) above a strain limit.
"""

import ctypes
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from umat_oti.provider import build_provider

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "parameter_sensitivity" / "models"
FIXTURE = ROOT / "tests" / "fixtures" / "provider_total_strain" / "contract_v2.json"

SHIM = r"""
subroutine c_total(props, nprops, ntens, nstatv, nparam, stress, statev, ddsdde, stran, dstran, &
    dtime, dsig, dstv, dsig_in, dstv_in, e0_dp, de_dp, dstv_de, pnewdt) bind(C, name="c_total")
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
  call umat_oti_eval_total(stress, statev, ddsdde, stran, dstran, time, dtime, 0.0d0, 0.0d0, &
      props, nprops, ntens, nstatv, nparam, dsig, dstv, dsig_in, dstv_in, e0_dp, de_dp, &
      dstv_de, coords, 1.0d0, 1, 1, 1, 1, pnewdt)
end subroutine

subroutine c_eval(props, nprops, ntens, nstatv, nparam, stress, statev, ddsdde, stran, dstran, &
    dtime, dsig, dstv, dsig_in, dstv_in) bind(C, name="c_eval")
  use iso_c_binding
  implicit none
  integer(c_int), value :: nprops, ntens, nstatv, nparam
  real(c_double) :: props(nprops), stress(ntens), statev(nstatv), ddsdde(ntens, ntens)
  real(c_double) :: stran(ntens), dstran(ntens), dsig(ntens, nparam), dstv(nstatv, nparam)
  real(c_double) :: dsig_in(ntens, nparam), dstv_in(nstatv, nparam)
  real(c_double), value :: dtime
  real(8) :: time(2)
  time = 0.0d0
  call umat_oti_eval(stress, statev, ddsdde, stran, dstran, time, dtime, 0.0d0, 0.0d0, &
      props, nprops, ntens, nstatv, nparam, dsig, dstv, dsig_in, dstv_in)
end subroutine

subroutine c_umat(props, nprops, ntens, nstatv, stress, statev, stran, dstran, dtime, pnewdt) &
    bind(C, name="c_umat")
  use iso_c_binding
  implicit none
  integer(c_int), value :: nprops, ntens, nstatv
  real(c_double) :: props(nprops), stress(ntens), statev(nstatv), stran(ntens), dstran(ntens), pnewdt
  real(c_double), value :: dtime
  real(8) :: dd(ntens, ntens), sse, spd, scd, rpl, ddsddt(ntens), drplde(ntens), drpldt
  real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3, 3), f0(3, 3), f1(3, 3)
  character(len=80) :: cmname
  integer :: k
  sse = 0; spd = 0; scd = 0; rpl = 0; drpldt = 0; ddsddt = 0; drplde = 0; dd = 0
  time = 0; predef = 0; dpred = 0; coords = 0; drot = 0; f0 = 0; f1 = 0
  do k = 1, 3
    drot(k, k) = 1; f0(k, k) = 1; f1(k, k) = 1
  end do
  pnewdt = 1.0d0
  cmname = 'MATERIAL'
  call umat(stress, statev, dd, sse, spd, scd, rpl, ddsddt, drplde, drpldt, stran, dstran, &
      time, dtime, 0.0d0, 0.0d0, predef, dpred, cmname, 3, 3, ntens, nstatv, props, nprops, &
      coords, drot, pnewdt, 1.0d0, f0, f1, 1, 1, 1, 1, 1, 1)
end subroutine
"""


class Provider:
    """ctypes view of one built provider: EVAL_TOTAL, EVAL and the ORIGINAL UMAT."""

    def __init__(self, contract_path, directory):
        built = build_provider(contract_path, directory / "provider")
        self.meta = json.loads(Path(built["contract"]).read_text())
        shim = directory / "shim.f90"
        shim.write_text(SHIM)
        subprocess.run(["gfortran", "-fPIC", "-c", str(shim), "-o", str(directory / "shim.o")], check=True)
        library = directory / "provider_total.so"
        subprocess.run(["gfortran", "-shared", str(directory / "shim.o"), built["object"], "-o",
                        str(library)], check=True)
        self.lib = ctypes.CDLL(str(library))
        dims = self.meta["dimensions"]
        self.nt, self.np_, self.ns, self.npar = dims["ntens"], dims["nprops"], dims["nstatev"], dims["nparam"]
        self.slots = [p["props_index"] - 1 for p in self.meta["parameters"]]

    @staticmethod
    def _f(array):
        return np.asfortranarray(np.array(array, dtype=float))

    def total(self, props, stress, state, stran, dstran, dtime, dsig_in, dstv_in, e0_dp, de_dp):
        s, v = self._f(stress), self._f(state)
        dd = np.zeros((self.nt, self.nt), order="F")
        dsig = np.zeros((self.nt, self.npar), order="F")
        dstv = np.zeros((self.ns, self.npar), order="F")
        dve = np.zeros((self.ns, self.nt), order="F")
        pnewdt = ctypes.c_double(0.0)
        p = ctypes.c_void_p
        args = [self._f(props), s, v, dd, self._f(stran), self._f(dstran)]
        seeds = [self._f(dsig_in), self._f(dstv_in), self._f(e0_dp), self._f(de_dp)]
        self.lib.c_total(args[0].ctypes.data_as(p), self.np_, self.nt, self.ns, self.npar,
                         *(a.ctypes.data_as(p) for a in args[1:]), ctypes.c_double(dtime),
                         dsig.ctypes.data_as(p), dstv.ctypes.data_as(p),
                         *(a.ctypes.data_as(p) for a in seeds), dve.ctypes.data_as(p),
                         ctypes.byref(pnewdt))
        return s, v, dd, dsig, dstv, dve, pnewdt.value

    def eval(self, props, stress, state, stran, dstran, dtime, dsig_in, dstv_in):
        s, v = self._f(stress), self._f(state)
        dd = np.zeros((self.nt, self.nt), order="F")
        dsig = np.zeros((self.nt, self.npar), order="F")
        dstv = np.zeros((self.ns, self.npar), order="F")
        p = ctypes.c_void_p
        args = [self._f(props), s, v, dd, self._f(stran), self._f(dstran)]
        self.lib.c_eval(args[0].ctypes.data_as(p), self.np_, self.nt, self.ns, self.npar,
                        *(a.ctypes.data_as(p) for a in args[1:]), ctypes.c_double(dtime),
                        dsig.ctypes.data_as(p), dstv.ctypes.data_as(p),
                        self._f(dsig_in).ctypes.data_as(p), self._f(dstv_in).ctypes.data_as(p))
        return s, v, dd, dsig, dstv

    def original(self, props, stress, state, stran, dstran, dtime):
        s, v = self._f(stress), self._f(state)
        pnewdt = ctypes.c_double(0.0)
        p = ctypes.c_void_p
        self.lib.c_umat(self._f(props).ctypes.data_as(p), self.np_, self.nt, self.ns,
                        s.ctypes.data_as(p), v.ctypes.data_as(p), self._f(stran).ctypes.data_as(p),
                        self._f(dstran).ctypes.data_as(p), ctypes.c_double(dtime), ctypes.byref(pnewdt))
        return s, v, pnewdt.value


CASES = {
    # (contract, props, strain-increment path that reaches the nonlinear branch, dtime)
    "m3_j2": (MODELS / "m3_j2" / "contract_v2.json", [200000.0, 0.3, 250.0, 2000.0],
              [[6e-4, -1e-4, -1e-4, 8e-4, 1e-4, -2e-4]] * 4, 1.0),
    "m6_fcc": (MODELS / "m6_fcc" / "contract_v2.json",
               [168000.0, 121000.0, 75000.0, 16.0, 40.0, 300.0, 2.0, 1.4, 0.001, 0.05],
               [[1e-4, -2.5e-5, -3.75e-5, 5e-5, 1.25e-5, -2e-5]] * 5, 0.04),
    "total_strain_damage": (FIXTURE, [70000.0, 0.25, 5e-4, 400.0, 0.05],
                            [[4e-4, -1e-4, -1e-4, 3e-4, 0.0, 1e-4]] * 4, 1.0),
}


@pytest.fixture(scope="module", params=sorted(CASES))
def case(request, tmp_path_factory):
    contract, props, path, dtime = CASES[request.param]
    provider = Provider(contract, tmp_path_factory.mktemp(request.param))
    props = np.array(props)
    stress, state, stran = np.zeros(6), np.zeros(provider.ns), np.zeros(6)
    for increment in path[:-1]:
        stress, state, _ = provider.original(props, stress, state, stran, increment, dtime)
        stran = stran + np.array(increment)
    rng = np.random.default_rng(7)
    scale = np.abs(props[provider.slots])
    seeds = {
        "dsig_in": rng.normal(size=(6, provider.npar)) * (np.abs(stress).max() + 1.0)[..., None] / scale,
        "dstv_in": rng.normal(size=(provider.ns, provider.npar)) * (np.abs(state).max() + 1e-4) / scale,
        "e0_dp": rng.normal(size=(6, provider.npar)) * np.abs(stran).max() / scale,
        "de_dp": rng.normal(size=(6, provider.npar)) * np.abs(path[-1]).max() / scale,
    }
    return request.param, provider, props, stress, state, stran, np.array(path[-1]), dtime, seeds


def test_total_symbol_is_advertised(case):
    _, provider, *_ = case
    symbols = provider.meta["symbols"]
    assert symbols["oti_eval_total"] == "umat_oti_eval_total_"
    assert len(symbols["oti_eval_total_signature"]) == 28
    assert len(symbols["oti_eval_signature"]) == 18       # the existing ABI is unchanged


def test_zero_strain_seeds_reproduce_eval_bit_for_bit(case):
    _, provider, props, stress, state, stran, dstran, dtime, seeds = case
    zero = np.zeros((6, provider.npar))
    total = provider.total(props, stress, state, stran, dstran, dtime, seeds["dsig_in"],
                           seeds["dstv_in"], zero, zero)
    legacy = provider.eval(props, stress, state, stran, dstran, dtime, seeds["dsig_in"], seeds["dstv_in"])
    for left, right in zip(total[:5], legacy):
        np.testing.assert_array_equal(left, right)
    assert total[6] == 1.0


def _central(provider, props, stress, state, stran, dstran, dtime, direction, step):
    def at(sign):
        p = props.copy()
        p += sign * step * direction["props"]
        return provider.original(p, stress + sign * step * direction["stress"],
                                 state + sign * step * direction["state"],
                                 stran + sign * step * direction["stran"],
                                 dstran + sign * step * direction["dstran"], dtime)
    plus, minus = at(+1), at(-1)
    return (plus[0] - minus[0]) / (2 * step), (plus[1] - minus[1]) / (2 * step)


def _plateau_error(computed, estimates):
    """Relative error vs the finer FD estimate, and the FD plateau spread."""
    coarse, fine = estimates
    scale = max(np.abs(fine).max(), 1e-30)
    return np.abs(computed - fine).max() / scale, np.abs(coarse - fine).max() / scale


def test_every_seed_is_a_total_derivative_of_the_original_umat(case):
    name, provider, props, stress, state, stran, dstran, dtime, seeds = case
    _, _, _, dsig, dstv, _, pnewdt = provider.total(props, stress, state, stran, dstran, dtime,
                                                    seeds["dsig_in"], seeds["dstv_in"],
                                                    seeds["e0_dp"], seeds["de_dp"])
    assert pnewdt == 1.0
    for j, slot in enumerate(provider.slots):
        unit = np.zeros_like(props)
        unit[slot] = 1.0
        direction = {"props": unit, "stress": seeds["dsig_in"][:, j], "state": seeds["dstv_in"][:, j],
                     "stran": seeds["e0_dp"][:, j], "dstran": seeds["de_dp"][:, j]}
        estimates = [_central(provider, props, stress, state, stran, dstran, dtime, direction,
                              h * abs(props[slot])) for h in (2e-6, 1e-6)]
        error, spread = _plateau_error(dsig[:, j], [e[0] for e in estimates])
        assert spread < 1e-6, (name, j, spread)
        assert error < 1e-6, (name, "stress", j, error)
        if provider.ns:
            error, spread = _plateau_error(dstv[:, j], [e[1] for e in estimates])
            assert spread < 1e-6 and error < 1e-6, (name, "state", j, error, spread)


def test_state_and_stress_tangents_match_original_fd(case):
    name, provider, props, stress, state, stran, dstran, dtime, seeds = case
    zero = np.zeros((6, provider.npar))
    _, _, ddsdde, _, _, dstv_de, _ = provider.total(props, stress, state, stran, dstran, dtime,
                                                    zero, np.zeros((provider.ns, provider.npar)), zero, zero)
    nothing = {"props": np.zeros_like(props), "stress": np.zeros(6), "state": np.zeros(provider.ns),
               "stran": np.zeros(6)}
    for axis in range(6):
        direction = dict(nothing, dstran=np.eye(6)[axis])
        estimates = [_central(provider, props, stress, state, stran, dstran, dtime, direction, h)
                     for h in (2e-9, 1e-9)]
        error, spread = _plateau_error(ddsdde[:, axis], [e[0] for e in estimates])
        assert spread < 1e-5 and error < 1e-5, (name, "DDSDDE", axis, error, spread)
        if provider.ns and np.abs(estimates[1][1]).max() > 0:
            error, spread = _plateau_error(dstv_de[:, axis], [e[1] for e in estimates])
            assert spread < 1e-5 and error < 1e-5, (name, "dSTATEV/dDSTRAN", axis, error, spread)


def test_nonzero_state_tangent_where_the_state_evolves(case):
    name, provider, props, stress, state, stran, dstran, dtime, seeds = case
    zero = np.zeros((6, provider.npar))
    out = provider.total(props, stress, state, stran, dstran, dtime, zero,
                         np.zeros((provider.ns, provider.npar)), zero, zero)
    assert np.abs(out[5]).max() > 0, name     # the path was chosen to be on the evolving branch


def test_cutback_request_is_returned_not_a_process_stop(tmp_path):
    provider = Provider(FIXTURE, tmp_path)
    props = np.array(CASES["total_strain_damage"][1])
    zero = np.zeros((6, provider.npar))
    beyond = np.array([0.08, 0, 0, 0, 0, 0])            # above EPSMAX=0.05
    out = provider.total(props, np.zeros(6), np.zeros(1), np.zeros(6), beyond, 1.0, zero,
                         np.zeros((1, provider.npar)), zero, zero)
    assert out[6] == 0.5
    assert provider.original(props, np.zeros(6), np.zeros(1), np.zeros(6), beyond, 1.0)[2] == 0.5
