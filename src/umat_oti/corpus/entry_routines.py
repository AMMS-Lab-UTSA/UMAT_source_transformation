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

The second half of the module answers a different question about the same
files: when the TRANSFORMER refused a source, what was the source? A refusal
is a fact about this repository's transformer and about nothing else. It is
not evidence that the file is not a UMAT, it is not evidence that the file is
broken, and it is not evidence that anything is missing beside it. Each of
those is a separate claim needing its own evidence, and
:func:`classify_refusal` is where the evidence is combined -- the parsed entry
point, a digest match against another acquired source, an offline compile of
the author's own text, and the companion resolution. A refusal with none of
that evidence behind it stays :data:`GENUINE_UMAT`, which is the answer that
keeps the work in our column rather than moving it into the corpus's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
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

#: What an acquired source turned out to be, once the transformer had refused
#: it. These are answers about the FILE. "The transformer refused it" is not
#: one of them and can never become one: it is an answer about the
#: transformer, and the whole point of parsing the file is that the two
#: questions have different answers.
GENUINE_UMAT = "genuine_umat"
OTHER_ABAQUS_ROUTINE = "other_abaqus_routine"
HELPER_OR_MODULE_ONLY = "helper_or_module_only"
DUPLICATE_SOURCE = "duplicate_of_another_source"
INCOMPLETE_OR_CORRUPT = "incomplete_or_corrupt_source"
MISSING_EXTERNAL_DEPENDENCY = "missing_external_dependency"
REFUSAL_CLASSES: tuple[str, ...] = (
    GENUINE_UMAT,
    OTHER_ABAQUS_ROUTINE,
    HELPER_OR_MODULE_ONLY,
    DUPLICATE_SOURCE,
    INCOMPLETE_OR_CORRUPT,
    MISSING_EXTERNAL_DEPENDENCY,
)

#: The classes that say the work is this repository's. Kept as a set so a
#: caller can count "ours" without re-deriving the rule.
OURS: tuple[str, ...] = (GENUINE_UMAT,)

_UNIT = re.compile(
    r"^\s*(?:\d+\s+)?"
    r"(?:(?:RECURSIVE|PURE|ELEMENTAL|MODULE)\s+)*"
    r"(?:(?:DOUBLE\s+PRECISION|REAL|INTEGER|LOGICAL|CHARACTER|COMPLEX)"
    r"(?:\s*\*\s*\d+|\s*\([^)]*\))?\s+)?"
    r"(SUBROUTINE|FUNCTION)\s+([A-Za-z_]\w*)\s*(\((.*?)\))?\s*$",
    re.IGNORECASE)

_CALL = re.compile(r"\bCALL\s+([A-Za-z_]\w*)", re.IGNORECASE)

#: A main program. It is a program unit, it is never an Abaqus entry point,
#: and a file whose only unit is one is a driver somebody wrote to exercise a
#: UMAT that lives somewhere else. Recognised so that such a file quotes its
#: own first line as the evidence for "this is not a UMAT", rather than coming
#: out as ``no SUBROUTINE or FUNCTION was found`` -- a true sentence that reads
#: as though the file were unparseable.
_PROGRAM = re.compile(r"^\s*PROGRAM\s+([A-Za-z_]\w*)\s*$", re.IGNORECASE)
_END_PROGRAM = re.compile(r"^\s*END\s*PROGRAM(?:\s+[A-Za-z_]\w*)?\s*$",
                          re.IGNORECASE)

#: The opening and closing of an INTERFACE block, including a named operator
#: or assignment interface and the ABSTRACT form.
#:
#: Everything between them is a DECLARATION of a routine defined elsewhere --
#: it has no body, and it is not a program unit of this file.
#: ``sas229__geomat/tests/umat_integration.f90`` is a ``program main`` that
#: declares a 37-argument ``subroutine umat`` in an interface block at line 7
#: so that it can CALL it; the routine itself is in a C++ library this
#: repository does not publish as Fortran. Read without this rule, that
#: declaration matched the UMAT interface exactly, the file was classified as
#: a genuine UMAT, and a test driver with no constitutive code in it sat in
#: the count of UMATs this project had failed to convert.
_INTERFACE = re.compile(
    r"^\s*(?:ABSTRACT\s+)?INTERFACE\s*"
    r"(?:[A-Za-z_]\w*|OPERATOR\s*\(.*?\)|ASSIGNMENT\s*\(\s*=\s*\))?\s*$",
    re.IGNORECASE)
_END_INTERFACE = re.compile(r"^\s*END\s*INTERFACE(?:\s+.*)?$", re.IGNORECASE)
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
        if self.kind == "PROGRAM":
            return None
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
    #: The form the units were read under. Recorded because it is a decision
    #: this module made and not a property of the file, and because reading a
    #: free-form file as fixed form finds no arguments at all.
    source_form: str = ""
    #: The line of the author's own file that the entry point was read from,
    #: verbatim. A classification that cannot be checked against the source it
    #: came from is an assertion, so every record carries the line back.
    entry_text: str = ""

    @property
    def is_umat(self) -> bool:
        return self.kind == UMAT

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "entry_routine": self.entry_routine,
            "entry_interface": self.entry_interface,
            "entry_line": self.entry_line,
            "source_form": self.source_form,
            "entry_text": self.entry_text,
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
    #: How many INTERFACE blocks deep the reader is. A header inside one is a
    #: declaration of somebody else's routine, not a unit of this file.
    interface_depth = 0

    for logical in logical_lines_from_text(source, form):
        text = getattr(logical, "text", str(logical))
        numbers = getattr(logical, "line_numbers", ()) or ()
        number = numbers[0] if numbers else 0
        if _END_INTERFACE.match(text):
            interface_depth = max(0, interface_depth - 1)
            continue
        if _INTERFACE.match(text):
            interface_depth += 1
            continue
        if interface_depth:
            continue
        main = _PROGRAM.match(text)
        if main:
            current = ProgramUnit(name=main.group(1), kind="PROGRAM",
                                  line=number)
            units.append(current)
            by_name.setdefault(main.group(1).upper(), current)
            continue
        if _END_PROGRAM.match(text):
            current = None
            continue
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
    interface_depth = 0
    for logical in logical_lines_from_text(source, form):
        text = getattr(logical, "text", str(logical))
        if _END_INTERFACE.match(text):
            interface_depth = max(0, interface_depth - 1)
            continue
        if _INTERFACE.match(text):
            interface_depth += 1
            continue
        if interface_depth:
            continue
        main = _PROGRAM.match(text)
        if main:
            current = main.group(1).upper()
            continue
        if _END_PROGRAM.match(text):
            current = ""
            continue
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

    The form is retried. Four corpus sources under
    ``sahmotaman__TMM-FE-Simulation`` are free-form Fortran in files named
    ``.for``, and the form detector -- which sees both free and fixed evidence
    and falls back to the suffix -- reads them as fixed. Read as fixed, the
    37-argument ``subroutine umat(sigma, sv, C, ... &`` header loses its whole
    continued argument list and comes out as ``UMAT`` with ZERO arguments,
    which fails the interface check and lands four genuine Abaqus UMATs in
    ``helper_only``. That is the exact error this module exists to prevent,
    pointed the other way, so when the first form finds no Abaqus interface at
    all the other form is tried and the reading that finds one wins. It can
    only ever promote a file from "no Abaqus entry point" to a named one: a
    file that already matched an interface is never re-read.
    """
    found = _classify_one_form(source, form, path)
    if found.kind in (HELPER_ONLY, NO_PROGRAM_UNIT) and not form:
        other = "free" if found.source_form == "fixed" else "fixed"
        retry = _classify_one_form(source, other, path)
        if retry.kind in (UMAT, OTHER_ABAQUS_ENTRY):
            return replace(retry, reason=(
                f"{retry.reason}; read as {other} form -- as "
                f"{found.source_form} form this file matches no Abaqus "
                f"interface, which is a property of the reading and not of "
                f"the file"))
    return found


def _classify_one_form(source: str, form: str,
                       path: Optional[Path] = None) -> Classification:
    """One reading of the file, under one source form."""
    units = program_units(source, form, path)
    used = form or (detect_source_form(path, source) if path is not None
                    else detect_form_from_text(source))
    if not units:
        return Classification(kind=NO_PROGRAM_UNIT, source_form=used,
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
        # A file with no Abaqus entry point still gets a line quoted: the unit
        # that shares an Abaqus name but not its interface where there is one,
        # and otherwise the file's first program unit. A verdict of "this is
        # not an Abaqus routine" that quotes nothing is an assertion, and the
        # reader has no way to check it without opening the file themselves.
        witness = next((u for u in units if u.name.upper() in INTERFACES),
                       units[0])
        return Classification(kind=HELPER_ONLY, reason=reason,
                              source_form=used, units=tuple(units),
                              entry_line=witness.line,
                              entry_text=source_line(source, witness.line))

    # An entry point is one nothing in this file calls.
    entries = [(unit, name) for unit, name in abaqus if not unit.called_by]
    if not entries:
        entries = abaqus

    umats = [(unit, name) for unit, name in entries if name == "UMAT"]
    if umats:
        unit, name = umats[0]
        return Classification(
            kind=UMAT, entry_routine=unit.name, entry_interface=name,
            entry_line=unit.line, units=tuple(units), source_form=used,
            entry_text=source_line(source, unit.line),
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
        entry_line=unit.line, units=tuple(units), source_form=used,
        entry_text=source_line(source, unit.line),
        abaqus_entries=tuple(others),
        reason=(f"this file's Abaqus entry point is SUBROUTINE {unit.name} "
                f"({name}, {unit.argument_count} arguments) at line "
                f"{unit.line}{callee_note}"))


def source_line(source: str, number: int) -> str:
    """One physical line of the author's file, verbatim.

    The evidence for a classification is the line it was read from. Quoting it
    is what lets a reader disagree with the verdict without re-running
    anything, and what stops a classification becoming a bare assertion.
    """
    if number <= 0:
        return ""
    lines = source.splitlines()
    if number > len(lines):
        return ""
    return lines[number - 1].strip()[:300]


@dataclass(frozen=True)
class RefusalVerdict:
    """What a source the transformer refused turned out to be.

    ``evidence`` is the parsed entry-point line where there is one, or the
    line of the file that settled the question where there is not. ``basis``
    names which piece of evidence decided it, so a reader can tell a verdict
    that came from the compiler apart from one that came from the parser.
    """

    refusal_class: str
    entry_interface: str = ""
    entry_routine: str = ""
    entry_line: int = 0
    evidence: str = ""
    basis: str = ""
    confident: bool = True
    duplicate_of: str = ""
    missing_externals: tuple[str, ...] = ()
    #: What the file is on its own, before duplication was considered. A
    #: second copy of a UEL is still a UEL; a second copy of a UMAT is still a
    #: UMAT. Collapsing that into "duplicate" would lose the only fact that
    #: decides whether the pair belongs in a count of UMATs.
    underlying_class: str = ""

    @property
    def is_umat(self) -> bool:
        """Whether the FILE presents a UMAT, whatever became of the transform.

        A duplicate of a UMAT is still a UMAT and a UMAT that does not build
        is still a UMAT; neither is ``not_a_umat``. Only the two classes that
        say the file's Abaqus entry point is something else, or that it has
        none at all, answer this question with "no".
        """
        return (self.underlying_class or self.refusal_class) not in (
            OTHER_ABAQUS_ROUTINE, HELPER_OR_MODULE_ONLY)

    def as_dict(self) -> dict:
        return {"refusal_class": self.refusal_class,
                "underlying_class": self.underlying_class or self.refusal_class,
                "entry_interface": self.entry_interface,
                "entry_routine": self.entry_routine,
                "entry_line": self.entry_line,
                "evidence": self.evidence,
                "basis": self.basis,
                "confident": self.confident,
                "is_umat": self.is_umat,
                "duplicate_of": self.duplicate_of,
                "missing_externals": list(self.missing_externals)}


def classify_refusal(found: Classification, *,
                     duplicate_of: str = "",
                     missing_externals: tuple = (),
                     text_rejected: Optional[bool] = None,
                     compiler_evidence: str = "") -> RefusalVerdict:
    """What a refused source is, from evidence about the source.

    THE TRANSFORMER'S REFUSAL IS NOT AN INPUT HERE, and that is deliberate. A
    refusal says the transformer could not convert the file. It does not say
    the file is not a UMAT, that the file is broken, or that something is
    missing beside it -- those are three different claims about somebody
    else's repository, and each needs its own evidence before it may be made.
    Reading a refusal as any of them moves work out of this project's column
    and into the corpus's, which is the one direction the error must never go.

    The evidence is weighed in this order, each rung answering a question the
    ones below it cannot:

    1. **Is this file even a distinct member of the corpus?** A byte- or
       line-identical copy of another acquired source is one source counted
       twice, and every later question about it has already been answered.
    2. **What does this file present to Abaqus?** Settled by parsing. A UEL, a
       VUMAT or a UMATHT was never this transformer's to convert, and a file
       with no Abaqus entry point at all is a helper or a module.
    3. **Does the author's own text build?** Only asked of files that do
       present a UMAT, and only believed when the compiler rejected the TEXT
       -- a file that fails because a module was never published beside it is
       the next question's answer, not this one's.
    4. **Was everything it needs published?** An unresolved USE or INCLUDE.
    5. **Everything else is ours.** A UMAT, whole, with its companions, that
       this transformer could not convert.

    ``text_rejected`` being ``None`` means the compile did not settle it, and
    an unsettled compile leaves the verdict at :data:`GENUINE_UMAT` with
    ``confident`` false. That is the safe direction: it overstates this
    project's own unfinished work rather than the corpus's incompleteness.
    """
    base = _file_verdict(found, missing_externals, text_rejected,
                         compiler_evidence)
    if not duplicate_of:
        return base
    return replace(
        base, refusal_class=DUPLICATE_SOURCE, duplicate_of=duplicate_of,
        underlying_class=base.refusal_class,
        basis=(f"line-for-line identical to {duplicate_of}, which carries the "
               f"same answer; as a file it is {base.refusal_class}: "
               f"{base.basis}")[:600])


def _file_verdict(found: Classification, missing_externals: tuple,
                  text_rejected: Optional[bool],
                  compiler_evidence: str) -> RefusalVerdict:
    """What the file is, considered on its own."""
    missing = tuple(str(name) for name in missing_externals if str(name))

    if found.kind == OTHER_ABAQUS_ENTRY:
        return RefusalVerdict(
            OTHER_ABAQUS_ROUTINE, entry_interface=found.entry_interface,
            entry_routine=found.entry_routine, entry_line=found.entry_line,
            evidence=found.entry_text, basis=found.reason[:400])

    if found.kind in (HELPER_ONLY, NO_PROGRAM_UNIT):
        # A file whose text the compiler rejects may parse as nothing, and
        # "nothing" is then a symptom of the damage rather than a statement
        # that the author published a helper. But only where the compiler was
        # given everything: ``mrkearden__abaqus_umat/PlasticSolve.F90`` is an
        # Elmer solver module -- no Abaqus interface, settled by parsing -- and
        # the one diagnostic against it is a ``CONTIG`` that Elmer's own build
        # defines on the command line. Reading that as a corrupt file would
        # have made a claim about somebody's repository out of a gap in this
        # probe's build environment.
        if text_rejected and not missing:
            return RefusalVerdict(
                INCOMPLETE_OR_CORRUPT, evidence=compiler_evidence,
                basis=("this file matches no Abaqus interface AND its "
                       "published text is rejected by the compiler with "
                       "everything it needs present: " + found.reason[:200]))
        return RefusalVerdict(
            HELPER_OR_MODULE_ONLY, evidence=found.entry_text,
            entry_line=found.entry_line, missing_externals=missing,
            basis=found.reason[:400])

    if missing:
        return RefusalVerdict(
            MISSING_EXTERNAL_DEPENDENCY, entry_interface=found.entry_interface,
            entry_routine=found.entry_routine, entry_line=found.entry_line,
            evidence=found.entry_text, missing_externals=missing,
            basis=("this file presents a UMAT but USEs or INCLUDEs what was "
                   "never published beside it: " + "; ".join(missing[:6])))

    if text_rejected:
        return RefusalVerdict(
            INCOMPLETE_OR_CORRUPT, entry_interface=found.entry_interface,
            entry_routine=found.entry_routine, entry_line=found.entry_line,
            evidence=compiler_evidence or found.entry_text,
            basis="the author's own text is rejected by the compiler")

    return RefusalVerdict(
        GENUINE_UMAT, entry_interface=found.entry_interface,
        entry_routine=found.entry_routine, entry_line=found.entry_line,
        evidence=found.entry_text, confident=text_rejected is False,
        basis=(found.reason[:400] if text_rejected is False else
               (found.reason[:300] + "; the offline compile did not settle "
                "whether the published text builds, so the refusal stays "
                "this project's")))
