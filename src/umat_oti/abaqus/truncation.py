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


def _code_lines(text: str) -> Iterable[tuple]:
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped[0] == "!" or line[0] in "cC*":
            continue
        yield number, line.split("!")[0]


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
