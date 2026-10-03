"""Routine-level loading paths that exercise what a corpus UMAT is for.

A loading path here is a sequence of UMAT calls a *driver* makes -- not an
Abaqus deck. Each :class:`Increment` is exactly what one call is handed:
the strain increment ``DSTRAN`` (Voigt, ENGINEERING shear, Abaqus order
11,22,33,12,13,23 truncated to NTENS), the deformation gradient at the END of
the increment ``DFGRD1`` for a finite-strain routine, ``DTIME``, ``TEMP`` and
``DTEMP``. Everything a driver additionally needs (``DFGRD0``, ``DROT``, the
time) follows from the sequence: see :func:`dfgrd0_of`, :func:`drot_of`,
:func:`time_of` and :func:`kinematics_between`.

What is generated depends on the behaviour the model actually has, read from
the reviewed family classification (``corpus_run/material_families_checked_E``)
and from the registry fields NTENS, kinematics, time_dependent and
activation_amplitude:

* every family gets an ``elastic`` path (small amplitude, out and back);
* dissipative families get ``plastic`` (monotonic past activation),
  ``unload_reload`` and ``cyclic`` (two full tension-compression cycles,
  which is what separates kinematic from isotropic hardening);
* rate-dependent families get ``relaxation`` (ramp then hold) and a pair of
  ramps at two rates;
* growth families get ``growth`` paths driven by the clock (no deformation,
  and a held stretch);
* finite-strain routines get simple shear, uniaxial stretch and a
  rotation-superposed twin for objectivity, all through ``DFGRD1``;
* families whose material is isotropic get a rotated twin of a general path
  (isotropy: rotated strain must give rotated stress).

Amplitudes come from the entry's own data, in this order, and every one is
recorded with its provenance in ``LoadingPath.provenance``:

1. a yield strain ``sigma_y / E`` when both constants are identified by NAME
   in the source (``EMOD = PROPS(1)``) -- see :func:`identify_constants`;
2. the registry ``activation_amplitude`` (the amplitude at which the Abaqus
   amplitude search, :mod:`umat_oti.abaqus.amplitude_search`, saw the
   original material activate);
3. otherwise the amplitude is UNKNOWN and said to be: the elastic path uses
   :data:`umat_oti.abaqus.amplitude_search.FIRST_AMPLITUDE` (chosen there as
   below essentially every transition) and the inelastic paths are a
   documented LADDER -- one monotonic path whose increments sweep the strain
   log-uniformly over the same decades the Abaqus search escalates through --
   so whatever transition the model has in that range is crossed. A caller
   with a runner can instead call :func:`search_activation_amplitude`, which
   is the Abaqus search re-used on the routine-level driver.

Nothing here runs a routine and nothing here consults a transformed build: a
path chosen with the conversion in view would be a path chosen to agree.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# the shared interface (agreed with gauss, see corpus_campaign/OWNERSHIP.md)
# ---------------------------------------------------------------------------
REGIMES = ("elastic", "plastic", "unload_reload", "cyclic", "relaxation", "growth")
KINEMATICS = ("small", "finite")

Matrix3 = tuple[
    tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
]


@dataclass(frozen=True)
class Increment:
    """What one UMAT call is handed.

    ``dstran`` is the Voigt strain increment with ENGINEERING shear (gamma =
    2 eps), length NTENS, or None when the routine is driven by ``dfgrd1``
    alone. For finite-strain paths both are given: ``dfgrd1`` is the
    deformation gradient at the end of the increment and ``dstran`` the
    Abaqus-style strain increment derived from it (:func:`kinematics_between`).
    """

    dstran: tuple[float, ...] | None
    dfgrd1: Matrix3 | None
    dtime: float
    temp: float
    dtemp: float


@dataclass(frozen=True)
class LoadingPath:
    """One driver-level loading path and why it is the one it is.

    The first four fields are the shared interface. The rest default so that
    a consumer that only knows the interface keeps working:

    ``purpose``     what the path is for: ``response`` or one half of a pair
                    (``objectivity_reference``/``objectivity_rotated``,
                    ``isotropy_reference``/``isotropy_rotated``,
                    ``rate_slow``/``rate_fast``), or ``outside_model_domain``
                    when the path's clock leaves the range its author
                    documented (no verdict; see :func:`model_domain`).
    ``twin``        the name of the other half of a pair.
    ``rotation``    the constant rotation R of an isotropy twin, or the FINAL
                    rotation Q(1) of an objectivity twin (Q(s) ramps to it).
    ``closed``      True when the path returns to its starting strain / F,
                    so closed-cycle work is defined on it.
    ``provenance``  amplitude, time and temperature, each with its source.
    """

    name: str
    regime: str
    kinematics: str
    increments: list[Increment]
    ntens: int = 6
    ndi: int = 3
    nshr: int = 3
    purpose: str = "response"
    twin: str = ""
    rotation: Matrix3 | None = None
    rotation_angles: tuple[float, ...] = ()
    closed: bool = False
    reversal_at: int | None = None
    amplitude: float = 0.0
    provenance: dict = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        if self.regime not in REGIMES:
            raise ValueError(f"regime {self.regime!r} not in {REGIMES}")
        if self.kinematics not in KINEMATICS:
            raise ValueError(f"kinematics {self.kinematics!r} not in {KINEMATICS}")

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "regime": self.regime,
            "kinematics": self.kinematics,
            "ntens": self.ntens,
            "ndi": self.ndi,
            "nshr": self.nshr,
            "purpose": self.purpose,
            "twin": self.twin,
            "closed": self.closed,
            "reversal_at": self.reversal_at,
            "amplitude": self.amplitude,
            "increments": len(self.increments),
            "provenance": dict(self.provenance),
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Voigt conventions (Abaqus): 11,22,33,12,13,23; plane stress 11,22,12
# ---------------------------------------------------------------------------
_PAIRS = {
    6: ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2)),
    4: ((0, 0), (1, 1), (2, 2), (0, 1)),
    3: ((0, 0), (1, 1), (0, 1)),
}


def layout(ntens: int) -> tuple[int, int]:
    """(NDI, NSHR) for an NTENS the corpus uses (6: 3D, 4: plane strain or
    axisymmetric, 3: plane stress). Anything else is refused, not guessed."""
    if ntens == 6:
        return 3, 3
    if ntens == 4:
        return 3, 1
    if ntens == 3:
        return 2, 1
    raise ValueError(
        f"NTENS={ntens} is not a continuum layout this module drives (6, 4 or 3)"
    )


def voigt_pairs(ntens: int) -> tuple[tuple[int, int], ...]:
    return _PAIRS[ntens]


def tensor_to_voigt(tensor: Any, ntens: int, *, engineering: bool) -> np.ndarray:
    """A symmetric 3x3 tensor as an NTENS Voigt vector.

    ``engineering`` doubles the shear entries (strain); stress uses the plain
    tensor entries. Components NTENS does not carry (the out-of-plane ones)
    are dropped -- they are the routine's to compute, not the driver's.
    """
    t = np.asarray(tensor, dtype=float)
    out = np.zeros(ntens)
    for k, (i, j) in enumerate(_PAIRS[ntens]):
        out[k] = t[i, j] * (2.0 if (engineering and i != j) else 1.0)
    return out


def voigt_to_tensor(
    vector: Sequence[float], ntens: int, *, engineering: bool
) -> np.ndarray:
    """The inverse of :func:`tensor_to_voigt` (missing components are zero)."""
    t = np.zeros((3, 3))
    for k, (i, j) in enumerate(_PAIRS[ntens]):
        value = float(vector[k]) * (0.5 if (engineering and i != j) else 1.0)
        t[i, j] = value
        t[j, i] = value
    return t


def rotation(axis: Sequence[float], angle: float) -> np.ndarray:
    """Rodrigues rotation about ``axis`` by ``angle`` radians."""
    a = np.asarray(axis, dtype=float)
    a = a / np.linalg.norm(a)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * (k @ k)


def admissible_rotation_axis(ntens: int) -> tuple[float, float, float]:
    """A rotation that keeps the NTENS layout closed.

    In 3D a generic axis; in plane strain, axisymmetry and plane stress only a
    rotation about the out-of-plane axis maps in-plane tensors to in-plane
    tensors, so the axis is e3.
    """
    return (1.0, 2.0, 3.0) if ntens == 6 else (0.0, 0.0, 1.0)


def _as_matrix3(m: np.ndarray) -> Matrix3:
    return tuple(tuple(float(v) for v in row) for row in m)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# finite-strain kinematics a driver needs beside DFGRD1
# ---------------------------------------------------------------------------
def kinematics_between(f0: Any, f1: Any, ntens: int) -> tuple[np.ndarray, np.ndarray]:
    """(DSTRAN, DROT) for an increment from F0 to F1, the way Abaqus forms them.

    The rate of deformation and spin are taken at the midpoint configuration,
    ``L dt = (F1 - F0) F_mid^-1``; DSTRAN is ``sym(L dt)`` with engineering
    shear, DROT the Hughes-Winget increment ``(I - W/2)^-1 (I + W/2)`` with
    ``W = skew(L dt)``. This is the central-difference approximation Abaqus
    documents for NLGEOM (log strain increment, rotation increment); it is
    exact for coaxial stretches and second order otherwise.
    """
    f0 = np.asarray(f0, dtype=float)
    f1 = np.asarray(f1, dtype=float)
    lmid = (f1 - f0) @ np.linalg.inv(0.5 * (f0 + f1))
    d = 0.5 * (lmid + lmid.T)
    w = 0.5 * (lmid - lmid.T)
    eye = np.eye(3)
    drot = np.linalg.solve(eye - 0.5 * w, eye + 0.5 * w)
    return tensor_to_voigt(d, ntens, engineering=True), drot


def dfgrd0_of(path: LoadingPath, index: int) -> np.ndarray:
    """DFGRD0 of increment ``index``: the previous DFGRD1, or the identity."""
    for k in range(index - 1, -1, -1):
        if path.increments[k].dfgrd1 is not None:
            return np.asarray(path.increments[k].dfgrd1, dtype=float)
    return np.eye(3)


def drot_of(path: LoadingPath, index: int) -> np.ndarray:
    """DROT of increment ``index`` (identity for small-strain paths)."""
    inc = path.increments[index]
    if inc.dfgrd1 is None:
        return np.eye(3)
    return kinematics_between(dfgrd0_of(path, index), inc.dfgrd1, path.ntens)[1]


def time_of(path: LoadingPath, index: int) -> tuple[float, float]:
    """(TIME(1), TIME(2)) at the START of increment ``index``; one step."""
    t = sum(inc.dtime for inc in path.increments[:index])
    return t, t


def total_strain(path: LoadingPath) -> list[np.ndarray]:
    """Total Voigt strain (engineering shear) at the END of each increment."""
    acc = np.zeros(path.ntens)
    out = []
    for inc in path.increments:
        if inc.dstran is not None:
            acc = acc + np.asarray(inc.dstran, dtype=float)
        out.append(acc.copy())
    return out


# ---------------------------------------------------------------------------
# reading the entry's own data
# ---------------------------------------------------------------------------
#: Names an author gives an elastic or plastic constant, by role. Matched
#: whole-name, case-insensitively, on the left of ``NAME = PROPS(i)``.
_ROLE_NAMES: dict[str, tuple[str, ...]] = {
    "E": ("E", "EMOD", "YOUNG", "YOUNGS", "E0", "EE", "YM", "EYOUNG"),
    "nu": ("NU", "XNU", "ENU", "ANU", "POISSON", "PR", "V", "XNUE"),
    "sigma_y": (
        "SYIELD",
        "SIGY",
        "SIGY0",
        "SIGMAY",
        "SIGMA_Y",
        "SIG_Y",
        "SY0",
        "SY",
        "YIELD",
        "SIGYIELD",
        "S_Y",
        "SIGMA0",
    ),
    "H": ("H", "HARD", "HMOD", "EH", "HISO", "HARDENING"),
    "mu": ("MU", "G", "GMOD", "SHEAR"),
    "lambda": ("LAM", "LAMBDA", "XLAMBDA", "LAME"),
    "K": ("K", "BULK", "KAPPA", "XK", "EBULK"),
    "C10": ("C10",),
    "D1": ("D1",),
    "eta": ("ETA", "VISC", "VISCOSITY"),
    "critical_stretch": ("TCR", "LAMCR", "THCR", "LCRIT", "CRIT"),
}

#: A trailing comment that says the constant is NOT the plain quantity its
#: name suggests (``Sy=props(3) ! Yield stress multiplier`` in a power law).
_QUALIFIED = re.compile(
    r"multiplier|coefficient|factor|ratio of|exponent", re.IGNORECASE
)

_ASSIGN_FROM_PROPS = re.compile(
    r"^\s*(?:\d+\s+)?([A-Za-z_]\w*)\s*=\s*(?:(?:D?MIN|D?MAX)\s*\(\s*)?"
    r"PROPS\s*\(\s*(\d+)\s*\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Constant:
    """A material constant identified by the name the source gives it."""

    role: str
    value: float
    index: int
    evidence: str


def _code_lines(text: str) -> list[tuple[int, str, str]]:
    """(line number, code, trailing comment) for every line, form-aware.

    Fixed form marks a comment with C, c, * or ! in column 1; free form only
    with !. The form is read from the content (umat_oti.corpus), so a free-form
    ``C10 = PROPS(1)`` starting in column 1 is code, not a comment.
    """
    from umat_oti.corpus import detect_source_form

    free = str(detect_source_form(text)).lower().startswith("free")
    out = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not free and raw[:1] in ("c", "C", "*", "!"):
            out.append((number, "", raw))
            continue
        code, _, comment = raw.partition("!")
        out.append((number, code, comment))
    return out


def identify_constants(source_text: str, props: Sequence[float]) -> dict[str, Constant]:
    """Which PROPS entries are which physical constant, by the source's names.

    Only ``NAME = PROPS(i)`` (optionally wrapped in MIN/MAX) counts, and only
    when NAME is one an author uses for that quantity and no trailing comment
    qualifies it. The first assignment wins. A role that cannot be identified
    is simply absent: an unknown constant is never filled in from a guess.
    """
    found: dict[str, Constant] = {}
    if not source_text or not props:
        return found
    lookup = {name: role for role, names in _ROLE_NAMES.items() for name in names}
    for number, code, comment in _code_lines(source_text):
        if not code.strip():
            continue
        for statement in code.split(";"):
            match = _ASSIGN_FROM_PROPS.match(statement)
            if not match:
                continue
            name, index = match.group(1).upper(), int(match.group(2))
            role = lookup.get(name)
            if role is None or role in found:
                continue
            if _QUALIFIED.search(comment or ""):
                continue
            if not 1 <= index <= len(props):
                continue
            found[role] = Constant(
                role,
                float(props[index - 1]),
                index,
                f"line {number}: {statement.strip()}",
            )
    return found


def elastic_moduli(constants: Mapping[str, Constant]) -> dict | None:
    """Isotropic (E, nu, mu, lambda, K) from whichever pair was identified.

    Small-strain limits of the finite-strain conventions are used where the
    names are those of a hyperelastic potential: Abaqus's neo-Hookean
    ``mu0 = 2 C10``, ``K0 = 2 / D1``.
    """
    c = {k: v.value for k, v in constants.items()}
    basis = []
    e = nu = None
    if "E" in c and "nu" in c:
        e, nu = c["E"], c["nu"]
        basis = [constants["E"].evidence, constants["nu"].evidence]
    elif "lambda" in c and "mu" in c:
        lam, mu = c["lambda"], c["mu"]
        if mu > 0 and lam + mu != 0:
            e = mu * (3 * lam + 2 * mu) / (lam + mu)
            nu = lam / (2 * (lam + mu))
            basis = [constants["lambda"].evidence, constants["mu"].evidence]
    elif "C10" in c and "D1" in c and c["D1"] > 0:
        mu, k = 2.0 * c["C10"], 2.0 / c["D1"]
        e = 9 * k * mu / (3 * k + mu)
        nu = (3 * k - 2 * mu) / (2 * (3 * k + mu))
        basis = [
            constants["C10"].evidence,
            constants["D1"].evidence,
            "small-strain limit of Abaqus neo-Hookean: mu0=2*C10, K0=2/D1",
        ]
    elif "mu" in c and "K" in c:
        mu, k = c["mu"], c["K"]
        e = 9 * k * mu / (3 * k + mu)
        nu = (3 * k - 2 * mu) / (2 * (3 * k + mu))
        basis = [constants["mu"].evidence, constants["K"].evidence]
    if e is None or nu is None or not (e > 0) or not (-1.0 < nu < 0.5):
        return None
    mu = e / (2 * (1 + nu))
    lam = e * nu / ((1 + nu) * (1 - 2 * nu))
    return {
        "E": e,
        "nu": nu,
        "mu": mu,
        "lambda": lam,
        "K": e / (3 * (1 - 2 * nu)),
        "basis": basis,
    }


def hooke_matrix(e: float, nu: float, ntens: int) -> np.ndarray:
    """The isotropic elastic DDSDDE for this NTENS (engineering shear).

    NTENS=3 is PLANE STRESS (E/(1-nu^2) form); NTENS=4 plane strain /
    axisymmetric (3D law restricted); NTENS=6 full 3D.
    """
    mu = e / (2 * (1 + nu))
    lam = e * nu / ((1 + nu) * (1 - 2 * nu))
    if ntens == 3:
        f = e / (1 - nu * nu)
        return np.array([[f, f * nu, 0.0], [f * nu, f, 0.0], [0.0, 0.0, mu]])
    d = np.zeros((ntens, ntens))
    d[:3, :3] = lam
    for i in range(3):
        d[i, i] = lam + 2 * mu
    for i in range(3, ntens):
        d[i, i] = mu
    return d


# ---------------------------------------------------------------------------
# family -> behaviours
# ---------------------------------------------------------------------------
#: What each reviewed family is expected to do, and therefore which regimes
#: its paths must exercise. ``isotropic`` is the default material-symmetry
#: expectation, overridden by anisotropy evidence (see :func:`is_isotropic`).
FAMILY_BEHAVIOUR: dict[str, dict] = {
    "elasticity": {
        "regimes": ("elastic",),
        "dissipative": False,
        "reversible": True,
        "isotropic": True,
    },
    "hyperelasticity": {
        "regimes": ("elastic",),
        "dissipative": False,
        "reversible": True,
        "isotropic": True,
    },
    "plasticity": {
        "regimes": ("elastic", "plastic", "unload_reload", "cyclic"),
        "dissipative": True,
        "reversible": False,
        "isotropic": True,
    },
    "crystal plasticity": {
        "regimes": ("elastic", "plastic", "unload_reload", "cyclic"),
        "dissipative": True,
        "reversible": False,
        "isotropic": False,
    },
    "damage / phase field": {
        "regimes": ("elastic", "plastic", "unload_reload", "cyclic"),
        "dissipative": True,
        "reversible": False,
        "isotropic": True,
    },
    "viscoelasticity / rate dependent": {
        "regimes": ("elastic", "plastic", "unload_reload", "cyclic", "relaxation"),
        "dissipative": True,
        "reversible": False,
        "isotropic": True,
    },
    "concrete / geomaterials": {
        "regimes": ("elastic", "plastic", "unload_reload", "cyclic"),
        "dissipative": True,
        "reversible": False,
        "isotropic": True,
    },
    "growth / morphoelasticity": {
        "regimes": ("elastic", "growth"),
        "dissipative": False,
        "reversible": False,
        "isotropic": True,
    },
    "other / unclassified": {
        "regimes": ("elastic", "plastic", "unload_reload", "cyclic"),
        "dissipative": None,
        "reversible": None,
        "isotropic": None,
    },
}

_ANISOTROPY = re.compile(
    r"transverse|aniso|ortho|fib(?:er|re)|crystal|slip|cubic|lamina|ply|"
    r"composite|\bA0\b|\bM0\b|\bN0\b",
    re.IGNORECASE,
)


def behaviour(entry: Mapping) -> dict:
    """The family behaviour record for an entry (unknown family -> 'other')."""
    family = str(entry.get("family") or "other / unclassified")
    return FAMILY_BEHAVIOUR.get(family, FAMILY_BEHAVIOUR["other / unclassified"])


def is_isotropic(entry: Mapping) -> tuple[bool | None, str]:
    """Whether the material is expected to be isotropic, and why.

    True only when the family is isotropic by default AND neither the source
    FILE path (the part after the repository directory -- a repository named
    ``...CompositesInstitute`` says nothing about one file in it) nor the
    source code carries an anisotropy marker (fibre direction, transverse,
    orthotropic, crystal, ply ...). Growth laws are often directional, so a
    growth source is expected isotropic only when its file names itself
    isotropic (``iso``). Unknown -> None.
    """
    family = str(entry.get("family") or "")
    sid = str(entry.get("source_id") or "")
    local = sid.split("/", 1)[1] if "/" in sid else sid
    if family.startswith("growth"):
        if re.search(
            r"(?:^|[^a-z])iso", local, re.IGNORECASE
        ) and not _ANISOTROPY.search(local):
            return True, f"growth source whose file names itself isotropic ({local!r})"
        return None, (
            "growth laws are often directional and this file does "
            "not name itself isotropic"
        )
    expected = behaviour(entry).get("isotropic")
    if expected is None:
        return None, f"family {family!r} carries no symmetry expectation"
    if not expected:
        return False, f"family {family!r} is anisotropic by nature"
    marker = _ANISOTROPY.search(local)
    if marker:
        return False, f"source file path names an anisotropy marker {marker.group(0)!r}"
    text = str(entry.get("source_text") or "")
    if text:
        code = "\n".join(c for _, c, _ in _code_lines(text))
        marker = _ANISOTROPY.search(code)
        if marker:
            return False, (
                f"source code carries an anisotropy marker {marker.group(0)!r}"
            )
    return True, (
        f"family {family!r} is isotropic by default and no "
        f"anisotropy marker was found in the file path"
        + (" or code" if text else " (source text not supplied)")
    )


def reads_deformation_gradient(source_text: str) -> bool | None:
    """Whether an executable statement uses DFGRD1 (a total-F law).

    Declarations and the argument list are excluded
    (:func:`umat_oti.abaqus.experiment._executable`), because every UMAT
    names DFGRD1 whether or not it reads it. None when there is no text.
    """
    if not source_text:
        return None
    from umat_oti.abaqus.experiment import _executable

    return bool(re.search(r"\bDFGRD1\b", _executable(source_text), re.IGNORECASE))


def is_finite(entry: Mapping) -> bool:
    kin = str(entry.get("kinematics") or "").lower()
    return kin.startswith("finite") or kin == "nlgeom"


def is_rate_dependent(entry: Mapping) -> tuple[bool, str]:
    family = str(entry.get("family") or "")
    if family.startswith("viscoelasticity"):
        return True, "reviewed family is viscoelasticity / rate dependent"
    text = str(entry.get("source_text") or "")
    if text and re.search(r"/\s*DTIME\b", text, re.IGNORECASE):
        return True, "the source divides by DTIME"
    return False, "neither the family nor the source says rate"


# ---------------------------------------------------------------------------
# amplitudes, with provenance
# ---------------------------------------------------------------------------
#: Same constants the Abaqus search uses, so a routine-level ladder covers
#: exactly the decades the solver-level search would have.
from umat_oti.abaqus.amplitude_search import (
    CEILING as SEARCH_CEILING,
)
from umat_oti.abaqus.amplitude_search import (
    FIRST_AMPLITUDE,
)
from umat_oti.abaqus.amplitude_search import (
    GROWTH as SEARCH_GROWTH,
)

#: The ladder stops a decade below the search ceiling: past 10% a
#: small-strain routine is outside its own formulation.
LADDER_TOP = 0.1

#: A finite-strain path has to depart from the identity by more than a
#: linearisation can absorb. experiment.MEANINGFUL_ACTIVATION['finite strain']
#: asks for at least 2%; 20% puts the geometric terms (order a^2) at 4% of the
#: response, well above every tolerance the checks use. This is a kinematic
#: requirement, not a material datum, and is recorded as such.
FINITE_AMPLITUDE = 0.2


@dataclass(frozen=True)
class Amplitudes:
    elastic: float
    inelastic: float | None
    finite: float
    ladder: bool
    provenance: dict


def amplitudes(entry: Mapping) -> Amplitudes:
    """Elastic, inelastic and finite amplitudes for this entry, with sources."""
    props = list(entry.get("props") or ())
    constants = identify_constants(str(entry.get("source_text") or ""), props)
    moduli = elastic_moduli(constants)
    prov: dict[str, str] = {}
    eps_y = None
    if moduli and "sigma_y" in constants and constants["sigma_y"].value > 0:
        eps_y = constants["sigma_y"].value / moduli["E"]
        prov["yield_strain"] = (
            f"sigma_y/E = {constants['sigma_y'].value:g}/"
            f"{moduli['E']:g} = {eps_y:.4g} "
            f"({constants['sigma_y'].evidence}; "
            f"{'; '.join(moduli['basis'])})"
        )
    act = entry.get("activation_amplitude")
    act = float(act) if act not in (None, "", 0) else None
    if eps_y:
        elastic = 0.25 * eps_y
        inelastic: float | None = 5.0 * eps_y
        prov["elastic"] = "0.25 x identified yield strain"
        prov["inelastic"] = "5 x identified yield strain"
        ladder = False
    elif act:
        elastic = 0.1 * act
        inelastic = 2.0 * act
        prov["elastic"] = (
            f"one decade below the registry activation_amplitude "
            f"{act:g} (Abaqus amplitude search on the original)"
        )
        prov["inelastic"] = (
            f"2 x registry activation_amplitude {act:g}; note "
            f"the registry value is the amplitude the search "
            f"settled on, which for a model that never "
            f"activates is its probe amplitude, not a "
            f"transition"
        )
        ladder = False
    else:
        elastic = FIRST_AMPLITUDE
        inelastic = None
        prov["elastic"] = (
            f"UNKNOWN material scale: amplitude_search."
            f"FIRST_AMPLITUDE={FIRST_AMPLITUDE:g}, chosen there "
            f"as below essentially every transition"
        )
        prov["inelastic"] = (
            f"UNKNOWN: no yield strain identifiable and no "
            f"registry activation_amplitude; inelastic paths "
            f"are a LADDER sweeping {FIRST_AMPLITUDE:g}.."
            f"{LADDER_TOP:g} log-uniformly (the decades "
            f"amplitude_search escalates through, factor "
            f"{SEARCH_GROWTH:g}, ceiling {SEARCH_CEILING:g} "
            f"clipped at {LADDER_TOP:g}); or call "
            f"search_activation_amplitude() with a runner"
        )
        ladder = True
    finite = max(FINITE_AMPLITUDE, inelastic or 0.0)
    prov["finite"] = (
        f"{finite:g}: kinematic requirement (>= 2% per "
        f"experiment.MEANINGFUL_ACTIVATION['finite strain'], "
        f"x10 so geometric terms exceed check tolerances)"
    )
    if moduli:
        prov["moduli"] = "; ".join(moduli["basis"])
    return Amplitudes(elastic, inelastic, finite, ladder, prov)


# ---------------------------------------------------------------------------
# the model's documented domain
# ---------------------------------------------------------------------------
#: A path whose clock or amplitude leaves the domain the author documented is
#: still emitted -- the reader sees it was considered -- but with this
#: purpose, and the checks give it no verdict.
OUTSIDE_MODEL_DOMAIN = "outside_model_domain"

_IF_THEN = re.compile(r"^(?:\d+\s+)?IF\s*\((?P<cond>.*)\)\s*THEN$", re.IGNORECASE)
_ELSE_IF = re.compile(r"^ELSE\s*IF\s*\((?P<cond>.*)\)\s*THEN$", re.IGNORECASE)
_ELSE = re.compile(r"^ELSE$", re.IGNORECASE)
_END_IF = re.compile(r"^(?:\d+\s+)?END\s*IF\b", re.IGNORECASE)
_ASSIGN = re.compile(r"^(?:\d+\s+)?([A-Za-z_]\w*)\s*(?:\([^=]*\))?\s*=(?!=)")
_ROUTINE = re.compile(
    r"^(?:[A-Za-z*0-9 ]*\s)?(?:SUBROUTINE|FUNCTION|PROGRAM)\s+([A-Za-z_]\w*)",
    re.IGNORECASE,
)
_NUMBER = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?)"
_UPPER = re.compile(r"(?:\.LE\.|\.LT\.|<=|<)\s*" + _NUMBER, re.IGNORECASE)
_LOWER = re.compile(r"(?:\.GE\.|\.GT\.|>=|>)\s*" + _NUMBER, re.IGNORECASE)
_TIME_TEST = re.compile(r"\bTIME\s*\(\s*[12]\s*\)", re.IGNORECASE)
_STRAIN_TEST = re.compile(
    r"\b(?:D?STRAN|DFGRD[01]|STRETCH\w*|LAMBDA\w*|LAM\w*|EPS\w*|STRAIN\w*|DETF|"
    r"AJ|DET)\b",
    re.IGNORECASE,
)


def _statements(text: str) -> list[tuple[int, str]]:
    """(first line number, statement) with comments stripped and
    continuation lines joined, fixed or free form."""
    from umat_oti.corpus import detect_source_form

    free = str(detect_source_form(text)).lower().startswith("free")
    out: list[list] = []
    pending_free = False
    for number, raw in enumerate(text.splitlines(), start=1):
        if not free and raw[:1] in ("c", "C", "*", "!"):
            continue
        if (
            not free
            and len(raw) > 5
            and raw[5] not in (" ", "0")
            and raw[:5].strip() == ""
        ):
            if out:
                out[-1][1] += " " + raw[6:].split("!")[0].strip()
            continue
        code = raw.split("!")[0]
        if free and pending_free and out:
            out[-1][1] += " " + code.strip().lstrip("&")
        elif code.strip():
            out.append([number, code.strip()])
        else:
            continue
        pending_free = free and out[-1][1].rstrip().endswith("&")
        if pending_free:
            out[-1][1] = out[-1][1].rstrip()[:-1]
    return [(n, " ".join(c.split())) for n, c in out]


@dataclass(frozen=True)
class PiecewiseChain:
    """An IF / ELSE IF chain that defines a variable piecewise and has no ELSE.

    Outside the ranges its conditions cover, every variable it defines keeps
    whatever it held before -- an uninitialised local if nothing assigned it
    earlier, which is undefined behaviour of the ORIGINAL routine.
    """

    routine: str
    first_line: int
    last_line: int
    tested: str
    defines: tuple[str, ...]
    upper: float | None
    lower: float | None
    on_time: bool
    initialised_before: tuple[str, ...]
    conditions: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "routine": self.routine,
            "lines": f"{self.first_line}-{self.last_line}",
            "tested": self.tested,
            "defines": list(self.defines),
            "upper": self.upper,
            "lower": self.lower,
            "on_time": self.on_time,
            "initialised_before": list(self.initialised_before),
            "conditions": list(self.conditions),
        }


def _as_float(text: str) -> float:
    return float(text.replace("D", "E").replace("d", "e"))


def piecewise_chains(source_text: str) -> list[PiecewiseChain]:
    """Every IF / ELSE IF chain with no ELSE that assigns the same variable in
    every branch, with the range its conditions cover. Chains of >= 2
    branches are all listed; a one-branch IF only when it tests the clock or
    a strain measure and its variable had no value before it.

    ``Jeff97 .../BodyForce-Growth-2Stages.for`` (2.2 variant)::

        IF ( (TIME(2)+DTIME) .LE. 1.0) THEN
          G11=1.0 + (G11St1-1.0)*(TIME(2)+DTIME)/TotalT
        ELSE IF ( (TIME(2)+DTIME) .LE. 2.2) THEN
          G11=...
        END IF

    G11 is defined for total time <= 2.2 and is an uninitialised local after.
    """
    statements = _statements(source_text or "")
    chains: list[PiecewiseChain] = []
    routine, routine_start = "", 0
    assigned_at: dict[str, list[int]] = {}
    stack: list[dict] = []
    dummies: set[str] = set()
    for index, (line, stmt) in enumerate(statements):
        found = _ROUTINE.match(stmt)
        if found and not stmt.upper().startswith("END"):
            routine, routine_start = found.group(1).upper(), index
            assigned_at = {}
            stack = []
            inside = stmt[stmt.find("(") + 1 : stmt.rfind(")")] if "(" in stmt else ""
            # A dummy argument arrives with the caller's value: assigning it
            # on a range leaves it at that value elsewhere, never undefined.
            dummies = {a.strip().upper() for a in inside.split(",") if a.strip()}
            continue
        opened = _IF_THEN.match(stmt)
        if opened:
            stack.append(
                {
                    "line": line,
                    "conds": [opened.group("cond").strip()],
                    "branches": [set()],
                    "else": False,
                }
            )
            continue
        if stack and _ELSE_IF.match(stmt):
            stack[-1]["conds"].append(_ELSE_IF.match(stmt).group("cond").strip())
            stack[-1]["branches"].append(set())
            continue
        if stack and _ELSE.match(stmt):
            stack[-1]["else"] = True
            stack[-1]["branches"].append(set())
            continue
        if stack and _END_IF.match(stmt):
            block = stack.pop()
            if stack:  # assignments inside count for the enclosing branch too
                for branch in block["branches"]:
                    stack[-1]["branches"][-1] |= branch
            if block["else"]:
                continue
            on_time = all(_TIME_TEST.search(c) for c in block["conds"])
            strain_like = all(_STRAIN_TEST.search(c) for c in block["conds"])
            # A one-branch IF defines its variables on a range too; it is
            # listed only when it tests the clock or a strain measure and the
            # variable had no value before it, which is the G11 pattern.
            single = len(block["conds"]) < 2
            common = (
                set.intersection(*block["branches"]) if block["branches"] else set()
            )
            common -= dummies
            if not common:
                continue
            if single and not (on_time or strain_like):
                continue
            uppers = [_as_float(v) for c in block["conds"] for v in _UPPER.findall(c)]
            lowers = [_as_float(v) for c in block["conds"] for v in _LOWER.findall(c)]
            tested = re.sub(
                r"\s*(?:\.(?:LE|LT|GE|GT|EQ|NE)\.|<=|>=|<|>|==).*$",
                "",
                block["conds"][0],
                flags=re.IGNORECASE,
            ).strip("( )")
            before = tuple(
                sorted(
                    name
                    for name in common
                    if any(at < block["line"] for at in assigned_at.get(name, []))
                )
            )
            if single and before:
                continue
            chains.append(
                PiecewiseChain(
                    routine=routine,
                    first_line=block["line"],
                    last_line=line,
                    tested=tested,
                    defines=tuple(sorted(common)),
                    upper=max(uppers) if uppers and not lowers else None,
                    lower=min(lowers) if lowers and not uppers else None,
                    on_time=on_time,
                    initialised_before=before,
                    conditions=tuple(block["conds"]),
                )
            )
            continue
        target = _ASSIGN.match(stmt)
        if target and not stmt.upper().startswith(("IF", "DO ", "ELSE")):
            name = target.group(1).upper()
            assigned_at.setdefault(name, []).append(line)
            if stack:
                stack[-1]["branches"][-1].add(name)
    del routine_start
    return chains


def _positive(values) -> list[float]:
    return [float(v) for v in (values or ()) if float(v or 0) > 0]


def _step_periods(entry: Mapping) -> tuple[list[float], str]:
    """The step periods that bound the clock, and the label they are cited by.

    ``experiment_periods`` are the periods of the GENERATED experiment (the
    Abaqus probe's segments, :func:`harness.resolve_entry`); they are cited as
    the author's deck only when ``author_deck_periods`` was recorded and is the
    same list. ``deck_periods`` is a caller's statement that the periods ARE
    the author's ``*STEP`` times. The numbers are used as they come either way:
    which label applies never changes the bound (G0, D-19a rev 2).
    """
    if "experiment_periods" in entry:
        periods = _positive(entry.get("experiment_periods"))
        author = entry.get("author_deck_periods")
        if author is not None and _positive(author) == periods:
            return periods, "author's deck: step periods "
        why = (
            "the author's deck periods were not recorded"
            if author is None
            else "the author's deck runs "
            + (", ".join(f"{v:g}" for v in _positive(author)) or "no timed step")
        )
        return periods, f"periods of the generated experiment ({why}): "
    return _positive(entry.get("deck_periods")), "author's deck: step periods "


def model_domain(entry: Mapping) -> dict:
    """The time range the author documented for this model, with provenance.

    Two witnesses, the tighter wins, and both are recorded:

    * the step periods: ``deck_periods`` (the author's ``*STEP`` times) or
      ``experiment_periods`` (the generated experiment's segments, cited as
      the author's deck only when ``author_deck_periods`` matches them; see
      :func:`_step_periods`) sum to a total time;
    * the source: an IF/ELSE IF chain on TIME with no ELSE defines its
      variables only up to its last bound -- past it they are undefined (or
      stale) in the ORIGINAL routine.

    Non-time chains without ELSE are recorded (``unbounded_branches``) and not
    enforced: whether their tested quantity is reachable from a strain path is
    not decidable by reading, and refusing on a guess would hide paths.
    """
    periods, label = _step_periods(entry)
    limits: list[tuple[float, str]] = []
    if periods:
        limits.append(
            (
                sum(periods),
                (
                    label
                    + ", ".join(f"{v:g}" for v in periods)
                    + f" (total {sum(periods):g})"
                ),
            )
        )
    chains = piecewise_chains(str(entry.get("source_text") or ""))
    for chain in chains:
        # Only a PIECEWISE law in time (>= 2 branches, ascending upper bounds,
        # a positive last bound) documents a range. A one-branch
        # ``IF (TIME(1)-DTIME .LT. 0)`` is a first-call initialisation, not a
        # domain, and enforcing it would put every path outside.
        if (
            chain.on_time
            and len(chain.conditions) >= 2
            and chain.upper is not None
            and chain.upper > 0
            and not chain.initialised_before
        ):
            limits.append(
                (
                    chain.upper,
                    (
                        f"source {chain.routine} lines {chain.first_line}-{chain.last_line}: "
                        f"{', '.join(chain.defines)} defined only for {chain.tested} <= "
                        f"{chain.upper:g} (IF/ELSE IF with no ELSE)"
                    ),
                )
            )
    domain = {
        "time_max": None,
        "time_provenance": "no documented time range (no deck periods, no "
        "un-ELSEd time chain in the source)",
        "witnesses": [f"{value:g}: {why}" for value, why in limits],
        "unbounded_branches": [c.as_dict() for c in chains if not c.on_time],
    }
    if limits:
        value, why = min(limits, key=lambda item: item[0])
        domain["time_max"] = value
        domain["time_provenance"] = why
    # The kinematic and thermal domain the author DOCUMENTED (a harvest row's
    # ``documented_domain``, D-19a rev 2 R3): each witness is the stated
    # value with where it was stated. Absent, nothing is enforced.
    documented = entry.get("documented_domain") or {}
    for key in ("strain_max", "stretch_max", "temperature"):
        stated = documented.get(key)
        if not stated or stated.get("value") is None:
            continue
        value = stated["value"]
        where = f"{stated.get('where', '')}: {stated.get('quote', '')}".strip(": ")
        try:
            if key == "temperature":
                low, high = (
                    (float(value[0]), float(value[1]))
                    if isinstance(value, (list, tuple))
                    else (float(value), float(value))
                )
            else:
                number = float(value)
        except (TypeError, ValueError, IndexError):
            # a statement in words ("500 increments of -0.001, up to -0.5")
            # is recorded and not enforced: reading a bound out of prose would
            # be choosing it
            domain["witnesses"].append(f"{key} not a number, not enforced: {str(value)[:120]}"
                                       f" ({where})")
            continue
        if key == "temperature":
            domain["temperature"] = (low, high)
            text = f"{low:g}" if low == high else f"{low:g}..{high:g}"
        else:
            domain[key] = number
            text = f"{number:g}"
        domain[f"{key}_provenance"] = where
        domain["witnesses"].append(f"{key} {text}: {where}")
    return domain


def _peaks(path: LoadingPath) -> tuple[float, float, float, float]:
    """Peak |strain component|, peak stretch, lowest and highest TEMP+DTEMP
    over the path. A finite path's stretch is max(lambda_max, 1/lambda_min)
    of DFGRD1 and its strain max |lambda - 1|; a small-strain path's strain
    is its total Voigt strain and its stretch 1 + that."""
    strain = stretch = 0.0
    temps = []
    if all(inc.dfgrd1 is not None for inc in path.increments) and path.increments:
        for inc in path.increments:
            lam = np.linalg.svd(np.asarray(inc.dfgrd1, float), compute_uv=False)
            stretch = max(stretch, float(lam.max()), 1.0 / max(float(lam.min()), 1e-300))
            strain = max(strain, float(np.max(np.abs(lam - 1.0))))
    else:
        for total in total_strain(path):
            strain = max(strain, float(np.max(np.abs(total))) if total.size else 0.0)
        stretch = 1.0 + strain
    for inc in path.increments:
        temps.extend([float(inc.temp), float(inc.temp) + float(inc.dtemp)])
    return strain, stretch, min(temps, default=0.0), max(temps, default=0.0)


def _clock(entry: Mapping) -> tuple[float, str]:
    """Step period for the paths, and where it came from."""
    total = entry.get("total_time")
    if total:
        return float(total), f"entry total_time {float(total):g} (manifest requirement)"
    text = str(entry.get("source_text") or "")
    if text:
        from umat_oti.abaqus.time_scale import required_total_time

        req = required_total_time(
            text,
            list(entry.get("props") or ()),
            list(
                (
                    entry.get("experiment_periods")
                    if "experiment_periods" in entry
                    else entry.get("deck_periods")
                )
                or ()
            ),
        )
        if req.declared:
            return req.total_time, f"time_scale.required_total_time: {req.reason}"
    return 1.0, (
        "UNKNOWN time scale: no total_time, no declared scale, no "
        "deck period; using Abaqus's default step period 1.0"
    )


def _temperature(entry: Mapping) -> tuple[float, str]:
    if entry.get("temperature") is not None:
        return float(entry["temperature"]), "entry temperature (author's deck)"
    return 0.0, (
        "no temperature stated; TEMP=0 and DTEMP=0 (isothermal). A "
        "routine that reads TEMP as a field (e.g. non-local damage) "
        "sees zero"
    )


# ---------------------------------------------------------------------------
# building blocks
# ---------------------------------------------------------------------------
def _direction(kind: str, ntens: int) -> np.ndarray:
    """Unit Voigt strain directions (engineering shear)."""
    if kind == "uniaxial":
        v = np.zeros(ntens)
        v[0] = 1.0
        return v
    if kind == "shear":
        v = np.zeros(ntens)
        v[3 if ntens >= 4 else 2] = 1.0
        return v
    if kind == "general":
        full = {
            6: [1.0, -0.4, 0.25, 0.6, 0.35, -0.5],
            4: [1.0, -0.4, 0.25, 0.6],
            3: [1.0, -0.4, 0.6],
        }[ntens]
        return np.asarray(full, dtype=float)
    raise ValueError(kind)


def _small_increments(
    targets: Sequence[np.ndarray], per_leg: int, dtime: float, temp: float
) -> list[Increment]:
    """Linear legs between successive total-strain targets (start at 0)."""
    incs: list[Increment] = []
    prev = np.zeros_like(targets[0])
    for target in targets:
        step = (np.asarray(target) - prev) / per_leg
        for _ in range(per_leg):
            incs.append(
                Increment(tuple(float(x) for x in step), None, dtime, temp, 0.0)
            )
        prev = np.asarray(target)
    return incs


def _finite_increments(
    gradients: Sequence[np.ndarray], ntens: int, dtime: float, temp: float
) -> list[Increment]:
    incs: list[Increment] = []
    prev = np.eye(3)
    for f in gradients:
        dstran, _ = kinematics_between(prev, f, ntens)
        incs.append(
            Increment(tuple(float(x) for x in dstran), _as_matrix3(f), dtime, temp, 0.0)
        )
        prev = f
    return incs


def _small_increments_between(
    start: np.ndarray,
    targets: Sequence[np.ndarray],
    per_leg: int,
    dtime: float,
    temp: float,
) -> list[Increment]:
    """Linear legs between successive targets, starting from ``start``."""
    incs: list[Increment] = []
    prev = np.asarray(start, dtype=float)
    for target in targets:
        step = (np.asarray(target) - prev) / per_leg
        for _ in range(per_leg):
            incs.append(
                Increment(tuple(float(x) for x in step), None, dtime, temp, 0.0)
            )
        prev = np.asarray(target)
    return incs


def _ladder(direction: np.ndarray, top: float, per_decade: int = 4) -> list[np.ndarray]:
    lo = math.log10(FIRST_AMPLITUDE)
    hi = math.log10(top)
    n = max(2, round((hi - lo) * per_decade) + 1)
    return [direction * 10 ** (lo + (hi - lo) * k / (n - 1)) for k in range(n)]


def _small_from_strain(eps_voigt: np.ndarray, ntens: int) -> np.ndarray:
    return np.eye(3) + voigt_to_tensor(eps_voigt, ntens, engineering=True)


# ---------------------------------------------------------------------------
# the paths
# ---------------------------------------------------------------------------
PER_LEG = 10
#: How much finer the reverse leg of ``reverse_yield`` is than a cyclic leg.
REVERSE_REFINEMENT = 8
GROWTH_INCREMENTS = 20  # experiment.INCREMENTS["growth"]


def paths_for(entry: Mapping, *, per_leg: int = PER_LEG) -> list[LoadingPath]:
    """Every loading path this entry's behaviour calls for.

    ``entry`` keys read (all optional except ``ntens`` and ``family``):
    ``family`` (reviewed classification), ``ntens``, ``kinematics``,
    ``props``, ``nstatv``, ``time_dependent``, ``activation_amplitude``,
    ``source_text`` (enables constant identification and rate/anisotropy
    evidence), ``total_time`` / ``deck_periods`` / ``experiment_periods``, ``temperature``,
    ``source_id``.

    A family that is not a UMAT gets no path. An NTENS that is not a
    continuum layout raises: refusing is better than driving a routine with
    the wrong number of components.
    """
    family = str(entry.get("family") or "other / unclassified")
    if family == "not a UMAT":
        return []
    ntens = int(entry.get("ntens") or 0)
    ndi, nshr = layout(ntens)
    beh = behaviour(entry)
    amps = amplitudes(entry)
    period, period_prov = _clock(entry)
    domain = model_domain(entry)
    if domain["time_max"] is not None and period > domain["time_max"] * (1 + 1e-9):
        period_prov += (
            f"; shortened from {period:g} to {domain['time_max']:g}, the total "
            f"time the author documented ({domain['time_provenance']}): a path "
            f"is designed inside the model's domain, never run past it"
        )
        period = domain["time_max"]
    temp, temp_prov = _temperature(entry)
    finite = is_finite(entry)
    kin = "finite" if finite else "small"
    iso, iso_basis = is_isotropic(entry)
    rate, rate_basis = is_rate_dependent(entry)
    base_prov = {
        "period": period_prov,
        "temperature": temp_prov,
        "family": family,
        **amps.provenance,
    }
    common = {"ntens": ntens, "ndi": ndi, "nshr": nshr}
    paths: list[LoadingPath] = []

    def mk(
        name,
        regime,
        incs,
        *,
        amplitude,
        description,
        purpose="response",
        twin="",
        rotation=None,
        closed=False,
        reversal_at=None,
        kinematics=kin,
        extra=None,
        rotation_angles=(),
    ):
        prov = dict(base_prov)
        if extra:
            prov.update(extra)
        paths.append(
            LoadingPath(
                name,
                regime,
                kinematics,
                incs,
                **common,
                purpose=purpose,
                twin=twin,
                rotation=(_as_matrix3(rotation) if rotation is not None else None),
                rotation_angles=tuple(rotation_angles),
                closed=closed,
                reversal_at=reversal_at,
                amplitude=amplitude,
                provenance=prov,
                description=description,
            )
        )

    def strain_legs(direction, targets_scalar, n=per_leg, dt=None):
        targets = [direction * s for s in targets_scalar]
        dt = period / (n * len(targets)) if dt is None else dt
        if finite:
            grads = []
            prev = np.zeros(ntens)
            for target in targets:
                for k in range(1, n + 1):
                    grads.append(
                        _small_from_strain(prev + (target - prev) * k / n, ntens)
                    )
                prev = target
            return _finite_increments(grads, ntens, dt, temp)
        return _small_increments(targets, n, dt, temp)

    uni = _direction("uniaxial", ntens)
    shear = _direction("shear", ntens)
    general = _direction("general", ntens)
    general = general / np.linalg.norm(general)
    a_el = amps.elastic

    # -- elastic: out and back, uniaxial and shear (closed: work must vanish
    #    for a reversible model, and stress must return to zero)
    mk(
        "elastic_uniaxial",
        "elastic",
        strain_legs(uni, [a_el, 0.0]),
        amplitude=a_el,
        closed=True,
        reversal_at=per_leg - 1,
        description="uniaxial strain to the elastic amplitude and back to zero",
    )
    mk(
        "elastic_shear",
        "elastic",
        strain_legs(shear, [a_el, 0.0]),
        amplitude=a_el,
        closed=True,
        reversal_at=per_leg - 1,
        description="engineering shear strain to the elastic amplitude and back",
    )

    # -- isotropy pair (small-strain or finite, constant rotation R)
    if iso:
        axis = admissible_rotation_axis(ntens)
        r = rotation(axis, math.radians(35.0))
        amp_iso = (
            amps.inelastic if (amps.inelastic and "plastic" in beh["regimes"]) else a_el
        )
        regime_iso = "plastic" if amp_iso is not a_el else "elastic"
        ref_targets = [general * amp_iso]
        eps_ref = voigt_to_tensor(general * amp_iso, ntens, engineering=True)
        rot_dir = tensor_to_voigt(r @ eps_ref @ r.T, ntens, engineering=True) / amp_iso
        if finite:
            n = per_leg
            gref = [np.eye(3) + eps_ref * k / n for k in range(1, n + 1)]
            grot = [r @ g @ r.T for g in gref]
            inc_ref = _finite_increments(gref, ntens, period / n, temp)
            inc_rot = _finite_increments(grot, ntens, period / n, temp)
        else:
            inc_ref = _small_increments(ref_targets, per_leg, period / per_leg, temp)
            inc_rot = _small_increments(
                [rot_dir * amp_iso], per_leg, period / per_leg, temp
            )
        extra = {
            "isotropy": iso_basis,
            "rotation": f"35 deg about {axis} (layout-preserving for NTENS={ntens})",
        }
        mk(
            "isotropy_reference",
            regime_iso,
            inc_ref,
            amplitude=amp_iso,
            purpose="isotropy_reference",
            twin="isotropy_rotated",
            rotation=r,
            extra=extra,
            description="general (non-coaxial) strain path",
        )
        mk(
            "isotropy_rotated",
            regime_iso,
            inc_rot,
            amplitude=amp_iso,
            purpose="isotropy_rotated",
            twin="isotropy_reference",
            rotation=r,
            extra=extra,
            description="the same path with the strain rotated by R: an "
            "isotropic material must return R sigma R^T",
        )

    # -- inelastic regimes
    if any(r in beh["regimes"] for r in ("plastic", "unload_reload", "cyclic")):
        if amps.ladder:
            targets = _ladder(uni, LADDER_TOP)
            incs = (
                _small_increments_from_targets(targets, period, temp)
                if not finite
                else _finite_increments(
                    [_small_from_strain(t, ntens) for t in targets],
                    ntens,
                    period / len(targets),
                    temp,
                )
            )
            mk(
                "plastic_ladder",
                "plastic",
                incs,
                amplitude=LADDER_TOP,
                description="monotonic uniaxial strain swept log-uniformly over "
                "the amplitude-search decades (material scale unknown)",
            )
            a_in = LADDER_TOP
            a_un = 0.1 * LADDER_TOP
        else:
            a_in = float(amps.inelastic)
            # unload by one yield strain when it is known (a_in = 5 eps_y),
            # which stays elastic for isotropic and kinematic hardening alike
            a_un = a_in / 5.0 if amps.provenance.get("yield_strain") else 0.1 * a_in
            mk(
                "plastic_uniaxial",
                "plastic",
                strain_legs(uni, [a_in]),
                amplitude=a_in,
                description="monotonic uniaxial strain past activation",
            )
            mk(
                "plastic_compression",
                "plastic",
                strain_legs(uni, [-a_in]),
                amplitude=a_in,
                description="monotonic uniaxial compression past activation "
                "(tension/compression asymmetry, geomaterials)",
            )
        # unload/reload: one small first increment (FIRST_AMPLITUDE, below
        # essentially every transition, so the initial elastic slope is
        # measured), load past activation, partial unload, reload, continue.
        if "unload_reload" in beh["regimes"]:
            e0 = min(a_el, FIRST_AMPLITUDE)
            legs = [a_in, a_in - a_un, a_in, 1.5 * a_in]
            # the small first increment is inside the period, not after it
            dt_ur = period / (per_leg * len(legs) + 1)
            if finite:
                grads = [_small_from_strain(uni * e0, ntens)]
                prev = uni * e0
                for target in (uni * s for s in legs):
                    for k in range(1, per_leg + 1):
                        grads.append(
                            _small_from_strain(
                                prev + (target - prev) * k / per_leg, ntens
                            )
                        )
                    prev = target
                incs = _finite_increments(grads, ntens, dt_ur, temp)
            else:
                incs = _small_increments([uni * e0], 1, dt_ur, temp)
                incs += _small_increments_between(
                    uni * e0, [uni * s for s in legs], per_leg, dt_ur, temp
                )
            mk(
                "unload_reload",
                "unload_reload",
                incs,
                amplitude=a_in,
                reversal_at=per_leg,
                extra={
                    "unload_depth": f"{a_un:g} "
                    + (
                        "(= one yield strain: stays elastic for isotropic "
                        "and kinematic hardening)"
                        if amps.provenance.get("yield_strain")
                        else "(a tenth of the loading amplitude: yield strain "
                        "unknown; reverse yielding is detected from the "
                        "state, not assumed away)"
                    ),
                    "first_increment": f"{e0:g} (min(elastic amplitude, FIRST_AMPLITUDE))",
                },
                description="small elastic first increment, load past activation, "
                "partial unload, reload, continue loading",
            )
        if "cyclic" in beh["regimes"]:
            legs = [a_in, -a_in, a_in, -a_in, 0.0]
            mk(
                "cyclic",
                "cyclic",
                strain_legs(uni, legs),
                amplitude=a_in,
                closed=True,
                reversal_at=per_leg - 1,
                description="two full tension-compression cycles and return "
                "to zero strain (kinematic hardening / Bauschinger)",
            )
            # The cyclic path's reverse increments (2 a_in / PER_LEG) are as
            # wide as the elastic range of a typical metal, so the stress at
            # which reverse yielding starts is bracketed only to within that
            # range. This path reverses at REVERSE_REFINEMENT x the
            # resolution so the centre of the elastic range is measured.
            n_rev = REVERSE_REFINEMENT * per_leg
            dt_rev = period / (per_leg + n_rev)
            if finite:
                grads = [
                    _small_from_strain(uni * a_in * k / per_leg, ntens)
                    for k in range(1, per_leg + 1)
                ]
                grads += [
                    _small_from_strain(uni * a_in * (1.0 - 2.0 * k / n_rev), ntens)
                    for k in range(1, n_rev + 1)
                ]
                incs = _finite_increments(grads, ntens, dt_rev, temp)
            else:
                incs = _small_increments([uni * a_in], per_leg, dt_rev, temp)
                incs += _small_increments_between(
                    uni * a_in, [-uni * a_in], n_rev, dt_rev, temp
                )
            mk(
                "reverse_yield",
                "cyclic",
                incs,
                amplitude=a_in,
                reversal_at=per_leg - 1,
                extra={
                    "reverse_resolution": f"{2 * a_in / n_rev:g} strain per "
                    f"increment ({n_rev} increments from +{a_in:g} to -{a_in:g})"
                },
                description="load past activation, then reverse to the same "
                "strain in compression in fine increments (reverse-yield "
                "stress, Bauschinger shift)",
            )

    # -- rate dependence: relaxation hold + two rates
    if rate or "relaxation" in beh["regimes"] or entry.get("time_dependent"):
        a_r = amps.inelastic or amps.elastic
        n = per_leg
        ramp = period / 10.0
        why = (
            rate_basis
            if rate
            else (
                "family lists relaxation"
                if "relaxation" in beh["regimes"]
                else "registry time_dependent=True (the Abaqus run saw the clock matter)"
            )
        )
        if finite:
            ramp_g = [
                _small_from_strain(uni * a_r * k / n, ntens) for k in range(1, n + 1)
            ]
            # hold: DSTRAN 0 and F constant
            incs = _finite_increments(ramp_g, ntens, ramp / n, temp)
            incs += [
                Increment(
                    tuple(0.0 for _ in range(ntens)),
                    _as_matrix3(ramp_g[-1]),
                    0.9 * period / (2 * n),
                    temp,
                    0.0,
                )
                for _ in range(2 * n)
            ]
        else:
            incs = _small_increments([uni * a_r], n, ramp / n, temp) + [
                Increment(
                    tuple(0.0 for _ in range(ntens)),
                    None,
                    0.9 * period / (2 * n),
                    temp,
                    0.0,
                )
                for _ in range(2 * n)
            ]
        mk(
            "relaxation",
            "relaxation",
            incs,
            amplitude=a_r,
            extra={"rate": why, "hold": f"ramp {ramp:g}, hold {0.9 * period:g}"},
            description="ramp in a tenth of the period, then hold the strain "
            "for the rest of it (stress relaxation)",
        )
        # A factor of 100 between the two ramps, both inside the period: the
        # slow one used to take 10 periods, which walks a clocked law past the
        # range its author documented.
        for label, factor in (("rate_slow", 1.0), ("rate_fast", 0.01)):
            dt = factor * period / n
            mk(
                label,
                "relaxation",
                strain_legs(uni, [a_r], dt=dt),
                amplitude=a_r,
                purpose=label,
                twin="rate_fast" if label == "rate_slow" else "rate_slow",
                extra={"rate": why, "ramp_time": f"{factor * period:g}"},
                description=f"the same ramp walked over {factor:g} x the period",
            )

    # -- growth: clock-driven
    if family.startswith("growth") or "growth" in beh["regimes"]:
        n = GROWTH_INCREMENTS
        dt = period / n
        props = list(entry.get("props") or ())
        consts = identify_constants(str(entry.get("source_text") or ""), props)
        free = [
            Increment(
                tuple(0.0 for _ in range(ntens)),
                _as_matrix3(np.eye(3)) if finite else None,
                dt,
                temp,
                0.0,
            )
            for _ in range(n)
        ]
        mk(
            "growth_free",
            "growth",
            free,
            amplitude=0.0,
            kinematics=kin,
            extra={"growth": "no deformation; the clock alone"},
            description="no deformation for the whole period: a law driven by "
            "the clock grows, a stretch-driven one must not",
        )
        if "critical_stretch" in consts and consts["critical_stretch"].value > 0:
            lam = 1.1 * consts["critical_stretch"].value
            lam_prov = (
                f"1.1 x critical stretch {consts['critical_stretch'].value:g} "
                f"({consts['critical_stretch'].evidence})"
            )
        else:
            lam = 1.0 + amps.finite
            lam_prov = (
                f"1 + finite amplitude {amps.finite:g}: no critical "
                f"stretch identifiable in the source"
            )
        f_hold = np.diag([lam, 1.0, 1.0])
        ramp_g = [
            np.diag([1.0 + (lam - 1.0) * k / per_leg, 1.0, 1.0])
            for k in range(1, per_leg + 1)
        ]
        if finite:
            incs = _finite_increments(ramp_g, ntens, 0.1 * period / per_leg, temp)
            incs += [
                Increment(
                    tuple(0.0 for _ in range(ntens)),
                    _as_matrix3(f_hold),
                    0.9 * dt,
                    temp,
                    0.0,
                )
                for _ in range(n)
            ]
        else:
            incs = _small_increments(
                [uni * (lam - 1.0)], per_leg, 0.1 * period / per_leg, temp
            )
            incs += [
                Increment(tuple(0.0 for _ in range(ntens)), None, 0.9 * dt, temp, 0.0)
                for _ in range(n)
            ]
        mk(
            "growth_held_stretch",
            "growth",
            incs,
            amplitude=lam - 1.0,
            extra={"stretch": lam_prov},
            description="ramp to a stretch past the growth criterion in a "
            "tenth of the period, then hold it for the rest of the period",
        )

    # -- finite strain: simple shear, uniaxial stretch, objectivity pair
    if finite:
        a_f = amps.finite
        n = per_leg
        dt = period / n
        shear_g = [
            np.eye(3) + np.array([[0, a_f * k / n, 0], [0, 0, 0], [0, 0, 0]])
            for k in range(1, n + 1)
        ]
        mk(
            "finite_simple_shear",
            "elastic" if not beh.get("dissipative") else "plastic",
            _finite_increments(shear_g, ntens, dt, temp),
            amplitude=a_f,
            description="simple shear F = I + gamma e1 x e2",
        )
        out = [np.diag([1 + a_f * k / n, 1.0, 1.0]) for k in range(1, n + 1)]
        back = [np.diag([1 + a_f * (n - k) / n, 1.0, 1.0]) for k in range(1, n + 1)]
        mk(
            "finite_uniaxial_stretch",
            "elastic" if not beh.get("dissipative") else "plastic",
            _finite_increments(out + back, ntens, dt / 2, temp),
            amplitude=a_f,
            closed=True,
            reversal_at=n - 1,
            description="uniaxial stretch to 1+a and back to F = I",
        )
        # objectivity: F_b(s) general; rotated twin Q(s) F_b(s), Q ramps to
        # 90 deg. Walked at two resolutions so that an incremental law, which
        # is objective only to the order of its rotation integration, can be
        # judged by convergence rather than by a tolerance pulled from the air.
        axis = admissible_rotation_axis(ntens)
        q_end = rotation(axis, 0.5 * math.pi)
        extra = {"objectivity": f"Q(s) about {axis}, 0..90 deg linear in s"}
        regime = "elastic" if not beh.get("dissipative") else "plastic"
        for suffix, steps in (("", n), ("_fine", 4 * n)):
            base, rotated, angles = [], [], []
            for k in range(1, steps + 1):
                s = k / steps
                fb = np.eye(3) + a_f * s * np.array(
                    [
                        [1.0, 0.5, 0.0],
                        [0.0, -0.3, 0.0],
                        [0.0, 0.0, 0.0 if ntens == 3 else 0.1],
                    ]
                )
                th = 0.5 * math.pi * s
                base.append(fb)
                rotated.append(rotation(axis, th) @ fb)
                angles.append(th)
            dts = period / steps
            mk(
                "objectivity_reference" + suffix,
                regime,
                _finite_increments(base, ntens, dts, temp),
                amplitude=a_f,
                purpose="objectivity_reference",
                twin="objectivity_rotated" + suffix,
                rotation=q_end,
                extra=extra,
                rotation_angles=[0.0] * steps,
                description=f"general deformation F_b(s), {steps} increments",
            )
            mk(
                "objectivity_rotated" + suffix,
                regime,
                _finite_increments(rotated, ntens, dts, temp),
                amplitude=a_f,
                purpose="objectivity_rotated",
                twin="objectivity_reference" + suffix,
                rotation=q_end,
                extra=extra,
                rotation_angles=angles,
                description=f"Q(s) F_b(s), {steps} increments: an objective "
                f"model returns Q sigma Q^T",
            )
    return _within_domain(paths, domain)


def _beyond_documented(path: LoadingPath, domain: Mapping) -> str:
    """Why ``path`` leaves the documented strain, stretch or temperature
    domain, or ``""``."""
    if not any(k in domain for k in ("strain_max", "stretch_max", "temperature")):
        return ""
    strain, stretch, t_low, t_high = _peaks(path)
    tol = 1.0 + 1e-9
    if "strain_max" in domain and strain > domain["strain_max"] * tol:
        return (f"peak |strain| {strain:g} > {domain['strain_max']:g} documented "
                f"({domain.get('strain_max_provenance', '')})")
    if "stretch_max" in domain and stretch > domain["stretch_max"] * tol:
        return (f"peak stretch {stretch:g} > {domain['stretch_max']:g} documented "
                f"({domain.get('stretch_max_provenance', '')})")
    if "temperature" in domain:
        low, high = domain["temperature"]
        if t_low < low - 1e-9 * max(1.0, abs(low)) or t_high > high + 1e-9 * max(1.0, abs(high)):
            return (f"TEMP {t_low:g}..{t_high:g} outside {low:g}..{high:g} documented "
                    f"({domain.get('temperature_provenance', '')})")
    return ""


def _within_domain(paths: list[LoadingPath], domain: Mapping) -> list[LoadingPath]:
    """Record the documented domain on every path; relabel the ones that leave it.

    A path is never clipped to fit: clipping would change the experiment
    while keeping its name. A path that ends after ``time_max`` is emitted
    with ``purpose = outside_model_domain`` (its intended purpose kept in the
    provenance), and so is its twin, because a pair is one question.
    """
    from dataclasses import replace

    t_max = domain.get("time_max")
    outside: dict[str, float] = {}
    beyond: dict[str, str] = {}
    for path in paths:
        end = sum(inc.dtime for inc in path.increments)
        if t_max is not None and end > t_max * (1.0 + 1e-9):
            outside[path.name] = end
        why = _beyond_documented(path, domain)
        if why:
            beyond[path.name] = why
            outside.setdefault(path.name, end)
    for path in paths:
        if path.twin and path.twin in outside and path.name not in outside:
            outside[path.name] = sum(inc.dtime for inc in path.increments)
    out = []
    for path in paths:
        end = sum(inc.dtime for inc in path.increments)
        prov = dict(path.provenance)
        prov["model_domain"] = (
            f"total time <= {t_max:g} ({domain.get('time_provenance')}); this "
            f"path ends at {end:g}"
            if t_max is not None
            else str(domain.get("time_provenance"))
        )
        if domain.get("witnesses"):
            prov["model_domain_witnesses"] = "; ".join(domain["witnesses"])
        if domain.get("unbounded_branches"):
            prov["model_domain_unenforced"] = "; ".join(
                f"{c['routine']} lines {c['lines']}: {', '.join(c['defines'])} "
                f"piecewise in {c['tested']} with no ELSE"
                for c in domain["unbounded_branches"][:5]
            )
        if path.name in outside:
            prov["intended_purpose"] = path.purpose
            if path.name in beyond:
                prov["outside_model_domain"] = beyond[path.name]
            elif t_max is not None:
                prov["outside_model_domain"] = (
                    f"ends at total time {end:g} > {t_max:g} documented "
                    f"({domain.get('time_provenance')})"
                    + ("" if end > t_max * (1.0 + 1e-9) else "; its twin leaves it")
                )
            else:
                prov["outside_model_domain"] = "its twin leaves the documented domain"
            out.append(replace(path, purpose=OUTSIDE_MODEL_DOMAIN, provenance=prov))
        else:
            out.append(replace(path, provenance=prov))
    return out


def _small_increments_from_targets(
    targets: Sequence[np.ndarray], period: float, temp: float
) -> list[Increment]:
    incs = []
    prev = np.zeros_like(targets[0])
    for t in targets:
        incs.append(
            Increment(
                tuple(float(x) for x in (t - prev)),
                None,
                period / len(targets),
                temp,
                0.0,
            )
        )
        prev = t
    return incs


def rotation_at(path: LoadingPath, index: int) -> np.ndarray:
    """The superposed rotation at the END of increment ``index`` of a twin."""
    if path.purpose.startswith("objectivity") and path.rotation_angles:
        axis = admissible_rotation_axis(path.ntens)
        return rotation(axis, path.rotation_angles[index])
    if path.rotation is not None and path.purpose == "isotropy_rotated":
        return np.asarray(path.rotation, dtype=float)
    return np.eye(3)


# ---------------------------------------------------------------------------
# a routine-level amplitude search (re-uses the Abaqus search's logic)
# ---------------------------------------------------------------------------
def history_as_records(path: LoadingPath, history: Sequence[Mapping]) -> list[dict]:
    """Driver history in the probe-record shape activation.py reads."""
    strains = total_strain(path)
    out = []
    for k, (inc, row) in enumerate(zip(path.increments, history)):
        before = strains[k - 1] if k else np.zeros(path.ntens)
        out.append(
            {
                "step": 1,
                "increment": k + 1,
                "element": 1,
                "point": 1,
                "time": time_of(path, k)[1] + inc.dtime,
                "STRESS": [float(v) for v in row.get("stress", ())],
                "STATEV": [float(v) for v in row.get("statev", ())],
                "DDSDDE": [float(v) for v in np.ravel(row.get("ddsdde", ()))],
                "STRAN": [float(v) for v in before],
                "DSTRAN": [float(v) for v in (inc.dstran or ())],
            }
        )
    return out


def search_activation_amplitude(
    entry: Mapping,
    run_path: Callable[[LoadingPath], Sequence[Mapping]],
    *,
    per_leg: int = PER_LEG,
):
    """Find where the ORIGINAL routine activates, at the driver level.

    ``run_path(path)`` runs the original routine along ``path`` and returns
    its history (list of per-increment dicts with ``stress``, ``statev``,
    ``ddsdde``), raising or returning a short list when it cannot. The search
    itself is :func:`umat_oti.abaqus.amplitude_search.search_amplitude`
    unchanged -- start at FIRST_AMPLITUDE, escalate by GROWTH, refine the
    bracket -- with a monotonic uniaxial path of ``per_leg`` increments per
    amplitude. Returns its ``SearchResult``.
    """
    from umat_oti.abaqus.amplitude_search import search_amplitude

    ntens = int(entry.get("ntens") or 6)
    layout(ntens)
    finite = is_finite(entry)
    temp, _ = _temperature(entry)
    period, _ = _clock(entry)
    uni = _direction("uniaxial", ntens)

    def run(amplitude: float):
        if finite:
            grads = [
                _small_from_strain(uni * amplitude * k / per_leg, ntens)
                for k in range(1, per_leg + 1)
            ]
            incs = _finite_increments(grads, ntens, period / per_leg, temp)
        else:
            incs = _small_increments([uni * amplitude], per_leg, period / per_leg, temp)
        ndi, nshr = layout(ntens)
        path = LoadingPath(
            f"search_{amplitude:.3g}",
            "plastic",
            "finite" if finite else "small",
            incs,
            ntens=ntens,
            ndi=ndi,
            nshr=nshr,
            amplitude=amplitude,
        )
        try:
            history = list(run_path(path))
        except Exception as error:  # noqa: BLE001 -- the runner's failure is the search's datum
            return False, [], f"{type(error).__name__}: {error}"
        return True, history_as_records(path, history), ""

    return search_amplitude(run)


__all__ = [
    "FAMILY_BEHAVIOUR",
    "KINEMATICS",
    "OUTSIDE_MODEL_DOMAIN",
    "REGIMES",
    "Increment",
    "LoadingPath",
    "PiecewiseChain",
    "amplitudes",
    "behaviour",
    "dfgrd0_of",
    "drot_of",
    "elastic_moduli",
    "history_as_records",
    "hooke_matrix",
    "identify_constants",
    "is_finite",
    "is_isotropic",
    "is_rate_dependent",
    "kinematics_between",
    "layout",
    "model_domain",
    "paths_for",
    "piecewise_chains",
    "reads_deformation_gradient",
    "rotation",
    "rotation_at",
    "search_activation_amplitude",
    "tensor_to_voigt",
    "time_of",
    "total_strain",
    "voigt_to_tensor",
]
