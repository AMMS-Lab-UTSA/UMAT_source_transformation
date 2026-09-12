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



# ---------------------------------------------------------------------------
# clocks that are not a single normalisation
# ---------------------------------------------------------------------------
#: A branch on the TOTAL analysis time. TIME(2) is the whole analysis, not the
#: step, so a routine that tests it against 1, 2 and 3 is describing three
#: steps of unit period and not three fractions of one.
_STAGE = re.compile(
    r"TIME\s*\(\s*2\s*\)[^\n]*?(?:\.LE\.|\.LT\.|<=|<)\s*"
    r"([0-9]+(?:\.[0-9]*)?(?:[EeDd][-+]?[0-9]+)?)", re.IGNORECASE)

#: An exponential approach to a saturation, whose rate is a material constant.
#: ``theg = (tmax-1)*(1-exp(-time(2)/tau)) + 1`` is the whole growth law of
#: three mholla routines, and how long it has to run is decided by ``tau``.
_EXPONENTIAL = re.compile(
    r"EXP\s*\(\s*-\s*(?:TIME\s*\(\s*[12]\s*\)|DTIME)\s*/\s*([A-Za-z_]\w*)\s*\)",
    re.IGNORECASE)

#: An assignment of a named quantity from a material constant.
_FROM_PROPS = re.compile(
    r"^\s*(?:\d+\s+)?([A-Za-z_]\w*)\s*=\s*PROPS\s*\(\s*(\d+)\s*\)",
    re.IGNORECASE | re.MULTILINE)

#: How many time constants an exponential law has to run for before its
#: excursion is mostly done. Three: ``1 - exp(-3) = 0.95``, so the growth
#: stretch has developed 95% of ``tmax - 1``. One time constant gives 63% and
#: a quarter of one gives 22%, which is the material near its initial state.
TIME_CONSTANTS = 3.0


def declared_stage_boundaries(source_text: str) -> tuple[float, ...]:
    """The TOTAL-time boundaries a routine switches its own law at.

    ``BodyForce-Growth-2Stages.for``::

        IF ( (TIME(2)+DTIME) .LE. 1.0) THEN
          G11 = 1.0 + (G11St1-1.0)*(TIME(2)+DTIME)/TotalT
        ELSE IF ( (TIME(2)+DTIME) .LE. 2.0) THEN
          G11 = 2.0*G11St1-G11St2 + (G11St2-G11St1)*(TIME(2)+DTIME)/TotalT
        ELSE IF ( (TIME(2)+DTIME) .LE. 3.0) THEN
          G11 = G11St2

    Three boundaries, and its author's own deck runs three steps of period
    one. An experiment that stops at 0.34 has walked a third of the first of
    three stages and has not seen the second law at all, let alone the held
    one -- and the verdict that came back from it said "verified".
    """
    return tuple(sorted({
        float(value.replace("D", "E").replace("d", "e"))
        for value in _STAGE.findall(source_text or "")
        if float(value.replace("D", "E").replace("d", "e")) > 0.0}))


def exponential_time_constant(source_text: str,
                              props: Sequence[float] = ()) -> Optional[float]:
    """The time constant of an ``exp(-time/tau)`` law, taken from the constants.

    Returns None when the routine has no such law, or when the constant it
    divides by is not one this manifest carries a value for. Never invents
    one: a growth whose rate is unknown has no known duration either, and
    saying so is the answer.
    """
    names = {match.group(1).upper()
             for match in _EXPONENTIAL.finditer(source_text or "")}
    if not names:
        return None
    from_props = {name.upper(): int(index)
                  for name, index in _FROM_PROPS.findall(source_text or "")}
    for name in sorted(names):
        index = from_props.get(name)
        if index and 0 < index <= len(props):
            value = float(props[index - 1])
            if value > 0.0:
                return value
    return None


@dataclass
class Requirement:
    """How long an experiment has to run for this source's clock to matter."""

    total_time: float = 0.0
    #: Step periods, when the source's own law is staged across steps.
    periods: tuple[float, ...] = ()
    reason: str = ""

    @property
    def declared(self) -> bool:
        return self.total_time > 0.0

    def as_dict(self) -> dict:
        return {"total_time": self.total_time, "periods": list(self.periods),
                "reason": self.reason}


def required_total_time(source_text: str, props: Sequence[float] = (),
                        deck_periods: Sequence[float] = ()) -> Requirement:
    """The analysis time an experiment has to reach, from the source's own law.

    Three clocks, checked in the order of how specific they are.

    A STAGED law names its own boundaries in total time, and the experiment
    has to reach the last of them across that many steps. Shortening any of
    them moves the law into a different branch than the author's.

    An EXPONENTIAL law names a time constant among the material constants, and
    the experiment has to run for a few of them. ``tau`` comes from the
    manifest's props, which come from the author's deck; where the pairing
    could not establish the constants, this returns nothing rather than a
    duration computed from a number nobody published.

    A NORMALISED law divides its clock by a constant it assigns itself --
    ``TotalT = 1.0``, ``TotalT = 10.0`` -- and the experiment runs to that.

    Where the source declares none of the three, the author's own step periods
    are used if there are any, because a deck's period is a statement too.
    """
    stages = declared_stage_boundaries(source_text)
    if len(stages) >= 2:
        periods = tuple(
            stages[0] if index == 0 else stages[index] - stages[index - 1]
            for index in range(len(stages)))
        return Requirement(
            total_time=stages[-1], periods=periods,
            reason=(f"this routine switches its own law at total times "
                    + ", ".join(f"{value:g}" for value in stages)
                    + f", so it is written for {len(stages)} steps of periods "
                    + ", ".join(f"{value:g}" for value in periods)
                    + ". An experiment that stops inside the first of them "
                      "never reaches the others, and what it agreed about is "
                      "one branch of a law with " + str(len(stages))
                    + " of them"))

    tau = exponential_time_constant(source_text, props)
    if tau:
        total = TIME_CONSTANTS * tau
        return Requirement(
            total_time=total, periods=(total,),
            reason=(f"this routine's driver is exp(-time/tau) with tau = "
                    f"{tau:g} taken from the author's own constants; running "
                    f"for {TIME_CONSTANTS:g} time constants ({total:g}) "
                    f"develops {1 - 2.718281828 ** -TIME_CONSTANTS:.0%} of its "
                    f"excursion, and running for a fraction of one develops "
                    f"a fraction of it"))

    scale = declared_scale(source_text)
    if scale.declared:
        return Requirement(
            total_time=scale.value, periods=(scale.value,),
            reason=(f"this routine normalises its clock by {scale.name} = "
                    f"{scale.value:g} ({scale.evidence}), so one unit of "
                    f"{scale.name} is the whole of the history its author "
                    f"designed"))

    periods = tuple(float(value) for value in deck_periods if float(value) > 0)
    if periods:
        return Requirement(
            total_time=sum(periods), periods=periods,
            reason=(f"this routine declares no time scale of its own; the "
                    f"author's deck runs "
                    + ", ".join(f"{value:g}" for value in periods)
                    + " of step time and that is the history it was written "
                      "against"))
    return Requirement(
        reason=("this routine declares no time scale and the author's deck "
                "states no period, so there is nothing here that says how "
                "long an experiment has to run"))
