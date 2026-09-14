"""Where the converted source drops a derivative on the way to the stress.

The OTI type carries a value and its derivatives together. ``REAL(x)`` takes
the value and throws the derivatives away. That is exactly right at the end,
where the real stress has to be written back into Abaqus's own array, and it
is exactly wrong anywhere the result is used again: from that assignment on,
the quantity behaves like a constant, and every derivative computed from it is
short by whatever it contributed.

Measured on ``abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_strain.f``,
whose converted source contains

    detF2d = REAL(+DFGRD1_OTI(1,1)*DFGRD1_OTI(2,2) - DFGRD1_OTI(1,2)*...)

and then divides the stress by ``detF2d``. The primal history agrees with the
original to the last bit -- the VALUE is right -- and the tangent comes back
nearly diagonal and three orders of magnitude small, flat across every step
size of the finite difference. A flat error across five decades of step is not
a convergence failure; it is a different function.

Not every cast is a defect. ``GSHEAR = REAL(PROPS_OTI(1)/2/(1+PROPS_OTI(2)))``
throws away derivatives that were never there: PROPS carries no seed when the
tangent is what is being computed, so its shadow is a real number wearing a
hypercomplex type. What makes a cast a defect is that its argument depends,
through some chain of assignments, on a variable the transform SEEDED -- and
that is what this module traces.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

#: The transform's own writeback: taking the real part of these is the point.
SANCTIONED = frozenset({
    "STRESS", "STATEV", "DDSDDE", "SSE", "SPD", "SCD", "RPL", "PNEWDT",
    "DDSDDT", "DRPLDE", "DRPLDT",
})

#: A seed being planted: ``DSTRAN_OTI(3) = DSTRAN_OTI(3) + OTI_E3`` or
#: ``DFGRD1_OTI(1,2) = DFGRD1_OTI(1,2) + 0.5D0*OTI_E4``.
_SEEDING = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*\([^)]*\)\s*=.*?\+\s*(?:[\d.DdEe+-]+\s*\*\s*)?"
    r"(?:OTI_)?E\d+\b", re.IGNORECASE)

#: Any assignment, with the name being assigned to.
_ASSIGNMENT = re.compile(r"^\s*(?:\d+\s+)?([A-Za-z_]\w*)\s*(?:\([^=]*\))?\s*=(?!=)")

#: A REAL(...) cast, and what it is assigned to.
_CAST = re.compile(r"^\s*(?:\d+\s+)?([A-Za-z_]\w*)\s*(?:\([^=]*\))?\s*=\s*"
                   r"(?:REAL|DBLE)\s*\(", re.IGNORECASE)

_NAME = re.compile(r"[A-Za-z_]\w*")


@dataclass(frozen=True)
class Truncation:
    """One place a derivative was dropped and the result used again."""

    line: int
    target: str
    text: str
    #: Which seeded quantity the discarded derivative descended from.
    depends_on: tuple = ()


@dataclass
class Finding:
    """What the converted source drops, and what was seeded in the first place."""

    seeded: tuple = ()
    truncations: tuple = ()
    #: Casts whose argument carries no seed. Recorded, not reported as defects.
    harmless: int = 0

    @property
    def drops_a_derivative(self) -> bool:
        return bool(self.truncations)

    def as_dict(self) -> dict:
        return {"seeded": list(self.seeded), "harmless_casts": self.harmless,
                "truncations": [{"line": t.line, "target": t.target,
                                 "text": t.text,
                                 "depends_on": list(t.depends_on)}
                                for t in self.truncations]}

    def reason(self) -> str:
        if not self.truncations:
            return ("no assignment on the stress path takes the real part of "
                    "an expression that carries a seed")
        first = self.truncations[0]
        return (
            f"the converted source drops the derivative at {len(self.truncations)} "
            f"assignment(s) and then uses the result: line {first.line}, "
            f"`{first.text}`, takes the real part of an expression descended "
            f"from {', '.join(first.depends_on) or 'a seeded variable'}. From "
            f"there the quantity behaves like a constant, so the stress is "
            f"still right and every derivative computed through it is short by "
            f"whatever it contributed")


#: A one-line logical IF and the statement it guards. ``_ASSIGNMENT`` and
#: ``_CAST`` both take a name, an optional parenthesised subscript and an
#: ``=``, and ``[^=]*`` is greedy enough to swallow ``(NSHR .GE. 1) SOUT(4)``
#: whole as the subscript -- so ``IF (NSHR .GE. 1) SOUT(4) = REAL(SIGMA(1,2))``
#: read as an assignment to a variable called IF, and a truncation written
#: that way was neither traced nor reported. Splitting the guard off is what
#: the emitters do for the same reason.
_INLINE_IF = re.compile(r"^(\s*(?:\d+\s+)?(?:ELSE\s*)?IF\s*)\(", re.IGNORECASE)


def _without_the_inline_if_guard(line: str) -> str:
    """``IF (cond) stmt`` reduced to ``stmt``; any other line unchanged.

    A block ``IF (cond) THEN`` reduces to " THEN", which matches no assignment
    and so needs no separate test.
    """
    match = _INLINE_IF.match(line)
    if not match:
        return line
    depth = 0
    for index in range(match.end() - 1, len(line)):
        if line[index] == "(":
            depth += 1
        elif line[index] == ")":
            depth -= 1
            if depth == 0:
                return line[index + 1:]
    return line


def _code_lines(text: str) -> Iterable[tuple]:
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped[0] == "!" or line[0] in "cC*":
            continue
        yield number, _without_the_inline_if_guard(line.split("!")[0])


def _names(text: str) -> set:
    return {name.upper() for name in _NAME.findall(text)}


def analyse(converted: str) -> Finding:
    """Trace the seed through the converted source and find where it is cut.

    The dependency walk is textual and deliberately over-broad: any assignment
    whose right-hand side mentions a tainted name taints its target. It will
    call a quantity seed-dependent that a data-flow analysis would not, which
    is the right way round -- the cost is a false report on a source whose
    tangent is fine, and the cost of the other mistake is a wrong tangent
    reported as verified.
    """
    lines = list(_code_lines(converted))
    tainted: set = set()
    for _number, line in lines:
        found = _SEEDING.match(line)
        if found:
            tainted.add(found.group(1).upper())
    seeded = tuple(sorted(tainted))
    if not seeded:
        return Finding()

    # Fixpoint: an assignment whose right-hand side mentions a tainted name
    # taints its target. A REAL() cast CUTS the taint -- that is the whole
    # point of it -- so its target is not tainted by this step.
    for _pass in range(6):
        grew = False
        for _number, line in lines:
            assigned = _ASSIGNMENT.match(line)
            if not assigned:
                continue
            target = assigned.group(1).upper()
            right = line.split("=", 1)[1]
            if _CAST.match(line):
                continue
            if target in tainted:
                continue
            if _names(right) & tainted:
                tainted.add(target)
                grew = True
        if not grew:
            break

    truncations: list = []
    harmless = 0
    read_later: dict = {}
    for index, (number, line) in enumerate(lines):
        cast = _CAST.match(line)
        if not cast:
            continue
        target = cast.group(1).upper()
        right = line.split("=", 1)[1]
        carried = sorted(_names(right) & tainted)
        if not carried:
            harmless += 1
            continue
        if target in SANCTIONED:
            continue
        # Used again? A value taken out of the hypercomplex domain and never
        # read is a diagnostic print, not a defect.
        used = any(target in _names(later)
                   for _n, later in lines[index + 1:index + 400])
        if not used:
            harmless += 1
            continue
        truncations.append(Truncation(number, target, line.strip()[:120],
                                      tuple(carried[:4])))
    return Finding(seeded=seeded, truncations=tuple(truncations),
                   harmless=harmless)

#: A line the transform commented out, with the original statement after the
#: marker. The emitters write both spellings; ``OTIS-SKIP:`` is the one that
#: carries a statement, the bare ``C`` re-comment carries a continuation.
_SKIPPED = re.compile(r"^[!Cc*]\s*OTIS-SKIP:\s*(.*)$")

#: A Fortran assignment's target name, allowing a leading statement label and
#: an array subscript.
_SKIP_TARGET = re.compile(r"^\s*(?:\d+\s+)?(?:\d+\s+)?([A-Za-z_]\w*)\s*"
                          r"(?:\([^=]*\))?\s*=(?!=)")


@dataclass(frozen=True)
class LiveSkip:
    """A variable a skipped region defined, which live code reads afterwards."""

    name: str
    defined_at: int
    read_at: int
    text: str


def skipped_definitions_read_later(converted: str) -> tuple:
    """Variables a "tangent helper" skip deleted that the stress path still reads.

    The transform classifies a region as a tangent helper when its outputs feed
    only the old DDSDDE block, and comments the region out. When such a region
    also DEFINES something the stress path reads afterwards, the reading code
    is left with whatever the declaration initialised -- zero -- and the
    converted routine returns a stress that is not the author's, silently, with
    no blocker and a clean compile.

    MEASURED on ``thealanjason__umat_finite_viscoelasticity/UMAT/
    VISC_OGDEN_1EL.for`` (store key fc2b59d324a69a9e922be039). Its
    transform_report records one skipped region, TANGENT-007, lines 249-338,
    with the reason "DDEVTAUDEPSE feeds only the old DDSDDE/tangent block".
    Those lines are the whole local Newton return map of the Maxwell branch,
    and they also define ``Je`` and ``DEVTAU``. Twenty lines later the stress
    path still reads both::

        PVTAU_OTI(I) = DEVTAU_OTI(I) + KVIS/TWO*(JE_OTI*JE_OTI-ONE)

    with ``JE_OTI`` and ``DEVTAU_OTI`` left at the 0.0D0 their declarations
    gave them. At ``F = I`` the original returns STRESS = 0 exactly and the
    converted build returns -30.6931 on all three direct components, which is
    ``-KVIS/2`` for that deck's ``KVIS = 61.3862`` to six figures: the
    ``(Je^2 - 1)`` term evaluated at ``Je = 0``. At the finite-strain state
    used elsewhere in this file the converted stress is 6.476e+00 wrong
    relative to the original, its DDSDDE has all three direct columns equal and
    column 4 identically zero, and the residual against a corrected reference
    is 6.7e-01, flat over six decades of step.

    The existing semantic checks do not catch it: they guard reads of DDSDDE
    after a disabled assignment, not reads of a skipped region's outputs. Every
    one of them passed on this file, and ``blockers`` and ``warnings`` are both
    empty.

    Over pass10's 254 store entries this fires on 25. None is among the 44
    verified. Three are ``primal_disagreed``, and all three of those are
    recorded as "N compared values are not finite", which is what dividing by a
    quantity left at zero produces; three more are ``transformed_job_failed``.
    It is silent on all eight sources whose tangents are confirmed in
    :mod:`umat_oti.validation.finite_strain_tangent`.

    Returns one :class:`LiveSkip` per (name, first live read). A name the
    skipped region only reads, or that live code re-defines before reading, is
    not reported.
    """
    lines = converted.splitlines()
    defined: dict[str, int] = {}
    for number, line in enumerate(lines, start=1):
        match = _SKIPPED.match(line)
        if not match:
            continue
        target = _SKIP_TARGET.match(match.group(1))
        if target:
            defined.setdefault(target.group(1).upper(), number)
    if not defined:
        return ()
    findings: list[LiveSkip] = []
    seen: set = set()
    for number, statement in _code_lines(converted):
        target = _SKIP_TARGET.match(statement)
        assigned = target.group(1).upper() if target else ""
        read_part = statement[target.end():] if target else statement
        for name in _names(read_part):
            base = name[:-4] if name.upper().endswith("_OTI") else name
            for candidate in (name, base):
                key = candidate.upper()
                if key in defined and key not in seen and number > defined[key]:
                    seen.add(key)
                    findings.append(LiveSkip(
                        name=candidate, defined_at=defined[key], read_at=number,
                        text=statement.strip()[:120]))
        if assigned:
            # Re-defined by live code before any read: the skip cost nothing.
            # The promoted shadow and the author's name are one variable, so
            # the match has to run BOTH ways -- the skipped line carries the
            # author's "Je" and the live line the emitted "JE_OTI". Stripping
            # only one direction leaves every re-definition unrecognised and
            # reports a name that live code had already replaced.
            bare = assigned[:-4] if assigned.endswith("_OTI") else assigned
            for key in {assigned, bare, bare + "_OTI"}:
                # Only an assignment AFTER the skipped one restores the value.
                # One before it is the declaration's initialiser -- the
                # "JE_OTI = 0.0D0" the transform emits for every promoted
                # variable -- and that is the zero the reading code goes on to
                # use. Popping on it hides exactly the case being looked for.
                if key in defined and key not in seen and number > defined[key]:
                    defined.pop(key, None)
    return tuple(findings)
