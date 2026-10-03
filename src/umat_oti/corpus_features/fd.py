"""Finite-difference references: step ladders, plateau selection, judgement.

Pure numerics, no Fortran. Everything here works on arrays of evaluations of
the ORIGINAL routine that the drivers in :mod:`.drivers` produced, so it can be
tested on synthetic functions whose derivatives are known in closed form.

Vocabulary used throughout
--------------------------

``ladder``
    The relative step sizes ``h_rel`` tried, largest first. The absolute step
    is ``h = h_rel * scale`` where ``scale`` is the size of the independent
    variable (see :func:`step_scale`).
``central[k]``
    ``(f(x + h_k) - f(x - h_k)) / (2 h_k)`` -- one array per step.
``forward[k]`` / ``backward[k]``
    ``(f(x + h_k) - f(x)) / h_k`` and ``(f(x) - f(x - h_k)) / h_k``.
``plateau``
    The consecutive steps over which the central difference stops moving:
    truncation error (falls as h**2) has died out and cancellation (grows as
    1/h) has not yet taken over. The reference is read from inside it, never
    from one step chosen in advance.
``branch-consistent step``
    A step whose +h and -h evaluations ended in the same discrete state
    (active set) as the unperturbed call. Only those steps are allowed to
    define a smooth reference; see :func:`classify_and_reference`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

#: Relative step ladder, largest first. Six decades, so a plateau of three
#: consecutive steps can sit anywhere from 1e-2 to 1e-7.
DEFAULT_LADDER: tuple = (1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7)

#: Relative tolerance of the entrywise rule (see :func:`judge_column`).
DEFAULT_RTOL = 1e-6
#: ``atol`` is NOT a fixed number any more: it is the round-off scale of the
#: routine's output at the state (:func:`roundoff_atol`). ``DEFAULT_ATOL`` is
#: only the absolute floor below which nothing is distinguishable from zero in
#: double precision at all (it keeps a zero output from giving atol = 0).
DEFAULT_ATOL = 1e-300

#: One-sided slopes whose disagreement, relative to the column norm, stays
#: above this at every step are taken to straddle a kink.
NONSMOOTH_GAP = 1e-3

#: Decision D-4 (B2 form): a reference value exists only on a plateau of at
#: least this many CONSECUTIVE ladder steps of the FD alone. There is no
#: "plausible" (2-step) verdict any more: fewer steps = unresolved.
MIN_PLATEAU = 3

#: An entry whose FD uncertainty ``u_e`` exceeds this fraction of ``|D_e|`` is
#: UNRESOLVED -- never verified, never failed (Vera B1/B).
RESOLUTION = 1e-3

#: Round-off bound of a central difference: ``NOISE_FACTOR * eps * F / h``
#: with ``F`` the magnitude of the output (and of the terms it is computed
#: from) at the state. 8 = 2 (two evaluations) x 2 (each rounded at least
#: once relative to F) x 2 (margin for a few more roundings inside the routine).
NOISE_FACTOR = 8.0

EPS = float(np.finfo(float).eps)
#: Unit round-off of IEEE binary128 (gfortran REAL(16)): the quad reference.
EPS_QUAD = 2.0 ** -112


def step_scale(value: float, typical: float = 0.0, floor: float = 1e-8) -> float:
    """The size an absolute step is measured against.

    ``max(|value|, |typical|, floor)``. ``typical`` lets a quantity that is zero
    at this state (a plastic strain before yield, a damage variable at onset)
    borrow the magnitude it reaches elsewhere in the history, so its step is
    not decided by the floor alone.
    """
    return max(abs(float(value)), abs(float(typical)), float(floor))


def central(plus: np.ndarray, minus: np.ndarray, h: float) -> np.ndarray:
    return (np.asarray(plus, float) - np.asarray(minus, float)) / (2.0 * h)


def one_sided(plus, base, minus, h):
    plus, base, minus = (np.asarray(a, float) for a in (plus, base, minus))
    return (plus - base) / h, (base - minus) / h


def roundoff(magnitude, h: float, eps: float = EPS) -> np.ndarray:
    """Round-off bound of a central difference of an output of size ``magnitude``
    computed in arithmetic of unit round-off ``eps``."""
    return NOISE_FACTOR * eps * np.asarray(magnitude, float) / max(abs(float(h)), 1e-300)


def roundoff_atol(magnitude, steps: Sequence[float], *, floor: float = DEFAULT_ATOL,
                  eps: float = EPS) -> np.ndarray:
    """The absolute tolerance of an entry: round-off scale of the routine output.

    ``atol_e = NOISE_FACTOR * eps * F_e / h_(3)`` where ``F_e`` is the
    magnitude of output ``e`` at this state (largest of incoming, base and
    every perturbed evaluation; the harness takes the largest STRESS component
    for every STRESS entry because rotations and pressure mix components) and
    ``h_(3)`` is the MIN_PLATEAU-th largest absolute step of the ladder. It is
    the round-off of the central difference at the smallest step a
    MIN_PLATEAU-step plateau starting at the largest step must use, i.e. the
    smallest |derivative| any admissible plateau of this ladder can resolve.
    An FD reference below it is indistinguishable from zero; a difference
    below it is not evidence of disagreement.
    """
    hs = sorted((abs(float(h)) for h in steps), reverse=True)
    h3 = hs[min(MIN_PLATEAU, len(hs)) - 1] if hs else 1.0
    return np.maximum(roundoff(magnitude, h3, eps), float(floor))


def observed_order(estimates: Sequence[np.ndarray], usable: Sequence[int],
                   ladder_ratio: float = 10.0) -> Optional[float]:
    """Convergence order seen in the truncation-dominated part of the ladder.

    With consecutive decades, ``|D_k - D_{k+1}| ~ C h_k^p`` gives
    ``p = log10(delta_k / delta_{k+1})``. Measured on the column's infinity
    norm over the first pair of differences that are both above round-off;
    ``None`` when the very first difference is already at the noise floor (the
    function is locally polynomial of degree <= 2 in the input, e.g. linear,
    and central differences are exact up to rounding).
    """
    usable = list(usable)
    if len(usable) < 3:
        return None
    deltas = []
    for a, b in zip(usable, usable[1:]):
        d = float(np.nanmax(np.abs(np.asarray(estimates[a]) - np.asarray(estimates[b]))))
        deltas.append(d)
    scale = max(float(np.nanmax(np.abs(np.asarray(estimates[usable[0]])))), 1e-300)
    # Differences below sqrt(eps) of the column are round-off, not truncation:
    # a response that is linear in the input shows no order at all.
    noise = math.sqrt(np.finfo(float).eps) * scale
    for d0, d1 in zip(deltas, deltas[1:]):
        if d0 > noise and d1 > noise:
            return math.log(d0 / d1) / math.log(ladder_ratio)
    return None


@dataclass
class ColumnFD:
    """The FD ladder of one column (one input) at one state."""

    estimates: list            # central difference per ladder step
    forward: list
    backward: list
    usable: list               # finite AND branch-consistent ladder indices
    finite: list               # finite ladder indices
    smooth: bool
    reason: str
    gaps: list                 # |forward - backward|_inf / |central|_inf per step
    order: Optional[float] = None
    steps: list = field(default_factory=list)      # absolute steps
    base: Optional[np.ndarray] = None              # unperturbed outputs
    #: per output, the largest |value| among the base and every finite
    #: perturbed evaluation at this state (the round-off scale; callers widen
    #: it with the incoming state and, for STRESS, with the block maximum)
    magnitude: Optional[np.ndarray] = None


def classify_and_reference(plus: Sequence[np.ndarray], minus: Sequence[np.ndarray],
                           base: np.ndarray, steps: Sequence[float], *,
                           same_branch: Optional[Sequence[bool]] = None,
                           gap_threshold: float = NONSMOOTH_GAP,
                           output_scale: float = 0.0, magnitude=None,
                           eps: float = EPS) -> ColumnFD:
    """Build the FD ladder for one column and decide whether the state is smooth.

    ``plus[k]``/``minus[k]`` are the outputs at ``x +/- steps[k]`` (absolute),
    ``base`` the unperturbed output. ``same_branch[k]`` says whether both
    perturbed calls at step ``k`` ended in the unperturbed call's discrete
    state (active set); omitted means every step is consistent.

    Rules, in order:

    1. A step whose evaluations are non-finite is unusable.
    2. A step whose +h or -h call changed branch is unusable (it straddles a
       kink and measures a chord across it).
    3. If a branch change removed steps and fewer than MIN_PLATEAU consistent
       steps remain, the state is NONSMOOTH.
    4. If, on every consistent step, the one-sided slopes disagree by more
       than ``gap_threshold`` of the column's largest central slope, the state
       is NONSMOOTH by FD asymmetry (a kink the discrete state did not show).
       A gap below the round-off of a one-sided difference,
       ``16 eps output_scale / h`` (``output_scale`` = largest |output| on the
       path), is not counted: at a state where the response has cancelled to
       ~0 (a closed cycle back at the origin) both slopes are round-off.
    """
    base = np.asarray(base, float)
    estimates, forward, backward, gaps = [], [], [], []
    finite, consistent = [], []
    for k, h in enumerate(steps):
        p, m = np.asarray(plus[k], float), np.asarray(minus[k], float)
        c = central(p, m, h)
        f, b = one_sided(p, base, m, h)
        estimates.append(c); forward.append(f); backward.append(b)
        ok = bool(np.all(np.isfinite(c)) and np.all(np.isfinite(f)) and np.all(np.isfinite(b)))
        if ok:
            finite.append(k)
            if same_branch is None or same_branch[k]:
                consistent.append(k)
        norm = float(np.max(np.abs(c))) if ok and c.size else 0.0
        gap = float(np.max(np.abs(f - b))) if ok and c.size else 0.0
        if gap <= 16.0 * eps * float(output_scale) / max(abs(h), 1e-300):
            gap = 0.0
        gaps.append(gap / norm if ok and norm > 0 else (0.0 if ok else float("nan")))
    if magnitude is None:
        magnitude = np.abs(np.nan_to_num(base, nan=0.0, posinf=0.0, neginf=0.0)).reshape(-1)
        for k in finite:
            for arr in (plus[k], minus[k]):
                magnitude = np.maximum(magnitude, np.abs(np.asarray(arr, float)).reshape(-1))
    else:
        # caller-supplied (quad reference: plus/minus are DIFFERENCES from
        # the base, the magnitude comes from the absolute outputs)
        magnitude = np.asarray(magnitude, float).reshape(-1)
    column = ColumnFD(estimates, forward, backward, consistent, finite, True, "smooth", gaps,
                      order=observed_order(estimates, consistent), steps=list(steps), base=base,
                      magnitude=magnitude)
    if not finite:
        column.smooth, column.reason = False, "no step produced finite perturbed evaluations"
        return column
    rejected = [k for k in finite if k not in consistent]
    if rejected and len(consistent) < MIN_PLATEAU:
        column.smooth = False
        column.reason = (f"branch change across +/-h at {len(rejected)} of {len(finite)} "
                         f"finite steps; {len(consistent)} consistent step(s) left")
        return column
    usable_gaps = [gaps[k] for k in consistent if math.isfinite(gaps[k])]
    if usable_gaps and min(usable_gaps) > gap_threshold:
        column.smooth = False
        column.reason = (f"one-sided slopes disagree by >= {min(usable_gaps):.3e} of the "
                         "column at every consistent step (kink not visible in the "
                         "discrete state)")
    elif rejected:
        column.reason = f"smooth on the {len(consistent)} branch-consistent steps"
    return column


#: Per-entry verdict codes (``ColumnVerdict.codes``).
PASS, ZERO_PASS, FAIL, UNRESOLVED_PLATEAU, UNRESOLVED_SPREAD, UNRESOLVED_ZERO, OTI_NONFINITE = (
    "pass", "zero_pass", "fail", "unresolved_no_plateau", "unresolved_spread",
    "unresolved_zero_spread", "fail_oti_nonfinite")
UNRESOLVED_ROUNDOFF = "unresolved_roundoff"
#: the reference sits below atol, but atol is not < RESOLUTION x the column's
#: derivative scale and the FD differences are not exactly zero: "structural
#: zero" cannot be told from "true derivative under the noise" (Vera B2/C)
UNRESOLVED_ZERO_SCALE = "unresolved_zero_scale"


@dataclass
class ColumnVerdict:
    """One derivative column (one input) at one state, judged entry by entry."""

    compared: int = 0
    passed: int = 0           # nonzero reference, resolved, |oti - D| <= tau
    zero_passed: int = 0      # reference below atol (structural zero), |oti| <= atol + 2u
    failed: int = 0           # resolved and outside tau, or OTI non-finite
    unresolved: int = 0       # no >=3-step FD plateau, or u_e too large
    unresolved_reasons: dict = field(default_factory=dict)
    max_abs: float = 0.0
    max_rel: float = 0.0      # |oti - D| / |D| over resolved nonzero entries
    max_ratio: float = 0.0    # |oti - D| / tau over resolved entries
    max_rel_tolerance: float = 0.0   # tau / |D| over resolved nonzero entries
    #: the entry with the largest err/t over BOTH branches (zero and nonzero
    #: reference; Vera B10: it was taken over the nonzero branch only, so a
    #: column failing on a zero entry reported a passing worst entry)
    worst_entry: int = -1
    tolerance_at_worst: float = 0.0
    worst_ratio: float = -1.0
    error_at_worst: float = 0.0
    min_plateau: int = 0      # shortest plateau run among resolved entries
    plateau_steps: tuple = ()
    reference: Optional[np.ndarray] = None     # D_e (nan where no plateau)
    uncertainty: Optional[np.ndarray] = None   # u_e
    tolerance: Optional[np.ndarray] = None     # tau_e
    atol: Optional[np.ndarray] = None
    codes: list = field(default_factory=list)  # per-entry verdict code
    failed_entries: list = field(default_factory=list)   # (entry, oti, fd, tol, plateau)

    @property
    def resolved(self) -> int:
        return self.passed + self.zero_passed + self.failed

    @property
    def status(self) -> str:
        if self.failed:
            return "failed"
        if self.unresolved:
            return "unresolved"
        return "verified"


def entry_plateau(series: np.ndarray, usable: Sequence[int], noise: np.ndarray,
                  atol: float, *, rtol: float = DEFAULT_RTOL) -> Optional[tuple]:
    """The FD-only plateau of ONE entry.

    ``series[k]`` = central difference at ladder step ``k``, ``noise[k]`` its
    round-off bound. A step is admissible for this entry when it is usable
    (finite, branch-consistent) and its round-off bound is at most
    ``max(RESOLUTION * |D_k|, atol)`` -- or when the entry is bit-identical at
    every usable step (exactly linear or independent of the input; round-off
    bounds do not apply to an exact result). Two admissible steps adjacent IN
    THE LADDER agree when ``|D_k - D_k+1| <= max(rtol max(|D_k|,|D_k+1|),
    noise_k + noise_k+1)``. A run is a maximal sequence of consecutive agreeing
    steps; only runs of >= MIN_PLATEAU count. Within them, the plateau is the
    window of MIN_PLATEAU consecutive steps with the smallest spread (adding
    steps can only widen it); ties go to the larger steps.

    Returns ``(D, u, first, last, run_length)``: ``D`` the median of the window,
    ``u`` = its spread ``max |D_k - D|``, and the window's ladder indices;
    ``None`` when no run of MIN_PLATEAU steps exists. (The round-off bound
    decides admissibility and agreement; it is NOT added to ``u``: measured on
    Jeff97 DDSDDE(4,4), a bound from the STRESS block maximum (3.7e9) was 1000x
    the actual agreement of the ladder, 3e-9 relative.)
    """
    usable = sorted(k for k in set(usable) if np.isfinite(series[k]))
    if len(usable) < MIN_PLATEAU:
        return None
    values = np.array([series[k] for k in usable])
    constant = bool(np.all(values == values[0]))
    admissible = [k for k in usable
                  if constant or noise[k] <= max(RESOLUTION * abs(series[k]), atol)]
    runs, current = [], []
    for k in admissible:
        if current and k == current[-1] + 1:
            a, b = series[current[-1]], series[k]
            if abs(a - b) <= max(rtol * max(abs(a), abs(b)), noise[current[-1]] + noise[k]):
                current.append(k)
                continue
        if len(current) >= MIN_PLATEAU:
            runs.append(current)
        current = [k]
    if len(current) >= MIN_PLATEAU:
        runs.append(current)
    best = None
    for run in runs:
        for i in range(len(run) - MIN_PLATEAU + 1):
            window = run[i:i + MIN_PLATEAU]
            seg = np.array([series[k] for k in window])
            d = float(np.median(seg))
            spread = float(np.max(np.abs(seg - d)))
            u = spread
            if best is None or u < best[1]:
                best = (d, u, window[0], window[-1], len(run))
    return best


def judge_column(oti: np.ndarray, estimates: Sequence[np.ndarray], usable: Sequence[int],
                 ladder: Sequence[float], *, steps: Optional[Sequence[float]] = None,
                 magnitude: Optional[np.ndarray] = None, rtol: float = DEFAULT_RTOL,
                 atol_floor: float = DEFAULT_ATOL, eps: float = EPS,
                 value_eps: float = EPS,
                 value_magnitude: Optional[np.ndarray] = None,
                 euler=True,
                 derivative_scale: float = 0.0,
                 kinematic_input: float = 0.0,
                 block_derivative: float = 0.0,
                 double_zero=None,
                 n_increments: int = 1) -> ColumnVerdict:
    """Compare one column of derivatives against the FD ladder, entry by entry.

    The rule (B2; Vera B1/B, C):

    * reference ``D_e`` and uncertainty ``u_e`` from the entry's own FD-only
      plateau of >= MIN_PLATEAU consecutive steps (:func:`entry_plateau`);
      the value under test plays no part in finding it;
    * ``atol_e`` = round-off scale of the routine output (:func:`roundoff_atol`)
      with ``F_e = max(own magnitude of output e at the state, max_e' |D_e'| |x|)``
      -- the second term is the size of the terms that carry the input into
      the output (a cancelled component carries their round-off); it puts
      atol_e near 1.8e-11 of the column at most, a round-off scale, not a
      tolerance floor;
    * ``|D_e| <= atol_e`` (atol_e with the value term capped, below): STRUCTURAL
      ZERO candidate. Resolved if ``u_e <= atol_e`` AND (the entry's central
      differences are exactly 0 at every usable step, OR
      ``atol_e < RESOLUTION * S`` with ``S`` the column's derivative scale,
      ``max(max_e |D_e|, derivative_scale)``); otherwise UNRESOLVED
      (``unresolved_zero_scale``: a true derivative under the noise cannot be
      told from a zero). Passes iff ``|oti_e| <= atol_e + 2 u_e``;
    * otherwise ``u_e > RESOLUTION |D_e|`` or ``atol_e > RESOLUTION |D_e|`` ->
      UNRESOLVED (never verified, never failed); else passes iff
      ``|oti_e - D_e| <= tau_e = atol_e + rtol |D_e| + 2 u_e`` (so tau_e <= ~3e-3 |D_e|);
    * no plateau -> UNRESOLVED; a non-finite value under test -> FAILED.

    The value-under-test round-off term (``value_magnitude``, n x max|o| for
    a total derivative) is capped at ``RESOLUTION * S``: it can never open a
    window larger than 1e-3 of the column's derivative scale (Vera B2/C: with
    D=500 and the uncapped term 888, a dropped derivative passed as zero).
    ``euler`` (default True) widens each output's round-off magnitude with
    the column-max Euler term ``max_e' |D_e'| |x|``; it is meant for a block
    of ONE unit (STRESS, DDSDDE). A STATEV block mixes units (an energy-like
    slot 1e12 times a plastic-strain slot), so the harness passes
    ``euler="bracket"`` there: the column is judged with each slot's OWN
    magnitude and with the Euler term; an entry whose verdict differs between
    the two (a slot that is a cancelled difference of large terms fails on its
    own magnitude and passes on the Euler one; a wrong small slot passes only
    on the Euler one) is UNRESOLVED (``unresolved_euler_window``) -- never
    passed, never failed on a round-off model the two disagree about. ``eps`` is the unit round-off of the arithmetic the reference was
    evaluated in (EPS, or EPS_QUAD for the quad-precision reference build);
    ``kinematic_input`` / ``block_derivative`` (Vera B7 A1): the Euler term is
    ``max(column_max, block_derivative) * max(|x|, kinematic_input)`` -- the
    largest derivative term across the BLOCK times the TOTAL kinematic input
    (``|STRAN + DSTRAN|`` or ``|DFGRD1|``), not the increment: a stress built
    as K (J - 1) from a total measure carries the round-off of the total, and
    with the increment (2.7e-8 on PureGravity) quantised entries read as
    resolved and failed. An entry whose central differences are exactly zero
    at every usable step is a structural zero only if ``atol < 1e-3 S``; the
    exact-zero exemption applies to the QUAD reference only (in double a
    zero can be quantisation). ``double_zero`` (quad pass, per entry: the
    double ladder was exactly zero too): a zero in both precisions against a
    nonzero value under test FAILS (Vera B7 A3);
    ``value_eps`` that of the value under test (double: EPS).
    ``steps`` are the absolute steps (default: the relative ladder) and
    ``magnitude`` the output magnitude at the state per entry (default: the
    largest |central difference x step| seen, a weak lower bound -- callers
    that have the outputs pass them).
    """
    if euler == "bracket":
        kw = dict(steps=steps, magnitude=magnitude, rtol=rtol, atol_floor=atol_floor, eps=eps,
                  value_eps=value_eps, value_magnitude=value_magnitude,
                  derivative_scale=derivative_scale, kinematic_input=kinematic_input,
                  block_derivative=block_derivative, double_zero=double_zero,
                  n_increments=n_increments)
        own = judge_column(oti, estimates, usable, ladder, euler=False, **kw)
        wide = judge_column(oti, estimates, usable, ladder, euler=True, **kw)
        return _bracket(own, wide, np.asarray(oti, float).reshape(-1), ladder)
    oti = np.asarray(oti, float).reshape(-1)
    n = oti.size
    steps = list(ladder if steps is None else steps)
    verdict = ColumnVerdict()
    est = [np.asarray(e, float).reshape(-1) for e in estimates]
    usable = [k for k in usable if k < len(est)]
    if magnitude is None:
        stack = np.stack([np.abs(est[k]) * abs(steps[k]) for k in usable]) if usable else np.zeros((1, n))
        magnitude = np.nanmax(stack, axis=0) if stack.size else np.zeros(n)
    mag = np.broadcast_to(np.asarray(magnitude, float).reshape(-1), (n,)) if np.size(magnitude) in (1, n) \
        else np.asarray(magnitude, float).reshape(-1)
    finite_est = [np.abs(est[k]) for k in usable if np.all(np.isfinite(est[k]))]
    column_max = float(np.max(np.median(np.stack(finite_est), axis=0))) if finite_est else 0.0
    input_scale = abs(float(steps[0])) / max(abs(float(ladder[0])), 1e-300)
    # Round-off magnitude per output: its own size, or the size of the terms
    # that carry the input's influence into it (|do/dx|_max |x|, Euler
    # scaling), whichever is larger -- a component that is the cancelled
    # difference of such terms (sigma_22 ~ 1e-15 from terms ~ 4 in the
    # independence check) has their round-off, not its own.
    if euler:
        mag = np.maximum(mag, max(column_max, abs(float(block_derivative)))
                         * max(input_scale, abs(float(kinematic_input))))
    noise = np.array([roundoff(mag, h, eps) for h in steps])      # (steps, n)
    # atol is the larger of the REFERENCE's round-off scale and the round-off
    # of the VALUE UNDER TEST (computed in double: its derivative terms are
    # ~F_e/|x| by the same Euler scaling). With a double reference the first
    # always dominates; with the quad reference the second is what keeps an
    # exact zero computed in double from "failing" against 1e-22 (measured on
    # the independence check: sigma_22 of a uniaxial-stress-like direction).
    # ``value_magnitude`` (the harness passes n x the output's history maximum
    # for a TOTAL derivative) widens only the value-under-test term: a
    # derivative carried through n increments carries their round-off, which
    # a quad reference resolves far below (measured: abaci, Lemaitre, irfancn
    # total derivatives at states where the response had cancelled to ~0).
    vmag = mag if value_magnitude is None else np.maximum(
        mag, np.broadcast_to(np.asarray(value_magnitude, float).reshape(-1), mag.shape))
    atol_ref = roundoff_atol(mag, steps, floor=atol_floor, eps=eps)
    # the value under test's own round-off: its terms are ~F/|x| with x the
    # same kinematic scale the Euler term uses (A1), not the increment alone
    # (Vera G10 review B2: with |F| in vmag and the increment here the
    # allowance was |F|/|dx| too large, and a 1e-4 defect passed under quad)
    value_term = NOISE_FACTOR * value_eps * vmag / max(input_scale, abs(float(kinematic_input)),
                                                       1e-300)
    # pass 1: every entry's FD-only plateau (admissibility from the
    # REFERENCE's round-off only), and the column's derivative scale from them
    series_all, found_all = [], []
    for e in range(n):
        series = np.array([est[k][e] if k < len(est) else np.nan for k in range(len(steps))])
        series_all.append(series)
        found_all.append(entry_plateau(series, usable, noise[:, e], float(atol_ref[e]), rtol=rtol))
    scale = max([abs(f[0]) for f in found_all if f is not None and np.isfinite(f[0])]
                + [abs(float(derivative_scale))], default=0.0)
    atol = np.maximum(atol_ref, np.minimum(value_term, RESOLUTION * scale))
    ref = np.full(n, np.nan); unc = np.full(n, np.nan); tau = np.full(n, np.nan)
    plateaus = []
    for e in range(n):
        verdict.compared += 1
        series, found = series_all[e], found_all[e]
        if not np.isfinite(oti[e]):
            verdict.failed += 1
            verdict.codes.append(OTI_NONFINITE)
            verdict.failed_entries.append((e, float(oti[e]), float("nan") if found is None
                                           else found[0], float("nan"), ()))
            continue
        if found is None:
            verdict.unresolved += 1
            verdict.codes.append(UNRESOLVED_PLATEAU)
            continue
        d, u, first, last, run = found
        ref[e], unc[e] = d, u
        if abs(d) <= atol[e]:
            if u > atol[e]:
                verdict.unresolved += 1
                verdict.codes.append(UNRESOLVED_ZERO)
                continue
            exact_zero = all(series[k] == 0.0 for k in usable)
            quad = eps < EPS
            both_zero = bool(quad and exact_zero and double_zero is not None
                             and bool(np.asarray(double_zero, bool).reshape(-1)[e]))
            if not ((exact_zero and quad) or atol[e] < RESOLUTION * scale):
                verdict.unresolved += 1
                verdict.codes.append(UNRESOLVED_ZERO_SCALE)
                continue
            t = atol[e] + 2.0 * u
            # The value under test is computed in DOUBLE, so it is "nonzero"
            # only above floor_v = NOISE eps max(S, |block|) (x n for a total
            # derivative), capped at RESOLUTION S (Vera pass21 review: Flat/
            # Th01 BodyForce (1,5), OTI 1.9e-27 against a zero in both
            # precisions, failed A3 with no floor).
            floor_v = min(NOISE_FACTOR * EPS * max(scale, abs(float(block_derivative)))
                          * max(int(n_increments), 1), RESOLUTION * scale)
            # the threshold the decision actually used is the one reported
            # (Vera B10: a FAIL never shows a ratio < 1)
            t = floor_v if both_zero else max(t, floor_v)
            ok = abs(oti[e]) <= t
            # reported: where quad resolves a small nonzero D (u <= 1e-3 |D|),
            # the distance on a PASS is to the nearer of 0 and D; a FAIL
            # reports the quantity it was decided on, |oti|
            err = (min(abs(oti[e]), abs(oti[e] - d))
                   if ok and quad and d != 0.0 and u <= RESOLUTION * abs(d) else abs(oti[e]))
            verdict.zero_passed += ok
            code = ZERO_PASS if ok else FAIL
        else:
            if u > RESOLUTION * abs(d):
                verdict.unresolved += 1
                verdict.codes.append(UNRESOLVED_SPREAD)
                continue
            if atol[e] > RESOLUTION * abs(d):
                # resolved plateau, but within 1000x of the round-off scale:
                # the tolerance would exceed the stated resolution
                verdict.unresolved += 1
                verdict.codes.append(UNRESOLVED_ROUNDOFF)
                continue
            t = atol[e] + rtol * abs(d) + 2.0 * u
            err = abs(oti[e] - d)
            ok = err <= t
            verdict.passed += ok
            code = PASS if ok else FAIL
            rel = err / abs(d)
            verdict.max_rel_tolerance = max(verdict.max_rel_tolerance, t / abs(d))
            verdict.max_rel = max(verdict.max_rel, rel)
        ratio = float(err / t) if t > 0 else float("inf")
        if ratio > verdict.worst_ratio:
            verdict.worst_entry, verdict.worst_ratio = e, ratio
            verdict.tolerance_at_worst, verdict.error_at_worst = float(t), float(err)
            verdict.plateau_steps = (ladder[first], ladder[last])
        tau[e] = t
        verdict.codes.append(code)
        plateaus.append(run)
        verdict.max_abs = max(verdict.max_abs, float(err))
        verdict.max_ratio = max(verdict.max_ratio, float(err / t) if t > 0 else float("inf"))
        if not ok:
            verdict.failed += 1
            verdict.failed_entries.append((e, float(oti[e]), float(d), float(t),
                                           (ladder[first], ladder[last])))
    for code in verdict.codes:
        if code.startswith("unresolved"):
            verdict.unresolved_reasons[code] = verdict.unresolved_reasons.get(code, 0) + 1
    verdict.min_plateau = min(plateaus) if plateaus else 0
    verdict.reference, verdict.uncertainty, verdict.tolerance, verdict.atol = ref, unc, tau, atol
    return verdict


UNRESOLVED_EULER = "unresolved_euler_window"
_OK = (PASS, ZERO_PASS)


def _bracket(own: ColumnVerdict, wide: ColumnVerdict, oti: np.ndarray, ladder) -> ColumnVerdict:
    """Entry-wise agreement of the own-magnitude and Euler verdicts (see
    judge_column, ``euler="bracket"``). The own-magnitude verdict is kept where
    both agree (pass/zero_pass count as agreeing); elsewhere UNRESOLVED."""
    v = ColumnVerdict(compared=own.compared, reference=own.reference,
                      uncertainty=own.uncertainty, atol=own.atol,
                      tolerance=own.tolerance.copy() if own.tolerance is not None else None)
    plateaus = []
    for e, (a, b) in enumerate(zip(own.codes, wide.codes)):
        agree = (a == b) or (a in _OK and b in _OK)
        code = a if agree else UNRESOLVED_EULER
        v.codes.append(code)
        if code.startswith("unresolved"):
            v.unresolved += 1
            if v.tolerance is not None:
                v.tolerance[e] = np.nan
            continue
        if code == OTI_NONFINITE:
            v.failed += 1
            v.failed_entries.append((e, float(oti[e]), float(own.reference[e]), float("nan"), ()))
            continue
        d, t = float(own.reference[e]), float(own.tolerance[e])
        err = abs(oti[e]) if code == ZERO_PASS or (code == FAIL and abs(d) <= own.atol[e])             else abs(oti[e] - d)
        v.max_abs = max(v.max_abs, float(err))
        v.max_ratio = max(v.max_ratio, float(err / t) if t > 0 else float("inf"))
        if code == PASS:
            v.passed += 1
        elif code == ZERO_PASS:
            v.zero_passed += 1
        else:
            v.failed += 1
            v.failed_entries.append((e, float(oti[e]), d, t, ()))
        if code in (PASS, FAIL) and d != 0 and abs(d) > own.atol[e]:
            rel = err / abs(d)
            v.max_rel_tolerance = max(v.max_rel_tolerance, t / abs(d))
            v.max_rel = max(v.max_rel, rel)
        ratio = float(err / t) if t > 0 else float("inf")
        if ratio > v.worst_ratio:
            v.worst_entry, v.worst_ratio = e, ratio
            v.tolerance_at_worst, v.error_at_worst = t, float(err)
            v.plateau_steps = own.plateau_steps
        plateaus.append(own.min_plateau)
    for code in v.codes:
        if code.startswith("unresolved"):
            v.unresolved_reasons[code] = v.unresolved_reasons.get(code, 0) + 1
    v.min_plateau = min(plateaus) if plateaus else 0
    return v


def judge_primal(a: np.ndarray, b: np.ndarray, *, rtol: float = 1e-10,
                 atol: float = 1e-14) -> dict:
    """Primal agreement of two trajectories of one array (rows = increments).

    Scaled per row by the row's largest magnitude, the same rule the corpus
    primal comparison applies: a component that is a vanishing fraction of the
    response carries each build's rounding and nothing else.
    """
    a, b = np.atleast_2d(np.asarray(a, float)), np.atleast_2d(np.asarray(b, float))
    if a.shape != b.shape:
        return {"agrees": False, "reason": f"shape {a.shape} vs {b.shape}"}
    both_nan = ~np.isfinite(a) & ~np.isfinite(b)
    one_nan = np.isfinite(a) ^ np.isfinite(b)
    if one_nan.any():
        return {"agrees": False, "reason": "finite in one build, not in the other",
                "max_abs": float("inf"), "max_rel": float("inf")}
    magnitude = np.where(both_nan, 0, np.abs(a))
    scale = np.maximum(np.nanmax(magnitude, axis=1, keepdims=True),
                       1e-3 * float(np.nanmax(magnitude, initial=0.0)))
    err = np.where(both_nan, 0.0, np.abs(a - b))
    tol = atol + rtol * scale
    rel = err / np.where(scale > 0, scale, 1.0)
    return {"agrees": bool(np.all(err <= tol)), "max_abs": float(err.max(initial=0.0)),
            "max_rel": float(rel.max(initial=0.0)),
            "max_error_over_tolerance": float((err / tol).max(initial=0.0)),
            "rtol": rtol, "atol": atol,
            "scale_rule": "per increment, max(largest |component| of the array, 1e-3 x its "
                          "largest |component| over the history)"}
