"""Which Abaqus user subroutine a file actually implements.

A name is not a classification. ``detect_entry_routines`` matched
``SUBROUTINE UMAT`` anywhere in a file and returned an unordered set, so a
file whose Abaqus entry point is a 36-argument ``SUBROUTINE UEL`` -- with a
``SUBROUTINE UMAT`` beside it that the element calls as its own private
constitutive kernel -- read as a UMAT. Twenty-five such files were driven
through a ``*USER MATERIAL`` deck, Abaqus resolved the global symbol ``UMAT``
to the element's kernel, and the finite-difference reference then perturbed a
deformation gradient that kernel never reads: the difference came out
identically zero at every step size, and the row was recorded as a tangent
failure. Nothing about anyone's UMAT was tested.

So classification here rests on three things a filename cannot fake:

* the routine's **name**,
* its **exact dummy-argument count**, because the Abaqus interfaces are
  positional and fixed -- UMAT takes 37, UEL takes 36, UMATHT takes 22 -- and
  a routine that shares a name but not the count is somebody's own routine
  that happens to be called ``UMAT``,
* whether any **other unit in the same file calls it**, because a routine
  reached only through a sibling is that sibling's callee and not the file's
  entry point.

What this module does not do is decide whether a UMAT is any good. It decides
what interface a file presents to Abaqus, so that a result is attributed to
the right question -- and so a file that is not a UMAT never sits inside a
count of UMATs that verified.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from umat_oti.corpus import detect_source_form as detect_form_from_text
from umat_oti.fortran.parser import detect_source_form, logical_lines_from_text

#: Every Abaqus user subroutine this project can recognise, with the exact
#: number of dummy arguments its documented interface takes. The count is the
#: discriminator: several corpus files define a routine called UMAT that is
#: not the Abaqus UMAT, and the argument list is what says so.
INTERFACES: dict[str, tuple[int, ...]] = {
    # STRESS..KINC. Some sources predate JSTEP and take KSTEP as a scalar;
    # both spellings are 37 arguments.
    "UMAT": (37,),
    # RHS..PERIOD.
    "UEL": (36,),
    # The explicit-dynamics material interface. Block-based and completely
    # unlike UMAT: it is handed NBLOCK material points at once.
    "VUMAT": (33, 34),
    "VUEL": (33,),
    # Heat transfer material.
    "UMATHT": (22,),
    # Fully incompressible hyperelastic strain energy.
    "UHYPER": (21,),
    "UANISOHYPER_INV": (22,),
    "USDFLD": (25,),
    "UEXPAN": (16,),
    "UVARM": (25,),
    "UFIELD": (23,),
    "SDVINI": (8,),
    "UAMP": (16, 17),
    "DLOAD": (12,),
    "UTRACLOAD": (14,),
    "URDFIL": (5,),
    "DISP": (10,),
    "HETVAL": (12,),
    "USDFLD_ORIENT": (),
}

#: What a file is, once its units have been ranked.
UMAT = "umat"
OTHER_ABAQUS_ENTRY = "other_abaqus_entry"
HELPER_ONLY = "helper_only"
NO_PROGRAM_UNIT = "no_program_unit"

_UNIT = re.compile(
    r"^\s*(?:\d+\s+)?"
    r"(?:(?:RECURSIVE|PURE|ELEMENTAL|MODULE)\s+)*"
    r"(?:(?:DOUBLE\s+PRECISION|REAL|INTEGER|LOGICAL|CHARACTER|COMPLEX)"
    r"(?:\s*\*\s*\d+|\s*\([^)]*\))?\s+)?"
    r"(SUBROUTINE|FUNCTION)\s+([A-Za-z_]\w*)\s*(\((.*?)\))?\s*$",
    re.IGNORECASE)

_CALL = re.compile(r"\bCALL\s+([A-Za-z_]\w*)", re.IGNORECASE)
#: The end of a PROGRAM UNIT, and nothing else. Written as `END\s*$` or
#: `END SUBROUTINE [name]` / `END FUNCTION [name]`.
#:
#: It must NOT match `END IF`, `END DO`, `END SELECT` or `END WHERE`. A
#: pattern that allowed any trailing word treated every `END IF` as the end
#: of the subroutine, so a CALL after the first conditional was attributed to
#: no unit at all -- which is why the `CALL UMAT` inside a UEL was never seen
#: and the UEL's private kernel read as the file's entry point.
_END_UNIT = re.compile(r"^\s*END\s*(?:(SUBROUTINE|FUNCTION)(?:\s+[A-Za-z_]\w*)?)?\s*$",
                       re.IGNORECASE)


@dataclass
class ProgramUnit:
    """One SUBROUTINE or FUNCTION, with what its header declares."""

    name: str
    kind: str
    line: int
    arguments: tuple[str, ...] = ()
    called_by: set[str] = field(default_factory=set)

    @property
    def argument_count(self) -> int:
        return len(self.arguments)

    def matches_interface(self) -> Optional[str]:
        """The Abaqus interface this unit implements, by name AND count.

        A routine called UMAT with nine arguments is somebody's own routine
        that happens to share the name, and saying otherwise is how a UEL's
        private kernel came to be driven as a material.
        """
        counts = INTERFACES.get(self.name.upper())
        if counts is None:
            return None
        if counts and self.argument_count not in counts:
            return None
        return self.name.upper()


@dataclass
class Classification:
    """What a file presents to Abaqus, and why."""

    kind: str
    entry_routine: str = ""
    entry_interface: str = ""
    entry_line: int = 0
    reason: str = ""
    units: tuple[ProgramUnit, ...] = ()
    abaqus_entries: tuple[str, ...] = ()

    @property
    def is_umat(self) -> bool:
        return self.kind == UMAT

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "entry_routine": self.entry_routine,
            "entry_interface": self.entry_interface,
            "entry_line": self.entry_line,
            "reason": self.reason,
            "abaqus_entries": list(self.abaqus_entries),
            "units": [{"name": u.name, "kind": u.kind, "line": u.line,
                       "arguments": u.argument_count,
                       "called_by": sorted(u.called_by)} for u in self.units],
        }


def _arguments(text: Optional[str]) -> tuple[str, ...]:
    if not text or not text.strip():
        return ()
    return tuple(piece.strip().upper() for piece in text.split(",")
                 if piece.strip())


def program_units(source: str, form: str = "",
                  path: Optional[Path] = None) -> list[ProgramUnit]:
    """Every SUBROUTINE and FUNCTION in the file, and who calls whom.

    Works from logical lines, so a header split across continuations is one
    header and a continuation marker is never read as an argument.

    ``path`` decides the source form where the caller knows it, because the
    suffix is the strongest signal there is. Guessing a name instead gets it
    wrong in one direction or the other: a fixed-form guess read every
    free-form ``.f90`` as fixed and found no program unit at all in files that
    plainly declare one, and a free-form guess does the same to every ``.for``.
    With no path the form is read from the CONTENT -- column-1 comment
    markers, six blank columns before a statement -- which needs no guess.
    """
    if not form:
        form = (detect_source_form(path, source) if path is not None
                else detect_form_from_text(source))
    units: list[ProgramUnit] = []
    current: Optional[ProgramUnit] = None
    by_name: dict[str, ProgramUnit] = {}

    for logical in logical_lines_from_text(source, form):
        text = getattr(logical, "text", str(logical))
        numbers = getattr(logical, "line_numbers", ()) or ()
        number = numbers[0] if numbers else 0
        header = _UNIT.match(text)
        if header:
            kind = header.group(1).upper()
            name = header.group(2)
            current = ProgramUnit(name=name, kind=kind, line=number,
                                  arguments=_arguments(header.group(4)))
            units.append(current)
            by_name.setdefault(name.upper(), current)
            continue
        if _END_UNIT.match(text):
            current = None
            continue
        if current is not None:
            for call in _CALL.finditer(text):
                callee = call.group(1).upper()
                if callee != current.name.upper():
                    target = by_name.get(callee)
                    if target is not None:
                        target.called_by.add(current.name.upper())
    # A CALL can appear before its callee's own header, so who-calls-whom is
    # resolved in a second pass over the same logical lines rather than left
    # depending on the order the author happened to write the units in.
    _resolve_calls(source, form, {u.name.upper(): u for u in units})
    return units


def _resolve_calls(source: str, form: str,
                   by_name: dict[str, ProgramUnit]) -> None:
    """Who calls whom, independent of declaration order."""
    current = ""
    for logical in logical_lines_from_text(source, form):
        text = getattr(logical, "text", str(logical))
        header = _UNIT.match(text)
        if header:
            current = header.group(2).upper()
            continue
        if _END_UNIT.match(text):
            current = ""
            continue
        if not current:
            continue
        for call in _CALL.finditer(text):
            callee = call.group(1).upper()
            target = by_name.get(callee)
            if target is not None and callee != current:
                target.called_by.add(current)


def classify(source: str, form: str = "",
             path: Optional[Path] = None) -> Classification:
    """What Abaqus interface this file presents, decided by parsing it.

    The entry point is the Abaqus routine that no other unit in the same file
    calls. Where a file defines several, the one Abaqus would reach first for
    the deck this project generates decides how the file must be driven -- and
    a file whose entry point is a UEL is not a UMAT, however many routines
    called UMAT it contains.
    """
    units = program_units(source, form, path)
    if not units:
        return Classification(kind=NO_PROGRAM_UNIT,
                              reason="no SUBROUTINE or FUNCTION was found")

    abaqus = [(unit, unit.matches_interface()) for unit in units]
    abaqus = [(unit, name) for unit, name in abaqus if name]
    if not abaqus:
        named = sorted({u.name.upper() for u in units
                        if u.name.upper() in INTERFACES})
        reason = ("no unit matches an Abaqus user-subroutine interface")
        if named:
            counts = ", ".join(
                f"{u.name.upper()} takes {u.argument_count} arguments where "
                f"the interface takes {'/'.join(str(c) for c in INTERFACES[u.name.upper()])}"
                for u in units if u.name.upper() in named)
            reason = (f"a unit shares an Abaqus name but not its interface: "
                      f"{counts}")
        return Classification(kind=HELPER_ONLY, reason=reason,
                              units=tuple(units))

    # An entry point is one nothing in this file calls.
    entries = [(unit, name) for unit, name in abaqus if not unit.called_by]
    if not entries:
        entries = abaqus

    umats = [(unit, name) for unit, name in entries if name == "UMAT"]
    if umats:
        unit, name = umats[0]
        return Classification(
            kind=UMAT, entry_routine=unit.name, entry_interface=name,
            entry_line=unit.line, units=tuple(units),
            abaqus_entries=tuple(sorted({n for _, n in entries})),
            reason=(f"SUBROUTINE {unit.name} at line {unit.line} takes "
                    f"{unit.argument_count} arguments and is called by nothing "
                    f"else in this file"))

    unit, name = entries[0]
    others = sorted({n for _, n in entries})
    callee_note = ""
    umat_callees = [u for u, n in abaqus if n == "UMAT" and u.called_by]
    if umat_callees:
        called = umat_callees[0]
        callee_note = (f"; the SUBROUTINE {called.name} at line {called.line} "
                       f"is called by {', '.join(sorted(called.called_by))} "
                       f"and is that routine's own callee, not this file's "
                       f"entry point")
    return Classification(
        kind=OTHER_ABAQUS_ENTRY, entry_routine=unit.name, entry_interface=name,
        entry_line=unit.line, units=tuple(units),
        abaqus_entries=tuple(others),
        reason=(f"this file's Abaqus entry point is SUBROUTINE {unit.name} "
                f"({name}, {unit.argument_count} arguments) at line "
                f"{unit.line}{callee_note}"))
