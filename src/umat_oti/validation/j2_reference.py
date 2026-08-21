"""Reference small-strain 3D J2 plasticity with linear isotropic hardening.

This is the reference implementation of the focused SoftwareX case:

* NTENS = 6 (3D)
* Parameters : E, nu, SIGY0, H
* State      : EQPLAS (accumulated equivalent plastic strain)

It exists so we can generate a *history-consistent* reference for the
material-tangent, primal stress/state, and parameter-sensitivity outputs
without depending on Abaqus or on an external Fortran compilation. Every
equation here mirrors the standard closed-form radial-return / small-strain
J2 hardening algorithm; nothing is fit to a target number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence


PARAM_NAMES = ("E", "NU", "SIGY0", "H")
STATE_NAMES = ("EQPLAS",)
NTENS = 6

_SQRT_2_3 = math.sqrt(2.0 / 3.0)
_SQRT_3_2 = math.sqrt(3.0 / 2.0)


@dataclass(frozen=True)
class J2Parameters:
    """Material parameters for the SoftwareX J2 case."""

    E: float = 200000.0     # MPa
    nu: float = 0.3         # -
    SIGY0: float = 250.0    # MPa, initial yield stress
    H: float = 2000.0       # MPa, linear isotropic hardening modulus

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.E, self.nu, self.SIGY0, self.H)

    def with_replaced(self, name: str, value: float) -> "J2Parameters":
        upper = name.upper()
        if upper == "E":
            return J2Parameters(E=value, nu=self.nu, SIGY0=self.SIGY0, H=self.H)
        if upper == "NU":
            return J2Parameters(E=self.E, nu=value, SIGY0=self.SIGY0, H=self.H)
        if upper == "SIGY0":
            return J2Parameters(E=self.E, nu=self.nu, SIGY0=value, H=self.H)
        if upper == "H":
            return J2Parameters(E=self.E, nu=self.nu, SIGY0=self.SIGY0, H=value)
        raise ValueError(f"unknown parameter {name!r}")


@dataclass
class J2State:
    """Per-integration-point state at the start of an increment."""

    stress: tuple[float, ...] = (0.0,) * NTENS
    statev: tuple[float, ...] = (0.0,)
    stran: tuple[float, ...] = (0.0,) * NTENS

    def copy(self) -> "J2State":
        return J2State(stress=self.stress, statev=self.statev, stran=self.stran)


@dataclass
class J2IncrementResult:
    """Result of a single increment (radial return)."""

    stress: tuple[float, ...]
    statev: tuple[float, ...]
    stran: tuple[float, ...]
    ddsdde: tuple[tuple[float, ...], ...]
    yielded: bool
    dgamma: float


def elastic_stiffness(params: J2Parameters) -> tuple[tuple[float, ...], ...]:
    """Isotropic elastic 6x6 stiffness (Voigt engineering shear)."""
    E, nu = params.E, params.nu
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu = E / (2.0 * (1.0 + nu))
    rows: list[list[float]] = []
    for i in range(NTENS):
        row = [0.0] * NTENS
        for j in range(NTENS):
            if i < 3 and j < 3:
                row[j] = lam + (2.0 * mu if i == j else 0.0)
            elif i == j and i >= 3:
                row[j] = mu
        rows.append(row)
    return tuple(tuple(row) for row in rows)


def _matvec(A: Sequence[Sequence[float]], x: Sequence[float]) -> tuple[float, ...]:
    return tuple(sum(A[i][j] * x[j] for j in range(len(x))) for i in range(len(A)))


def _deviator(sigma: Sequence[float]) -> tuple[float, ...]:
    p = (sigma[0] + sigma[1] + sigma[2]) / 3.0
    return (
        sigma[0] - p,
        sigma[1] - p,
        sigma[2] - p,
        sigma[3],
        sigma[4],
        sigma[5],
    )


def _mises_from_dev(s: Sequence[float]) -> float:
    # von Mises with engineering shear representation: q = sqrt(3/2 * s:s),
    # where s:s uses factor 2 on shear components (Voigt engineering).
    return math.sqrt(
        1.5 * (s[0] * s[0] + s[1] * s[1] + s[2] * s[2])
        + 3.0 * (s[3] * s[3] + s[4] * s[4] + s[5] * s[5])
    )


def integrate_increment(
    params: J2Parameters,
    state: J2State,
    dstran: Sequence[float],
) -> J2IncrementResult:
    """Radial-return small-strain J2 update with linear isotropic hardening."""
    if len(dstran) != NTENS:
        raise ValueError(f"dstran must have length {NTENS}")
    C = elastic_stiffness(params)
    stress_trial = tuple(
        state.stress[i] + sum(C[i][j] * dstran[j] for j in range(NTENS))
        for i in range(NTENS)
    )
    dev_trial = _deviator(stress_trial)
    q_trial = _mises_from_dev(dev_trial)
    eqplas_n = state.statev[0]
    sigma_y = params.SIGY0 + params.H * eqplas_n
    phi_trial = q_trial - sigma_y

    E, nu = params.E, params.nu
    mu = E / (2.0 * (1.0 + nu))

    if phi_trial <= 0.0 or q_trial <= 0.0:
        stress_new = stress_trial
        statev_new = state.statev
        ddsdde = C
        yielded = False
        dgamma = 0.0
    else:
        # Closed-form dgamma for linear isotropic hardening.
        dgamma = phi_trial / (3.0 * mu + params.H)
        # Flow direction n = 3/(2 q_trial) * dev_trial (with engineering shear
        # doubling on off-diagonals): here we build the deviatoric decrement
        # directly consistent with the stress representation used above.
        scale = 3.0 * mu * dgamma / q_trial
        dev_new = (
            dev_trial[0] * (1.0 - scale),
            dev_trial[1] * (1.0 - scale),
            dev_trial[2] * (1.0 - scale),
            dev_trial[3] * (1.0 - scale),
            dev_trial[4] * (1.0 - scale),
            dev_trial[5] * (1.0 - scale),
        )
        p_trial = (stress_trial[0] + stress_trial[1] + stress_trial[2]) / 3.0
        stress_new = (
            dev_new[0] + p_trial,
            dev_new[1] + p_trial,
            dev_new[2] + p_trial,
            dev_new[3],
            dev_new[4],
            dev_new[5],
        )
        statev_new = (eqplas_n + dgamma,)
        ddsdde = _consistent_tangent(params, dev_trial, q_trial, dgamma)
        yielded = True

    stran_new = tuple(state.stran[i] + dstran[i] for i in range(NTENS))
    return J2IncrementResult(
        stress=stress_new,
        statev=statev_new,
        stran=stran_new,
        ddsdde=ddsdde,
        yielded=yielded,
        dgamma=dgamma,
    )


# Voigt index -> (i, j) tensor pair used throughout.
_VOIGT_PAIR = ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))


def _tensor_from_voigt_stress(sigma: Sequence[float]) -> list[list[float]]:
    """Build a symmetric 3x3 stress tensor from a Voigt 6-vector."""
    t = [[0.0] * 3 for _ in range(3)]
    for p, (i, j) in enumerate(_VOIGT_PAIR):
        t[i][j] = sigma[p]
        t[j][i] = sigma[p]
    return t


def _consistent_tangent(
    params: J2Parameters,
    dev_trial: Sequence[float],
    q_trial: float,
    dgamma: float,
) -> tuple[tuple[float, ...], ...]:
    """Small-strain J2 consistent tangent (Voigt engineering-shear form).

    Reference: Simo & Hughes, *Computational Inelasticity* eq. (3.7.12)::

        C^ep = kappa * I ⊗ I + 2 mu (1 - beta) I^dev - 2 mu gammabar n ⊗ n

    with ``beta = 3 mu dgamma / q_trial`` and
    ``gammabar = 3 mu / (3 mu + H) - beta``. The unit flow direction
    ``n = sqrt(3/2) * s_trial / q_trial`` satisfies ``n:n = 1``.

    We assemble the tangent directly in Voigt form using the tensor
    conversion ``C_pq = C_ijkl`` where ``(i,j) <-> p`` and ``(k,l) <-> q``
    (each shear pair contributes once, since strain columns use engineering
    shear ``gamma = 2 eps``).
    """
    E, nu = params.E, params.nu
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu = E / (2.0 * (1.0 + nu))
    kappa = lam + 2.0 * mu / 3.0

    beta = 3.0 * mu * dgamma / q_trial
    gammabar = 3.0 * mu / (3.0 * mu + params.H) - beta

    # Full 3x3 unit flow direction n_ij = sqrt(3/2) s_ij / q_trial.
    s = _tensor_from_voigt_stress(dev_trial)
    n = [[math.sqrt(1.5) * s[i][j] / q_trial for j in range(3)] for i in range(3)]

    def kron(a: int, b: int) -> float:
        return 1.0 if a == b else 0.0

    rows: list[list[float]] = [[0.0] * NTENS for _ in range(NTENS)]
    for p, (i, j) in enumerate(_VOIGT_PAIR):
        for q, (k, l) in enumerate(_VOIGT_PAIR):
            # Volumetric term: kappa * delta_ij * delta_kl.
            c = kappa * kron(i, j) * kron(k, l)
            # Deviatoric-elastic remnant: 2 mu (1 - beta) * (I_sym_ijkl - 1/3 delta_ij delta_kl).
            i_sym = 0.5 * (kron(i, k) * kron(j, l) + kron(i, l) * kron(j, k))
            c += 2.0 * mu * (1.0 - beta) * (i_sym - kron(i, j) * kron(k, l) / 3.0)
            # Plastic rank-1 correction: -2 mu gammabar * n_ij * n_kl.
            c -= 2.0 * mu * gammabar * n[i][j] * n[k][l]
            rows[p][q] = c
    return tuple(tuple(row) for row in rows)


# ---------------------------------------------------------------------------
# Loading paths + drivers
# ---------------------------------------------------------------------------

@dataclass
class LoadingPath:
    """A deterministic strain path expressed as a sequence of dstran vectors."""

    name: str
    increments: tuple[tuple[float, ...], ...]

    def total_strain(self) -> tuple[float, ...]:
        totals = [0.0] * NTENS
        for inc in self.increments:
            for i in range(NTENS):
                totals[i] += inc[i]
        return tuple(totals)


def build_softwarex_j2_path() -> LoadingPath:
    """Deterministic elastic -> yield -> plastic path used in the SoftwareX case.

    The path applies uniaxial tension along direction 1 with a fixed dstran11
    step of 1.5e-4. Given SIGY0=250, E=200000, the elastic-limit strain is
    e_y = SIGY0/E = 1.25e-3, so the first 8 increments stay elastic and
    subsequent increments enter linear hardening.
    """
    dstran_per_increment = (1.5e-4, 0.0, 0.0, 0.0, 0.0, 0.0)
    n_increments = 20
    return LoadingPath(
        name="uniaxial_tension_softwarex",
        increments=tuple(dstran_per_increment for _ in range(n_increments)),
    )


@dataclass
class IncrementRecord:
    increment: int
    stress: tuple[float, ...]
    statev: tuple[float, ...]
    ddsdde: tuple[tuple[float, ...], ...]
    yielded: bool
    dgamma: float


def run_path(params: J2Parameters, path: LoadingPath) -> list[IncrementRecord]:
    """Integrate a full loading path and record every increment."""
    state = J2State()
    records: list[IncrementRecord] = []
    for idx, dstran in enumerate(path.increments, start=1):
        result = integrate_increment(params, state, dstran)
        records.append(
            IncrementRecord(
                increment=idx,
                stress=result.stress,
                statev=result.statev,
                ddsdde=result.ddsdde,
                yielded=result.yielded,
                dgamma=result.dgamma,
            )
        )
        state = J2State(stress=result.stress, statev=result.statev, stran=result.stran)
    return records
