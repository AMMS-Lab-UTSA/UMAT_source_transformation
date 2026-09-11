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

#: A SEARCH HEURISTIC, not a verification criterion.
#:
#: Used to decide whether an experiment is worth extending, and reported
#: alongside the fraction so a reader can see what it was compared against.
#: It is NOT evidence that the intended behaviour activated, and nothing
#: verifies on it: a detected symbol may be a growth normalisation, a
#: relaxation time, a retardation time, a creep scale, a loading period or a
#: plain numerical parameter, and one fraction over all of those would be a
#: threshold pretending to be a criterion. What decides activation is the
#: observed response -- see umat_oti.abaqus.plausibility and the activation
#: indicators read off the frozen run.
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
    #: Always True. Coverage is reported, not asserted: see
    #: ENOUGH_OF_THE_SCALE. Kept so callers read the fraction and the role
    #: rather than a pass mark.
    enough: bool = True
    #: Whether the fraction cleared the search heuristic. Advisory only.
    reaches_heuristic: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {"scale": self.scale.as_dict(), "total_time": self.total_time,
                "fraction": self.fraction, "enough": self.enough,
                "reaches_heuristic": self.reaches_heuristic,
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
    # Reported, never asserted. The role of the symbol decides what the
    # fraction means, and this cannot read a role off a name.
    reaches = fraction >= floor
    return Coverage(
        scale=scale, total_time=total, fraction=fraction, enough=True,
        reaches_heuristic=reaches,
        reason=(f"the source normalises its clock by {scale.name} = "
                f"{scale.value:g} ({scale.evidence}); this experiment runs to "
                f"a total time of {total:g}, which is {fraction:.1%} of it "
                f"({'above' if reaches else 'below'} the {floor:.0%} search "
                f"heuristic -- what that fraction MEANS depends on whether "
                f"{scale.name} is a growth normalisation, a relaxation time "
                f"or a numerical parameter, which this cannot read off a "
                f"name)"))
