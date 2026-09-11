"""A stress four orders above the material's own constants is not a regime.

An experiment can be finite, complete, and mechanically active, and still be
somewhere the author never wrote. Measured on
BodyForce-Growth-2Stages.for at the amplitude the resolution ladder settled
on: PROPS carries one constant, 1e8, and the run reaches a peak stress of
2.158e12 -- 21,580 times it. The growth genuinely developed (STATEV(9), which
the source documents as the norm of the growth tensor, ran 0.003125 to
0.40625), and both builds agreed, and the derivative matched. None of that
makes 2e12 a stress this material has.

So the response is checked against the scales the problem itself supplies,
and a run that is orders away from all of them does not become a verified
case on its own -- it becomes one that has to be explained first.

No universal physical limits are imposed here. A UMAT may legitimately work
in pascals or megapascals, may carry constants that are not moduli, and may
be nonlinear enough that stress is not proportional to any single constant.
What is flagged is a response that no combination of the material's own
numbers accounts for, measured three ways:

* against the material constants the deck supplies;
* against the same model's response at the smallest amplitude the search
  probed, which is the closest thing to a linear reference this harness has;
* against bounds that hold whatever the units are -- a determinant of the
  deformation gradient that is not positive, a state variable that ran away,
  an energy that changed sign.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

#: How far above the largest material constant a peak stress may sit before
#: it has to be explained rather than accepted.
#:
#: A thousand. Not a physical limit and not a tolerance: a bound generous
#: enough that ordinary modelling never trips it. An elastic strain of order
#: one against a modulus gives a stress of order that modulus, so a thousand
#: already allows a strain of a thousand, or a stiffness a thousand times the
#: largest constant the deck supplies, or a hundredfold of both. The measured
#: case sits at 21,580.
FAR_ABOVE_THE_CONSTANTS = 1.0e3

#: How far above the response at the search's own smallest amplitude a peak
#: may sit, once scaled for the amplitude it was driven to. Ten: a material
#: whose response at the verification amplitude is ten times what
#: proportionality predicts from the smallest probe is being asked something
#: qualitatively different from what the search measured.
FAR_ABOVE_THE_PROBE = 1.0e1


@dataclass
class Check:
    """One plausibility question, its answer and the numbers behind it."""

    name: str
    plausible: bool
    detail: str
    measured: float = 0.0
    against: float = 0.0

    def as_dict(self) -> dict:
        return {"name": self.name, "plausible": self.plausible,
                "detail": self.detail, "measured": self.measured,
                "against": self.against}


@dataclass
class Report:
    """Every plausibility question asked of one run."""

    checks: list = field(default_factory=list)

    @property
    def plausible(self) -> bool:
        return all(check.plausible for check in self.checks)

    @property
    def concerns(self) -> list:
        return [check for check in self.checks if not check.plausible]

    def as_dict(self) -> dict:
        return {"plausible": self.plausible,
                "checks": [check.as_dict() for check in self.checks]}

    def reason(self) -> str:
        if not self.checks:
            return "nothing here supplied a scale to check the response against"
        if self.plausible:
            return ("the response sits within the scales this problem supplies: "
                    + "; ".join(check.detail for check in self.checks))
        return ("the response is not accounted for by the scales this problem "
                "supplies, so it is not verified on that basis until it is "
                "explained: "
                + "; ".join(check.detail for check in self.concerns))


def _peak(history: Sequence[dict], field_name: str) -> float:
    best = 0.0
    for record in history or ():
        for value in (record.get(field_name) or ()):
            try:
                value = abs(float(value))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                best = max(best, value)
    return best


def against_material_constants(history: Sequence[dict],
                               props: Sequence[float]) -> Optional[Check]:
    """Is the peak stress within reach of the constants the deck supplies?

    The largest constant is used as an upper bound on any modulus among them,
    which is deliberately crude: it cannot tell a modulus from a yield stress
    from a dimensionless exponent, and it does not need to. What it answers is
    whether the response is within a thousandfold of ANY number this material
    was given, which no ordinary model fails.
    """
    usable = [abs(float(value)) for value in (props or ())
              if isinstance(value, (int, float)) and math.isfinite(float(value))
              and abs(float(value)) > 0.0]
    if not usable:
        return None
    scale = max(usable)
    peak = _peak(history, "STRESS")
    if not peak:
        return None
    ratio = peak / scale
    plausible = ratio <= FAR_ABOVE_THE_CONSTANTS
    return Check(
        name="stress against material constants", plausible=plausible,
        measured=peak, against=scale,
        detail=(f"peak stress {peak:.4g} against a largest material constant "
                f"of {scale:.4g}, a ratio of {ratio:.4g}"
                + ("" if plausible else
                   f" -- beyond {FAR_ABOVE_THE_CONSTANTS:.0e}, which no "
                   f"combination of this material's own numbers accounts "
                   f"for")))


def against_the_smallest_probe(history: Sequence[dict], amplitude: float,
                               attempts: Sequence[dict]) -> Optional[Check]:
    """Is the response proportional to what the smallest probe measured?

    The search drove this model at amplitudes far below the verification's,
    and the smallest of them is the closest thing to a linear reference this
    harness has. Scaled for amplitude, a peak an order beyond it is a
    different question being asked of the material, not more of the same one.
    """
    ran = [a for a in (attempts or ())
           if a.get("ran") and (a.get("largest_stress") or 0.0) > 0.0
           and (a.get("amplitude") or 0.0) > 0.0]
    if not ran or not amplitude:
        return None
    smallest = min(ran, key=lambda a: float(a["amplitude"]))
    reference = float(smallest["largest_stress"])
    at = float(smallest["amplitude"])
    peak = _peak(history, "STRESS")
    if not peak or not reference:
        return None
    # Proportionality is the generous reading: a material whose stress grows
    # LESS than linearly is not the concern here.
    expected = reference * max(1.0, amplitude / at)
    ratio = peak / expected
    plausible = ratio <= FAR_ABOVE_THE_PROBE
    return Check(
        name="stress against the smallest probe", plausible=plausible,
        measured=peak, against=expected,
        detail=(f"peak stress {peak:.4g} against {expected:.4g} expected by "
                f"proportionality from {reference:.4g} at an amplitude of "
                f"{at:.3g}, a ratio of {ratio:.4g}"
                + ("" if plausible else
                   f" -- beyond {FAR_ABOVE_THE_PROBE:.0e}, so this is not "
                   f"more of what the search measured")))


def deformation_gradient_stays_positive(history: Sequence[dict]) -> Optional[Check]:
    """det F > 0 wherever a deformation gradient was recorded.

    True whatever the units, whatever the material. A non-positive
    determinant is matter turned inside out, and any number computed after it
    is arithmetic rather than mechanics.
    """
    worst: Optional[float] = None
    where = ""
    for record in history or ():
        values = record.get("DFGRD1") or ()
        if len(values) < 9:
            continue
        f = [float(v) for v in values[:9]]
        det = (f[0] * (f[4] * f[8] - f[5] * f[7])
               - f[1] * (f[3] * f[8] - f[5] * f[6])
               + f[2] * (f[3] * f[7] - f[4] * f[6]))
        if worst is None or det < worst:
            worst, where = det, (f"step {record.get('step')} increment "
                                 f"{record.get('increment')}")
    if worst is None:
        return None
    return Check(
        name="determinant of the deformation gradient", plausible=worst > 0.0,
        measured=worst, against=0.0,
        detail=(f"the smallest det F over the history is {worst:.6g}"
                + ("" if worst > 0.0 else
                   f" at {where}, which is not a deformation")))


def examine(history: Sequence[dict], props: Sequence[float] = (),
            amplitude: float = 0.0, attempts: Sequence[dict] = ()) -> Report:
    """Every plausibility question this run supplies the scales to ask."""
    report = Report()
    for check in (against_material_constants(history, props),
                  against_the_smallest_probe(history, amplitude, attempts),
                  deformation_gradient_stays_positive(history)):
        if check is not None:
            report.checks.append(check)
    return report
