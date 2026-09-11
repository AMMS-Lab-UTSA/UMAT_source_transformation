"""A shorter step is not a safer version of the same experiment.

Shortening the clock is the right repair for a model whose failure moves with
the period -- and it is a change to the mechanical problem, not only to the
numerics. A growth law, a creep law, a relaxation and a viscoplastic flow all
integrate over time, so less of it means less of the behaviour under test.

Measured on BodyForce-Growth-2Stages.for, whose growth stretch is a ramp in
the TOTAL analysis time against a normalisation the author wrote into the
source::

    TotalT = 1.0
    G11 = 1.0 + (G11St1-1.0)*(TIME(2)+DTIME)/TotalT
              + (G11St2-G11St1)*(TIME(2)+DTIME)/TotalT

The repair that made its history finite ran to a total time of 0.34, so G11
reached about a third of the excursion the author designed, and the verdict
that came back said "verified" about a growth model that had barely grown.
Three of its nine state variables moved at all, and the stresses it agreed on
were 1e12 -- the ceiling amplitude, not the author's regime.

So the source is read for the time scale it declares, and an experiment is
asked to cover a meaningful fraction of it before anything is verified on it.
Where a source declares none, this says so rather than inventing one: the
absence of a declared scale is not permission to assume any duration will do.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

#: How much of a declared constitutive time scale an experiment has to cover
#: before it can be said to exercise the behaviour that scale belongs to.
#:
#: A quarter. Below that a ramp normalised by the scale has developed less
#: than a quarter of its range, and a verification of it is a verification of
#: the material near its initial state -- which is the part every build gets
#: right. Not a tolerance on an answer; a floor on how much of the author's
#: own problem the experiment reaches.
ENOUGH_OF_THE_SCALE = 0.25

#: An assignment of a total-time normalisation, as authors write it. Matched
#: on the NAME rather than on a list of spellings, because the point is a
#: quantity a routine divides its own clock by.
_DECLARED = re.compile(
    r"^\s*(?:\d+\s+)?(?P<name>TOTAL_?T\w*|T_?TOTAL\w*|TFINAL\w*|TEND\w*|"
    r"T_?MAX\w*|PERIOD\w*|TAU\w*|T_?REF\w*)\s*=\s*(?P<value>[-+0-9.EeDd]+)\s*$",
    re.IGNORECASE | re.MULTILINE)

#: A routine that divides its clock by that quantity is using it as a scale.
_USED_AS_SCALE = re.compile(
    r"(?:TIME\s*\(\s*[12]\s*\)|DTIME)[^\n]*?/\s*(?P<name>[A-Z_]\w*)",
    re.IGNORECASE)


@dataclass
class Scale:
    """A constitutive time scale a source declares for itself."""

    name: str = ""
    value: float = 0.0
    evidence: str = ""

    @property
    def declared(self) -> bool:
        return bool(self.name) and self.value > 0.0

    def as_dict(self) -> dict:
        return {"name": self.name, "value": self.value,
                "evidence": self.evidence, "declared": self.declared}


def declared_scale(source_text: str) -> Scale:
    """The total-time normalisation this source divides its own clock by.

    Both halves are required: a variable assigned a constant, and that same
    variable used as the divisor of TIME or DTIME. A constant named TAU that
    nothing divides by is not a time scale, and a division by a quantity the
    routine never fixes is not one either.
    """
    text = source_text or ""
    divisors = {match.group("name").upper()
                for match in _USED_AS_SCALE.finditer(text)}
    if not divisors:
        return Scale()
    best: Optional[Scale] = None
    for match in _DECLARED.finditer(text):
        name = match.group("name").upper()
        if name not in divisors:
            continue
        try:
            value = float(match.group("value").replace("D", "E").replace("d", "e"))
        except ValueError:
            continue
        if value <= 0.0:
            continue
        candidate = Scale(name=name, value=value,
                          evidence=match.group(0).strip())
        # The last assignment wins: a source that sets a default and then
        # overrides it runs with the override.
        best = candidate
    return best or Scale()


@dataclass
class Coverage:
    """How much of the declared scale an experiment actually walks."""

    scale: Scale = field(default_factory=Scale)
    total_time: float = 0.0
    fraction: float = 0.0
    enough: bool = True
    reason: str = ""

    def as_dict(self) -> dict:
        return {"scale": self.scale.as_dict(), "total_time": self.total_time,
                "fraction": self.fraction, "enough": self.enough,
                "reason": self.reason}


def covers(source_text: str, loading: Sequence,
           floor: float = ENOUGH_OF_THE_SCALE) -> Coverage:
    """Does this loading run long enough to exercise what the source declares?"""
    scale = declared_scale(source_text)
    total = sum(float(getattr(segment, "period", 0.0) or 0.0)
                for segment in loading or ())
    if not scale.declared:
        return Coverage(scale=scale, total_time=total, fraction=0.0, enough=True,
                        reason=("this source declares no time scale of its "
                                "own, so there is nothing here to measure the "
                                "experiment's duration against"))
    fraction = total / scale.value if scale.value else 0.0
    enough = fraction >= floor
    return Coverage(
        scale=scale, total_time=total, fraction=fraction, enough=enough,
        reason=(f"the source normalises its clock by {scale.name} = "
                f"{scale.value:g} ({scale.evidence}); this experiment runs to "
                f"a total time of {total:g}, which is {fraction:.1%} of it"
                + ("" if enough else
                   f" -- below the {floor:.0%} a verification needs, so "
                   f"whatever it agreed about is the material near its "
                   f"initial state rather than the behaviour that scale "
                   f"belongs to")))
