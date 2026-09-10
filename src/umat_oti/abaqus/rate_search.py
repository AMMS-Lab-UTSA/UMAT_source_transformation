"""Whether this material cares how fast, or how long -- which no amplitude asks.

The amplitude search escalates the strain until the material does something.
For a viscoelastic, viscoplastic, creep or ageing model that is the wrong
question and it gets the wrong answer: driven at one rate, a Kelvin-Voigt
solid is linear in the strain at every amplitude, so the search reports
``linear_to_the_ceiling`` -- "nothing here to activate" -- about a material
whose whole subject is time.

Measured on ``irfancn__Abaqus-UMAT-viscoelastic/umat_viscoelastic.for``, whose
stiffness is ``lambda*(1 + 3*eta/(E*dtime))``: six runs from 1e-4 to 1 strain,
every one of them linear, every one of them at the same DTIME.

Two probes, and neither is an amplitude:

**Rate.** The same strain path over a different step time. Same targets, same
increments, different DTIME -- so a difference between the two stress histories
at the same strain is rate dependence and can be nothing else.

**Hold.** The strain stopped where it was and time allowed to pass. A
rate-independent material's stress does not move; a relaxing one's does, and
the size of the movement is the measurement.

Both are run on the ORIGINAL only, like the amplitude search and for the same
reason: a loading chosen with the converted build in view is a loading chosen
to agree.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

#: A relative difference below this is the last bits of two doubles.
NOISE = 1e-9

#: How far two stress histories at the same strain may differ before the
#: material is called rate dependent. The two runs solve the same increments
#: with the same boundary values, so anything a converged Newton leaves is far
#: below this; a viscosity that matters to a result is far above it.
RATE_TOLERANCE = 1e-6

#: How many times slower or faster the second run is. Two decades: enough that
#: a relaxation time anywhere near the step time shows, and not so much that
#: the fast run's increments underflow the solver's minimum.
RATE_FACTOR = 0.01

#: How much of the loading's own step time to hold for. Ten: long enough that
#: a relaxation time of the order of the loading time decays visibly, short
#: enough not to double the job.
HOLD_PERIODS = 10.0


def _finite(values) -> list:
    return [float(v) for v in (values or ()) if math.isfinite(float(v))]


def _largest(values) -> float:
    return max((abs(v) for v in _finite(values)), default=0.0)


@dataclass
class RateFinding:
    """What the time probes saw."""

    rate_dependent: bool = False
    #: Largest relative stress difference between the two rates, at equal strain.
    rate_difference: float = 0.0
    rate_at: tuple = ()
    relaxed: bool = False
    #: Largest relative stress movement during the hold.
    relaxation: float = 0.0
    ran: bool = False
    reason: str = ""

    @property
    def time_dependent(self) -> bool:
        return self.rate_dependent or self.relaxed

    def as_dict(self) -> dict:
        return {"ran": self.ran, "rate_dependent": self.rate_dependent,
                "rate_difference": self.rate_difference,
                "rate_at": list(self.rate_at), "relaxed": self.relaxed,
                "relaxation": self.relaxation,
                "time_dependent": self.time_dependent, "reason": self.reason}


def compare_rates(slow: Sequence[dict], fast: Sequence[dict], *,
                  tolerance: float = RATE_TOLERANCE) -> tuple[float, tuple]:
    """The largest relative stress difference at matching increments.

    The two runs prescribe the same displacement at the same increment, so
    increment ``k`` of one is at the same strain as increment ``k`` of the
    other. Comparing by index is comparing at equal strain, and the only thing
    that differs between them is how much time passed.
    """
    worst, where = 0.0, ()
    for index, (a, b) in enumerate(zip(slow, fast), start=1):
        left, right = _finite(a.get("STRESS")), _finite(b.get("STRESS"))
        if not left or not right:
            continue
        scale = max(_largest(left), _largest(right))
        if scale <= 0:
            continue
        for component, (x, y) in enumerate(zip(left, right), start=1):
            difference = abs(x - y) / scale
            if difference > worst:
                worst, where = difference, (index, component, x, y)
    return worst, where


def relaxation_during(records: Sequence[dict], first: int) -> float:
    """The largest relative stress movement from ``first`` onward.

    ``first`` is the index at which the hold begins. The strain is constant
    from there, so any stress movement is the material's own.
    """
    held = [r for r in list(records)[first:] if _finite(r.get("STRESS"))]
    if len(held) < 2:
        return 0.0
    start = _finite(held[0].get("STRESS"))
    scale = max((_largest(r.get("STRESS")) for r in held), default=0.0) or 1.0
    worst = 0.0
    for record in held[1:]:
        for a, b in zip(start, _finite(record.get("STRESS"))):
            worst = max(worst, abs(a - b) / scale)
    return worst


def probe_time(run_slow, run_fast, *, hold_from: Optional[int] = None,
               tolerance: float = RATE_TOLERANCE) -> RateFinding:
    """Run the same path at two rates and say whether the material noticed.

    ``run_slow`` and ``run_fast`` each return ``(ran, records, reason)``, the
    same contract the amplitude search uses. The slow run carries the hold, so
    relaxation and rate dependence cost two jobs between them rather than three.
    """
    ran, slow, why = run_slow()
    if not ran:
        return RateFinding(ran=False, reason=(
            f"the slow run did not produce a history, so nothing can be said "
            f"about time dependence: {why}"))
    ran, fast, why = run_fast()
    if not ran:
        return RateFinding(ran=False, reason=(
            f"the fast run did not produce a history, so the two rates could "
            f"not be compared: {why}"))

    difference, where = compare_rates(slow, fast, tolerance=tolerance)
    relaxed = relaxation_during(slow, hold_from) if hold_from is not None else 0.0
    finding = RateFinding(
        ran=True,
        rate_dependent=difference > tolerance, rate_difference=difference,
        rate_at=where,
        relaxed=relaxed > tolerance, relaxation=relaxed)
    if finding.time_dependent:
        parts = []
        if finding.rate_dependent:
            parts.append(
                f"the same strain path applied over {1 / RATE_FACTOR:g} times "
                f"less step time gives a stress that differs by "
                f"{difference:.3e} relative")
        if finding.relaxed:
            parts.append(f"stress moved by {relaxed:.3e} relative while the "
                         f"strain was held")
        finding.reason = ("this material is time dependent: " + "; and ".join(parts)
                          + ". No amplitude would have found that, because "
                            "raising the strain does not make time pass")
    else:
        finding.reason = (
            f"the same path at {1 / RATE_FACTOR:g} times the rate gives the "
            f"same stress to {difference:.3e}"
            + (f", and stress moved by {relaxed:.3e} while the strain was held"
               if hold_from is not None else "")
            + ": nothing here depends on time")
    return finding
