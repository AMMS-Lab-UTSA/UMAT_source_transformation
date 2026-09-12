"""A body force is a loading, and some UMATs have no other.

A prescribed-displacement deck asks a material what stress a strain history
produces. That is the right question for almost every UMAT in the corpus and
the wrong one for a family of them: a plate growing under its own weight is
driven by a force per unit volume that a ``SUBROUTINE DLOAD`` in the same
file computes, and the UMAT reads what DLOAD wrote through a COMMON block.
Prescribe every node's displacement and DLOAD is never called, the COMMON
holds whatever it held, and the routine returns values that are not numbers
at any amplitude the search can reach.

Measured on the twenty-two entries that came back as "both builds went
non-finite": every one carries a SUBROUTINE DLOAD beside its UMAT, and the
amplitude search had already established that the model produces no numbers
from 8e-07 to 1e-04 of strain before the fixed probe was run at 0.005.

Nothing here is invented. Which components carry the force, what reference
magnitude each takes and which face is held come from the author's own deck:

    *Dload
    Plate-1.WholeRegion, BXNU, 0.
    Plate-1.WholeRegion, BYNU, 1.
    *Boundary
    Plate-1.LeftEnd, 1, 1
    Plate-1.LeftEnd, 2, 2

A source that defines DLOAD but whose repository publishes no deck saying how
it is loaded is not given a body force this module made up; it keeps the
verdict the search gave it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

#: The body-force labels Abaqus routes to a user's DLOAD. The uniform forms
#: (BX, BY, BZ) take their magnitude from the deck and never call it.
NON_UNIFORM = ("BXNU", "BYNU", "BZNU")

_DLOAD_ROUTINE = re.compile(
    r"^\s*(?:\d+\s+)?SUBROUTINE\s+DLOAD\s*\(", re.IGNORECASE | re.MULTILINE)
_KEYWORD = re.compile(r"^\s*\*\s*([A-Za-z][A-Za-z0-9 _-]*)")


def defines_dload(source_text: str) -> bool:
    """Does this file carry the routine Abaqus calls for a non-uniform load?"""
    return bool(_DLOAD_ROUTINE.search(source_text or ""))


@dataclass(frozen=True)
class Loads:
    """What the author's deck says drives this model, and where it came from."""

    components: tuple[tuple[str, float], ...] = ()
    provenance: str = ""

    @property
    def found(self) -> bool:
        return bool(self.components)

    @property
    def driven(self) -> tuple[tuple[str, float], ...]:
        """The components with a non-zero reference magnitude."""
        return tuple((label, value) for label, value in self.components if value)

    def as_dict(self) -> dict:
        return {"components": [list(pair) for pair in self.components],
                "provenance": self.provenance}


def read_loads(deck: Path) -> Loads:
    """The ``*DLOAD`` block of a deck, as the author wrote it.

    Only the non-uniform labels are taken: a uniform BX takes its magnitude
    from the deck and never reaches the user's routine, so it says nothing
    about how this source is meant to be driven.
    """
    try:
        text = Path(deck).read_text(errors="replace")
    except OSError:
        return Loads()
    found: list[tuple[str, float]] = []
    inside = False
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            keyword = (_KEYWORD.match(line) or [None, ""])[1]
            inside = str(keyword).strip().upper().replace(" ", "") == "DLOAD"
            continue
        if not inside:
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 2:
            continue
        label = fields[1].upper()
        if label not in NON_UNIFORM:
            continue
        try:
            magnitude = float(fields[2]) if len(fields) > 2 else 1.0
        except ValueError:
            continue
        if not any(label == seen for seen, _ in found):
            found.append((label, magnitude))
    if not found:
        return Loads()
    return Loads(tuple(found),
                 provenance=f"{Path(deck).name}: *DLOAD "
                            + "; ".join(f"{label} {value:g}"
                                        for label, value in found))


def held_directions(deck: Path) -> tuple[int, ...]:
    """Which degrees of freedom the author's own deck holds.

    A body-force problem needs the rigid-body modes removed and nothing more:
    hold every degree of freedom and the force does no work and the model
    never deforms. The author's deck says which ones, and it is read rather
    than guessed -- ``LeftEnd, 1, 1`` and ``LeftEnd, 2, 2`` on a cantilever
    plate, plus ``WholeRegion, 3, 3`` for the plane-strain constraint.
    """
    try:
        text = Path(deck).read_text(errors="replace")
    except OSError:
        return ()
    held: list[int] = []
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            keyword = (_KEYWORD.match(line) or [None, ""])[1]
            inside = str(keyword).strip().upper().replace(" ", "") == "BOUNDARY"
            continue
        if not inside:
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 2:
            continue
        try:
            first = int(float(fields[1]))
        except ValueError:
            continue
        if 1 <= first <= 6 and first not in held:
            held.append(first)
    return tuple(sorted(held))


#: Node-set names that mean "the whole model" rather than "a support". A
#: constraint on all of them is a statement about the material's kinematics --
#: plane strain -- and one on a face is what holds the model up. Jeff97's
#: growth decks carry both in the same step::
#:
#:     *Boundary
#:     Plate-1.LeftEnd, 1, 1
#:     Plate-1.LeftEnd, 2, 2
#:     *Boundary
#:     Plate-1.WholeRegion, 3, 3
#:
#: and a single-element verification has to keep the second and drop the
#: first: the element is an interior one, not the clamped end.
_WHOLE = ("WHOLEREGION", "WHOLE", "ALL", "EVERYTHING", "MODEL", "DOMAIN",
          "REGION", "SET-ALL")


@dataclass(frozen=True)
class Restraints:
    """What the author's deck holds, separated by what the holding MEANS."""

    everywhere: tuple[int, ...] = ()
    supports: tuple[int, ...] = ()
    provenance: str = ""

    def as_dict(self) -> dict:
        return {"everywhere": list(self.everywhere),
                "supports": list(self.supports),
                "provenance": self.provenance}


def read_restraints(deck: Path) -> Restraints:
    """The author's boundary conditions, split into kinematics and support.

    A constraint applied to every node of the model is part of the problem the
    material is being asked about; a constraint on a face is what stops the
    model floating away. A single-element verification of an INTERIOR material
    point keeps the first and must not inherit the second, because clamping one
    face of a one-element model does not reproduce a cantilever -- it prevents
    the deformation the experiment exists to produce.
    """
    try:
        text = Path(deck).read_text(errors="replace")
    except OSError:
        return Restraints()
    everywhere: list[int] = []
    supports: list[int] = []
    where: list[str] = []
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            keyword = (_KEYWORD.match(line) or [None, ""])[1]
            inside = str(keyword).strip().upper().replace(" ", "") == "BOUNDARY"
            continue
        if not inside:
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 2:
            continue
        name = fields[0].upper().split(".")[-1]
        try:
            first = int(float(fields[1]))
            last = int(float(fields[2])) if len(fields) > 2 and fields[2] else first
        except ValueError:
            continue
        if not 1 <= first <= 6:
            continue
        target = everywhere if any(mark in name for mark in _WHOLE) else supports
        for dof in range(first, min(last, 6) + 1):
            if dof not in target:
                target.append(dof)
                where.append(f"{fields[0]} {dof}")
    if not (everywhere or supports):
        return Restraints()
    return Restraints(
        tuple(sorted(everywhere)), tuple(sorted(supports)),
        provenance=(f"{Path(deck).name}: *BOUNDARY " + "; ".join(where[:8])))
