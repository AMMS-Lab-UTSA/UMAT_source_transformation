"""Mechanical admissibility checks on a driver-level UMAT history.

Numerical agreement between two builds says the conversion did not change the
routine. It says nothing about whether the routine is a material. These checks
ask the second question, from the history of the ORIGINAL routine (they can be
run on the OTI build too, and should give the same verdicts).

Every check returns a :class:`CheckResult` whose ``passed`` is

* ``True``  -- the property holds within ``tolerance``;
* ``False`` -- it does not, and ``detail`` says by how much and where;
* ``None``  -- NOT APPLICABLE: the family is not supposed to have the property,
  the routine does not report the quantity, or the path cannot inform it.
  A model is never failed for a property it is not supposed to have.

Each check states its assumptions and the families it applies to
(:data:`CATALOGUE`). The applicability rules live in the check, next to the
arithmetic, so the catalogue cannot drift from what is enforced.

Conventions: Voigt order 11,22,33,12,13,23 truncated to NTENS; stress with
tensor shear, strain with ENGINEERING shear, so ``sigma . deps`` is the work
increment; DDSDDE[i][j] = d(dsigma_i)/d(deps_j). Finite-strain work is the
Kirchhoff power ``J sigma : D`` (per unit reference volume), with D the
increment's DSTRAN.

``history`` is a list with one mapping per increment of ``path`` holding the
values at the END of the increment: ``stress`` (NTENS), ``statev`` (NSTATV),
``ddsdde`` (NTENS x NTENS nested, or flat ROW-major), ``sse``, ``spd``,
``scd``. A mapping with an ``increments`` list (and optionally ``statev0``)
is accepted too.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from umat_oti.corpus_features.loading_paths import (
    OUTSIDE_MODEL_DOMAIN,
    LoadingPath,
    behaviour,
    elastic_moduli,
    hooke_matrix,
    identify_constants,
    is_isotropic,
    is_rate_dependent,
    rotation_at,
    total_strain,
    voigt_to_tensor,
)


@dataclass
class CheckResult:
    """One admissibility check on one path."""

    name: str
    passed: bool | None
    value: float | None
    tolerance: float | None
    detail: str
    applies_to: str = ""
    assumptions: str = ""
    path: str = ""
    #: ``passed`` / ``failed`` / ``not_applicable`` / ``unsupported``. Derived
    #: from ``passed`` unless set: ``unsupported`` (passed None) means the
    #: question was not askable of this source in this LAYOUT -- e.g. plane
    #: stress requested of a routine whose shear starts at index 4 -- which is
    #: this harness's limitation, not the material's failure.
    status: str = ""

    def __post_init__(self) -> None:
        if not self.status:
            self.status = (
                "passed"
                if self.passed is True
                else "failed"
                if self.passed is False
                else "not_applicable"
            )

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "passed": self.passed,
            "value": self.value,
            "tolerance": self.tolerance,
            "detail": self.detail,
            "applies_to": self.applies_to,
            "assumptions": self.assumptions,
            "path": self.path,
        }


# ---------------------------------------------------------------------------
# the catalogue: name -> (applies to, assumptions)
# ---------------------------------------------------------------------------
CATALOGUE: dict[str, tuple[str, str]] = {
    "history_finite": (
        "every family, every path",
        (
            "a routine that returns NaN/Inf has left its domain; nothing else can "
            "be said about that increment"
        ),
    ),
    "stress_free_reference": (
        "every family except growth, on elastic-regime response paths",
        (
            "the reference state is stress-free (no prestress, no clock-driven "
            "growth at t=0) and the first two equal increments stay on one smooth "
            "branch: the stress extrapolated to zero strain, 2 s1 - s2, is "
            "O(increment^2) relative to s1. Judged only when increments 1-2 are "
            "DEMONSTRATED elastic"
        ),
    ),
    "closed_cycle_returns_stress_free": (
        "reversible families (elasticity, hyperelasticity), closed paths",
        (
            "a reversible material's stress is a function of the current strain "
            "only; back at zero strain it is back at zero stress"
        ),
    ),
    "ddsdde_major_symmetry": (
        (
            "elasticity and hyperelasticity (hyperelastic potential, and Abaqus's "
            "Jaumann correction preserves major symmetry); plasticity only when the "
            "flow rule is identified as associative; never when the author declared "
            "an unsymmetric Jacobian"
        ),
        (
            "the tangent derives from a potential; non-associative flow, damage, "
            "growth and rate laws legitimately produce unsymmetric tangents"
        ),
    ),
    "initial_tangent_positive_definite": (
        "every family, first increment of elastic-regime paths",
        (
            "the virgin material is stable: deps . D . deps > 0 for every nonzero "
            "deps (engineering-shear Voigt makes the eigenvalues of sym(D) the "
            "right test). Later states may legitimately soften. Judged only when "
            "increment 1 is DEMONSTRATED elastic (no internal variable moved, no "
            "SPD/SCD); D is the DDSDDE the routine RETURNS, which need not be the "
            "derivative of its stress update"
        ),
    ),
    "initial_tangent_matches_identified_moduli": (
        (
            "families with an elastic reference (not rate dependent) whose E,nu (or "
            "lambda,mu / C10,D1 / mu,K) are identified BY NAME in the source"
        ),
        (
            "isotropic linear elasticity at the reference state; NTENS=3 is plane "
            "stress (E/(1-nu^2)), NTENS=4 plane strain/axisymmetric; finite-strain "
            "routines are compared at their first increment with a tolerance that "
            "admits the O(strain) stress terms. Judged only when increment 1 is "
            "DEMONSTRATED elastic; compares the RETURNED DDSDDE"
        ),
    ),
    "objectivity": (
        "finite-strain paths with a rotation-superposed twin",
        (
            "F' = Q(t) F(t) must give sigma' = Q sigma Q^T (material frame "
            "indifference). A total-F (hyperelastic/growth) law is exact to "
            "round-off; an incremental (hypoelastic) law is objective only to the "
            "order of its rotation integration, hence a looser tolerance"
        ),
    ),
    "isotropy": (
        "families expected isotropic with no anisotropy marker in the source",
        (
            "rotating the whole strain (or F -> R F R^T) history by a constant R "
            "rotates the stress history: sigma' = R sigma R^T, exactly (to "
            "round-off) for an isotropic algorithm"
        ),
    ),
    "closed_cycle_work": (
        (
            "closed paths of every family except growth; vanishing for reversible "
            "families, non-negative for the rest"
        ),
        (
            "isothermal, starting from the virgin stress-free state at its energy "
            "minimum: W = psi_end - psi_0 + D >= 0 (Clausius-Duhem); reversible: "
            "W = 0. Trapezoidal integration, error O(increment^2)"
        ),
    ),
    "dissipation_increment_nonnegative": (
        "any routine that reports SPD or SCD",
        (
            "SPD and SCD are cumulative plastic/creep dissipation per unit volume "
            "(Abaqus UMAT convention); their increments cannot be negative"
        ),
    ),
    "energy_balance": (
        "dissipative families whose routine reports both SSE and SPD",
        (
            "W = SSE + SPD + SCD along the path (stored + dissipated = external "
            "work, isothermal). A violation is an ENERGY-REPORTING defect; it "
            "does not by itself mean the stress is wrong"
        ),
    ),
    "sse_equals_work": (
        (
            "reversible families (and growth paths where the state does not move) "
            "whose routine reports SSE"
        ),
        (
            "for a hyperelastic material SSE is the stored energy, equal to the "
            "work done on the path (per unit reference volume)"
        ),
    ),
    "internal_variable_monotone": (
        (
            "plasticity/damage-type families, only for STATEV slots the source "
            "itself names as damage or equivalent plastic strain"
        ),
        (
            "damage does not heal and accumulated plastic strain does not "
            "decrease in these laws"
        ),
    ),
    "elastic_unloading_slope": (
        (
            "plasticity and crystal plasticity (slope = initial, or <= initial "
            "when the source reads its elastic modulus from STATEV); damage "
            "(slope <= initial); unload_reload paths that actually activated"
        ),
        (
            "unloading from a plastic state is elastic; damage degrades but cannot "
            "stiffen the unloading modulus; the first increment of the path is "
            "elastic"
        ),
    ),
    "yield_consistency": (
        (
            "routines whose yield function is identified (KNOWN_YIELD_FUNCTIONS), "
            "at increments where the identified plastic multiplier grew"
        ),
        (
            "rate-independent plasticity returns to the yield surface: "
            "|f(sigma, q)| / sigma_y within the routine's own Newton tolerance"
        ),
    ),
    "bauschinger_shift": (
        (
            "plasticity, crystal plasticity, damage and geomaterial families, on "
            "the reverse_yield path (forward leg, then a reverse leg at 8x the "
            "cyclic resolution) when both legs yielded"
        ),
        (
            "after forward plastic flow the centre of the elastic range moves "
            "WITH the flow (Prager/Armstrong-Frederick/Yoshida-Uemori kinematic "
            "hardening, distortional HAH) or stays put (isotropic hardening): "
            "alpha = (q_f + q_r)/2 >= 0, with q the signed von Mises stress "
            "(sign of the 11 deviator) normalised by the forward direction, q_f "
            "the flow stress at reversal and q_r the reverse-yield stress. "
            "q_r is bracketed by the two increments around reverse-yield onset "
            "(identified slots moving, else the q-strain slope dropping below "
            "98% of the initial elastic slope), so alpha is an interval and "
            "only a whole-interval violation fails"
        ),
    ),
    "back_stress_sign": (
        (
            "routines whose back-stress STATEV slots are identified "
            "(``entry['back_stress_slots']`` or :func:`back_stress_for`), on "
            "the cyclic and reverse_yield paths, per plastic segment"
        ),
        (
            "the back stress evolves toward the direction of plastic flow: over "
            "each plastic segment (consecutive plastic increments in one strain "
            "direction) the net d(alpha) : dev(sigma - alpha) >= 0. Judged per "
            "segment, not per increment: a discrete step may overshoot the "
            "saturation of a recovery term (Armstrong-Frederick, Yoshida-Uemori) "
            "and relax back, which is admissible"
        ),
    ),
    "relaxation_fading_memory": (
        "rate-dependent families, the hold segment of a relaxation path",
        (
            "under held strain a viscoelastic/viscoplastic solid relaxes: "
            "|sigma| does not grow during the hold"
        ),
    ),
}


def _result(
    name: str, passed: bool | None, value, tol, detail: str, path: LoadingPath
) -> CheckResult:
    applies, assumptions = CATALOGUE[name]
    # numpy comparisons return numpy.bool_, which is neither True nor False
    # to an `is` test and serialises as a string: normalise here, once.
    passed = None if passed is None else bool(passed)
    return CheckResult(
        name,
        passed,
        None if value is None else float(value),
        None if tol is None else float(tol),
        detail,
        applies,
        assumptions,
        path.name,
    )


def _na(name: str, why: str, path: LoadingPath) -> CheckResult:
    return _result(name, None, None, None, "not applicable: " + why, path)


def _unsupported(name: str, why: str, path: LoadingPath) -> CheckResult:
    result = _result(name, None, None, None, "unsupported: " + why, path)
    result.status = "unsupported"
    return result


_SIZE_TEST = re.compile(
    r"\b(NTENS|NDI|NSHR)\s*(?:\.EQ\.|==|\.NE\.|/=)\s*(\d+)", re.IGNORECASE
)


def layout_unsupported(entry: Mapping, path: LoadingPath) -> str:
    """Why the source cannot represent ``path``'s NTENS layout, or ``""``.

    Read from the source text by :func:`umat_oti.abaqus.formulation.from_source`
    (the same reader that chooses the verification element):

    * a source whose shear starts at index 4 (``do i=4,ntens``) has NDI=3 and
      cannot be handed NTENS=3 -- its loop over the shear never runs and the
      slot Abaqus reads as s12 holds what it computed as s33;
    * a source that DECIDES its own size (a DO loop bounded at 4 or 6 over the
      whole of STRESS/DDSDDE, or 3 with index 3 a shear) cannot be handed a
      different one -- unless the source tests for the path's size itself, in
      which case it says it handles that layout.

    A source that says nothing is not refused here: no evidence is not
    evidence of incompatibility.
    """
    from umat_oti.abaqus.formulation import from_source

    text = str(entry.get("source_text") or "")
    if not text:
        return ""
    found = from_source(text, str(entry.get("source_id") or entry.get("name") or ""))
    if found.min_ntens and path.ntens < found.min_ntens:
        return (
            f"the source needs at least NTENS={found.min_ntens} "
            f"({found.undecided or '; '.join(found.evidence[:1])}) and this path "
            f"hands it NTENS={path.ntens}"
        )
    if found.ntens and found.ntens != path.ntens:
        handled = {
            (which.upper(), int(value)) for which, value in _SIZE_TEST.findall(text)
        }
        if ("NTENS", path.ntens) in handled or ("NDI", path.ndi) in handled:
            return ""
        return (
            f"the source fills a {found.ntens}-component tensor "
            f"({'; '.join(found.evidence[:1])}) and this path hands it "
            f"NTENS={path.ntens}; no test on NTENS/NDI in the source says it "
            f"handles that layout"
        )
    return ""


# ---------------------------------------------------------------------------
# reading a history
# ---------------------------------------------------------------------------
def _rows(history: Any) -> list[Mapping]:
    if isinstance(history, Mapping):
        return list(history.get("increments") or [])
    return list(history or [])


def _statev0(history: Any, entry: Mapping) -> np.ndarray | None:
    if isinstance(history, Mapping) and history.get("statev0") is not None:
        return np.asarray(history["statev0"], dtype=float)
    if entry.get("initial_statev"):
        return np.asarray(entry["initial_statev"], dtype=float)
    return None


def _vec(row: Mapping, key: str) -> np.ndarray:
    value = row.get(key)
    if value is None:
        return np.zeros(0)
    return np.asarray(value, dtype=float).ravel()


def _ddsdde(row: Mapping, ntens: int) -> np.ndarray:
    value = row.get("ddsdde")
    if value is None:
        return np.zeros((ntens, ntens))
    d = np.asarray(value, dtype=float)
    if d.ndim == 1:
        d = d.reshape(ntens, ntens)
    return d


def _scalar(row: Mapping, key: str) -> float:
    value = row.get(key)
    try:
        return float(np.asarray(value, dtype=float).ravel()[0])
    except (TypeError, ValueError, IndexError):
        return 0.0


def _stress_scale(rows: Sequence[Mapping]) -> float:
    best = 0.0
    for row in rows:
        s = _vec(row, "stress")
        if s.size and np.all(np.isfinite(s)):
            best = max(best, float(np.max(np.abs(s))))
    return best


def work_increments(path: LoadingPath, rows: Sequence[Mapping]) -> np.ndarray:
    """Trapezoidal work increments ``0.5 (tau_{k-1} + tau_k) . deps_k``.

    Small strain: tau = sigma. Finite strain: tau = J sigma (Kirchhoff), deps
    the increment's DSTRAN (rate of deformation x dt), so the sum is work per
    unit REFERENCE volume -- the measure Abaqus's SSE/SPD refer to.
    """
    out = []
    prev = np.zeros(path.ntens)
    for inc, row in zip(path.increments, rows):
        s = _vec(row, "stress")
        if inc.dfgrd1 is not None:
            s = s * float(np.linalg.det(np.asarray(inc.dfgrd1, dtype=float)))
        d = np.asarray(
            inc.dstran if inc.dstran is not None else np.zeros(path.ntens), dtype=float
        )
        out.append(0.5 * float(np.dot(prev + s, d)))
        prev = s
    return np.asarray(out)


# ---------------------------------------------------------------------------
# identification of state slots and yield functions from the source
# ---------------------------------------------------------------------------
_MONOTONE_NAMES = {
    "damage": ("DAMAGE", "DMG", "DAM", "DNEW", "DAMAGEVAR"),
    "equivalent plastic strain": (
        "EQPLAS",
        "PEEQ",
        "EPBAR",
        "EQPS",
        "EPEQ",
        "PEQ",
        "EBAR",
        "EQPL",
        "EPSEQ",
    ),
}
_STATEV_WRITE = re.compile(
    r"^\s*(?:\d+\s+)?STATEV\s*\(\s*([^()]+?)\s*\)\s*=\s*([A-Za-z_]\w*)\s*$",
    re.IGNORECASE,
)
_INT_EXPR = re.compile(r"^[0-9+\-*\s()A-Za-z]+$")


def _evaluate_index(expr: str, ntens: int, ndi: int, nshr: int) -> int | None:
    if not _INT_EXPR.match(expr):
        return None
    names = {"NTENS": ntens, "NDI": ndi, "NSHR": nshr}
    text = expr.upper()
    for name in re.findall(r"[A-Z_]\w*", text):
        if name not in names:
            return None
    try:
        value = eval(text, {"__builtins__": {}}, names)
    except Exception:  # noqa: BLE001 -- an index that does not evaluate is "not identified"
        return None
    return int(value) if isinstance(value, int) else None


def monotone_state_slots(
    source_text: str, ntens: int, ndi: int, nshr: int
) -> dict[int, tuple[str, str]]:
    """STATEV slots (1-based) the source names as damage or eq. plastic strain.

    Only ``STATEV(expr) = NAME`` with NAME one of the conventional names, and
    expr an integer expression in NTENS/NDI/NSHR. Anything else is not
    identified -- and the monotonicity check is then not applicable rather
    than guessed.
    """
    from umat_oti.corpus_features.loading_paths import _code_lines

    found: dict[int, tuple[str, str]] = {}
    lookup = {n: kind for kind, names in _MONOTONE_NAMES.items() for n in names}
    for number, code, _ in _code_lines(source_text or ""):
        for statement in code.split(";"):
            m = _STATEV_WRITE.match(statement)
            if not m:
                continue
            kind = lookup.get(m.group(2).upper())
            if kind is None:
                continue
            slot = _evaluate_index(m.group(1), ntens, ndi, nshr)
            if slot is not None and slot not in found:
                found[slot] = (kind, f"line {number}: {statement.strip()}")
    return found


def von_mises(stress_voigt: Sequence[float], ntens: int) -> float:
    """Physical von Mises stress of an NTENS Voigt stress (sigma33=0 in plane
    stress)."""
    s = voigt_to_tensor(stress_voigt, ntens, engineering=False)
    dev = s - np.trace(s) / 3.0 * np.eye(3)
    return math.sqrt(1.5 * float(np.sum(dev * dev)))


@dataclass(frozen=True)
class YieldFunction:
    """An identified yield function: residual f/sigma_y from (stress, statev)."""

    description: str
    evidence: str
    residual: Callable[
        [np.ndarray, np.ndarray, Sequence[float], int], tuple[float, float]
    ]
    plastic_slot: Callable[[int], int]
    tolerance: float


def _j2_linear(stress, statev, props, ntens):
    sy = props[2] + props[3] * statev[0]
    return von_mises(stress, ntens) - sy, sy


def _lemaitre_power(stress, statev, props, ntens):
    p = statev[2 * ntens]
    sf = props[2] * (1e-4 + p) ** props[3]
    # The routine returns gd*stress0 with gd = 1 - TEMP-carried non-local
    # damage; the yield test is on stress0, which it stores in STATEV.
    stress0 = statev[2 * ntens + 2 : 3 * ntens + 2]
    # normalised by max(Sf, Sy): with the published exponent Sf is ~0 and a
    # residual relative to it would be a ratio of round-off
    return von_mises(stress0, ntens) - sf, max(sf, props[2])


def _hockett_sherby_von_mises(stress, statev, props, ntens):
    # MML ISO_HARD, FLOW_PAR=5: P1-(P1-P2)*EXP(-P3*p**P4) + P5*p, p=STATEV(1)
    # (EQPLAS0 = 1e-9 at p = 0, exactly as the routine does)
    p1, p2, p3, p4, p5 = (float(v) for v in props[8:13])
    p = float(statev[0]) or 1e-9
    sy = p1 - (p1 - p2) * math.exp(-p3 * p**p4) + p5 * p
    return von_mises(stress, ntens) - sy, sy


#: Yield functions identified by reading the source, keyed by the SHA-256 of
#: the source text. Each entry says what was read and where.
KNOWN_YIELD_FUNCTIONS: dict[str, YieldFunction] = {}


def register_yield_function(source_text: str, function: YieldFunction) -> str:
    key = hashlib.sha256(source_text.encode("utf-8", "replace")).hexdigest()
    KNOWN_YIELD_FUNCTIONS[key] = function
    return key


def yield_function_for(entry: Mapping) -> YieldFunction | None:
    """The identified yield function for this entry, if any.

    Looked up by ``entry['sha256']`` or by hashing ``entry['source_text']``;
    two identifications are built in, both read from the sources:

    * ``UMATs/UMATs/generic_ps/j2_props.f`` (repository fixture): von Mises,
      linear isotropic hardening sigma_y = PROPS(3) + PROPS(4) * STATEV(1);
    * ``awhelanUCD/.../lemaitreDamageNonLocal.f``: von Mises of the undegraded
      stress STATEV(3+2N..2+3N), power hardening
      Sf = PROPS(3) * (1e-4 + STATEV(1+2N))**PROPS(4) (source lines 69, 86).
    """
    text = str(entry.get("source_text") or "")
    key = entry.get("sha256") or (
        hashlib.sha256(text.encode("utf-8", "replace")).hexdigest() if text else ""
    )
    if key in KNOWN_YIELD_FUNCTIONS:
        return KNOWN_YIELD_FUNCTIONS[key]
    upper = text.upper()
    if (
        "SIGY0 = PROPS(3)" in upper
        and "H     = PROPS(4)" in upper
        and "STATEV(1)" in upper
        and "RADIAL-RETURN" in upper
    ):
        return YieldFunction(
            "von Mises, linear isotropic hardening",
            "j2_props.f: SIGY0 = PROPS(3), H = PROPS(4), EQPLAS = STATEV(1)",
            _j2_linear,
            lambda ntens: 1,
            1e-6,
        )
    if "SF=SY*(0.0001+EQPLAS)**XN" in upper.replace(
        " ", ""
    ) and "STATEV(1+2*NTENS)=EQPLAS" in upper.replace(" ", ""):
        return YieldFunction(
            "von Mises of undegraded stress, power hardening Sy(1e-4+p)^n",
            "lemaitreDamageNonLocal.f: Sf=Sy*(0.0001+eqplas)**xn; "
            "statev(1+2*ntens)=eqplas; statev(3+2*ntens:..)=stress0",
            _lemaitre_power,
            lambda ntens: 1 + 2 * ntens,
            1e-5,
        )
    compact = upper.replace(" ", "")
    if (
        "SYIELD=PROPS(3)" in compact
        and "HARD=PROPS(4)" in compact
        and "STRESS(K1)=FLOW(K1)*SYIELD+SHYDRO" in compact
        and "STATEV(1+2*NTENS)=EQPLAS" in compact
    ):
        # jasonanewcoder umat_mises_plasticity_official.f: the header states
        # "ISOTROPIC HARDENING - RADIAL RETURN", PROPS(3)=SYIELD, PROPS(4)=HARD
        # (lines 27-32) and the Newton loop solves SMISES-3G dp = SYIELD+HARD dp
        # (line 106). The documented surface is sigma_y = PROPS(3) +
        # PROPS(4) * EQPLAS with EQPLAS = STATEV(1+2N).
        return YieldFunction(
            "von Mises, linear isotropic hardening (as the header documents)",
            "umat_mises_plasticity_official.f:27-32 header; :79-80 SYIELD, HARD; "
            ":106 Newton residual; :115/:118 returned stress; :130 EQPLAS update, :160 STATEV(1+2N)=EQPLAS",
            lambda st, sv, pr, n: (
                von_mises(st, n) - (pr[2] + pr[3] * sv[2 * n]),
                pr[2] + pr[3] * sv[2 * n],
            ),
            lambda ntens: 1 + 2 * ntens,
            1e-5,
        )
    props = [float(v) for v in (entry.get("props") or ())]
    if (
        "SUBROUTINEFLOW_STRESS(STAT_VAR,EQPLAS,FLOW_SIG" in compact
        and "STATEV(1)=EQPLAS" in compact
        and len(props) >= 13
        and props[0] == 0.0
        and props[1] == 1.0
        and props[2] == 5.0
        and not ("PEC0=PROPS(6)" in compact and props[5] != 0.0)
    ):
        # theysy MML_U2/MML_U3 with PROPS(1)=0 (isotropic hardening),
        # PROPS(2)=1 (von Mises), PROPS(3)=5 (Hockett-Sherby + linear, ISO_HARD)
        # and no pressure effect: f = SIG_BAR - FLOW_SIG (YIELD_CONDITION).
        return YieldFunction(
            "von Mises, Hockett-Sherby + linear isotropic hardening (MML options "
            "PROPS(1:3) = 0, 1, 5)",
            "MML header PROPS(1..3) option tables; ISO_HARD FLOW_PAR=5 branch; "
            "YIELD_CONDITION FVAL = SIG_BAR + PEC*CVAL*SIG_KK - CVAL with PEC=0; "
            "STATEV(1)=EQPLAS",
            _hockett_sherby_von_mises,
            lambda ntens: 1,
            1e-5,
        )
    return None


#: Back-stress slots identified by reading the source.
def back_stress_for(entry: Mapping) -> tuple[list[int], str] | None:
    """STATEV slots (1-based, NTENS layout) holding the back stress, if known.

    ``entry['back_stress_slots']`` wins (a list of slots plus
    ``entry['back_stress_evidence']``). Otherwise one identification is
    built in, read from the source: theysy MML_U2/MML_U3 store the Chaboche
    and Yoshida-Uemori back stress ALPHA in STATEV(7:6+NTENS) (``NDIM0=6``;
    ``STATEV(NDIM0+I)=STAT_VAR(I)`` for ``HARD_PAR .EQ. 1`` or ``2``), and
    add it back onto the returned stress (``STRESS(I)=STRESS(I)+STAT_VAR(I)``).
    """
    slots = entry.get("back_stress_slots")
    if slots:
        return [int(v) for v in slots], str(entry.get("back_stress_evidence") or "")
    text = str(entry.get("source_text") or "").upper().replace(" ", "")
    props = [float(v) for v in (entry.get("props") or ())]
    ntens = int(entry.get("ntens") or 0)
    if (
        "STATEV(NDIM0+I)=STAT_VAR(I)" in text
        and "IF(HARD_PAR.EQ.1.D0.OR.HARD_PAR.EQ.2.D0)THEN" in text
        and props
        and props[0] in (1.0, 2.0)
        and ntens
    ):
        return list(range(7, 7 + ntens)), (
            "MML: HARD_PAR = PROPS(1) in (1 Chaboche, 2 Yoshida-Uemori) stores "
            "ALPHA in STATEV(NDIM0+I), NDIM0=6"
        )
    return None


# ---------------------------------------------------------------------------
# single-path checks
# ---------------------------------------------------------------------------
def check_history_finite(entry, path, rows) -> CheckResult:
    bad = None
    for k, row in enumerate(rows):
        for key in ("stress", "statev", "ddsdde"):
            v = _vec(row, key)
            if v.size and not np.all(np.isfinite(v)):
                bad = (k + 1, key)
                break
        if bad:
            break
    if len(rows) < len(path.increments):
        return _result(
            "history_finite",
            False,
            len(rows),
            len(path.increments),
            f"only {len(rows)} of {len(path.increments)} increments returned",
            path,
        )
    if bad:
        return _result(
            "history_finite",
            False,
            bad[0],
            0,
            f"non-finite {bad[1]} at increment {bad[0]}",
            path,
        )
    return _result(
        "history_finite", True, 0, 0, f"{len(rows)} increments, all finite", path
    )


def check_stress_free_reference(entry, path, rows, statev0=None) -> CheckResult:
    name = "stress_free_reference"
    fam = str(entry.get("family") or "")
    if fam.startswith("growth"):
        return _na(
            name, "growth family: the clock can stress the reference state", path
        )
    if path.regime != "elastic" or path.purpose != "response" or len(rows) < 2:
        return _na(name, "only on elastic response paths with >= 2 increments", path)
    elastic, basis = first_increment_elastic(entry, path, rows, statev0, upto=2)
    if elastic is not True:
        return _na(name, f"elastic increments 1-2 not demonstrated: {basis}", path)
    d1 = np.asarray(path.increments[0].dstran or (), dtype=float)
    d2 = np.asarray(path.increments[1].dstran or (), dtype=float)
    if d1.size == 0 or not np.allclose(d1, d2, rtol=1e-6, atol=1e-15):
        return _na(name, "first two increments are not equal", path)
    s1, s2 = _vec(rows[0], "stress"), _vec(rows[1], "stress")
    scale = max(float(np.max(np.abs(s1))), 1e-300)
    value = float(np.max(np.abs(2 * s1 - s2))) / scale
    # curvature of a smooth law makes 2 s1 - s2 = O(increment) relative to
    # s1; a prestress makes it O(1/increment). The tolerance follows the
    # increment so the first is admitted and the second is not.
    tol = max(1e-3, 5.0 * float(np.max(np.abs(d1))))
    return _result(
        name,
        value <= tol,
        value,
        tol,
        f"|2 s1 - s2| / |s1| = {value:.3e} (extrapolated stress at "
        f"zero strain, relative to the first increment's stress "
        f"{scale:.4g})",
        path,
    )


def check_closed_cycle_returns_stress_free(entry, path, rows) -> CheckResult:
    name = "closed_cycle_returns_stress_free"
    if not behaviour(entry).get("reversible"):
        return _na(
            name,
            f"family {entry.get('family')!r} is not reversible: "
            f"residual stress at zero strain is allowed",
            path,
        )
    if not path.closed or not rows:
        return _na(name, "path does not return to its start", path)
    scale = _stress_scale(rows)
    if scale == 0:
        return _na(name, "the path produced no stress", path)
    value = float(np.max(np.abs(_vec(rows[-1], "stress")))) / scale
    tol = 1e-6
    return _result(
        name, value <= tol, value, tol, f"|sigma_end| / max|sigma| = {value:.3e}", path
    )


def check_ddsdde_symmetry(entry, path, rows) -> CheckResult:
    name = "ddsdde_major_symmetry"
    if entry.get("unsymmetric"):
        return _na(name, "the author declared an unsymmetric Jacobian", path)
    fam = str(entry.get("family") or "")
    yf = yield_function_for(entry)
    if behaviour(entry).get("reversible"):
        why = f"family {fam!r} derives from a potential"
    elif fam == "plasticity" and (
        entry.get("associative")
        or (yf is not None and "Mises" in yf.description and "damage" not in fam)
    ):
        why = "associative von Mises plasticity (identified)"
    else:
        return _na(
            name,
            f"family {fam!r} may legitimately have an unsymmetric "
            f"tangent (non-associative, damage, growth or rate)",
            path,
        )
    worst, where = 0.0, 0
    seen = 0
    for k, row in enumerate(rows):
        d = _ddsdde(row, path.ntens)
        norm = float(np.max(np.abs(d)))
        if norm == 0 or not np.all(np.isfinite(d)):
            continue
        seen += 1
        rel = float(np.max(np.abs(d - d.T))) / norm
        if rel > worst:
            worst, where = rel, k + 1
    if not seen:
        return _na(name, "the routine returned no tangent", path)
    tol = 1e-6
    return _result(
        name,
        worst <= tol,
        worst,
        tol,
        f"{why}; max |D - D^T| / max|D| = {worst:.3e}"
        + (f" at increment {where}" if where else ""),
        path,
    )


def first_increment_elastic(
    entry: Mapping,
    path: LoadingPath,
    rows: Sequence[Mapping],
    statev0=None,
    upto: int = 1,
) -> tuple[bool | None, str]:
    """Whether increments 1..``upto`` are DEMONSTRATED free of internal-variable
    movement.

    ``(True, basis)`` only on evidence: the routine reports no SPD/SCD growth
    and either carries no STATEV, or the slots the source names as damage /
    equivalent plastic strain did not move, or (no slot named) no STATEV slot
    moved at all. ``(False, what)`` when something inelastic is seen.
    ``(None, why)`` when STATEV moved and nothing says whether the slot that
    moved is an internal variable (it may be a stored elastic strain).

    The incoming state is ``statev0`` when given, else zeros -- the driver
    convention (``drivers.RunConfig``: no statev0 means a zero state).
    """
    if len(rows) < upto:
        return None, "the history is shorter than the increments to check"
    span = "increment 1" if upto == 1 else f"increments 1..{upto}"
    sv = _vec(rows[0], "statev")
    if statev0 is not None and np.asarray(statev0).size == sv.size:
        before = np.asarray(statev0, dtype=float)
        origin = "the supplied initial STATEV"
    else:
        before = np.zeros(sv.size)
        origin = "a zero initial STATEV (driver convention)"
    slots = monotone_state_slots(
        str(entry.get("source_text") or ""), path.ntens, path.ndi, path.nshr
    )
    moved: set[int] = set()
    spd0 = scd0 = 0.0
    for k in range(upto):
        spd, scd = _scalar(rows[k], "spd"), _scalar(rows[k], "scd")
        if spd > spd0 or scd > scd0:
            return False, (
                f"increment {k + 1} dissipated (SPD={spd:.4g}, SCD={scd:.4g})"
            )
        spd0, scd0 = spd, scd
        now = _vec(rows[k], "statev")
        if now.size != before.size:
            return None, f"STATEV changed length at increment {k + 1}"
        moved |= {
            j + 1
            for j in range(now.size)
            if abs(now[j] - before[j]) > 1e-14 * max(1.0, abs(before[j]))
        }
        before = now
    if sv.size == 0:
        return True, "the routine carries no STATEV"
    if slots:
        hit = [s for s in slots if s in moved]
        if hit:
            kinds = ", ".join(f"STATEV({s}) {slots[s][0]}" for s in hit)
            return False, f"internal variables moved in {span} ({kinds}, from {origin})"
        return True, (
            f"identified internal variables unmoved in {span} ("
            + ", ".join(f"STATEV({s}) {k}" for s, (k, _e) in slots.items())
            + f", from {origin})"
        )
    if moved:
        listed = ", ".join(map(str, sorted(moved)[:6]))
        return None, (
            f"STATEV({listed}) moved in {span} (from {origin}) and the source "
            f"names none of them as damage or equivalent plastic strain, so an "
            f"elastic {span} is not demonstrated"
        )
    return True, f"no STATEV slot moved in {span} (from {origin})"


def check_initial_tangent_pd(entry, path, rows, statev0=None) -> CheckResult:
    name = "initial_tangent_positive_definite"
    if path.regime != "elastic" or not rows:
        return _na(name, "only on the first increment of elastic paths", path)
    elastic, basis = first_increment_elastic(entry, path, rows, statev0)
    if elastic is not True:
        return _na(name, f"elastic increment 1 not demonstrated: {basis}", path)
    d = _ddsdde(rows[0], path.ntens)
    if not np.any(d) or not np.all(np.isfinite(d)):
        return _na(name, "the routine returned no (finite) tangent", path)
    eig = np.linalg.eigvalsh(0.5 * (d + d.T))
    value = float(eig.min() / max(abs(eig.max()), 1e-300))
    tol = 1e-10
    return _result(
        name,
        value > tol,
        value,
        tol,
        "eigenvalues of sym(returned DDSDDE) at increment 1: "
        + ", ".join(f"{e:.4g}" for e in eig)
        + f" [{basis}]",
        path,
    )


def check_initial_tangent_moduli(entry, path, rows, statev0=None) -> CheckResult:
    name = "initial_tangent_matches_identified_moduli"
    if path.name not in ("elastic_uniaxial",) or not rows:
        return _na(name, "evaluated once, on elastic_uniaxial", path)
    elastic, basis = first_increment_elastic(entry, path, rows, statev0)
    if elastic is not True:
        return _na(name, f"elastic increment 1 not demonstrated: {basis}", path)
    rate, _ = is_rate_dependent(entry)
    if rate:
        return _na(name, "rate-dependent: the tangent depends on DTIME", path)
    if behaviour(entry).get("isotropic") is False:
        return _na(name, "anisotropic family", path)
    iso, iso_basis = is_isotropic(entry)
    if iso is False:
        return _na(name, iso_basis, path)
    moduli = elastic_moduli(
        identify_constants(
            str(entry.get("source_text") or ""), list(entry.get("props") or ())
        )
    )
    if moduli is None:
        return _na(
            name,
            "no isotropic elastic constants identified by name in the source",
            path,
        )
    d = _ddsdde(rows[0], path.ntens)
    if not np.any(d):
        return _na(name, "the routine returned no tangent", path)
    ref = hooke_matrix(moduli["E"], moduli["nu"], path.ntens)
    value = float(np.max(np.abs(d - ref)) / np.max(np.abs(ref)))
    strain = float(np.max(np.abs(np.asarray(path.increments[0].dstran or [0.0]))))
    tol = 1e-6 if path.kinematics == "small" else max(1e-6, 20.0 * strain)
    worst = np.unravel_index(int(np.argmax(np.abs(d - ref))), d.shape)
    return _result(
        name,
        value <= tol,
        value,
        tol,
        f"E={moduli['E']:.6g}, nu={moduli['nu']:.4g} "
        f"({'; '.join(moduli['basis'])}); worst entry "
        f"D[{worst[0] + 1},{worst[1] + 1}] = {d[worst]:.6g} vs "
        f"Hooke {ref[worst]:.6g} (NTENS={path.ntens}"
        f"{', plane stress' if path.ntens == 3 else ''}) [{basis}]",
        path,
    )


def check_closed_cycle_work(entry, path, rows) -> CheckResult:
    name = "closed_cycle_work"
    fam = str(entry.get("family") or "")
    if fam.startswith("growth"):
        return _na(
            name,
            "growth exchanges energy with the clock; a closed "
            "strain cycle need not dissipate",
            path,
        )
    if not path.closed or len(rows) < len(path.increments):
        return _na(name, "path is not closed (or history is incomplete)", path)
    dw = work_increments(path, rows)
    w, scale = float(dw.sum()), float(np.abs(dw).sum())
    if scale == 0 or _stress_vanished(path, rows):
        return _na(name, "no work above round-off was done", path)
    value = w / scale
    if behaviour(entry).get("reversible"):
        tol = 1e-2
        return _result(
            name,
            abs(value) <= tol,
            value,
            tol,
            f"reversible: W = {w:.4g}, sum|dW| = {scale:.4g}",
            path,
        )
    tol = 1e-3
    return _result(
        name,
        value >= -tol,
        value,
        tol,
        f"W = {w:.4g} (>= 0 required), sum|dW| = {scale:.4g}",
        path,
    )


def check_dissipation_nonnegative(entry, path, rows) -> CheckResult:
    name = "dissipation_increment_nonnegative"
    spd = np.array([_scalar(r, "spd") for r in rows])
    scd = np.array([_scalar(r, "scd") for r in rows])
    if not np.any(spd) and not np.any(scd):
        return _na(name, "the routine reports neither SPD nor SCD", path)
    worst = 0.0
    for series in (spd, scd):
        if np.any(series):
            inc = np.diff(np.concatenate([[0.0], series]))
            worst = min(
                worst, float(inc.min()) / max(float(np.abs(series).max()), 1e-300)
            )
    tol = 1e-9
    return _result(
        name,
        worst >= -tol,
        worst,
        tol,
        f"most negative increment of SPD/SCD relative to its "
        f"largest value: {worst:.3e}",
        path,
    )


#: Up to this strain the energy measures a source may use (Cauchy stress with
#: log or small strain, Kirchhoff with rate of deformation) agree to within
#: the energy_balance tolerance; beyond it the comparison tests a convention.
ENERGY_MEASURE_STRAIN = 0.05


def check_energy_balance(entry, path, rows) -> CheckResult:
    name = "energy_balance"
    if behaviour(entry).get("reversible") or str(entry.get("family") or "").startswith(
        "growth"
    ):
        return _na(name, "not a dissipative family", path)
    sse = np.array([_scalar(r, "sse") for r in rows])
    spd = np.array([_scalar(r, "spd") for r in rows])
    scd = np.array([_scalar(r, "scd") for r in rows])
    if not np.any(sse) or not (np.any(spd) or np.any(scd)):
        return _na(name, "the routine does not report both SSE and SPD/SCD", path)
    if _stress_vanished(path, rows):
        return _na(
            name,
            "the stress stayed at round-off level on this path; "
            "the energy ratio would be a ratio of noise",
            path,
        )
    strain = max((float(np.max(np.abs(e))) for e in total_strain(path)), default=0.0)
    if path.kinematics == "finite" and strain > ENERGY_MEASURE_STRAIN:
        return _na(
            name,
            f"finite path to strain {strain:.3g}: an SSE written "
            f"as 1/2 sigma:eps_e (Cauchy, log strain) and the "
            f"Kirchhoff work differ at O(strain) by convention, "
            f"so the balance is only tested up to "
            f"{ENERGY_MEASURE_STRAIN:g}",
            path,
        )
    w = np.cumsum(work_increments(path, rows))
    gap = w - (sse + spd + scd)
    scale = max(float(np.abs(w).max()), 1e-300)
    k = int(np.argmax(np.abs(gap)))
    value = float(abs(gap[k])) / scale
    tol = 2e-2
    return _result(
        name,
        value <= tol,
        value,
        tol,
        f"worst at increment {k + 1}: W={w[k]:.5g}, SSE={sse[k]:.5g}, "
        f"SPD={spd[k]:.5g}, SCD={scd[k]:.5g}; at the end W={w[-1]:.5g}, "
        f"SSE+SPD+SCD={(sse + spd + scd)[-1]:.5g}",
        path,
    )


def _state_moved(rows, statev0=None) -> bool:
    states = [_vec(r, "statev") for r in rows]
    if (
        statev0 is not None
        and statev0.size
        and states
        and states[0].size == statev0.size
    ):
        states = [statev0] + states
    return any(
        a.shape != states[0].shape
        or not np.allclose(a, states[0], rtol=1e-10, atol=1e-14)
        for a in states[1:]
    )


def _stress_vanished(path, rows) -> bool:
    """True when the stress stayed at round-off level for the whole path,
    relative to what the routine's own first tangent gives for the path's
    largest strain -- energy ratios are then ratios of noise."""
    if not rows:
        return True
    d0 = _ddsdde(rows[0], path.ntens)
    strain = max((float(np.max(np.abs(e))) for e in total_strain(path)), default=0.0)
    expected = float(np.max(np.abs(d0))) * strain
    return expected > 0 and _stress_scale(rows) < 1e-9 * expected


def check_sse_equals_work(entry, path, rows, statev0=None) -> CheckResult:
    name = "sse_equals_work"
    beh = behaviour(entry)
    fam = str(entry.get("family") or "")
    sse = np.array([_scalar(r, "sse") for r in rows])
    if not np.any(sse):
        return _na(name, "the routine does not report SSE", path)
    if not (beh.get("reversible") or fam.startswith("growth")):
        return _na(name, f"family {fam!r} is not reversible (see energy_balance)", path)
    if path.regime == "growth" or _state_moved(rows, statev0):
        return _na(
            name,
            "the state moved on this path (growth, viscous or "
            "other internal variable): SSE is then the energy of "
            "the elastic part only, not the work",
            path,
        )
    w = np.cumsum(work_increments(path, rows))
    scale = max(float(np.abs(w).max()), float(np.abs(sse).max()), 1e-300)
    gap = np.abs(w - sse)
    k = int(np.argmax(gap))
    value = float(gap[k]) / scale
    tol = 1e-2
    return _result(
        name,
        value <= tol,
        value,
        tol,
        f"worst at increment {k + 1}: SSE={sse[k]:.6g} vs integrated work {w[k]:.6g}",
        path,
    )


def check_internal_variable_monotone(entry, path, rows, statev0=None) -> CheckResult:
    name = "internal_variable_monotone"
    beh = behaviour(entry)
    if beh.get("reversible") or not beh.get("dissipative"):
        return _na(
            name,
            f"family {entry.get('family')!r} has no irreversible "
            f"internal variable expected",
            path,
        )
    slots = monotone_state_slots(
        str(entry.get("source_text") or ""), path.ntens, path.ndi, path.nshr
    )
    if not slots:
        return _na(
            name,
            "no damage or equivalent-plastic-strain STATEV slot is named in the source",
            path,
        )
    worst, where = 0.0, ""
    for slot, (kind, evidence) in slots.items():
        series = [r for r in (_vec(row, "statev") for row in rows) if r.size >= slot]
        values = np.array([s[slot - 1] for s in series])
        if statev0 is not None and statev0.size >= slot:
            values = np.concatenate([[statev0[slot - 1]], values])
        if values.size < 2:
            continue
        drop = float(np.min(np.diff(values)))
        scale = max(float(np.abs(values).max()), 1e-300)
        if drop / scale < worst:
            worst, where = drop / scale, f"STATEV({slot}) ({kind})"
    tol = 1e-12
    names = "; ".join(f"STATEV({s}) {k} [{e}]" for s, (k, e) in slots.items())
    return _result(
        name,
        worst >= -tol,
        worst,
        tol,
        f"slots: {names}; largest relative decrease {worst:.3e}"
        + (f" in {where}" if where else ""),
        path,
    )


def _legs(path: LoadingPath) -> list[tuple[int, int, float]]:
    """(first, last, sign) of maximal runs of equal-sign DSTRAN(1)."""
    legs = []
    start, sign = 0, 0.0
    for k, inc in enumerate(path.increments):
        s = (
            math.copysign(1.0, inc.dstran[0])
            if inc.dstran and inc.dstran[0] != 0
            else 0.0
        )
        if k == 0:
            sign = s
        elif s != sign:
            legs.append((start, k - 1, sign))
            start, sign = k, s
    legs.append((start, len(path.increments) - 1, sign))
    return legs


_MODULUS_FROM_STATE = re.compile(
    r"^\s*(?:\d+\s+)?(E|EMOD|EMOD0|EMODULUS|YMOD|YOUNG\w*|EYOUNG)\s*=\s*STATEV\s*\(",
    re.IGNORECASE,
)


def modulus_evolves(source_text: str) -> str:
    """Evidence that the elastic modulus is an internal variable, or ``""``.

    A routine that reads Young's modulus back from STATEV carries an evolving
    modulus (chord-modulus degradation of AHSS, Yoshida-Uemori's E(p)):
    theysy MML_U3 ``EMOD=STATEV(3)`` with ``STATEV(3)=EMOD0-(EMOD0-EMOD_A)*
    (1-EXP(-EMOD_B*EQPLAS))``. Its unloading slope legitimately falls below
    the initial one, and demanding equality would fail an admissible model.
    """
    from umat_oti.corpus_features.loading_paths import _code_lines

    for number, code, _ in _code_lines(source_text or ""):
        if _MODULUS_FROM_STATE.match(code):
            return f"line {number}: {code.strip()[:60]}"
    return ""


def check_elastic_unloading_slope(entry, path, rows, statev0=None) -> CheckResult:
    name = "elastic_unloading_slope"
    fam = str(entry.get("family") or "")
    if path.regime != "unload_reload":
        return _na(name, "only on unload_reload paths", path)
    evolving = modulus_evolves(str(entry.get("source_text") or ""))
    if fam in ("plasticity", "crystal plasticity") and not evolving:
        mode = "equal"
    elif fam in ("plasticity", "crystal plasticity") or fam.startswith("damage"):
        mode = "not_stiffer"
    else:
        return _na(
            name,
            f"family {fam!r}: unloading slope has no family "
            f"expectation (rate, pressure-dependent elasticity)",
            path,
        )
    legs = _legs(path)
    if len(legs) < 2 or len(rows) < legs[1][1] + 1:
        return _na(name, "path has no unloading leg (or history incomplete)", path)
    eps = [e[0] for e in total_strain(path)]
    sig = [_vec(r, "stress")[0] for r in rows]
    slots = monotone_state_slots(
        str(entry.get("source_text") or ""), path.ntens, path.ndi, path.nshr
    )
    states = [_vec(r, "statev") for r in rows]
    first_state = (
        statev0 if statev0 is not None and statev0.size else np.zeros_like(states[0])
    )

    def inelastic(k: int) -> bool | None:
        """Did increment k move the identified irreversible slots? None if
        no slot is identified."""
        if not slots:
            return None
        before = states[k - 1] if k else first_state
        return any(
            abs(states[k][s - 1] - before[s - 1]) > 1e-14 * max(1.0, abs(before[s - 1]))
            for s in slots
            if states[k].size >= s and before.size >= s
        )

    def slope(k):
        e0 = eps[k - 1] if k else 0.0
        s0 = sig[k - 1] if k else 0.0
        return (sig[k] - s0) / (eps[k] - e0)

    first = inelastic(0)
    if first:
        return _na(
            name,
            "the path's first increment was already inelastic "
            "(identified slots moved), so the initial elastic "
            "slope was not measured",
            path,
        )
    s_init = slope(0)
    load_end = slope(legs[0][1])
    if abs(load_end / s_init - 1.0) <= 1e-3:
        return _na(
            name,
            f"not informative: the loading leg stayed on its "
            f"initial slope (end/initial = {load_end / s_init:.6g})",
            path,
        )
    unload = list(range(legs[1][0], legs[1][1] + 1))
    if slots:
        elastic_unload = []
        for k in unload:
            if inelastic(k):
                break  # reverse yielding / further damage: stop here
            elastic_unload.append(k)
        basis = "unloading increments until an identified slot moved"
    else:
        elastic_unload = unload[:1]
        basis = (
            "first unloading increment only (no irreversible slot "
            "identified, so reverse yielding cannot be detected)"
        )
    if not elastic_unload:
        return _na(
            name,
            "the first unloading increment was already inelastic (reverse yielding)",
            path,
        )
    ratios = np.array([slope(k) for k in elastic_unload]) / s_init
    tol = 1e-3 if path.kinematics == "small" else 3e-2
    head = (
        f"{basis}: {len(elastic_unload)} of {len(unload)}; "
        f"initial assumption: increment 1 elastic"
        + (" (identified slots unmoved)" if first is False else " (not verifiable)")
    )
    if mode == "equal":
        value = float(np.max(np.abs(ratios - 1.0)))
        return _result(
            name,
            value <= tol,
            value,
            tol,
            f"{head}; unloading/initial slope in [{ratios.min():.6g}, "
            f"{ratios.max():.6g}] (loading leg ended at "
            f"{load_end / s_init:.4g} x initial)",
            path,
        )
    value = float(ratios.max() - 1.0)
    return _result(
        name,
        value <= tol,
        value,
        tol,
        f"{head}; "
        + (
            f"elastic modulus is a state variable ({evolving})"
            if evolving and not fam.startswith("damage")
            else "damage"
        )
        + ": unloading/initial slope in "
        f"[{ratios.min():.6g}, {ratios.max():.6g}] must not exceed 1 "
        f"(loading leg ended at {load_end / s_init:.4g} x initial)",
        path,
    )


def check_yield_consistency(entry, path, rows, statev0=None) -> CheckResult:
    name = "yield_consistency"
    yf = yield_function_for(entry)
    if yf is None:
        return _na(name, "no yield function identified for this source", path)
    props = list(entry.get("props") or ())
    slot = yf.plastic_slot(path.ntens)
    prev = statev0[slot - 1] if statev0 is not None and statev0.size >= slot else 0.0
    worst, where, n = 0.0, 0, 0
    for k, row in enumerate(rows):
        sv = _vec(row, "statev")
        if sv.size < slot:
            return _na(name, "STATEV shorter than the identified slot", path)
        if sv[slot - 1] > prev + 1e-14:
            f, sy = yf.residual(_vec(row, "stress"), sv, props, path.ntens)
            rel = abs(f) / abs(sy)
            n += 1
            if rel > worst:
                worst, where = rel, k + 1
        prev = sv[slot - 1]
    if not n:
        return _na(name, "no plastic increment on this path", path)
    return _result(
        name,
        worst <= yf.tolerance,
        worst,
        yf.tolerance,
        f"{yf.description} ({yf.evidence}); {n} plastic increments, "
        f"worst |f|/sigma_y at increment {where}",
        path,
    )


def signed_equivalent(stress_voigt: Sequence[float], ntens: int) -> float:
    """von Mises stress carrying the sign of the 11 deviator: on a uniaxial
    strain path it runs through zero continuously as the load reverses."""
    s = voigt_to_tensor(stress_voigt, ntens, engineering=False)
    dev = s - np.trace(s) / 3.0 * np.eye(3)
    vm = math.sqrt(1.5 * float(np.sum(dev * dev)))
    return math.copysign(vm, float(dev[0, 0])) if dev[0, 0] else vm


_HARDENING_FAMILIES = ("plasticity", "crystal plasticity")


def _hardening_family(fam: str) -> bool:
    return fam in _HARDENING_FAMILIES or fam.startswith(("damage", "concrete"))


def _cyclic_reversal(entry, path, rows, statev0):
    """Shared bookkeeping for the cyclic checks.

    Returns ``(None, why)`` or ``(data, "")`` with the legs, signed
    equivalent stresses normalised by the forward direction, the strain, and
    an ``inelastic(k)`` predicate (identified slots moved, else the slope
    criterion).
    """
    if path.regime != "cyclic":
        return None, "only on the cyclic path"
    legs = _legs(path)
    if len(legs) < 2 or len(rows) < legs[1][1] + 1:
        return None, "the path has no reverse leg (or the history is incomplete)"
    direction = legs[0][2] or 1.0
    q = [direction * signed_equivalent(_vec(r, "stress"), path.ntens) for r in rows]
    eps = [direction * e[0] for e in total_strain(path)]
    slots = monotone_state_slots(
        str(entry.get("source_text") or ""), path.ntens, path.ndi, path.nshr
    )
    yf = yield_function_for(entry)
    if yf is not None:
        slots = dict(slots)
        slots.setdefault(
            yf.plastic_slot(path.ntens), ("plastic multiplier", yf.evidence)
        )
    states = [_vec(r, "statev") for r in rows]
    first = (
        np.asarray(statev0, dtype=float)
        if statev0 is not None and np.asarray(statev0).size
        else np.zeros_like(states[0])
    )

    def slope(k):
        e0 = eps[k - 1] if k else 0.0
        q0 = q[k - 1] if k else 0.0
        de = eps[k] - e0
        return (q[k] - q0) / de if de else float("nan")

    s_init = slope(0)

    def inelastic(k):
        if slots:
            before = states[k - 1] if k else first
            return any(
                states[k].size >= sl
                and before.size >= sl
                and abs(states[k][sl - 1] - before[sl - 1])
                > 1e-14 * max(1.0, abs(before[sl - 1]))
                for sl in slots
            )
        return not (slope(k) >= 0.98 * s_init)

    basis = (
        "identified slots "
        + ", ".join(f"STATEV({sl}) {kind}" for sl, (kind, _e) in slots.items())
        if slots
        else "slope below 98% of the initial elastic slope (no slot identified)"
    )
    if not (s_init > 0):
        return None, "the first increment produced no positive stiffness"
    return {
        "legs": legs,
        "q": q,
        "eps": eps,
        "inelastic": inelastic,
        "basis": basis,
        "slots": slots,
    }, ""


def check_bauschinger_shift(entry, path, rows, statev0=None) -> CheckResult:
    name = "bauschinger_shift"
    fam = str(entry.get("family") or "")
    if not _hardening_family(fam):
        return _na(name, f"family {fam!r} has no yield surface to shift", path)
    if path.name != "reverse_yield":
        return _na(name, "evaluated on the reverse_yield path (fine reverse leg)", path)
    data, why = _cyclic_reversal(entry, path, rows, statev0)
    if data is None:
        return _na(name, why, path)
    legs, q, inelastic = data["legs"], data["q"], data["inelastic"]
    forward = range(legs[0][0], legs[0][1] + 1)
    if not any(inelastic(k) for k in forward):
        return _na(name, "not informative: the forward leg never yielded", path)
    if data["slots"] and inelastic(legs[0][0]):
        return _na(
            name,
            "the first increment was already inelastic, so no elastic range "
            "was measured",
            path,
        )
    q_f = q[legs[0][1]]
    if not q_f > 0:
        return _na(name, "no positive flow stress at the reversal", path)
    reverse = list(range(legs[1][0], legs[1][1] + 1))
    onset = next((k for k in reverse if inelastic(k)), None)
    if onset is None:
        return _na(
            name,
            "no reverse yield inside the reverse leg (elastic range wider "
            "than the reverse strain)",
            path,
        )
    q_hi = q[onset - 1]  # last stress known to be elastic (or q_f)
    q_lo = q[onset]  # first stress known to be past reverse yield
    alpha_lo, alpha_hi = 0.5 * (q_f + q_lo) / q_f, 0.5 * (q_f + q_hi) / q_f
    # Inside the bracket: intersect the elastic line through q_hi with the
    # plastic line through q_lo (slopes of the neighbouring increments).
    # Exact for linear hardening, a good estimate for smooth hardening.
    eps = data["eps"]
    alpha_est = None
    if onset + 1 <= legs[1][1] and inelastic(onset + 1) and onset - 1 >= 0:
        d_e = eps[onset] - eps[onset - 1]
        e_prev = eps[onset - 2] if onset >= 2 else 0.0
        q_prev = q[onset - 2] if onset >= 2 else 0.0
        s_e = (
            (q[onset - 1] - q_prev) / (eps[onset - 1] - e_prev)
            if onset - 1 >= legs[1][0] and eps[onset - 1] != e_prev
            else None
        )
        d_p = eps[onset + 1] - eps[onset]
        s_p = (q[onset + 1] - q[onset]) / d_p if d_p else None
        if s_e is not None and s_p is not None and s_e != s_p and d_e:
            x = (q_lo - q_hi - s_p * d_e) / (s_e - s_p)
            x = min(max(x, min(d_e, 0.0)), max(d_e, 0.0))
            alpha_est = 0.5 * (q_f + q_hi + s_e * x) / q_f
    tol = 1e-3
    detail = (
        f"q_f={q_f:.6g} at reversal; reverse yield between q={q_hi:.6g} and "
        f"q={q_lo:.6g} (increments {onset}..{onset + 1}); centre shift "
        f"alpha/q_f in [{alpha_lo:.4g}, {alpha_hi:.4g}]"
        + (f" (bilinear estimate {alpha_est:.4g})" if alpha_est is not None else "")
        + f", elastic range (q_f-q_r)/q_f in [{(q_f - q_hi) / q_f:.4g}, "
        f"{(q_f - q_lo) / q_f:.4g}]; onset by {data['basis']}"
    )
    if alpha_hi < -tol:
        return _result(
            name,
            False,
            alpha_hi,
            tol,
            "the elastic-range centre moved AGAINST the prior flow; " + detail,
            path,
        )
    kinematic = back_stress_for(entry)
    #: the bilinear estimate is trusted to 2% of q_f (curvature of the
    #: hardening law inside one increment)
    est_tol = 2e-2
    no_shift = alpha_hi <= tol or (alpha_est is not None and alpha_est <= est_tol)
    if kinematic is not None and no_shift and alpha_lo <= tol:
        return _result(
            name,
            False,
            alpha_hi if alpha_est is None else alpha_est,
            tol if alpha_est is None else est_tol,
            "the source carries a back stress but reverse yield shows no "
            "Bauschinger shift; " + detail,
            path,
        )
    kind = (
        "Bauschinger shift (kinematic/distortional)"
        if alpha_lo > tol
        else "no shift (isotropic hardening)"
        if alpha_hi <= tol
        else f"no shift resolved: |alpha|/q_f <= {alpha_hi:.3g}, the bracket of "
        f"one reverse increment (isotropic within resolution)"
    )
    return _result(name, True, alpha_lo, tol, f"{kind}; " + detail, path)


def check_back_stress_sign(entry, path, rows, statev0=None) -> CheckResult:
    name = "back_stress_sign"
    found = back_stress_for(entry)
    if found is None:
        return _na(name, "no back-stress slot identified in the source", path)
    slots, evidence = found
    data, why = _cyclic_reversal(entry, path, rows, statev0)
    if data is None:
        return _na(name, why, path)
    if max(slots) > _vec(rows[0], "statev").size:
        return _na(name, "STATEV shorter than the back-stress slots", path)

    def alpha_at(k):
        if k < 0:
            base = (
                np.asarray(statev0, dtype=float)
                if statev0 is not None and np.asarray(statev0).size
                else np.zeros(_vec(rows[0], "statev").size)
            )
        else:
            base = _vec(rows[k], "statev")
        return voigt_to_tensor(
            [base[sl - 1] for sl in slots], path.ntens, engineering=False
        )

    def dev(t):
        return t - np.trace(t) / 3.0 * np.eye(3)

    # Plastic SEGMENTS: maximal runs of consecutive plastic increments under
    # one strain direction. Increment-wise d(alpha) may turn against the flow
    # when a discrete step overshoots the saturation value of a recovery term
    # (Armstrong-Frederick, Yoshida-Uemori) and relaxes back -- admissible,
    # an integration artefact -- so the NET change over a segment is judged.
    eps = data["eps"]
    segments: list[tuple[int, int]] = []
    start = None
    for k in range(len(rows)):
        step = eps[k] - (eps[k - 1] if k else 0.0)
        plastic = data["inelastic"](k)
        if plastic and start is not None:
            prev_step = eps[start] - (eps[start - 1] if start else 0.0)
            if step * prev_step < 0:
                segments.append((start, k - 1))
                start = k
            continue
        if plastic:
            start = k
        elif start is not None:
            segments.append((start, k - 1))
            start = None
    if start is not None:
        segments.append((start, len(rows) - 1))
    scale = _stress_scale(rows)
    worst, where, n = float("inf"), "", 0
    for first, last in segments:
        d_alpha = dev(alpha_at(last) - alpha_at(first - 1))
        sigma = voigt_to_tensor(
            _vec(rows[last], "stress"), path.ntens, engineering=False
        )
        flow = dev(sigma - alpha_at(last))
        na, nf = float(np.linalg.norm(d_alpha)), float(np.linalg.norm(flow))
        if na <= 1e-3 * scale or nf == 0:
            continue
        cosine = float(np.sum(d_alpha * flow)) / (na * nf)
        n += 1
        if cosine < worst:
            worst, where = cosine, f"increments {first + 1}..{last + 1}"
    if not n:
        return _na(
            name,
            "no plastic segment moved the back stress above 1e-3 of the stress",
            path,
        )
    tol = 1e-6
    return _result(
        name,
        worst >= -tol,
        worst,
        tol,
        f"back stress STATEV({slots[0]}..{slots[-1]}) [{evidence}]; over {n} "
        f"plastic segments the smallest cos(net d alpha, dev(sigma - alpha) at "
        f"the segment end) = {worst:.4g} ({where})",
        path,
    )


def check_relaxation(entry, path, rows) -> CheckResult:
    name = "relaxation_fading_memory"
    rate, why = is_rate_dependent(entry)
    if not rate:
        return _na(name, why, path)
    if path.name != "relaxation":
        return _na(name, "only on the relaxation path", path)
    hold = [
        k
        for k, inc in enumerate(path.increments)
        if inc.dstran is not None and not np.any(inc.dstran)
    ]
    if len(hold) < 2 or len(rows) <= hold[-1]:
        return _na(name, "no hold segment in the history", path)
    mags = [
        float(np.linalg.norm(_vec(rows[k], "stress"))) for k in [hold[0] - 1] + hold
    ]
    growth = max(b - a for a, b in itertools.pairwise(mags))
    scale = max(max(mags), 1e-300)
    value = growth / scale
    # 1e-6: routines that hold constants in REAL*4 carry ~1e-7 relative noise
    tol = 1e-6
    return _result(
        name,
        value <= tol,
        value,
        tol,
        f"|sigma| from {mags[0]:.5g} at the end of the ramp to "
        f"{mags[-1]:.5g} after the hold; largest rise {value:.3e}",
        path,
    )


# ---------------------------------------------------------------------------
# pair checks
# ---------------------------------------------------------------------------
def _pair_error(
    ref_path: LoadingPath, ref_rows, rot_path: LoadingPath, rot_rows
) -> tuple[float, int]:
    n = min(len(ref_rows), len(rot_rows))
    scale = max(_stress_scale(ref_rows), 1e-300)
    worst, where = 0.0, 0
    for k in range(n):
        q = rotation_at(rot_path, k)
        s = voigt_to_tensor(
            _vec(ref_rows[k], "stress"), ref_path.ntens, engineering=False
        )
        expected = q @ s @ q.T
        got = voigt_to_tensor(
            _vec(rot_rows[k], "stress"), rot_path.ntens, engineering=False
        )
        # compare only the components NTENS carries
        mask = (
            voigt_to_tensor(np.ones(rot_path.ntens), rot_path.ntens, engineering=False)
            != 0
        )
        err = float(np.max(np.abs((got - expected)[mask]))) / scale
        if err > worst:
            worst, where = err, k + 1
    return worst, where


def check_pair(
    entry: Mapping,
    ref_path: LoadingPath,
    ref_history,
    rot_path: LoadingPath,
    rot_history,
) -> CheckResult:
    """Objectivity or isotropy from a reference path and its rotated twin."""
    ref_rows, rot_rows = _rows(ref_history), _rows(rot_history)
    if ref_path.purpose == "objectivity_reference":
        name = "objectivity"
        if ref_path.kinematics != "finite":
            return _na(name, "small-strain path", ref_path)
        fam = str(entry.get("family") or "")
        total_f = (
            fam in ("hyperelasticity", "elasticity")
            or fam.startswith("growth")
            or bool(entry.get("reads_dfgrd1"))
        )
        tol = 1e-6 if total_f else 1e-3
        kind = (
            "total-F law (exact to round-off)"
            if total_f
            else "incremental law (objective to the order of rotation integration)"
        )
    elif ref_path.purpose == "isotropy_reference":
        name = "isotropy"
        iso, basis = is_isotropic(entry)
        if not iso:
            return _na(name, basis, ref_path)
        tol = 1e-7
        kind = basis
    else:
        raise ValueError(f"{ref_path.name} is not the reference half of a pair")
    if not ref_rows or not rot_rows:
        return _na(name, "one half of the pair has no history", ref_path)
    worst, where = _pair_error(ref_path, ref_rows, rot_path, rot_rows)
    if len(ref_rows) != len(rot_rows) or len(ref_rows) < len(ref_path.increments):
        detail_tail = (
            f"; histories incomplete ({len(ref_rows)}/"
            f"{len(rot_rows)} of {len(ref_path.increments)})"
        )
    else:
        detail_tail = ""
    passed = worst <= tol and not detail_tail
    return _result(
        name,
        passed,
        worst,
        tol,
        f"{kind}; max |sigma_rot - R sigma R^T| / max|sigma| = "
        f"{worst:.3e} at increment {where}{detail_tail}",
        ref_path,
    )


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------
def run_checks(
    entry: Mapping,
    path: LoadingPath,
    history: Any,
    *,
    twin: tuple[LoadingPath, Any] | None = None,
) -> list[CheckResult]:
    """Every single-path check on one path's history (plus its pair check
    when ``twin`` = (twin_path, twin_history) is given and ``path`` is the
    reference half)."""
    rows = _rows(history)
    statev0 = _statev0(history, entry)
    if path.purpose == OUTSIDE_MODEL_DOMAIN:
        # The routine is undefined (or undocumented) there: no check, not even
        # history_finite, may report a verdict on it.
        why = str(path.provenance.get("outside_model_domain") or "outside the domain")
        return [_na(n, f"{OUTSIDE_MODEL_DOMAIN}: {why}", path) for n in CATALOGUE]
    unsupported = layout_unsupported(entry, path)
    if unsupported:
        # The history is still a fact; every mechanical question about it is
        # one the source was never written to answer in this layout.
        names = [n for n in CATALOGUE if n != "history_finite"]
        if not (
            twin is not None
            and path.purpose in ("objectivity_reference", "isotropy_reference")
        ):
            names = [n for n in names if n not in ("objectivity", "isotropy")]
        return [check_history_finite(entry, path, rows)] + [
            _unsupported(n, unsupported, path) for n in names
        ]
    out = [
        check_history_finite(entry, path, rows),
        check_stress_free_reference(entry, path, rows, statev0),
        check_closed_cycle_returns_stress_free(entry, path, rows),
        check_ddsdde_symmetry(entry, path, rows),
        check_initial_tangent_pd(entry, path, rows, statev0),
        check_initial_tangent_moduli(entry, path, rows, statev0),
        check_closed_cycle_work(entry, path, rows),
        check_dissipation_nonnegative(entry, path, rows),
        check_energy_balance(entry, path, rows),
        check_sse_equals_work(entry, path, rows, statev0),
        check_internal_variable_monotone(entry, path, rows, statev0),
        check_elastic_unloading_slope(entry, path, rows, statev0),
        check_yield_consistency(entry, path, rows, statev0),
        check_bauschinger_shift(entry, path, rows, statev0),
        check_back_stress_sign(entry, path, rows, statev0),
        check_relaxation(entry, path, rows),
    ]
    if twin is not None and path.purpose in (
        "objectivity_reference",
        "isotropy_reference",
    ):
        out.append(check_pair(entry, path, history, twin[0], twin[1]))
    return out


def _objectivity_by_convergence(
    entry: Mapping, pairs: Sequence[tuple[LoadingPath, Any, LoadingPath, Any]]
) -> CheckResult | None:
    """One objectivity verdict from the same pair walked at two resolutions.

    A total-F law (reads DFGRD1) must be objective to round-off at both. An
    incremental law is objective only to the order of its rotation
    integration: it passes when the error at the finer resolution is below
    1e-6, or when refining the increments by 4x shrinks the error by at least
    3x (at least first-order convergence to zero), and the observed order is
    reported. Not converging means the non-objectivity is a property of the
    law, not of the step size.
    """
    from umat_oti.corpus_features.loading_paths import reads_deformation_gradient

    if len(pairs) < 2:
        return None
    measured = []
    for ref, ref_h, rot, rot_h in pairs:
        ref_rows, rot_rows = _rows(ref_h), _rows(rot_h)
        if len(ref_rows) < len(ref.increments) or len(rot_rows) < len(rot.increments):
            return None
        err, where = _pair_error(ref, ref_rows, rot, rot_rows)
        measured.append((len(ref.increments), err, where, ref))
    measured.sort(key=lambda m: m[0])
    (n1, e1, _, ref1), (n2, e2, w2, _) = measured[0], measured[-1]
    total_f = reads_deformation_gradient(str(entry.get("source_text") or ""))
    if total_f is None:
        fam = str(entry.get("family") or "")
        total_f = fam == "hyperelasticity" or fam.startswith("growth")
    order = (
        (math.log(e1 / e2) / math.log(n2 / n1)) if e1 > 0 and e2 > 0 else float("inf")
    )
    if total_f:
        tol = 1e-6
        passed = max(e1, e2) <= tol
        kind = "total-F law (reads DFGRD1): exact to round-off expected"
    else:
        tol = 1e-6
        passed = e2 <= tol or (e1 / max(e2, 1e-300) >= 3.0)
        kind = (
            "incremental law: objective to the order of the rotation "
            "integration; judged by convergence under 4x refinement"
        )
    return _result(
        "objectivity",
        passed,
        e2,
        tol,
        f"{kind}; max |sigma_rot - Q sigma Q^T| / max|sigma| = "
        f"{e1:.3e} at {n1} increments, {e2:.3e} at {n2} (increment "
        f"{w2}); observed order {order:.2f}",
        ref1,
    )


def run_all(
    entry: Mapping, runs: Mapping[str, tuple[LoadingPath, Any]]
) -> list[CheckResult]:
    """All checks over a set of paths keyed by name, pairs resolved by
    ``LoadingPath.twin``. Objectivity pairs walked at several resolutions are
    combined into ONE convergence verdict."""
    results: list[CheckResult] = []
    objectivity = []
    for path, history in runs.values():
        twin = runs.get(path.twin) if path.twin else None
        if path.purpose == "objectivity_reference" and twin is not None:
            objectivity.append((path, history, twin[0], twin[1]))
            results.extend(run_checks(entry, path, history))
            continue
        results.extend(run_checks(entry, path, history, twin=twin))
    blocked = layout_unsupported(entry, objectivity[0][0]) if objectivity else ""
    combined = None if blocked else _objectivity_by_convergence(entry, objectivity)
    if blocked:
        results.append(_unsupported("objectivity", blocked, objectivity[0][0]))
    elif combined is not None:
        results.append(combined)
    else:
        for ref, ref_h, rot, rot_h in objectivity:
            results.append(check_pair(entry, ref, ref_h, rot, rot_h))
    return results


def summarise(results: Sequence[CheckResult]) -> dict[str, dict[str, int]]:
    """Per check name: passed / failed / not_applicable / unsupported counts."""
    out: dict[str, dict[str, int]] = {}
    for r in results:
        row = out.setdefault(
            r.name, {"passed": 0, "failed": 0, "not_applicable": 0, "unsupported": 0}
        )
        row[r.status] += 1
    return out


__all__ = [
    "CATALOGUE",
    "KNOWN_YIELD_FUNCTIONS",
    "CheckResult",
    "YieldFunction",
    "back_stress_for",
    "check_pair",
    "first_increment_elastic",
    "layout_unsupported",
    "modulus_evolves",
    "monotone_state_slots",
    "register_yield_function",
    "run_all",
    "run_checks",
    "signed_equivalent",
    "summarise",
    "von_mises",
    "work_increments",
    "yield_function_for",
]
