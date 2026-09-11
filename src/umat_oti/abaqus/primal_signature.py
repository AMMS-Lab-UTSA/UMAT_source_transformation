"""Why two builds of one model disagree, named from the numbers themselves.

"primal_disagreed" is a stage, not a diagnosis. Thirty-seven entries reached
it at magnitudes spanning nine orders -- 2.3e-10 to 1.9 -- and a single name
over that range tells nobody which of them share a cause or which fix would
move any of them. The signature is read off the comparison and the source:
where along the history the difference first matters, which quantity carries
it, whether the two values look like the same number computed differently or
like two different answers, and whether the routine contains the kind of
construct that produces each.

Nothing here relaxes a tolerance or excuses a difference. A signature is a
hypothesis with the evidence for it attached, so that the entries sharing one
can be worked on together and the fix can be checked against all of them.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

#: Two values of opposite sign whose magnitudes agree this closely are not
#: the same number computed differently. Something chose a different branch.
SIGN_FLIP_CLOSENESS = 0.25

#: At or below this, a difference is the size round-off reaches through a
#: path of a few hundred increments; above it, arithmetic alone does not get
#: there and something structural is different.
ROUND_OFF = 1e-9

#: Constructs whose presence makes a particular signature likely. Searched in
#: the ORIGINAL source, because what the author wrote is what has to explain
#: the difference.
_ITERATION = re.compile(
    r"newton|raphson|\bdo\s+while\b|\bconverg|\btoler|\bnitr\b|\bmaxit",
    re.IGNORECASE)
_BRANCH_ON_STATE = re.compile(
    r"IF\s*\([^)]*\b(STATEV|STRESS|DSTRAN)\b", re.IGNORECASE)
_SINGLE_PRECISION = re.compile(r"^\s*REAL(?!\s*\*\s*8)(?!\s*\(\s*8)", re.IGNORECASE
                               | re.MULTILINE)
_FILE_IO = re.compile(r"^\s*(OPEN|READ)\s*\(", re.IGNORECASE | re.MULTILINE)
_SAVED = re.compile(r"^\s*(SAVE|COMMON)\b", re.IGNORECASE | re.MULTILINE)

#: The signatures. Ordered so the most specific explanation wins.
NON_FINITE = "non_finite_in_comparison"
SIGN_FLIP = "branch_divergence_sign_flip"
ITERATIVE_SOLVER = "iterative_solver_different_iterate"
FIRST_INCREMENT = "first_increment_disagreement"
ACCUMULATING = "accumulating_disagreement"
STATE_ONLY = "state_variables_only"
STRESS_ONLY = "stresses_only"
NEAR_ZERO = "near_zero_normalisation"
ROUND_OFF_SCALE = "round_off_scale"
DATA_OR_LIFETIME = "data_read_or_save_lifetime"
UNCLASSIFIED = "unclassified"


@dataclass
class Signature:
    """One disagreement, named, with what named it."""

    kind: str = UNCLASSIFIED
    magnitude: float = 0.0
    where: str = ""
    evidence: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "magnitude": self.magnitude,
                "where": self.where, "evidence": list(self.evidence)}


def _closeness(left: float, right: float) -> float:
    """How near two magnitudes are, as a fraction of the larger."""
    scale = max(abs(left), abs(right))
    return abs(abs(left) - abs(right)) / scale if scale else 0.0


def classify(primal: dict, source_text: str = "",
             complete_increments: int = 0) -> Signature:
    """Name a primal disagreement from its numbers and its source."""
    worst = float(primal.get("worst_stress_relative") or 0.0)
    state = float(primal.get("worst_state_relative") or 0.0)
    magnitude = max(worst if math.isfinite(worst) else 0.0,
                    state if math.isfinite(state) else 0.0)
    at = list(primal.get("worst_stress_at") or ())
    state_at = list(primal.get("worst_state_at") or ())
    evidence: list = []

    if primal.get("non_finite_components"):
        return Signature(NON_FINITE, magnitude, "",
                         [f"{primal['non_finite_components']} compared values "
                          f"are not finite, so nothing about this pair is "
                          f"established"])

    # Two values of opposite sign and near-equal size are two answers, not one
    # answer computed twice. A slip-system solver picking a different system,
    # or a yield branch taken one way in one build and the other way in the
    # other, looks exactly like this and nothing else does.
    for label, row in (("stress", at), ("state", state_at)):
        if len(row) >= 4:
            left, right = float(row[2]), float(row[3])
            if left * right < 0 and _closeness(left, right) <= SIGN_FLIP_CLOSENESS:
                evidence.append(
                    f"the worst {label} pair is {left:.6g} against "
                    f"{right:.6g}: opposite signs, magnitudes within "
                    f"{_closeness(left, right):.1%} of each other")
    if evidence:
        if source_text and _ITERATION.search(source_text):
            evidence.append("and the source runs its own Newton iteration, "
                            "which converges to a different iterate when its "
                            "residual is computed in a different order")
            return Signature(ITERATIVE_SOLVER, magnitude, _where(at), evidence)
        if source_text and _BRANCH_ON_STATE.search(source_text):
            evidence.append("and the source branches on its own stress or "
                            "state, so a difference below the branch can "
                            "decide which way it goes")
        return Signature(SIGN_FLIP, magnitude, _where(at), evidence)

    if source_text and _FILE_IO.search(source_text) and _SAVED.search(source_text):
        evidence.append("the source reads a file and keeps what it read "
                        "between calls, so a shadow whose lifetime does not "
                        "match would diverge from the first call that skips "
                        "the read")
        return Signature(DATA_OR_LIFETIME, magnitude, _where(at), evidence)

    if primal.get("unresolved_components") and magnitude > 0:
        resolved = int(primal.get("resolved_components") or 0)
        unresolved = int(primal.get("unresolved_components") or 0)
        if unresolved > resolved:
            evidence.append(
                f"{unresolved} of {resolved + unresolved} components sit "
                f"below the resolvable fraction of the response, so most of "
                f"what was compared carries rounding rather than signal")
            return Signature(NEAR_ZERO, magnitude, _where(at), evidence)

    first = at[0] if at else None
    if first is not None and int(first) <= 1:
        evidence.append("the worst difference is at the first record, so the "
                        "two builds part company before any history has "
                        "accumulated -- an input, an initial state or a "
                        "constant differs, not a path")
        return Signature(FIRST_INCREMENT, magnitude, _where(at), evidence)

    if magnitude and magnitude <= ROUND_OFF:
        evidence.append(f"{magnitude:.3e} over "
                        f"{complete_increments or primal.get('increments') or '?'} "
                        f"increments is the scale round-off reaches along a "
                        f"path, and no larger cause is visible")
        return Signature(ROUND_OFF_SCALE, magnitude, _where(at), evidence)

    if state > 0 and worst == 0:
        return Signature(STATE_ONLY, magnitude, _where(state_at),
                         ["only state variables differ; the stresses agree"])
    if worst > 0 and state == 0:
        evidence.append("only stresses differ; every state variable agrees")
        if first is not None:
            return Signature(ACCUMULATING if int(first) > 1 else FIRST_INCREMENT,
                             magnitude, _where(at), evidence)
        return Signature(STRESS_ONLY, magnitude, _where(at), evidence)
    if first is not None and int(first) > 1:
        evidence.append("the difference first matters part way along the "
                        "history, so it grows with the path rather than "
                        "arriving with the inputs")
        return Signature(ACCUMULATING, magnitude, _where(at), evidence)
    return Signature(UNCLASSIFIED, magnitude, _where(at), evidence)


def _where(at: Sequence) -> str:
    if len(at) >= 2:
        return f"record {at[0]}, component {at[1]}"
    return ""
