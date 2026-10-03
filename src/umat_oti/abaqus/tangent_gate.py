"""The Abaqus-side tangent gate under decision D-4 (G10; Curie B7 items 1-7,
Vera B7 amendments A1-A8).

The value under test is DDSDDE out of the transformed build's own probe
record; the reference is a centred difference of the ORIGINAL source,
replayed from the state that record began in (:func:`umat_oti.abaqus.replay.
difference_tangent`). This module judges one replayed state and then the
row, with the same entrywise rule the routine-level harness uses
(:func:`umat_oti.corpus_features.fd.judge_column`):

* every entry from its own FD-only plateau of >= 3 steps (no 2-step
  plateaus, no best-relative-per-entry: Curie's G1/G2);
* the round-off magnitude is the largest derivative across the block times
  the TOTAL kinematic input, plus the stress over every perturbed
  evaluation (A1); a bitwise-zero double ladder is a structural zero only
  if atol < 1e-3 of the scale; in quad it is exempt;
* smoothness per ENTRY (A6): an entry is nonsmooth when, at every step, its
  forward/backward gap exceeds both its own round-off bound and 1e-3 of the
  centred value; one nonsmooth entry makes its column nonsmooth;
* a state is JUDGED only if every entry passes or zero-passes and every
  column is smooth (A4). A failure anywhere, in either precision, stands
  (A3); a quad reference only resolves entries the double one left
  unresolved, and a zero in both precisions against a nonzero DDSDDE fails;
* the row: verified iff no failure, >= 2 judged states, judged >= 50% of
  the CHOSEN states (the denominator is every chosen state), and the
  coverage rule holds on the judged states only. The author's own tangent
  and a one-sided "branch" difference are diagnostics, never a verdict.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

from umat_oti.corpus_features import fd

#: Of the chosen states, the fraction that has to be judged (A4).
MIN_JUDGED_FRACTION = 0.5
#: Judged states needed at least.
MIN_JUDGED_STATES = 2
#: An entry's one-sided gap counts as a kink only above this fraction of its
#: centred value (A6), and above its own round-off bound.
ENTRY_GAP = 1e-3
#: Round-off of a ONE-sided difference: 2 evaluations x 2 roundings x 2
#: margin x 2 (one-sided, no averaging) = 16 eps F / h.
ONE_SIDED_NOISE = 16.0

_OK = (fd.PASS, fd.ZERO_PASS)


def _matrix(by_step: dict, relative: float, ntens: int) -> Optional[np.ndarray]:
    value = by_step.get(relative)
    if value is None:
        return None
    return np.asarray(value, float).reshape(ntens, ntens)


@dataclass
class StateJudgement:
    """One replayed state, judged entry by entry."""

    increment: Optional[int] = None
    ntens: int = 0
    codes: Counter = field(default_factory=Counter)
    #: (row, column) 1-based -> code
    entry_codes: dict = field(default_factory=dict)
    failures: list = field(default_factory=list)
    nonsmooth_entries: list = field(default_factory=list)
    nonsmooth_columns: list = field(default_factory=list)
    precision: str = "double"
    reason: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.failures)

    @property
    def smooth(self) -> bool:
        return not self.nonsmooth_columns

    @property
    def judged(self) -> bool:
        return (bool(self.entry_codes) and self.smooth and not self.failed
                and all(code in _OK for code in self.entry_codes.values()))

    def unresolved_entries(self) -> list:
        return [entry for entry, code in self.entry_codes.items()
                if code.startswith("unresolved")]

    def as_dict(self) -> dict:
        return {"increment": self.increment, "judged": self.judged, "smooth": self.smooth,
                "precision": self.precision, "entries": dict(self.codes),
                "failures": self.failures[:12],
                "nonsmooth_entries": self.nonsmooth_entries[:12],
                "nonsmooth_columns": self.nonsmooth_columns,
                "unresolved_entries": [list(e) for e in self.unresolved_entries()[:24]],
                "reason": self.reason}


def entry_smoothness(forward: Sequence[np.ndarray], backward: Sequence[np.ndarray],
                     centred: Sequence[np.ndarray], steps: Sequence[float],
                     magnitude: np.ndarray, eps: float = fd.EPS) -> np.ndarray:
    """Per entry of one column: True where it is nonsmooth (A6).

    Nonsmooth = at EVERY step, |forward - backward| exceeds both the entry's
    one-sided round-off bound (16 eps F / h) and 1e-3 |centred|."""
    if not forward:
        return np.zeros(np.asarray(magnitude).size, bool)
    kink = None
    for f, b, c, h in zip(forward, backward, centred, steps):
        f, b, c = (np.asarray(x, float).reshape(-1) for x in (f, b, c))
        gap = np.abs(f - b)
        noise = ONE_SIDED_NOISE * eps * np.asarray(magnitude, float) / max(abs(h), 1e-300)
        here = (gap > noise) & (gap > ENTRY_GAP * np.abs(c))
        kink = here if kink is None else (kink & here)
    return kink


def judge_state(oti, sweep, ladder: Sequence[float], scale: float, *,
                kinematic_input: float = 0.0, stress_magnitude=None,
                eps: float = fd.EPS, increment: Optional[int] = None,
                double_zero: Optional[np.ndarray] = None,
                undefined: Optional[np.ndarray] = None) -> StateJudgement:
    """Judge one state: ``oti`` (ntens x ntens) against ``sweep`` (a
    :class:`replay.DifferenceSweep`: ``matrices``/``forward``/``backward``
    keyed by relative step).

    ``stress_magnitude`` (per STRESS component): the largest |stress| over
    the unperturbed and every perturbed evaluation (A1); defaults to the
    unperturbed stress. ``kinematic_input``: max |STRAN + DSTRAN| (or
    |DFGRD1|) at the state (A1). ``double_zero`` (ntens x ntens bool, quad
    pass): entries the double ladder found exactly zero (A3). ``undefined``
    (ntens x ntens bool): entries undefined in the original (D-12), not
    compared."""
    oti = np.asarray(oti, float)
    ntens = oti.shape[0]
    out = StateJudgement(increment=increment, ntens=ntens,
                         precision="quad" if eps < fd.EPS else "double")
    rel = [r for r in ladder if r in sweep.matrices]
    if len(rel) < fd.MIN_PLATEAU:
        out.reason = f"only {len(rel)} step size(s) produced a complete difference"
        return out
    steps = [r * scale for r in rel]
    centred = {r: _matrix(sweep.matrices, r, ntens) for r in rel}
    forward = {r: _matrix(sweep.forward, r, ntens) for r in rel}
    backward = {r: _matrix(sweep.backward, r, ntens) for r in rel}
    if stress_magnitude is None:
        stress_magnitude = np.abs(np.asarray(sweep.unperturbed or np.zeros(ntens), float))
    magnitude = np.asarray(stress_magnitude, float).reshape(-1)
    block = max((float(np.max(np.abs(centred[rel[0]][:, j]))) for j in range(ntens)),
                default=0.0)
    for j in range(ntens):
        estimates = [centred[r][:, j] for r in rel]
        keep = np.ones(ntens, bool) if undefined is None else ~np.asarray(undefined)[:, j]
        if not keep.any():
            continue
        if all(forward[r] is not None and backward[r] is not None for r in rel):
            kink = entry_smoothness([forward[r][:, j] for r in rel],
                                    [backward[r][:, j] for r in rel],
                                    estimates, steps, magnitude, eps)
            kink = kink & keep
            if kink.any():
                out.nonsmooth_columns.append(j + 1)
                out.nonsmooth_entries.extend([[i + 1, j + 1] for i in np.flatnonzero(kink)])
                continue
        verdict = fd.judge_column(
            oti[keep, j], [e[keep] for e in estimates], list(range(len(rel))), list(rel),
            steps=steps, magnitude=magnitude[keep], eps=eps,
            kinematic_input=kinematic_input, block_derivative=block,
            double_zero=None if double_zero is None else np.asarray(double_zero)[keep, j])
        rows = np.flatnonzero(keep)
        for code, i in zip(verdict.codes, rows):
            out.entry_codes[(int(i) + 1, j + 1)] = code
            out.codes[code] += 1
        for e, o, d, t, plateau in verdict.failed_entries:
            out.failures.append({"entry": [int(rows[e]) + 1, j + 1], "oti": o, "fd": d,
                                 "tolerance": t, "plateau_relative_steps": list(plateau),
                                 "precision": out.precision})
    out.reason = (f"{out.codes.get(fd.PASS, 0)} pass, {out.codes.get(fd.ZERO_PASS, 0)} "
                  f"zero-pass, {sum(v for k, v in out.codes.items() if k.startswith('unres'))} "
                  f"unresolved, {len(out.failures)} failed; nonsmooth columns "
                  f"{out.nonsmooth_columns or 'none'}")
    return out


def exact_zero(sweep, ladder: Sequence[float], ntens: int) -> np.ndarray:
    """Entries whose centred difference is exactly zero at every step."""
    stack = [np.asarray(sweep.matrices[r], float).reshape(ntens, ntens)
             for r in ladder if r in sweep.matrices]
    if not stack:
        return np.zeros((ntens, ntens), bool)
    return np.all(np.stack(stack) == 0.0, axis=0)


def merge_quad(double: StateJudgement, quad: Optional[StateJudgement]) -> StateJudgement:
    """A3: a failure in either precision stands; the quad reference only
    resolves entries the double one left unresolved; never pick-best."""
    if quad is None:
        return double
    merged = StateJudgement(increment=double.increment, ntens=double.ntens,
                            precision="double+quad")
    merged.failures = list(double.failures) + [f for f in quad.failures]
    merged.nonsmooth_columns = sorted(set(double.nonsmooth_columns) | set(quad.nonsmooth_columns))
    merged.nonsmooth_entries = double.nonsmooth_entries + quad.nonsmooth_entries
    for entry, code in double.entry_codes.items():
        if code.startswith("unresolved") and entry in quad.entry_codes:
            code = quad.entry_codes[entry]
            if code.startswith("unresolved"):
                code = double.entry_codes[entry]
        merged.entry_codes[entry] = code
    for entry, code in quad.entry_codes.items():
        if code == fd.FAIL or code == fd.OTI_NONFINITE:
            merged.entry_codes[entry] = code
    merged.codes = Counter(merged.entry_codes.values())
    merged.reason = f"double: {double.reason}; quad: {quad.reason}"
    return merged


def row_verdict(states: Sequence[Optional[StateJudgement]], chosen: int, *,
                coverage_ok: bool, coverage_reason: str) -> tuple[bool, str]:
    """The row (A4): verified iff no failure at any state, >= 2 judged
    states, judged >= 50% of the CHOSEN states, and coverage on the judged
    states holds. ``states`` holds None for a chosen state that produced no
    sweep (it counts in the denominator)."""
    measured = [s for s in states if s is not None]
    failed = [s for s in measured if s.failed]
    judged = [s for s in measured if s.judged]
    if failed:
        first = failed[0]
        return False, (f"the tangent disagrees at increment {first.increment}: "
                       f"{first.failures[0]}")
    if len(judged) < MIN_JUDGED_STATES:
        return False, (f"{len(judged)} of {chosen} chosen states judged (every entry "
                       f"resolved and every column smooth); {MIN_JUDGED_STATES} are "
                       f"needed. Unresolved at the chosen states, not failed")
    if len(judged) < MIN_JUDGED_FRACTION * chosen:
        return False, (f"{len(judged)} of {chosen} chosen states judged, under "
                       f"{MIN_JUDGED_FRACTION:.0%}. Unresolved at the chosen states, "
                       f"not failed")
    if not coverage_ok:
        return False, f"every judged state agrees, but {coverage_reason}"
    return True, (f"{len(judged)} of {chosen} chosen states judged and every entry agrees "
                  f"(entrywise, FD-only plateau >= {fd.MIN_PLATEAU}); {coverage_reason}")
