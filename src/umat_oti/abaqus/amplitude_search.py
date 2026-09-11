"""Find a loading amplitude that makes the material do something.

A fixed amplitude is a guess about somebody else's material. Too small and the
model answers elastically -- and a verification run in the elastic regime
tests the part of a UMAT that every build gets right, so a converted routine
wrong about yielding, damage or hardening passes it. Too large and the model
is driven somewhere its author never intended, where it may diverge, return
NaN, or exercise a branch that is a modelling artefact rather than physics.

So the amplitude is searched for rather than chosen. Start small, run the
ORIGINAL material, ask :mod:`umat_oti.abaqus.activation` whether anything
happened, and escalate geometrically until it does. Then narrow the bracket,
because knowing that activation lies between 0.1% and 0.5% is worth more than
knowing it happened at 0.5%: the interesting states are the ones just before
and just after, and a loading built around them exercises the transition
rather than stepping over it.

The search is over the ORIGINAL material only. Nothing about the conversion is
consulted while choosing the loading, because a loading chosen with the
converted build in view would be a loading chosen to agree.

Four things stop it, and each is reported as itself rather than as failure:

* the material activated -- what the search is for;
* the ceiling was reached without activation, which for a linear elastic
  material is the correct and final answer, not a failure to try hard enough;
* the run stopped converging or returned values that are not numbers, which
  bounds the amplitude from above and is evidence about the model;
* a safety bound on stress or strain was crossed, which says the same thing
  before Abaqus has to.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from umat_oti.abaqus.activation import Activation, detect_activation

#: Where to start. Small enough that essentially every model answers it
#: elastically, so the search begins below any transition rather than
#: straddling one.
FIRST_AMPLITUDE = 1e-4

#: The escalation factor. Between two and five, per the method: large enough
#: to cross several decades in a handful of runs, small enough that the
#: bracket it leaves is worth refining. Five, at the top of that range,
#: because every step is a real Abaqus job and 1e-4 to 1 is four decades --
#: at three it takes nine jobs, at five it takes six, and the refinement
#: afterwards recovers the resolution the wider step gave up.
#:
#: Deliberately NOT solved by declaring a material linear once a few
#: amplitudes scale proportionally. Linearity over one decade does not imply
#: linearity above it: measured on a material yielding at 0.2%, three
#: proportional points at 1e-4, 3e-4 and 9e-4 are all below the transition,
#: and stopping there reports a plastic material as elastic.
GROWTH = 5.0

#: The ceiling. A strain of one hundred percent is past where a small-strain
#: formulation means anything, and a finite-strain one driven further is being
#: asked about a regime its author did not write.
CEILING = 1.0

#: How many times to step DOWN when the first amplitude already fails. A model
#: whose smallest probe returns NaN has a domain that does not reach 1e-4, and
#: escalating from there finds nothing while a smaller amplitude might run.
#: Measured on thirteen Jeff97 growth entries: the search left its domain at
#: its first attempt, reported an amplitude of zero, and the caller fell back
#: to a DEFAULT of 0.005 -- fifty times larger than the probe that had just
#: failed -- so both builds went non-finite at their second increment.
DESCENTS = 4

#: How many refinement steps to spend narrowing the bracket once activation is
#: found. Each halves the interval, so four takes a factor-of-three bracket
#: down to under ten percent.
REFINEMENTS = 4

#: Stress beyond this multiple of the largest stress seen in the FIRST,
#: certainly-elastic run is a runaway rather than a response.
STRESS_RUNAWAY = 1e6


@dataclass
class Attempt:
    """One amplitude, and what the material did at it."""

    amplitude: float
    ran: bool
    activation: Optional[Activation] = None
    reason: str = ""
    largest_stress: float = 0.0

    @property
    def activated(self) -> bool:
        return bool(self.activation and self.activation.activated)

    def as_dict(self) -> dict:
        return {"amplitude": self.amplitude, "ran": self.ran,
                "activated": self.activated, "reason": self.reason,
                "largest_stress": self.largest_stress,
                "activation": self.activation.as_dict() if self.activation else None}


#: Why a search stopped. Each is an answer, not a failure.
ACTIVATED = "activated"
LINEAR_TO_THE_CEILING = "linear_to_the_ceiling"
STOPPED_CONVERGING = "stopped_converging"
LEFT_ITS_DOMAIN = "left_its_domain"
NEVER_RAN = "never_ran"


@dataclass
class SearchResult:
    """What the search found, and everything it tried on the way."""

    outcome: str = NEVER_RAN
    amplitude: float = 0.0
    bracket: tuple[float, float] = (0.0, 0.0)
    attempts: list[Attempt] = field(default_factory=list)
    reason: str = ""

    @property
    def found(self) -> bool:
        return self.outcome == ACTIVATED

    def summary(self) -> str:
        if self.outcome == ACTIVATED:
            low, high = self.bracket
            return (f"activated at {self.amplitude:.3g}; the transition lies "
                    f"between {low:.3g} and {high:.3g}, found in "
                    f"{len(self.attempts)} runs of the original")
        if self.outcome == LINEAR_TO_THE_CEILING:
            return (f"linear to {CEILING:.3g} strain over "
                    f"{len(self.attempts)} runs: nothing here to activate, "
                    f"which for a linear elastic material is the right answer "
                    f"and not a failure to try harder")
        if self.outcome == STOPPED_CONVERGING:
            return (f"stopped converging above {self.amplitude:.3g}: "
                    f"{self.reason}")
        if self.outcome == LEFT_ITS_DOMAIN:
            return (f"left its domain above {self.amplitude:.3g}: {self.reason}")
        return f"never ran: {self.reason}"

    def as_dict(self) -> dict:
        return {"outcome": self.outcome, "amplitude": self.amplitude,
                "bracket": list(self.bracket), "reason": self.reason,
                "summary": self.summary(),
                "attempts": [a.as_dict() for a in self.attempts]}


def _largest_stress(records: Sequence[dict]) -> float:
    best = 0.0
    for record in records or ():
        for value in (record.get("STRESS") or ()):
            value = float(value)
            if math.isfinite(value):
                best = max(best, abs(value))
    return best


def first_non_finite(records: Sequence[dict]) -> Optional[int]:
    """The first increment whose stress or state is not a number.

    A run that produced NaN is not a quiet run. The search read one as "no
    indicator fired" -- every indicator skips a value it cannot compare -- and
    so escalated PAST it to the ceiling, choosing an amplitude of 0.3125 for
    nineteen materials that had already left their domain an order of
    magnitude below it. The verification then drove both builds to NaN by
    their second increment and reported "too few increments to rest a
    verification on".
    """
    for index, record in enumerate(records or (), start=1):
        for field in ("STRESS", "STATEV"):
            for value in (record.get(field) or ()):
                try:
                    if not math.isfinite(float(value)):
                        return index
                except (TypeError, ValueError):
                    return index
    return None


def search_amplitude(
    run: Callable[[float], tuple[bool, list, str]],
    *,
    first: float = FIRST_AMPLITUDE,
    growth: float = GROWTH,
    ceiling: float = CEILING,
    refinements: int = REFINEMENTS,
    reversal_at: Optional[int] = None,
) -> SearchResult:
    """Escalate until the material does something, then narrow the bracket.

    ``run(amplitude)`` drives the ORIGINAL material at that amplitude and
    returns ``(ran, records, reason)``: whether the job produced a history,
    the probe records if it did, and why not if it did not.

    Never runs the converted build. A loading chosen with the conversion in
    view would be a loading chosen to agree.
    """
    result = SearchResult()
    amplitude = float(first)
    last_quiet = 0.0
    elastic_stress = 0.0

    # Down before up. A model whose smallest probe already returns NaN has a
    # domain that does not reach it, and there is nothing above to find.
    for _descent in range(DESCENTS):
        ran, records, why = run(amplitude)
        if ran and first_non_finite(records) is None:
            break
        result.attempts.append(Attempt(amplitude=amplitude, ran=ran,
                                       reason=why or "returned a value that "
                                                     "is not a number"))
        amplitude /= growth
    else:
        result.outcome = LEFT_ITS_DOMAIN
        result.amplitude = 0.0
        result.bracket = (0.0, float(first))
        result.reason = (
            f"the model produced no numbers at any amplitude from "
            f"{float(first) / growth ** (DESCENTS - 1):.3g} to {float(first):.3g}; "
            f"there is no loading here this harness can drive it at")
        return result
    result.attempts.clear()

    while amplitude <= ceiling:
        ran, records, why = run(amplitude)
        attempt = Attempt(amplitude=amplitude, ran=ran, reason=why)
        if ran:
            attempt.activation = detect_activation(records, reversal_at)
            attempt.largest_stress = _largest_stress(records)
        result.attempts.append(attempt)

        if not ran:
            # An amplitude the model cannot be driven to is a bound on the
            # search, and evidence about the model. The last quiet amplitude
            # is still the best that was reached.
            result.outcome = STOPPED_CONVERGING
            result.amplitude = last_quiet
            result.bracket = (last_quiet, amplitude)
            result.reason = why or "the job produced no history"
            return result

        broke_at = first_non_finite(records)
        if broke_at is not None:
            result.outcome = LEFT_ITS_DOMAIN
            result.amplitude = last_quiet
            result.bracket = (last_quiet, amplitude)
            result.reason = (
                f"the model returned a value that is not a number at "
                f"increment {broke_at} of this run, so it had left its domain "
                f"before this amplitude; the largest amplitude it answered "
                f"with numbers is {last_quiet:.3g}")
            attempt.reason = result.reason
            return result

        if not elastic_stress:
            elastic_stress = attempt.largest_stress or 0.0
        elif (elastic_stress and attempt.largest_stress
              > STRESS_RUNAWAY * elastic_stress * (amplitude / first)):
            result.outcome = LEFT_ITS_DOMAIN
            result.amplitude = last_quiet
            result.bracket = (last_quiet, amplitude)
            result.reason = (
                f"stress reached {attempt.largest_stress:.3g}, more than "
                f"{STRESS_RUNAWAY:.0e} times what the first elastic run gave "
                f"scaled to this amplitude")
            return result

        if attempt.activated:
            low, high = _refine(run, last_quiet or amplitude / growth, amplitude,
                                refinements, reversal_at, result)
            result.outcome = ACTIVATED
            result.amplitude = high
            result.bracket = (low, high)
            return result

        last_quiet = amplitude
        amplitude *= growth

    result.outcome = LINEAR_TO_THE_CEILING
    result.amplitude = last_quiet
    result.bracket = (last_quiet, last_quiet)
    result.reason = (f"nothing activated up to a strain of {ceiling:.3g}")
    return result


def _refine(run, low: float, high: float, steps: int,
            reversal_at: Optional[int], result: SearchResult) -> tuple[float, float]:
    """Halve the bracket, keeping the smallest amplitude that still activates.

    Knowing the transition lies between 0.1% and 0.12% is worth more than
    knowing it happened at 0.3%: a loading built around a narrow bracket puts
    states on both sides of it, which is where a tangent is worth checking.
    """
    for _ in range(max(0, steps)):
        if high <= low or not math.isfinite(low) or not math.isfinite(high):
            break
        middle = 0.5 * (low + high)
        ran, records, why = run(middle)
        attempt = Attempt(amplitude=middle, ran=ran, reason=why)
        if ran:
            attempt.activation = detect_activation(records, reversal_at)
            attempt.largest_stress = _largest_stress(records)
        result.attempts.append(attempt)
        if not ran:
            break
        if attempt.activated:
            high = middle
        else:
            low = middle
    return low, high
