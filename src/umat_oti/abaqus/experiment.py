"""Which experiment this source is for, and what would count as having run it.

One universal experiment -- drive a unit cube along a prescribed strain path
and raise the amplitude until something moves -- answers one question: what
stress does this strain produce? That is the right question for most of this
corpus and the wrong one for a sixth of it, and the wrong question does not
fail loudly. It comes back as "this harness generated no experiment this source
will run", or worse as ``verified``.

Four things were wrong with the universal assumptions, each measured on a
repository in the corpus:

**The driver.** A growth law is driven by TIME. ``PureGrowth.for`` builds its
growth tensor as ``1 + (Pi/2 + Y*(-Pi) - 1)*(TIME(1)+DTIME)/TotalT`` with
``TotalT = 1.0`` written into the source. Raising a prescribed strain does not
make time pass, and shortening the step to make a history finite shrinks the
growth in proportion: a run that reached a third of the author's step agreed
about a growth model that had barely grown. A cohesive law is driven by a
SEPARATION, not a strain. A body-force problem is driven by a force per unit
volume that a ``SUBROUTINE DLOAD`` in the same file computes -- and prescribing
every node's displacement means DLOAD is never called at all.

**The place.** A UMAT that reads COORDS computes a different material at a
different point. See :mod:`umat_oti.abaqus.coordinate_domain`.

**The element.** A cohesive law and a shell law were both refused for being
what they are. Both are drivable. See :mod:`umat_oti.abaqus.formulation`.

**What counts as having activated it.** "Some STATEV slot moved" is true of a
growth law from its first increment and says nothing about whether the growth
developed. Each family here states its own criterion, and the criterion names
the quantity rather than the slot: for a growth law, the components of the
GROWTH TENSOR have to develop; for a damage law, the reopened branch has to
return less traction than the first; for a rate-dependent one, the same strain
walked twice at different speeds has to give two different stresses.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from umat_oti.abaqus import time_scale
from umat_oti.abaqus.coordinate_domain import statements
from umat_oti.abaqus.elements import geometry_for
from umat_oti.abaqus.manifest import (LoadingSegment, VerificationManifest,
                                      cohesive_open_and_release, let_time_pass,
                                      off_axis, separate, simple_shear,
                                      under_body_force_over, uniaxial)

_COMMENT = re.compile(r"^[cC*!]")


def _code_lines(text: str):
    for line in (text or "").splitlines():
        if not line.strip() or _COMMENT.match(line) or line.lstrip().startswith("!"):
            continue
        yield line.split("!")[0]


def _code(text: str) -> str:
    return "\n".join(_code_lines(text))


#: A statement that NAMES variables rather than using them. A UMAT's own
#: argument list mentions COORDS, DFGRD0 and DFGRD1 whether or not it ever
#: looks at them, and reading the DIMENSION line as use put two routines that
#: never touch the deformation gradient into the finite-strain family.
_DECLARATION = re.compile(
    r"^\s*(?:\d+\s+)?(DOUBLE\s*PRECISION|REAL|INTEGER|DIMENSION|COMMON"
    r"|PARAMETER|CHARACTER|LOGICAL|IMPLICIT|SUBROUTINE|FUNCTION|INCLUDE|DATA"
    r"|SAVE|EXTERNAL|INTENT|ALLOCATABLE)\b", re.IGNORECASE)


def _executable(text: str) -> str:
    """The routine's statements, with its declarations and their continuations
    removed, so that naming a variable is not mistaken for using one."""
    kept: list[str] = []
    declaring = False
    for line in statements(text):
        stripped = line.strip()
        continued = (len(line) > 5 and line[:5].strip() == ""
                     and line[5:6] not in (" ", "")) or stripped.startswith(("&", "#"))
        if _DECLARATION.match(line):
            declaring = True
            continue
        if declaring and continued:
            continue
        declaring = False
        kept.append(line)
    return "\n".join(kept)


# ---------------------------------------------------------------------------
# what drives this source
# ---------------------------------------------------------------------------
_TIME_READ = re.compile(r"\bTIME\s*\(\s*[12]\s*\)", re.IGNORECASE)
_ASSIGN = re.compile(r"^\s*(?:\d+\s+)?([A-Za-z_]\w*(?:\(\s*\d+\s*\))?)\s*=\s*(.+)$")
_STATEV_SLOT = re.compile(r"^STATEV\s*\(\s*(\d+)\s*\)$", re.IGNORECASE)
_DLOAD = re.compile(r"^\s*(?:\d+\s+)?SUBROUTINE\s+DLOAD\s*\(",
                    re.IGNORECASE | re.MULTILINE)
#: A DLOAD whose only assignment to F is a literal zero is a DLOAD that applies
#: nothing. ``PureGrowth.for`` ends its routine with ``! TODO: for testing``
#: and ``F = 0.0``, and a body-force experiment built for it would be an
#: experiment with no load in it.
_F_ASSIGNMENT = re.compile(r"^\s*(?:\d+\s+)?F\s*=\s*(.+?)\s*$",
                           re.IGNORECASE | re.MULTILINE)
_DFGRD = re.compile(r"\bDFGRD[01]\b", re.IGNORECASE)
_PER_DTIME = re.compile(r"/\s*DTIME\b", re.IGNORECASE)
_TIMES_DTIME = re.compile(r"\bDTIME\s*\*|\*\s*DTIME\b", re.IGNORECASE)


def time_driven_names(source_text: str) -> dict[str, str]:
    """Every quantity this routine computes from the clock, and the statement.

    One level of assignment, because that is where these laws put it::

        G11 = 1.0 + (G11St1-1.0)*(TIME(2)+DTIME)/TotalT
        theg = (tmax-1.d0)*(1.d0-exp(-time(2)/tau)) + 1.d0
        STATEV(1)=1.0+(Lambda1-1.0)*(TIME(1)+DTIME)/TotalT

    A quantity computed from TIME is the thing an amplitude cannot reach. It
    is what makes these laws a separate family, and finding it by name is what
    lets the criterion say "the growth tensor developed" rather than "a state
    variable moved".
    """
    found: dict[str, str] = {}
    lines = statements(source_text)
    # A fixed point, not one pass. ``PureGrowth.for`` computes
    # ``DtltaG11`` from TIME, then ``G11 = 1.0 + DtltaG11``, then
    # ``STATEV(8) = G11``: three hops from the clock to the state variable a
    # growth criterion has to watch, and stopping at one found none of them.
    for _round in range(6):
        before = len(found)
        for line in lines:
            match = _ASSIGN.match(line)
            if not match:
                continue
            target, expression = match.group(1), match.group(2)
            key = "".join(target.split()).upper()
            if key in found:
                continue
            if _TIME_READ.search(expression):
                found[key] = line.strip()[:110]
                continue
            names = {"".join(name.split()).upper() for name
                     in re.findall(r"[A-Za-z_]\w*(?:\s*\(\s*\d+\s*\))?",
                                   expression)}
            reached = names & set(found)
            if reached:
                found[key] = (f"{line.strip()[:70]} <- "
                              f"{found[sorted(reached)[0]][:90]}")
        if len(found) == before:
            break
    return found


def time_driven_state_slots(source_text: str) -> dict[int, str]:
    """Which STATEV slots hold a quantity the clock decides.

    Directly, where the routine writes ``STATEV(1) = 1.0 + ... TIME(1) ...``,
    and one copy further, where it computes ``G11`` from the clock and then
    writes ``STATEV(8) = G11``. Those slots are the ones a growth criterion
    has to watch: ``PureGrowth.for`` moves three of its nine state variables
    under any loading at all, and only two of them are the growth tensor.
    """
    driven = time_driven_names(source_text)
    slots: dict[int, str] = {}
    for name, statement in driven.items():
        slot = _STATEV_SLOT.match(name)
        if slot:
            slots[int(slot.group(1))] = statement
    return slots


def applies_a_body_force(source_text: str) -> tuple[bool, str]:
    """Does this file's DLOAD actually apply anything?

    Both halves matter. ``PureGrowth.for`` and ``BodyForce-Growth-2Stages.for``
    carry the same DLOAD routine, and the first one ends it with::

        ! TODO: for testing
        F = 0.0

    so its experiment is a pure growth with no load, and the second ends it
    with ``F = TargetF*(TIME(1))/TotalT``. Two files, one routine, two
    different experiments -- and reading only ``SUBROUTINE DLOAD`` would give
    them both the same one.
    """
    opened = _DLOAD.search(source_text or "")
    if not opened:
        return False, "this source defines no SUBROUTINE DLOAD"
    # Only inside DLOAD. A UMAT in the same file routinely has a local ``F``
    # of its own -- ``PureGrowth.for`` writes ``F = DFGRD1`` in the UMAT --
    # and reading that as the body force said that a routine whose DLOAD ends
    # with ``F = 0.0`` applies the deformation gradient as a load.
    body = "\n".join(statements(source_text[opened.start():]))
    end = re.search(r"^\s*(?:\d+\s+)?END\b\s*$", body, re.IGNORECASE | re.MULTILINE)
    if end:
        body = body[:end.end()]
    assignments = [value.strip() for value in _F_ASSIGNMENT.findall(body)]
    if not assignments:
        return False, ("this source defines SUBROUTINE DLOAD and never "
                       "assigns F in it")
    last = assignments[-1]
    try:
        if abs(float(last.replace("D", "E").replace("d", "e"))) == 0.0:
            return False, (f"this source's DLOAD ends with F = {last}, so it "
                           f"applies no body force however it is loaded")
    except ValueError:
        pass
    return True, (f"this source's DLOAD computes F = {last}, so a body force "
                  f"is what drives it")


# ---------------------------------------------------------------------------
# the families
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Family:
    """What kind of experiment this source is for, and how it was decided."""

    name: str
    driver: str
    evidence: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"name": self.name, "driver": self.driver,
                "evidence": list(self.evidence), "notes": list(self.notes)}


#: Every family this module knows, with the criterion that says an experiment
#: in it has actually exercised the behaviour the family is named for. These
#: are the coverage criteria; they are quoted into every run request filed
#: from here, so a reader can tell what the run was supposed to establish.
MEANINGFUL_ACTIVATION: dict[str, str] = {
    "growth": (
        "the components of the GROWTH TENSOR must develop -- not merely any "
        "STATEV slot moving. The slots the source itself computes from TIME "
        "are identified by name, and at least one of them must change by 1% "
        "or more of its initial value, monotonically, over an analysis that "
        "reaches the whole of the total time the source's own law is written "
        "against. A run that stops inside the first of three staged branches "
        "has not exercised the second or the third, whatever it agreed about"),
    "body force": (
        "the element must DEFORM under a load nothing prescribed. No "
        "displacement is imposed except the rigid-body restraint, so a "
        "strain that is still zero at the end of the step means DLOAD was "
        "never called or returned nothing -- which is the failure this family "
        "exists to catch, and it is invisible to any amplitude"),
    "cohesive": (
        "the separation must pass the law's own damage-onset value and the "
        "traction must then FALL while the separation rises. Softening is the "
        "whole of a cohesive law; an opening that stops on the elastic branch "
        "verifies a penalty stiffness. The reopening must return a smaller "
        "traction than the first excursion reached at the same separation, "
        "which is what separates damage from nonlinear elasticity"),
    "rate dependent": (
        "the same strain path walked over two different step periods must "
        "give two different stresses at the same strain. Amplitude cannot "
        "show this: raising the strain does not make time pass, and a "
        "viscoplastic law driven fast and slow to the same place is the only "
        "experiment that separates its viscosity from its elasticity"),
    "damage": (
        "a reversal must return along a DIFFERENT slope than the loading "
        "went out on, and the reloading must meet a lower stress than the "
        "first excursion reached. A monotonic path cannot tell a damaged "
        "stiffness from a softening hardening law"),
    "oriented": (
        "a prescribed DIRECT strain must produce a non-zero SHEAR stress. "
        "That coupling exists only in a frame rotated off the loading axis, "
        "so it is the observable that says the material's own axes reached "
        "the routine; a build that lost the orientation returns zero there "
        "and agrees with nothing"),
    "finite strain": (
        "the deformation gradient must depart from the identity by enough to "
        "distinguish a finite-strain measure from its linearisation -- 2% or "
        "more in some component -- and a superposed rigid rotation must leave "
        "the material response unchanged, which is what objectivity means and "
        "what a dropped DROT breaks"),
    "plane stress": (
        "the routine must be driven with the three components a plane-stress "
        "element hands it and no more, and whatever threshold it carries -- a "
        "yield surface, a failure index -- must be crossed inside the path. "
        "The out-of-plane condition is the routine's to enforce and a "
        "verification that never loads it has not asked"),
    "strain driven": (
        "something in the routine must depart from linear-elastic inside the "
        "path: a state variable that moves, a tangent that changes, or a "
        "residual after reversal. An agreement reached where stress is linear "
        "in strain is an agreement about the part every build gets right"),
}


def classify(source_text: str, *, element: str = "",
             family_of_element: str = "", props: Sequence[float] = (),
             reads_coordinates: bool = False,
             oriented: bool = False) -> Family:
    """Which experiment family this source belongs to, from what it reads.

    Ordered by how much the answer changes the experiment. A cohesive law is
    handed a different quantity than a strain; a time-driven law cannot be
    reached by any amplitude; a body force is not applied by a boundary
    condition. Those three decide the whole deck. The rest -- rate dependence,
    damage, orientation -- decide which segments it is made of, and are
    carried as notes so a strain-driven experiment still knows what to include.
    """
    text = _executable(source_text)
    evidence: list[str] = []
    notes: list[str] = []

    driven = time_driven_names(source_text)
    slots = time_driven_state_slots(source_text)
    has_body_force, body_force_why = applies_a_body_force(source_text)
    finite = bool(_DFGRD.search(text))
    rate = bool(_PER_DTIME.search(text)) or bool(
        re.search(r"\bDTIME\b[^\n]*\*\*", text))

    if reads_coordinates:
        notes.append("this routine reads COORDS, so where the element sits is "
                     "part of what it computes")
    if finite:
        notes.append("this routine reads the deformation gradient, so its "
                     "step must carry NLGEOM=YES")
    if rate:
        notes.append("this routine divides by DTIME, so it has a rate and two "
                     "step periods will separate it from its elasticity")
    if oriented:
        notes.append("the author's deck gives this material its own axes, so "
                     "the verification carries them and looks for the "
                     "direct-to-shear coupling they produce")

    if family_of_element == "cohesive" or (
            element or "").upper().startswith("COH"):
        return Family("cohesive", "separation",
                      evidence=(f"the author's deck runs this material on "
                                f"{element or 'a cohesive element'}, which "
                                f"hands the UMAT a displacement jump rather "
                                f"than a strain",), notes=tuple(notes))

    if slots:
        named = ", ".join(f"STATEV({slot})" for slot in sorted(slots))
        evidence.append(f"this routine computes {named} from the clock: "
                        + "; ".join(slots[slot] for slot in sorted(slots))[:220])
        if has_body_force:
            notes.append(body_force_why)
        return Family("growth", "time", tuple(evidence), tuple(notes))
    if driven and not rate:
        evidence.append("this routine computes "
                        + ", ".join(sorted(driven)[:4])
                        + " from the clock: "
                        + "; ".join(driven[name]
                                    for name in sorted(driven))[:200])
        if has_body_force:
            notes.append(body_force_why)
        return Family("growth", "time", tuple(evidence), tuple(notes))

    if has_body_force:
        return Family("body force", "body force", (body_force_why,),
                      tuple(notes))

    if rate:
        return Family("rate dependent", "strain",
                      ("this routine divides a state increment by DTIME, so "
                       "the same strain applied over two step periods gives "
                       "two different answers",), tuple(notes))

    if oriented:
        return Family("oriented", "strain",
                      ("the author's deck gives this material a local frame, "
                       "and an off-axis response is what shows the frame "
                       "reached the routine",), tuple(notes))

    if family_of_element in ("plane stress", "shell", "membrane"):
        return Family("plane stress", "strain",
                      (f"the author runs this material in {family_of_element}, "
                       f"so the routine enforces its own out-of-plane "
                       f"condition and is handed three components",),
                      tuple(notes))

    if finite:
        return Family("finite strain", "strain",
                      ("this routine reads the deformation gradient rather "
                       "than the strain increment, so the experiment has to "
                       "reach a deformation a linearisation would get wrong",),
                      tuple(notes))

    return Family("strain driven", "strain",
                  ("nothing in this routine reads the clock, a body force, a "
                   "separation or a coordinate, so a prescribed strain path "
                   "is what it is for",), tuple(notes))


# ---------------------------------------------------------------------------
# building the experiment
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Experiment:
    """A manifest to run, the criterion it answers, and why it is that one."""

    manifest: Optional[VerificationManifest] = None
    family: Family = field(default_factory=lambda: Family("", ""))
    criterion: str = ""
    requirement: Any = None
    reason: str = ""
    refusal: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return self.manifest is not None

    def as_dict(self) -> dict:
        return {"family": self.family.as_dict(), "criterion": self.criterion,
                "requirement": (self.requirement.as_dict()
                                if self.requirement is not None else None),
                "reason": self.reason, "refusal": self.refusal,
                "warnings": list(self.warnings),
                "manifest": (self.manifest.as_dict() if self.manifest
                             else None)}


#: How many increments a family's own segments are walked in. A time-driven
#: law is integrated rather than sampled, and its increment size is part of the
#: integration; twenty over a step that the author ran with a maximum
#: increment of a tenth is the same resolution the author used.
INCREMENTS = {"growth": 20, "body force": 20, "cohesive": 20}


def _cohesive_onset(props: Sequence[float]) -> Optional[tuple[float, float]]:
    """The separation a bilinear cohesive law damages at, and where it ends.

    Read from the constants the way the law reads them:
    ``DELTA_NC = TAU_N/A_KN`` is the onset and ``2*G_NC/TAU_N`` is the
    separation at which the traction reaches zero -- which is what makes a
    target of ``0.2`` on the author's own numbers a point two thirds of the
    way down the softening branch rather than a number somebody liked.

    Returns None unless the block has the shape the law expects, because a
    target computed from the wrong constants is a target in the wrong place.
    """
    if len(props) < 5:
        return None
    stiffness, strength, _shear, _tear, toughness = (float(value)
                                                     for value in props[:5])
    if stiffness <= 0.0 or strength <= 0.0 or toughness <= 0.0:
        return None
    onset = strength / stiffness
    final = 2.0 * toughness / strength
    if not (final > onset > 0.0):
        return None
    return onset, final


def build(source_text: str, manifest: VerificationManifest, *,
          family: Optional[Family] = None,
          deck_periods: Sequence[float] = (),
          body_force: tuple = (), held: tuple = (),
          body_force_provenance: str = "",
          strain: float = 0.01) -> Experiment:
    """The experiment this source is for, as a manifest ready to be written.

    Nothing about the amplitude search is replaced for a strain-driven source:
    this returns the manifest unchanged for those and says so, because the
    search is the right instrument when the driver IS the strain. What it
    replaces is the assumption that the driver always is.
    """
    element = manifest.element_type
    geometry = geometry_for(element)
    chosen = family or classify(
        source_text, element=element,
        family_of_element=geometry.kind if geometry.kind == "cohesive" else "",
        props=manifest.props,
        reads_coordinates=bool(manifest.node_coordinates),
        oriented=manifest.orientation_axes is not None)
    criterion = MEANINGFUL_ACTIVATION.get(chosen.name, "")
    requirement = time_scale.required_total_time(
        source_text, manifest.props, deck_periods)
    warnings: list[str] = []

    if chosen.name == "cohesive":
        bounds = _cohesive_onset(manifest.props)
        if bounds is None:
            return Experiment(
                family=chosen, criterion=criterion, requirement=requirement,
                refusal=("this is a traction-separation law and the "
                         "separation it has to be opened to is decided by its "
                         "own constants -- the onset is the strength over the "
                         "penalty stiffness and the end of softening is twice "
                         "the toughness over the strength. The material block "
                         "paired with it does not have that shape, so how far "
                         "to open it is not something this harness can read "
                         "off anything the author published"))
        onset, final = bounds
        target = 0.5 * (onset + final)
        loading = cohesive_open_and_release(
            onset, target)
        loading = tuple(replace(segment, increments=INCREMENTS["cohesive"],
                                period=(requirement.periods[0]
                                        if requirement.periods else 1.0))
                        for segment in loading)
        return Experiment(
            manifest=replace(manifest, loading=loading),
            family=chosen, criterion=criterion, requirement=requirement,
            reason=(f"a traction-separation law, opened to {target:g}: its own "
                    f"constants put damage onset at {onset:g} and the end of "
                    f"softening at {final:g}, so this lands halfway down the "
                    f"softening branch, where the traction is falling while "
                    f"the separation rises. Then released to zero and "
                    f"reopened, because a single opening cannot tell damage "
                    f"from nonlinear elasticity"),
            warnings=tuple(warnings))

    if chosen.name == "growth":
        if not requirement.declared:
            return Experiment(
                family=chosen, criterion=criterion, requirement=requirement,
                refusal=("this law is driven by the clock and neither the "
                         "source nor the author's deck says how long its "
                         "clock runs. Choosing a duration would choose how "
                         "much of the growth happens, which is the "
                         "constitutive problem and not the numerics"))
        periods = requirement.periods or (requirement.total_time,)
        segments: list[LoadingSegment] = []
        for index, period in enumerate(periods, start=1):
            name = "grow" if len(periods) == 1 else f"stage{index}"
            if body_force:
                segments.append(under_body_force_over(
                    body_force, held or (1, 2), period,
                    increments=INCREMENTS["growth"], name=f"{name}_loaded",
                    provenance=body_force_provenance))
            else:
                segments.append(let_time_pass(
                    period, increments=INCREMENTS["growth"], name=name,
                    why=requirement.reason[:160]))
        return Experiment(
            manifest=replace(manifest, loading=tuple(segments),
                             kinematics="finite" if _DFGRD.search(
                                 _executable(source_text))
                             else manifest.kinematics),
            family=chosen, criterion=criterion, requirement=requirement,
            reason=(f"driven by the clock and by nothing else: "
                    f"{requirement.reason}. The element is held only where "
                    f"rigid-body motion requires, so the growth produces the "
                    f"deformation rather than fighting a boundary condition "
                    f"the author never wrote"
                    + (f", and the author's own body force is applied through "
                       f"the source's DLOAD ({body_force_provenance})"
                       if body_force else "")),
            warnings=tuple(warnings))

    if chosen.name == "body force":
        if not body_force:
            return Experiment(
                family=chosen, criterion=criterion, requirement=requirement,
                refusal=("this source's DLOAD applies a force per unit volume "
                         "and no deck paired with it names which components "
                         "carry it. A body force this harness chose would be "
                         "a load the author never applied"))
        period = requirement.periods[0] if requirement.periods else 1.0
        return Experiment(
            manifest=replace(manifest, loading=(under_body_force_over(
                body_force, held or (1, 2), period,
                increments=INCREMENTS["body force"],
                provenance=body_force_provenance),)),
            family=chosen, criterion=criterion, requirement=requirement,
            reason=(f"driven by the author's own body force through the "
                    f"source's SUBROUTINE DLOAD ({body_force_provenance}); "
                    f"{requirement.reason}"),
            warnings=tuple(warnings))

    if chosen.name == "oriented":
        loading = (off_axis(strain), simple_shear(strain))
        return Experiment(
            manifest=replace(manifest, loading=loading),
            family=chosen, criterion=criterion, requirement=requirement,
            reason=("an anisotropic material in a frame the author published: "
                    "a direct strain along the deck's global axis is off the "
                    "material's own axes, and the shear stress it produces is "
                    "the evidence that the frame reached the routine"),
            warnings=tuple(warnings))

    # Strain-driven, plane stress, finite strain, rate dependent: the driver
    # IS the strain, and the amplitude search is the right instrument for
    # choosing how far. Say what the family is and leave the loading alone.
    return Experiment(
        manifest=manifest, family=chosen, criterion=criterion,
        requirement=requirement,
        reason=("the driver of this source is the strain increment, so the "
                "amplitude search chooses the experiment and this adds only "
                "what the family needs beside it"),
        warnings=tuple(warnings))


# ---------------------------------------------------------------------------
# one call that does the whole chain
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Plan:
    """Everything decided about one source, with every decision's evidence."""

    source: Path
    experiment: Experiment = field(default_factory=Experiment)
    pairing: Any = None
    settled: Any = None
    placement: Any = None
    restraints: Any = None
    loads: Any = None

    @property
    def found(self) -> bool:
        return self.experiment.found

    @property
    def manifest(self) -> Optional[VerificationManifest]:
        return self.experiment.manifest

    def as_dict(self) -> dict:
        return {
            "source": str(self.source),
            "experiment": self.experiment.as_dict(),
            "pairing": self.pairing.as_dict() if self.pairing else None,
            "formulation": self.settled.as_dict() if self.settled else None,
            "placement": self.placement.as_dict() if self.placement else None,
            "restraints": (self.restraints.as_dict() if self.restraints
                           else None),
            "loads": self.loads.as_dict() if self.loads else None,
        }


def plan(source: Path, repository: Path, name: str = "",
         source_text: Optional[str] = None) -> Plan:
    """Read one source and its repository, and decide the whole experiment.

    The chain in one call, so that a caller gets a manifest or a refusal and
    not a pile of half-answers: which deck actually uses this UMAT, which
    element that deck runs it on, where in the author's own mesh the element
    has to stand, which family the routine belongs to, and what would count as
    having exercised it.

    Every step can refuse, and a refusal is returned rather than worked
    around. "No material published in this repository can feed this routine"
    is a different finding from "this harness has no experiment for it", and
    reporting the second when the first is true is how three mholla growth
    UMATs were recorded as unloadable when what was missing was their
    constants.
    """
    from umat_oti.abaqus import deck_pairing
    from umat_oti.abaqus.body_force import read_loads, read_restraints
    from umat_oti.abaqus.coordinate_domain import (coordinate_aliases, place,
                                                   reads_coordinates)
    from umat_oti.abaqus.formulation import settle

    source = Path(source)
    text = source_text if source_text is not None else source.read_text(
        errors="replace")
    pairing = deck_pairing.pair(source, Path(repository), source_text=text)
    if not pairing.found:
        return Plan(source, Experiment(refusal=pairing.refusal), pairing)
    material = pairing.material
    deck_text = Path(material.deck).read_text(errors="replace")

    settled = settle(text, str(source), deck_text, str(material.deck),
                     material.name)
    if not settled.element:
        return Plan(source, Experiment(refusal=settled.formulation.reason),
                    pairing, settled)

    placement = place(text, deck_text, material.elements)
    if reads_coordinates(text) and coordinate_aliases(text) and not placement.found:
        return Plan(source, Experiment(refusal=placement.refusal),
                    pairing, settled, placement)

    restraints = read_restraints(Path(material.deck))
    loads = read_loads(Path(material.deck))
    has_force, _why = applies_a_body_force(text)

    geometry = geometry_for(settled.element)
    nodes: tuple = ()
    node_provenance = ""
    if placement.found and placement.coordinate_dependent:
        corners = placement.element.nodes[:geometry.node_count]
        if len(corners) == geometry.node_count:
            nodes = tuple(corners)
            node_provenance = (
                f"element {placement.element.number} "
                f"({placement.element.element_type}) of "
                f"{Path(material.deck).name}, reduced to its corner nodes: "
                f"{placement.reason}")

    base = VerificationManifest(
        name=name or source.stem[:40],
        source=source,
        element_type=settled.element,
        kinematics="finite" if _DFGRD.search(_executable(text)) else "small strain",
        props=tuple(material.values),
        nprops=material.constants,
        nstatv=max(material.depvar, 1),
        unsymmetric=material.unsymmetric,
        material_provenance=(f"{Path(material.deck).name} *MATERIAL "
                             f"{material.name}: {material.constants} "
                             f"constants, *DEPVAR {material.depvar} -- "
                             f"{pairing.why}"),
        initial_state_from_user_subroutine=material.user_initial_state,
        node_coordinates=nodes,
        node_provenance=node_provenance,
        plane_strain_directions=restraints.everywhere,
    )
    family = classify(
        text, element=settled.element,
        family_of_element=(settled.formulation.family
                           if settled.formulation.family == "cohesive"
                           else settled.formulation.family),
        props=base.props, reads_coordinates=bool(coordinate_aliases(text)),
        oriented=base.orientation_axes is not None)
    built = build(
        text, base, family=family, deck_periods=material.step_periods,
        body_force=(loads.components if (has_force and loads.driven) else ()),
        held=restraints.supports or (1, 2),
        body_force_provenance=loads.provenance)
    return Plan(source, built, pairing, settled, placement, restraints, loads)
