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


def time_driven_state_slots(source_text: str,
                            path: Optional[Path] = None) -> dict[int, str]:
    """Which STATEV slots hold a quantity the clock decides.

    Directly, where the routine writes ``STATEV(1) = 1.0 + ... TIME(1) ...``,
    and one copy further, where it computes ``G11`` from the clock and then
    writes ``STATEV(8) = G11``. Those slots are the ones a growth criterion
    has to watch: ``PureGrowth.for`` moves three of its nine state variables
    under any loading at all, and only two of them are the growth tensor.

    This is the set the clock REACHES, read from the shape of the code and
    nothing else. It is deliberately wider than the set the clock DECIDES:
    ``STATEV(9) = (TIME(2)+DTIME)`` is reached by the clock and is the clock,
    and ``STATEV(8) = G11`` is reached by the clock in a source whose own
    constants fix G11 at 1.0 for all time. Narrowing the two is
    :func:`clock_reading`'s job, and keeping the wide reading separate is what
    lets a record say which of the two a slot failed.
    """
    driven = time_driven_names(source_text)
    slots: dict[int, str] = {}
    for name, statement in driven.items():
        slot = _STATEV_SLOT.match(name)
        if slot:
            slots[int(slot.group(1))] = statement
    return slots


#: Names that are the clock itself rather than something a law computes from
#: it. A state variable assigned nothing but these is a RECORD of the time,
#: not a growth quantity -- ``BodyForce-Growth-2Stages.for`` writes
#: ``STATEV(9) = (TIME(2)+DTIME)`` -- and it moves in every run by definition,
#: including the runs this family's criterion exists to reject.
_CLOCK_ONLY = {"TIME", "DTIME", "TOTALT", "KSTEP", "KINC"}


@dataclass(frozen=True)
class ClockReading:
    """Which quantities the clock DECIDES, separated from the ones it touches.

    Three ways a statement can read as clock-driven without the clock deciding
    anything, each measured on the corpus:

    ``constant`` -- the routine's own literal constants make the clock's
    coefficient zero. ``PureGravity.for`` writes the ordinary growth ramp
    ``DtltaG11 = (Lambda1z0 + Y*Lambda1z1 - 1.0)*(TIME(1)+DTIME)/TotalT`` two
    lines after ``Lambda1z0 = 1.0`` and ``Lambda1z1 = 0.0``, so the increment
    is identically zero and G is the identity for all time.

    ``load_only`` -- the quantity is computed by a load definition and not by
    the material. The same file's ``SUBROUTINE DLOAD`` ends with
    ``F = TargetF*TIME(1)/TotalT``, which is gravity being switched on over the
    step. That is a load ramp; the body-force family is what it is for, and
    reading it as growth put a body-force problem in the growth family.

    ``clock_only`` -- the slot holds the time itself.
    ``BodyForce-Growth-2Stages.for`` writes ``STATEV(9) = (TIME(2)+DTIME)``,
    which moves in every run of any length by construction.

    What is left in ``driven`` is what the clock actually decides.
    """

    driven: dict = field(default_factory=dict)
    slots: dict = field(default_factory=dict)
    constant: dict = field(default_factory=dict)
    load_only: dict = field(default_factory=dict)
    clock_only: dict = field(default_factory=dict)
    #: Routines whose straight-line reading a GOTO could invalidate. Empty for
    #: every entry in the corpus whose family this changes; carried so that a
    #: caller who wants the stronger guarantee can ask for it.
    jumps: tuple = ()

    @property
    def found(self) -> bool:
        return bool(self.driven)

    def as_dict(self) -> dict:
        return {"driven": dict(self.driven),
                "slots": {str(slot): statement
                          for slot, statement in self.slots.items()},
                "constant": dict(self.constant),
                "load_only": dict(self.load_only),
                "clock_only": dict(self.clock_only),
                "jumps": list(self.jumps)}


def clock_reading(source_text: str,
                  path: Optional[Path] = None) -> ClockReading:
    """Separate the quantities the clock decides from the ones it only touches.

    :func:`time_driven_names` reads the SHAPE of the code: which assignments
    reach TIME, directly or through a chain of copies. Shape is where it has to
    start -- these laws write their growth in a dozen different spellings -- but
    shape alone put thirteen ``PureGravity.for`` variants into the growth family
    and then failed them all for a growth that never happened. The gate was
    right; the family was wrong.

    Three filters turn the shape into a reading, each of them a general
    statement about Fortran and none of them about this repository:

    1. **A quantity the routine's own constants pin to a value is not computed
       from the clock.** :mod:`umat_oti.abaqus.constant_folding` propagates the
       literal assignments and folds the expression; a name that comes out with
       a value does not depend on the clock, whatever the statement looks like.
       The fold is one-directional -- it says "constant" or "undecided", never
       "varies" -- so a growth law it cannot evaluate stays a growth law. The
       sibling ``HelixUp/.../PureGravity.for`` writes the same statements
       against the point's coordinate X and is undecidable here, which is why
       it is still growth and still verified.

    2. **A quantity only a load definition computes is a load ramp.** Growth is
       a property of a material, so it has to be the material routine that
       computes it. DLOAD computing a force that rises with TIME is the author
       describing how gravity is applied, not a material growing.

    3. **A slot holding the clock itself is not a growth quantity.** Kept from
       the reading this module already made: a slot assigned nothing but TIME
       and DTIME moves in every run by definition, including the runs the
       criterion exists to reject.
    """
    from umat_oti.abaqus import constant_folding

    if not _TIME_READ.search(_code(source_text)):
        return ClockReading()
    try:
        folding = constant_folding.fold(source_text, path=path)
    except Exception:                                      # pragma: no cover
        folding = constant_folding.Folding()
    units = folding.units or (constant_folding.Routine(
        "", "", "material", 1, frozenset(), source_text or ""),)

    driven: dict[str, str] = {}
    constant: dict[str, str] = {}
    load_only: dict[str, str] = {}
    clock_only: dict[str, str] = {}
    #: Names a load definition computes from the clock, so that one the
    #: MATERIAL also computes is not thrown away with them.
    from_a_load: dict[str, str] = {}
    for unit in units:
        # Per routine, because a name is a name only inside one.
        # ``PureGravity.for`` computes the scalar body force F from the clock
        # in its DLOAD and assigns the deformation gradient to a different F
        # in its UMAT; read as one namespace, the load ramp made the material
        # look like a growth law and no filter downstream could undo it.
        shaped = time_driven_names(unit.text)
        if not shaped:
            continue
        for name, statement in shaped.items():
            pinned = folding.constant_in(unit.name, name)
            if pinned is not None:
                constant.setdefault(name, (
                    f"{statement} -- but this routine's own constants make it "
                    f"{pinned.value:g} for all time"
                    + (f" ({pinned.statement})" if pinned.statement else "")))
                continue
            head = statement.split("<-")[0]
            _target, _, expression = head.partition("=")
            words = {word.upper() for word
                     in re.findall(r"[A-Za-z_]\w*", expression)}
            if not words - _CLOCK_ONLY:
                clock_only.setdefault(name, f"{statement} -- this is the clock itself")
                continue
            if unit.role == "load":
                where = unit.name or "a load definition"
                from_a_load.setdefault(name, (
                    f"{statement} -- computed in {where}, so it is the shape "
                    f"of the loading in time and not a material quantity"))
                continue
            driven[name] = statement
    for name, why in from_a_load.items():
        if name not in driven:
            load_only[name] = why

    slots: dict[int, str] = {}
    for name, statement in driven.items():
        match = _STATEV_SLOT.match(name)
        if match:
            slots[int(match.group(1))] = statement
    return ClockReading(driven=driven, slots=slots, constant=constant,
                        load_only=load_only, clock_only=clock_only,
                        jumps=tuple(folding.jumps))


#: Which of the two clocks a law reads. TIME(1) is the time within the current
#: STEP and restarts at zero in the next one; TIME(2) is the time since the
#: analysis began and does not.
_STEP_CLOCK = re.compile(r"\bTIME\s*\(\s*1\s*\)", re.IGNORECASE)
_TOTAL_CLOCK = re.compile(r"\bTIME\s*\(\s*2\s*\)", re.IGNORECASE)


def clock_read(source_text: str) -> str:
    """``"step"``, ``"total"``, ``"both"`` or ``""`` -- which clock drives this law.

    It decides whether the experiment may have more than one step, and getting
    it wrong throws the whole history away. ``PureGrowth.for`` ramps its growth
    in ``(TIME(1)+DTIME)/TotalT``, and TIME(1) restarts at zero when a step
    ends: a second step would reset the growth tensor to the identity and the
    run would look like a model that ungrew. ``BodyForce-Growth-2Stages.for``
    ramps in ``TIME(2)`` and branches on it at 1, 2 and 3, so it REQUIRES three
    steps to reach its own third branch.
    """
    body = _executable(source_text)
    step = bool(_STEP_CLOCK.search(body))
    total = bool(_TOTAL_CLOCK.search(body))
    if step and total:
        return "both"
    if step:
        return "step"
    if total:
        return "total"
    return ""


def growth_state_slots(source_text: str) -> dict[int, str]:
    """The state variables that hold a growth QUANTITY, not the clock.

    A growth criterion has to watch the growth tensor. Watching every slot the
    clock reaches watches the clock as well, and a slot assigned
    ``(TIME(2)+DTIME)`` moves by construction in any run of any length -- so a
    criterion built on it is met by the run it was written to reject.

    Measured on the three sources this separates: ``PureGrowth.for`` keeps G11
    in STATEV(8) and the norm of the growth tensor in STATEV(9), and this
    keeps both; ``BodyForce-Growth-2Stages.for`` keeps G11 in STATEV(8) and
    the elapsed time in STATEV(9), and this keeps only the first;
    ``umat_iso_morph_Abaqus.f`` keeps the growth multiplier in statev(1) and
    its cube in statev(2), and this keeps both; ``PureGravity.for`` keeps a G11
    its own constants fix at 1.0 in STATEV(8) and the norm of an identity
    tensor in STATEV(9), and this keeps NEITHER -- which is the whole reason
    that source is not a growth experiment.
    """
    return dict(clock_reading(source_text).slots)


_STATEV_WRITE = re.compile(
    r"^\s*(?:\d+\s+)?STATEV\s*\(([^)]*)\)\s*=\s*(.+)$", re.IGNORECASE)
_COMMON_BLOCK = re.compile(
    r"^\s*(?:\d+\s+)?COMMON\s*/\s*\w+\s*/\s*(.+)$", re.IGNORECASE)
_ARRAY_READ = re.compile(r"^\s*([A-Za-z_]\w*)\s*\(")


def state_is_not_its_own(source_text: str,
                         path: Optional[Path] = None) -> str:
    """Does this routine COMPUTE its state variables, or copy them in?

    A material routine whose every ``STATEV`` write reads an array out of a
    COMMON block does not own its state. Something else fills that block, and
    driven on its own the routine reports zeros however it is loaded -- so "no
    state variable moved" is a fact about the experiment's reach and not about
    the material, and no amplitude, clock or load will change it.

    Returns the reason, or ``""`` when the routine computes its own state.

    Two sources in the corpus do this, and both are the same construction: a
    phase-field or user element carries the mechanics and a ghost continuum
    element carries a UMAT whose only job is to put the element's results
    somewhere the ODB can see them. ``hamza-djeloud__thesis_project/
    plate_with_notch.for`` ends its UMAT with::

        NELEMAN = NOEL - TWO*N_ELEM
        DO I=1,NSTATV
         STATEV(I)=USRVAR(NELEMAN,I,NPT)
        END DO

    where ``COMMON/KUSER/USRVAR`` is written by the two UELs above it, and its
    own constitutive content is ``STRESS = STRESS + DDSDDE*DSTRAN`` at the
    E = 1e-11 its author's deck publishes. In pass10 it reached
    ``experiment_not_informative`` on "4 smooth states on a material that never
    activates", which is exactly right and says nothing about why.
    """
    from umat_oti.abaqus import constant_folding

    try:
        units = constant_folding.routines(source_text, path=path)
    except Exception:                                      # pragma: no cover
        return ""
    for unit in units:
        if unit.role != "material":
            continue
        lines = statements(unit.text)
        shared: set[str] = set()
        for line in lines:
            block = _COMMON_BLOCK.match(line)
            if not block:
                continue
            for piece in re.split(r",(?![^()]*\))", block.group(1)):
                name = piece.split("(")[0].strip().upper()
                if name:
                    shared.add(name)
        if not shared:
            continue
        writes = [match for match in (_STATEV_WRITE.match(line)
                                      for line in lines) if match]
        if not writes:
            continue
        copied = []
        for write in writes:
            read = _ARRAY_READ.match(write.group(2))
            if read is None or read.group(1).upper() not in shared:
                copied = []
                break
            copied.append(write.group(0).strip()[:80])
        if copied:
            return (f"every state variable {unit.name or 'this routine'} "
                    f"writes is copied out of a COMMON block rather than "
                    f"computed -- {copied[0]} -- so something else fills it. "
                    f"Driven on its own this routine reports the same state "
                    f"however it is loaded, and no amplitude, clock or load "
                    f"reaches what that state is for")
    return ""


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
             oriented: bool = False,
             path: Optional[Path] = None) -> Family:
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

    reading = clock_reading(source_text, path=path)
    driven = reading.driven
    slots = reading.slots
    # A source whose growth-shaped statements all fold to constants is not a
    # growth law, and saying so is worth a note wherever it lands: the reader
    # of a body-force verification needs to know that the file it came from
    # writes a growth tensor and switches it off.
    if reading.constant:
        # STATEV slots first. They are the names the growth criterion would
        # have watched, so they are what a reader of the refusal needs to see
        # before the list is cut short.
        named = sorted(reading.constant,
                       key=lambda name: (not name.startswith("STATEV"), name))
        notes.append(
            "this routine writes "
            + ", ".join(named[:4])
            + " in the shape of a law computed from the clock, but its own "
              "literal constants fix "
            + ("them" if len(reading.constant) > 1 else "it")
            + " for all time, so the clock decides nothing here: "
            + "; ".join(reading.constant[name] for name in named)[:320])
    has_body_force, body_force_why = applies_a_body_force(source_text)
    finite = bool(_DFGRD.search(text))
    rate = bool(_PER_DTIME.search(text)) or bool(
        re.search(r"\bDTIME\b[^\n]*\*\*", text))

    borrowed = state_is_not_its_own(source_text, path=path)
    if borrowed:
        notes.append(borrowed)
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
        if reading.load_only:
            notes.append(
                "the clock appears in this source's load definition -- "
                + "; ".join(reading.load_only[name]
                            for name in sorted(reading.load_only))[:200]
                + " -- which is how far the author ramps the load, and is "
                  "carried by the body-force segment rather than by a growth "
                  "criterion")
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


#: How far past its own onset a cohesive law with no closed-form end of
#: softening is opened. Ten: far enough that a damage law driven at a rate --
#: ``dd = (1/Eta1)*PP(-Ad1 - Gc*Da)`` -- has accumulated damage over a decade
#: of separation, and near enough that the element is not turned inside out.
#: A choice, and the same class of choice as the tool's own
#: BEYOND_TRANSITION: how far past a threshold the SOURCE defines to walk.
OPEN_PAST_ONSET = 10.0

#: What a cohesive constant is called, by the names these authors use.
_STIFFNESS = re.compile(r"^(A_?K|DK|K)[A-Z_0-9]*$", re.IGNORECASE)
_STRENGTH = re.compile(r"^(TAU|SIG|STRENGTH)[A-Z_0-9]*$", re.IGNORECASE)
_TOUGHNESS = re.compile(r"^(G_?N?C|GC|GIC)$", re.IGNORECASE)


def cohesive_scales(source_text: str,
                    props: Sequence[float]) -> Optional[tuple]:
    """The separation this law damages at, from what the law calls its own
    constants.

    Two parameterisations appear in this corpus and they are read the same
    way -- by asking the source what each constant IS, not by counting
    positions.

    ``harshaa765__Bilinear-CZM-UMAT`` names ``A_KN = PROPS(1)``,
    ``TAU_N = PROPS(2)`` and ``G_NC = PROPS(5)`` and writes the onset out
    itself: ``DELTA_NC = TAU_N/A_KN``. The separation at which the traction
    reaches zero is ``2*G_NC/TAU_N``.

    ``lucassalmon83860-bit``'s healing law names ``DKplus = PROPS(1)`` and
    ``Gc = PROPS(7)`` and has no strength at all: its damage grows while
    ``2(1-Da)*Kplus*eps^2/2 > Gc*Da``, so the separation at which the elastic
    energy density reaches the toughness is ``sqrt(Gc/Kplus)``. There is no
    closed form for where the traction reaches zero, so the path is opened a
    stated multiple past the onset instead of to a computed end.

    Returns ``(onset, target, how)`` or None when the source names neither
    pairing, because opening a cohesive law to a separation nothing published
    justifies is choosing the experiment.
    """
    from umat_oti.abaqus.deck_pairing import named_constants

    names = named_constants(source_text)
    if not names:
        return None

    def value_of(pattern) -> Optional[tuple[int, float]]:
        for index in sorted(names):
            if not pattern.match(names[index]):
                continue
            if 0 < index <= len(props):
                number = float(props[index - 1])
                if number > 0.0:
                    return index, number
        return None

    stiffness = value_of(_STIFFNESS)
    toughness = value_of(_TOUGHNESS)
    if stiffness is None or toughness is None:
        return None
    strength = value_of(_STRENGTH)
    if strength is not None:
        onset = strength[1] / stiffness[1]
        final = 2.0 * toughness[1] / strength[1]
        if final > onset > 0.0:
            return onset, 0.5 * (onset + final), (
                f"the law names PROPS({stiffness[0]})={names[stiffness[0]]} a "
                f"stiffness, PROPS({strength[0]})={names[strength[0]]} a "
                f"strength and PROPS({toughness[0]})={names[toughness[0]]} a "
                f"toughness, which put damage onset at {onset:g} and the end "
                f"of softening at {final:g}; this opens halfway down the "
                f"softening branch")
    onset = math.sqrt(toughness[1] / stiffness[1])
    if not onset > 0.0:                            # pragma: no cover - guarded
        return None
    return onset, OPEN_PAST_ONSET * onset, (
        f"the law names PROPS({stiffness[0]})={names[stiffness[0]]} a "
        f"stiffness and PROPS({toughness[0]})={names[toughness[0]]} a "
        f"toughness and no strength at all, so the separation at which its "
        f"elastic energy density reaches its toughness -- "
        f"sqrt(Gc/K) = {onset:g} -- is its own scale; there is no closed form "
        f"for the end of softening, so this opens {OPEN_PAST_ONSET:g} times "
        f"past it and lets the softening criterion say whether that was far "
        f"enough")


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
          path: Optional[Path] = None,
          deck_periods: Sequence[float] = (),
          body_force: tuple = (), held: tuple = (),
          body_force_provenance: str = "",
          clamp_a_face: bool = False,
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
        oriented=manifest.orientation_axes is not None,
        path=path or manifest.source)
    criterion = MEANINGFUL_ACTIVATION.get(chosen.name, "")
    requirement = time_scale.required_total_time(
        source_text, manifest.props, deck_periods)
    warnings: list[str] = []

    if chosen.name == "cohesive":
        scales = cohesive_scales(source_text, manifest.props)
        if scales is None:
            bounds = _cohesive_onset(manifest.props)
            scales = ((bounds[0], 0.5 * (bounds[0] + bounds[1]),
                       "read from the positions a bilinear law puts its "
                       "stiffness, strength and toughness in")
                      if bounds else None)
        if scales is None:
            return Experiment(
                family=chosen, criterion=criterion, requirement=requirement,
                refusal=("this is a traction-separation law and how far to "
                         "open it is decided by its own constants: a "
                         "stiffness with a strength gives an onset and an end "
                         "of softening, a stiffness with a toughness gives an "
                         "onset. This source names neither pairing among the "
                         "constants its deck publishes, so opening it to any "
                         "particular separation would be choosing the "
                         "experiment rather than reading it"))
        onset, target, how = scales
        loading = cohesive_open_and_release(onset, target)
        loading = tuple(replace(segment, increments=INCREMENTS["cohesive"],
                                period=(requirement.periods[0]
                                        if requirement.periods else 1.0))
                        for segment in loading)
        return Experiment(
            manifest=replace(manifest, loading=loading),
            family=chosen, criterion=criterion, requirement=requirement,
            reason=(f"a traction-separation law, opened to {target:g}: {how}. "
                    f"Then released to zero and reopened, because a single "
                    f"opening cannot tell damage from nonlinear elasticity"),
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
        clock = clock_read(source_text)
        if clock == "step" and len(periods) > 1:
            # A law that reads the time within its STEP cannot be walked
            # across several of them: the clock restarts and the growth with
            # it. One step of the whole duration is the only shape that keeps
            # the history this law was written against.
            periods = (requirement.total_time,)
            warnings.append(
                "this law reads TIME(1), the time within the current step, "
                "which restarts at zero when a step ends -- so the whole "
                "duration is run as ONE step. A staged experiment would reset "
                "its growth tensor to the identity at every boundary")
        elif clock == "total" and len(periods) == 1 and requirement.total_time:
            warnings.append(
                "this law reads TIME(2), the time since the analysis began, "
                "so its history is continuous across steps and the single "
                "step here carries the whole of it")
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
            if clamp_a_face:
                segments[-1] = replace(
                    segments[-1], clamped_face=tuple(held or (1, 2)),
                    name=f"{segments[-1].name}_restrained",
                    description=(segments[-1].description
                                 + "; the face at minimum x is held in "
                                 + ", ".join(str(dof) for dof in (held or (1, 2)))
                                 + ", as the author's own support holds one end "
                                   "of their plate, so the growth is resisted "
                                   "and carries a stress instead of being "
                                   "traction-free"))
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
                    + (". A face is held in the directions the author's own "
                       "support holds, so the growth is resisted and the "
                       "element carries a stress: a freely growing element is "
                       "traction-free by construction, and an agreement about "
                       "a zero is not a verification" if clamp_a_face else "")
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
    # choosing how far. What this decides is the SHAPE of the path, which the
    # search does not: how many legs it has and whether it reverses.
    loading = manifest.loading or _strain_path(
        strain, reverses=len(deck_periods) >= 2,
        components=geometry.ntens)
    shape = ("out, back through zero and out again, because the author's own "
             "deck runs " + str(len(deck_periods)) + " steps and a deck that "
             "reverses is a deck whose material was expected to behave "
             "differently on the way back"
             if len(deck_periods) >= 2 else
             "extension, compression and shear, which is the smallest set "
             "that reaches a threshold in any of the three")
    return Experiment(
        manifest=replace(manifest, loading=loading),
        family=chosen, criterion=criterion,
        requirement=requirement,
        reason=(f"the driver of this source is the strain increment, so the "
                f"amplitude search chooses how far and this chooses the shape: "
                f"{shape}"),
        warnings=tuple(warnings))


def _strain_path(strain: float, reverses: bool,
                 components: int = 6) -> tuple[LoadingSegment, ...]:
    """The legs a strain-driven experiment is made of.

    Three questions a single monotonic extension cannot answer: whether the
    material is different in compression, whether it does anything under
    deviatoric loading, and -- when the author's own deck reverses -- whether
    it comes back the way it went out. The author's step count decides the
    last: ``MML_U2/SHELL_TCT_IM.inp`` runs TENS1, COMP1 and TESN2, which is a
    tension-compression-tension test, and a monotonic path would verify a
    kinematic-hardening model on the half of it that looks isotropic.
    """
    from umat_oti.abaqus.manifest import compression, cyclic

    if reverses:
        return cyclic(strain) + (simple_shear(strain),)
    return (uniaxial(strain), compression(strain), simple_shear(strain))


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
    from umat_oti.abaqus.formulation import (read_orientation, settle,
                                             stated_temperature)

    source = Path(source)
    text = source_text if source_text is not None else source.read_text(
        errors="replace")
    pairing = deck_pairing.pair(source, Path(repository), source_text=text)
    if not pairing.found:
        return Plan(source, Experiment(refusal=pairing.refusal), pairing)
    material = pairing.material
    deck_text = Path(material.deck).read_text(errors="replace")

    temperature, temperature_why = stated_temperature(deck_text)
    settled = settle(text, str(source), deck_text, str(material.deck),
                     material.name, temperature=temperature)
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
        # The author's own numbering for this material's elements, where the
        # deck gave one. A UMAT is handed NOEL and some of the corpus indexes
        # with it, so calling the single element 1 is not always the neutral
        # choice it looks like: irfancn/Abaqus-UEL-elastic computes
        # kelem = noel - 185 against elements the author numbers from 186, and
        # at NOEL=1 that reads a COMMON block at -184 and takes Abaqus down
        # with a signal 11 inside the element loop.
        element_label=material.first_element_label or 1,
        # Either witness settles it. The routine reading the deformation
        # gradient means the MATERIAL is finite-strain; the author's own step
        # carrying NLGEOM=YES means the PROBLEM is, and a cohesive element
        # opened to half its own thickness is one whether or not its law reads
        # DFGRD. Running a deck the author wrote NLGEOM=YES for without it
        # would be running a different analysis.
        kinematics=("finite"
                    if (_DFGRD.search(_executable(text)) or material.nlgeom)
                    else "small strain"),
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
        isothermal_temperature=(temperature
                                if geometry_for(settled.element).kind.endswith(
                                    "thermal") else None),
        temperature_provenance=(f"{Path(material.deck).name} {temperature_why}"
                                if temperature is not None else
                                temperature_why),
    )
    frame = read_orientation(deck_text, material.name)
    if frame.known:
        base = replace(base, orientation_axes=frame.axes,
                       orientation_rotation=frame.rotation,
                       orientation_provenance=(
                           f"{Path(material.deck).name}: {frame.provenance}"))
    family = classify(
        text, element=settled.element,
        family_of_element=(settled.formulation.family
                           if settled.formulation.family == "cohesive"
                           else settled.formulation.family),
        props=base.props, reads_coordinates=bool(coordinate_aliases(text)),
        oriented=base.orientation_axes is not None, path=source)
    built = build(
        text, base, family=family, path=source,
        deck_periods=material.step_periods,
        body_force=(loads.components if (has_force and loads.driven) else ()),
        held=restraints.supports or (1, 2),
        body_force_provenance=loads.provenance)
    return Plan(source, built, pairing, settled, placement, restraints, loads)


# ---------------------------------------------------------------------------
# what would count as having run the experiment
# ---------------------------------------------------------------------------
#: How much a growth quantity has to move before the growth has happened. One
#: percent of its own initial value -- a growth stretch starts at 1, so this is
#: a stretch of 1.01. Below that the element is the element the author started
#: with, and a comparison of two builds there is a comparison of the part every
#: build gets right.
GROWTH_MOVEMENT = 0.01

#: How far above the material's own constants a stress may go before the
#: response stops being about the material. Re-exported from
#: :mod:`umat_oti.abaqus.plausibility` rather than declared again here, so
#: there is one number and not two that happen to agree.
#:
#: An elastic constant IS a stress: it is what the material carries at unit
#: strain. A thousand times it is either a strain of a thousand or arithmetic
#: that has left the model, and no single-element experiment here is driven
#: past a few tens of percent. Measured on BodyForce-Growth-2Stages.for under
#: the deck this module replaces: peak stress 1.575e13 against a material
#: block carrying one constant, 1e8 -- a ratio of 157,500, returned by a run
#: that was finite, complete, and reported as verified. The same model sat at
#: about 4e13 at the SMALLEST amplitude the search probed, so no amplitude
#: would have rescued that deck; the deck was wrong.
from umat_oti.abaqus.plausibility import (                        # noqa: E402
    FAR_ABOVE_THE_CONSTANTS as PLAUSIBLE_STRESS_MULTIPLE)


@dataclass(frozen=True)
class Finding:
    """Whether one criterion was met, and the number that says so.

    ``met`` is None when the run does not carry what the criterion needs.
    That is a third answer and not a failure: "the probe recorded no state
    variables" and "the growth tensor did not move" are different findings,
    and reporting the first as the second would blame the model for the
    instrument.
    """

    name: str
    met: Optional[bool]
    reason: str
    magnitude: float = 0.0

    def as_dict(self) -> dict:
        return {"name": self.name, "met": self.met, "reason": self.reason,
                "magnitude": self.magnitude}


def _values(record: dict, key: str) -> list[float]:
    out: list[float] = []
    for value in (record.get(key) or ()):
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append(number)
    return out


def _results(records: Sequence[dict]) -> list[dict]:
    return [record for record in (records or ())
            if record.get("kind") != "entry"]


def growth_developed(records: Sequence[dict], slots: dict,
                     total_time: float = 0.0) -> Finding:
    """Did the GROWTH TENSOR develop, or did some other state variable move?

    The slots are the ones the source itself computes from the clock, found by
    name in :func:`time_driven_state_slots`. ``PureGrowth.for`` has nine state
    variables and three of them move under any loading at all -- it caches the
    point's coordinates in the first three -- so "a state variable changed" is
    true of it from the first increment and says nothing about growth.

    What this asks is whether the quantity the growth law computes actually
    ran: at least one clock-driven slot changed by 1% or more of its own
    starting value. For a growth stretch, which starts at one, that is a
    stretch of 1.01.

    ``total_time`` is how long the experiment was supposed to run, and it is
    carried so that a failure can say WHICH failure it is. Two entries in the
    pass10 corpus run failed this at 0.383% and 0.195% having run the whole of
    their author's clock, and they are not short runs:
    ``BodyForce-Growth-2Stages.for`` builds its growth on the author's own
    dimensionless parameter ``Epsilon = RhoR*fZ*L/C0``, where C0 is the single
    constant the deck publishes. At the 25 MPa deck that parameter caps
    ``|G11 - 1|`` at 0.2997% anywhere in the element, so no experiment of any
    length reaches 1% -- the model's own growth is small. At the 1 MPa deck the
    same source reaches 75% and the criterion passes. A message that says only
    "the material near its initial state" invites the reader to lengthen a run
    that was already complete.
    """
    results = _results(records)
    if not results:
        return Finding("growth developed", None,
                       "this run recorded no completed UMAT calls")
    if not slots:
        return Finding("growth developed", None,
                       "no state variable in this source is computed from the "
                       "clock, so there is no growth quantity to watch")
    first = _values(results[0], "STATEV")
    last = _values(results[-1], "STATEV")
    if not first or not last:
        return Finding("growth developed", None,
                       "the probe recorded no state variables, so whether the "
                       "growth quantities moved cannot be read off this run")
    moved: list[tuple[int, float]] = []
    for slot in sorted(slots):
        index = slot - 1
        if index >= len(first) or index >= len(last):
            continue
        scale = abs(first[index]) or 1.0
        moved.append((slot, abs(last[index] - first[index]) / scale))
    if not moved:
        return Finding("growth developed", None,
                       f"this source computes STATEV"
                       f"{sorted(slots)} from the clock and the probe recorded "
                       f"{len(first)} state variables, so those slots are not "
                       f"in this run")
    best_slot, best = max(moved, key=lambda pair: pair[1])
    detail = ", ".join(f"STATEV({slot}) moved {value:.3%}"
                       for slot, value in moved)
    if best >= GROWTH_MOVEMENT:
        return Finding("growth developed", True,
                       f"the growth quantities this source computes from the "
                       f"clock developed: {detail}", best)
    reached = 0.0
    for record in results:
        try:
            reached = max(reached, float(record.get("time") or 0.0))
        except (TypeError, ValueError):
            continue
    if total_time > 0.0 and reached >= 0.99 * total_time:
        how = (f". The run reached {reached:g} of the {total_time:g} this "
               f"source's own law is written against, so it is not a short "
               f"run: this model's growth is small, and whether that is "
               f"enough to verify it on is a question about the model and not "
               f"about the experiment")
    elif total_time > 0.0:
        how = (f". The run reached only {reached:g} of the {total_time:g} "
               f"this source's own law is written against, so the growth was "
               f"cut off rather than small")
    else:
        how = (", so whatever this run agreed about is the material near its "
               "initial state")
    return Finding(
        "growth developed", False,
        f"the growth quantities this source computes from the clock barely "
        f"moved: {detail}. The largest, STATEV({best_slot}), changed "
        f"{best:.3%} of its starting value against the {GROWTH_MOVEMENT:.0%} "
        f"this family needs" + how, best)


def stress_stays_on_the_material_scale(records: Sequence[dict],
                                       props: Sequence[float],
                                       amplitude: float = 0.0,
                                       attempts: Sequence[dict] = ()) -> Finding:
    """Is the response the size the scales this problem supplies say it can be?

    Delegated to :mod:`umat_oti.abaqus.plausibility`, which asks three
    questions rather than one: the peak stress against the material constants,
    the peak stress against the same model's response at the smallest
    amplitude the search probed, and det F > 0. This module carried its own
    copy of the first of them while that module was on a branch this worktree
    could not see; two thresholds that agree today are still two, and the
    second one drifts.

    It is a coverage criterion and not only a safety net. For the growth
    family it is part of what "the experiment ran" means: a growth deck whose
    element sits where the growth tensor's determinant passes through zero
    returns finite, complete, monotone numbers 1e5 times the only material
    constant in the deck, and every generic activation indicator fires on
    them.
    """
    from umat_oti.abaqus import plausibility

    results = _results(records)
    if not results:
        return Finding("stress on the material scale", None,
                       "this run recorded no completed UMAT calls")
    report = plausibility.examine(results, props=props, amplitude=amplitude,
                                  attempts=attempts)
    if not report.checks:
        return Finding("stress on the material scale", None,
                       "nothing here supplied a scale to check the response "
                       "against: no material constant, no probe to compare "
                       "with and no deformation gradient recorded")
    worst = max((check.measured / check.against
                 for check in report.checks if check.against),
                default=0.0)
    return Finding("stress on the material scale", report.plausible,
                   report.reason(), worst)


#: A strain below which "the element moved" is a statement about round-off
#: rather than about a load. The comparison this pipeline makes is relative
#: and its tolerance is 1e-10, so a strain at that size is not resolved by the
#: instrument that would have to see it.
RESOLVED_STRAIN = 1e-10


def deformed_under_the_load(records: Sequence[dict],
                            props: Sequence[float] = ()) -> Finding:
    """Did the element move at all, when nothing prescribed that it should?

    The whole point of a body-force segment. No displacement is imposed beyond
    the rigid-body restraint, so a strain still at zero at the end of the step
    means DLOAD was never called or returned nothing -- which is exactly the
    failure this family exists to catch and is invisible to any amplitude,
    because there is no amplitude in the deck to raise.

    **What this criterion does NOT establish, stated because the same shape of
    gap is what put thirteen sources in the wrong family.** "Moved at all" is a
    threshold at the resolution of the instrument, not at a size that means
    anything mechanically, and a criterion whose threshold sits there can be
    met by a run that exercised nothing. Measured on the ten ``PureGravity.for``
    entries this module reclassifies: they reach strains of 5.5e-07 to 1.4e-05
    and peak stresses 1.3e-06 to 3.1e-05 of their own largest material
    constant. The load did work on the element -- that much is established and
    it is what this criterion claims -- but the response is linear-elastic at
    microstrain, and an agreement there is an agreement about the part every
    build gets right.

    The threshold is deliberately NOT raised to fix that, because there is no
    honest number to raise it to. A growth stretch starts at one, so "1% of its
    initial value" is a statement about the quantity; a body force produces a
    strain that depends on the specimen's SPAN, and a single element has no
    span. Picking a percentage here would be choosing the experiment rather
    than reading it, which is the thing this module exists to stop. What is
    reported instead is the size the strain reached against the scale the
    problem supplies, so the weakness is visible in the record rather than
    hidden behind a boolean. Whether a single element can carry a body-force
    experiment that means anything is a question for a run, and it is filed as
    one.
    """
    from umat_oti.abaqus.activation import strain_at

    results = _results(records)
    if not results:
        return Finding("deformed under the load", None,
                       "this run recorded no completed UMAT calls")
    reached = 0.0
    stress = 0.0
    for record in results:
        for value in strain_at(record):
            reached = max(reached, abs(value))
        for value in _values(record, "STRESS"):
            stress = max(stress, abs(value))
    scale = max((abs(float(value)) for value in props or ()), default=0.0)
    against = ""
    if scale > 0.0 and stress > 0.0:
        against = (f". It carried a peak stress of {stress:g} against a "
                   f"largest material constant of {scale:g}, a ratio of "
                   f"{stress / scale:.3e}, which is how far into the "
                   f"material's own range this load reached")
    if reached > RESOLVED_STRAIN:
        return Finding("deformed under the load", True,
                       f"the element reached a strain of {reached:g} with no "
                       f"displacement prescribed, so the load did work on it"
                       + against,
                       reached)
    return Finding("deformed under the load", False,
                   "no displacement was prescribed and the strain never left "
                   "zero, so nothing drove this element: either DLOAD was "
                   "never called or it returned nothing", reached)


def cohesive_softened(records: Sequence[dict]) -> Finding:
    """Did the traction FALL while the separation rose?

    Softening is the whole of a cohesive law. An opening that stops on the
    elastic branch verifies a penalty stiffness, which is one number the
    author wrote down, and says nothing about the damage evolution that is the
    model.
    """
    from umat_oti.abaqus.activation import strain_at

    results = _results(records)
    pairs: list[tuple[float, float]] = []
    for record in results:
        separation = strain_at(record)
        traction = _values(record, "STRESS")
        if separation and traction:
            pairs.append((separation[0], traction[0]))
    if len(pairs) < 4:
        return Finding("softened after onset", None,
                       f"only {len(pairs)} increments carry both a separation "
                       f"and a traction, which is too few to see a branch")
    peak = max(pairs, key=lambda pair: pair[1])
    after = [pair for pair in pairs if pair[0] > peak[0]]
    if not after:
        return Finding("softened after onset", False,
                       f"the traction rose to {peak[1]:g} at a separation of "
                       f"{peak[0]:g} and the run never opened further, so this "
                       f"path stayed on the elastic branch", 0.0)
    lowest = min(pair[1] for pair in after)
    drop = (peak[1] - lowest) / abs(peak[1]) if peak[1] else 0.0
    if drop > 0.05:
        return Finding("softened after onset", True,
                       f"the traction peaked at {peak[1]:g} at a separation of "
                       f"{peak[0]:g} and fell to {lowest:g} as the separation "
                       f"rose further -- a drop of {drop:.1%}", drop)
    return Finding("softened after onset", False,
                   f"the traction peaked at {peak[1]:g} and had fallen only "
                   f"{drop:.1%} by the end of the opening, so this path did "
                   f"not reach the softening branch", drop)


def direct_strain_produced_shear(records: Sequence[dict]) -> Finding:
    """Did a pure direct strain produce a shear stress?

    The observable that says a material's own axes reached the routine. In a
    frame aligned with the loading there is no such coupling; in a rotated one
    there always is, and a build that lost the rotation returns zero here and
    agrees with nothing.
    """
    from umat_oti.abaqus.activation import strain_at

    results = _results(records)
    best = 0.0
    for record in results:
        separation = strain_at(record)
        stress = _values(record, "STRESS")
        if len(stress) < 3 or len(separation) < 3:
            continue
        direct = max(abs(value) for value in separation[:2])
        shear = max(abs(value) for value in separation[2:])
        if direct <= 0.0 or shear > 1e-12:
            continue
        size = max(abs(value) for value in stress) or 1.0
        best = max(best, max(abs(value) for value in stress[2:]) / size)
    if not best:
        return Finding("direct strain produced shear", None,
                       "no increment in this run applied a direct strain with "
                       "no shear, so the coupling has nothing to show up in")
    if best > 1e-3:
        return Finding("direct strain produced shear", True,
                       f"a prescribed direct strain produced a shear stress "
                       f"{best:.3%} of the largest component, which only a "
                       f"rotated material frame does", best)
    return Finding("direct strain produced shear", False,
                   f"a prescribed direct strain produced a shear stress only "
                   f"{best:.3%} of the largest component, which is what an "
                   f"unrotated frame gives", best)


#: Criteria a family needs which this module cannot measure from one run's
#: probe records, stated so that a run request can carry them anyway.
DECLARED_ONLY: dict[str, tuple[str, ...]] = {
    "rate dependent": (
        "the same strain path walked over two different step periods must "
        "return two different stresses at the same strain -- two runs, so it "
        "is checked by the pair and not by either one",),
    "finite strain": (
        "a superposed rigid rotation must leave the material response "
        "unchanged, which needs a second run whose path is the first one "
        "rotated",),
}


def assess(family: Family, records: Sequence[dict],
           manifest: VerificationManifest,
           source_text: str = "", amplitude: float = 0.0,
           attempts: Sequence[dict] = ()) -> tuple[Finding, ...]:
    """Every criterion this family carries, measured against one run.

    The plausibility of the response is checked for EVERY family, not only for
    the ones whose criterion mentions it. It is the check that would have
    caught the growth run this module exists because of: finite, complete,
    monotone, active by every generic indicator, and 1e5 times the size the
    material can be.
    """
    findings: list[Finding] = [
        stress_stays_on_the_material_scale(records, manifest.props,
                                           amplitude=amplitude,
                                           attempts=attempts)]
    if family.name == "growth":
        findings.append(growth_developed(
            records, growth_state_slots(source_text),
            total_time=sum(segment.period
                           for segment in manifest.loading)))
        if any(segment.body_force for segment in manifest.loading):
            findings.append(deformed_under_the_load(records, manifest.props))
    elif family.name == "body force":
        findings.append(deformed_under_the_load(records, manifest.props))
    elif family.name == "cohesive":
        findings.append(cohesive_softened(records))
    elif family.name == "oriented":
        findings.append(direct_strain_produced_shear(records))
    for statement in DECLARED_ONLY.get(family.name, ()):
        findings.append(Finding(statement[:40], None, statement))
    return tuple(findings)
