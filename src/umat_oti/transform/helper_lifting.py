from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Sequence

from umat_oti.core.model import ParsedFortranSource, ParsedSubroutine
from umat_oti.core.roles import common_block_names
from umat_oti.fortran.literals import (
    mask_character_literals,
    mask_real_literals,
    unmask_character_literals,
    unmask_real_literals,
    without_real_literals,
)
from umat_oti.fortran.normalize import strip_inline_comment
from umat_oti.transform.complex_support import (
    COMPLEX_INTRINSIC_NAMES, REAL_OTI_INTRINSICS_ADDED, declared_complex_names,
    retype_lifted_complex, source_declares_complex)
from umat_oti.fortran.parser import (
    parse_entity,
    FUNCTION_HEADER_RE,
    parse_declaration_line,
    parse_function_subprograms,
    split_top_level,
)


class HelperLiftingError(ValueError):
    """Raised when a helper closure cannot be safely lifted to OTI."""


@dataclass(frozen=True)
class LiftedHelperSet:
    helper_names: tuple[str, ...]
    source: str


#: A subroutine header, prefixes and all. ``PURE`` and ``RECURSIVE`` are
#: ordinary in externally authored Fortran -- every one of the fourteen
#: routines in MohrCoulombAbaqus.for is written ``pure subroutine`` -- and a
#: prefix the pattern did not admit made the lifter refuse the routine with
#: "Cannot parse helper header", which reads as a limitation of the source.
#: The prefix is captured so it can be ACTED ON rather than just dropped: see
#: :data:`_UNLIFTABLE_PREFIXES`.
_HEADER_RE = re.compile(
    r"^\s*(?P<prefix>(?:(?:RECURSIVE|PURE|IMPURE|ELEMENTAL|NON_RECURSIVE|MODULE)\s+)*)"
    r"SUBROUTINE\s+([A-Z_][A-Z0-9_]*)\s*\((.*)\)\s*$",
    re.IGNORECASE)

#: Prefixes the lifted copy cannot simply drop.
#:
#: PURE and RECURSIVE can be: the lifted routine is regenerated with a header
#: of its own, it is called only from code this transform also emits, and
#: nothing it is called from is itself PURE, so a non-pure copy is accepted
#: everywhere the original was.
#:
#: ELEMENTAL cannot. An elemental routine is called with array actuals and
#: applied element by element, and a scalar copy of it called the same way is
#: a different program. Refusing by name is the honest answer; silently
#: dropping the keyword would compile and would rank as a shape mismatch or,
#: worse, would not.
_UNLIFTABLE_PREFIXES = ("ELEMENTAL",)
_CALL_RE = re.compile(r"\bCALL\s+([A-Z_][A-Z0-9_]*)\s*\(", re.IGNORECASE)
#: The same two patterns the parser uses, against stitched statement text.
_INTERFACE_OPEN_RE = re.compile(
    r"^\s*(?:ABSTRACT\s+)?INTERFACE\b"
    r"(?:\s*(?:\w+|OPERATOR\s*\(.*\)|ASSIGNMENT\s*\(\s*=\s*\)))?\s*$",
    re.IGNORECASE)
_INTERFACE_CLOSE_RE = re.compile(r"^\s*END\s*INTERFACE(\s+.*)?$", re.IGNORECASE)
_PARAMETER_RE = re.compile(r"^\s*PARAMETER\s*\((.*)\)\s*$", re.IGNORECASE)
_DIMENSION_RE = re.compile(r"^\s*DIMENSION\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_INTEGER_RE = re.compile(r"^\s*INTEGER(?:\s*\*\s*\d+|\s*\([^)]*\))?\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_REAL_RE = re.compile(r"^\s*(?:REAL(?:\s*\*\s*\d+|\s*\([^)]*\))?|DOUBLE\s+PRECISION)\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_CHARACTER_RE = re.compile(r"^\s*CHARACTER(?:\s*\*\s*\d+|\s*\([^)]*\))?\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_LOGICAL_RE = re.compile(r"^\s*LOGICAL(?:\s*\*\s*\d+|\s*\([^)]*\))?\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_DATA_RE = re.compile(r"^\s*DATA\s+(.*)$", re.IGNORECASE)
_EXTERNAL_RE = re.compile(r"^\s*EXTERNAL\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_COMMON_RE = re.compile(r"^\s*COMMON\b(.*)$", re.IGNORECASE)
_ASSIGNMENT_STATEMENT_RE = re.compile(r"^(?:\d+\s+)?[A-Za-z_]\w*\s*(?:\([^=]*\))?\s*=(?!=)")
_BINARY32_TARGET = re.compile(
    r"^\s*(?:IF\s*\(.*\)\s*)?([A-Za-z_]\w*)\s*(?:\([^=]*\))?\s*=(?!=)", re.IGNORECASE)
_SAVE_RE = re.compile(r"^\s*SAVE\b\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"\b([A-Z_][A-Z0-9_]*)\b", re.IGNORECASE)
_LHS_ASSIGN_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*(?:\([^=]*\))?\s*=", re.IGNORECASE)
_IF_RE = re.compile(r"^(\s*(?:\d+\s+)?(?:ELSE\s*)?IF\s*)\(", re.IGNORECASE)
#: Statements whose integers are statement labels, not values. Promoting a bare
#: integer to a real literal is right for ``X = 1`` and wrong for ``GO TO 1000``,
#: which became ``GO TO 1000.0D0`` and stopped the build with "Syntax error in
#: GOTO statement". No arithmetic appears in these statements -- a computed GO
#: TO's selector is an integer expression -- so the whole statement is left
#: alone rather than trying to tell a label from a value inside it.
_LABEL_REFERENCE_STATEMENT_RE = re.compile(r"^\s*(?:GO\s*TO|ASSIGN)\b", re.IGNORECASE)
#: A FORMAT statement, label and all. Its contents are edit descriptors and not
#: numbers: ``FORMAT(7(E24.8E3))`` holds no literal ``8E3`` to promote, and
#: promoting it emitted ``E24.8D3``, which gfortran rejects with "Period
#: required in format specifier D". No arithmetic can appear in a FORMAT
#: statement, so the whole statement is left exactly as the author wrote it.
_FORMAT_STATEMENT_RE = re.compile(r"^\s*(?:\d+\s+)?FORMAT\s*\(", re.IGNORECASE)
_TYPED_INTRINSIC_MAP = {
    "DABS": "ABS",
    "DACOS": "ACOS",
    "DASIN": "ASIN",
    "DATAN": "ATAN",
    "DATAN2": "ATAN2",
    "DCOS": "COS",
    "DCOSH": "COSH",
    "DEXP": "EXP",
    "DLOG": "LOG",
    "DLOG10": "LOG10",
    "DMAX1": "MAX",
    "DMIN1": "MIN",
    "DMOD": "MOD",
    "DSIGN": "SIGN",
    "DSIN": "SIN",
    "DSINH": "SINH",
    "DSQRT": "SQRT",
    "DTAN": "TAN",
    "DTANH": "TANH",
}
_TYPED_INTRINSIC_RE = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in sorted(_TYPED_INTRINSIC_MAP, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_KEYWORDS = {
    "AND",
    "CALL",
    "CONTINUE",
    "DO",
    "ELSE",
    "END",
    "EQ",
    "ENDIF",
    "EQV",
    "NEQV",
    # .TRUE. and .FALSE. are logical LITERALS, and the dotted form makes them
    # look like the dotted operators above. Without them here the tokeniser
    # read `FALSE` as an identifier, found it undeclared and not implicitly
    # integer, and filed it as an implicitly typed hypercomplex variable --
    # after which the RHS of `OK_FLAG = .FALSE.` "mentions an OTI name" and
    # got wrapped as REAL(.FALSE.), which ifort refuses. Five converted builds
    # failed to compile on it.
    "FALSE",
    "TRUE",
    "GE",
    "GO",
    "GOTO",
    "GT",
    "IF",
    "LE",
    "LT",
    "NE",
    "NOT",
    "OR",
    "RETURN",
    "THEN",
}
_INTRINSIC_NAMES = {
    "ABS",
    "ACOS",
    "ALL",
    "ANY",
    "ASIN",
    "ATAN",
    "ATAN2",
    "COS",
    "COSH",
    "DOT_PRODUCT",
    "EXP",
    "LOG",
    "LOG10",
    "MAX",
    "MIN",
    "MOD",
    "REAL",
    "SIGN",
    "SIN",
    "SINH",
    "SQRT",
    "TAN",
    "TANH",
}
#: Intrinsics whose result is not a real number of the argument's value --
#: LOGICAL, INTEGER or CHARACTER inquiries about an argument's presence, extent
#: or kind. Under ``IMPLICIT TYPE(ONUMM6N1) (A-H,O-Z)`` a bare ``PRESENT`` or
#: ``SIZE`` reads as an implicitly hypercomplex name, and the condition wrapper
#: wrote ``IF (REAL(present(Dinv)))``, which does not compile (MohrCoulombAbaqus).
#: Their arguments are not values either: ``PRESENT(REAL(Dinv))`` is no more
#: Fortran than the first, because PRESENT asks about the dummy itself.
_INQUIRY_INTRINSICS = frozenset({
    "PRESENT", "ALLOCATED", "ASSOCIATED", "SIZE", "SHAPE", "LBOUND", "UBOUND",
    "KIND", "LEN", "LEN_TRIM", "STORAGE_SIZE", "IS_CONTIGUOUS", "RANK",
    "SELECTED_REAL_KIND", "SELECTED_INT_KIND", "DIGITS", "EPSILON", "HUGE",
    "TINY", "PRECISION", "RANGE", "RADIX", "MAXEXPONENT", "MINEXPONENT",
})
_INQUIRY_CALL_RE = re.compile(
    r"\b(?:" + "|".join(sorted(_INQUIRY_INTRINSICS)) + r")\s*\(", re.IGNORECASE)
_IMPLICIT_INTEGER_FIRST_LETTERS = frozenset("IJKLMN")


def routines_by_name(parsed: ParsedFortranSource) -> dict[str, ParsedSubroutine]:
    """Every program unit the lifter can lift, keyed by upper-case name.

    Subroutines and function subprograms both. A UMAT is free to put part of its
    constitutive law in a FUNCTION, and a closure walk over CALL statements alone
    never reaches one: the lifted module then calls an unlifted external with OTI
    arguments and the build fails at link with an undefined reference.
    """
    units = {routine.upper_name: routine for routine in parsed.subroutines}
    for function in parse_function_subprograms(parsed.logical_lines):
        units.setdefault(function.upper_name, function)
    return units


def function_names(parsed: ParsedFortranSource) -> frozenset[str]:
    """Names this source defines as function subprograms."""
    return frozenset(f.upper_name for f in parse_function_subprograms(parsed.logical_lines))


#: Abaqus utility routines a UMAT may call that are not in its source.
_ABAQUS_UTILITIES = frozenset({
    "SPRINC", "SPRIND", "SINV", "ROTSIG", "XIT", "GETOUTDIR", "GETJOBNAME",
    "GETNUMCPUS", "GETPARTINFO", "STDB_ABQERR", "MUTEXINIT",
    "MUTEXLOCK", "MUTEXUNLOCK", "GETVRM"})
#: Routines a lifted body may call without lifting them, because nothing of
#: the differentiated computation passes through them: the solver's abort and
#: its job/thread queries, and Fortran's intrinsic subroutines for time, the
#: environment and program control. They are called exactly as the author
#: wrote them. An OTI value handed to one is still an error -- for an
#: intrinsic the compiler says so; the transform's leak check covers the rest.
PASS_THROUGH_CALLS = frozenset({
    "XIT", "GETOUTDIR", "GETJOBNAME", "GETNUMCPUS", "GETRANK", "GETPARTINFO",
    "MUTEXINIT", "MUTEXLOCK", "MUTEXUNLOCK", "GETNUMTHREADS", "GET_THREAD_ID",
    "CPU_TIME", "DATE_AND_TIME", "SYSTEM_CLOCK", "RANDOM_SEED", "EXIT", "ABORT",
    "FLUSH", "GET_COMMAND_ARGUMENT", "GET_ENVIRONMENT_VARIABLE", "GETENV",
    "SYSTEM", "EXECUTE_COMMAND_LINE", "SLEEP",
    # Vendor wall-clock and CPU-time library routines (Intel/Compaq DTIME,
    # ETIME, SECOND, CLOCK, ITIME, IDATE, TIMER): they return elapsed time to
    # the program, never a value that enters the constitutive response.
    "DTIME", "ETIME", "SECOND", "CLOCK", "ITIME", "IDATE", "TIMER",
    # The solver's message routines, under the rule the selected routine
    # already follows (source_transform.ABAQUS_UTILITY_ROUTINES): what they
    # consume is printed, never returned, so an OTI value reaching REALV can
    # misprint a message and cannot touch a derivative.
    "STDB_ABQERR", "STDB_ABQPRT"})
_LAPACK_NAME = re.compile(r"^[SDCZ](?:GE|SY|PO|GB|GT|TR|OR|SP|HE)[A-Z]{2,3}$")


def _what_an_undefined_routine_is(names) -> str:
    """One sentence saying what kind of routine is missing and what to do."""
    names = [str(n).upper() for n in names]
    utilities = [n for n in names if n in _ABAQUS_UTILITIES]
    lapack = [n for n in names if _LAPACK_NAME.match(n)]
    if utilities:
        return (f"{', '.join(utilities)} is an Abaqus utility routine, supplied "
                f"by the solver as object code, so there is no body to lift "
                f"and no OTI form of it yet. What to do: compute the same "
                f"quantity in Fortran in the source (an eigen/invariant "
                f"routine the transform can lift), or keep the call off the "
                f"differentiated path.")
    if lapack:
        return (f"{', '.join(lapack)} is a LAPACK routine, linked as a "
                f"library, so there is no body to lift. What to do: put a "
                f"Fortran source of it (reference LAPACK) beside the UMAT or "
                f"in dependency_roots, or replace it with an explicit small "
                f"solve the transform can lift.")
    return (f"What to do: put the file that defines {', '.join(names)} beside "
            f"the UMAT or name its directory in dependency_roots so the "
            f"definition can be lifted with the routine that calls it.")


def _first_call_line(source_lines: Sequence[str], callee: str) -> str:
    """" ({callee} is first called at line N.)" from the source text, or ""."""
    pattern = re.compile(rf"^\s*(?:\d+\s+)?CALL\s+{re.escape(callee)}\b", re.IGNORECASE)
    for number, line in enumerate(source_lines, start=1):
        if line[:1] not in "Cc*!" and pattern.search(line):
            return f" ({callee} is first called at line {number}.)"
    return ""


def _call_site(routine, callee: str) -> str:
    """" (line N)" where ``routine`` references ``callee``, or ""."""
    pattern = re.compile(rf"\b{re.escape(callee)}\b", re.IGNORECASE)
    for line in getattr(routine, "lines", ()) or ():
        if pattern.search(line.text) and line.line_numbers:
            return f" (called at line {line.line_numbers[0]})"
    return ""


def helper_lift_closure(
    parsed: ParsedFortranSource,
    helper_roots: Iterable[str],
    *,
    selected_umat: str,
) -> tuple[str, ...]:
    routines = {name: routine for name, routine in routines_by_name(parsed).items()
                if name != selected_umat.upper()}
    defined_functions = function_names(parsed)
    source_lines = parsed.text.splitlines()
    pending = [str(name).upper() for name in helper_roots if str(name).strip()]
    if not pending:
        return ()
    pending = [name for name in pending if name not in PASS_THROUGH_CALLS]
    if not pending:
        return ()
    missing = sorted({name for name in pending if name not in routines})
    if missing:
        raise HelperLiftingError(
            f"Helper lifting requires source definitions for {missing}. The completed JSON rewrites those calls, so pass-through is unsafe."
            f"{_first_call_line(source_lines, missing[0])}"
            f" {_what_an_undefined_routine_is(missing)}"
        )
    ordered: list[str] = []
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        ordered.append(current)
        routine = routines[current]
        for callee in _routine_callees(routine, parsed.form, source_lines,
                                       function_names=defined_functions):
            if callee == selected_umat.upper():
                # A lifted body is OTI-typed; the selected routine is not
                # rewritten to accept that. Letting the call through would
                # pass hypercomplex values to REAL dummy arguments across an
                # implicit interface, which no compiler checks and no test
                # here would notice -- it links, runs, and reads garbage.
                # Refusing is free: instrumenting this branch across all 71
                # discovered sources takes it zero times.
                raise HelperLiftingError(
                    f"Helper {current} calls back into {selected_umat.upper()}, "
                    "the routine being transformed. The lifted body is "
                    "OTI-typed and that routine is not, so the call would "
                    "pass hypercomplex values to REAL dummy arguments through "
                    "an implicit interface. Lifting is refused rather than "
                    "rewritten around."
                )
            if callee in _LIFTED_BODY_INLINED:
                # Trivial utility (e.g. KCLEAR) inlined directly in the lifted
                # body, so it needs no definition and is not lifted. Lets UMATs
                # that omit its definition (it resolves from a shared library at
                # Abaqus link time) still lift their helper closures.
                continue
            if callee in PASS_THROUGH_CALLS and callee not in routines:
                continue
            if callee not in routines:
                raise HelperLiftingError(
                    f"Helper lifting for {current} reached external or undefined callee {callee}"
                    f"{_call_site(routine, callee)}. Add lifting support for that dependency before rewriting the call through OTI."
                    f" {_what_an_undefined_routine_is([callee])}"
                )
            if callee not in seen:
                pending.append(callee)
    return tuple(ordered)



_LIFTED_HEADER_RE = re.compile(
    r"^\s*(?:subroutine|function)\s+([A-Za-z_]\w*)\s*\((.*)$", re.IGNORECASE)
_LIFTED_END_RE = re.compile(r"^\s*end\s+(?:subroutine|function)\b", re.IGNORECASE)
_LIFTED_CALL_RE = re.compile(r"^(\s*call\s+)([A-Za-z_]\w*)\s*\((.*)$", re.IGNORECASE)


def _stitched_free_form(lines: list[str], start: int) -> tuple[str, int]:
    """The logical statement beginning at ``start``, and the line after it."""
    text = lines[start].rstrip()
    index = start
    while text.endswith("&"):
        index += 1
        if index >= len(lines):
            break
        text = text[:-1].rstrip() + " " + lines[index].strip()
    return text, index + 1


def _emitted_routine_spans(lines: list[str]) -> list[tuple[int, int, str, list[str]]]:
    """(first line, last line, name, dummy names) for each emitted routine."""
    spans: list[tuple[int, int, str, list[str]]] = []
    index = 0
    while index < len(lines):
        header = _LIFTED_HEADER_RE.match(lines[index])
        if not header:
            index += 1
            continue
        statement, after = _stitched_free_form(lines, index)
        match = _LIFTED_HEADER_RE.match(statement)
        name = match.group(1).upper()
        inside = match.group(2)
        close = _matching_paren_index("(" + inside, 0)
        arguments = [a.strip().upper() for a in
                     split_top_level(inside[:close - 1] if close > 0 else inside)
                     if a.strip()]
        end = after
        while end < len(lines) and not _LIFTED_END_RE.match(lines[end]):
            end += 1
        spans.append((index, min(end, len(lines) - 1), name, arguments))
        index = end + 1
    return spans


def _declared_types_in_span(lines: list[str], first: int, last: int,
                            type_name: str) -> tuple[set[str], set[str]]:
    """Names the span declares as the OTI type, and names it declares REAL."""
    oti: set[str] = set()
    real_constants: set[str] = set()
    pattern_oti = re.compile(rf"^\s*type\s*\(\s*{re.escape(type_name)}\s*\)\s*(?:,[^:]*)?::\s*(.+)$",
                             re.IGNORECASE)
    pattern_real = re.compile(r"^\s*real\s*\([^)]*\)\s*,\s*parameter\s*::\s*(.+)$",
                              re.IGNORECASE)
    for index in range(first, last + 1):
        statement, _ = _stitched_free_form(lines, index)
        found = pattern_oti.match(statement)
        if found:
            oti.update(_declared_names(found.group(1)))
            continue
        found = pattern_real.match(statement)
        if found:
            real_constants.update(_declared_names(found.group(1)))
    return oti, real_constants


def reconcile_helper_argument_types(body: str, type_name: str) -> str:
    """Make every lifted helper's call to another agree about argument types.

    Each routine is lifted on its own, so the two ends of a call between them
    are decided independently and can disagree. A PARAMETER stays REAL where
    it is declared -- real times hypercomplex is an overload the module has --
    but the callee that receives it has no declaration of its own and takes
    the body's ``implicit type(OTI) (a-h,o-z)``. One viscoplastic UMAT's
    helpers do this twice: a ``real(8), parameter`` tolerance is passed to a
    dummy the callee declares as the hypercomplex type, and the
    callee reads 96 doubles where 1 was written. gfortran says only
    "-Wargument-mismatch" and the program aborts inside free().

    A constant carries no derivative, so promoting a copy of it is exact. The
    copy is what gets passed; the constant keeps its own type for the
    arithmetic around it.

    Only constants are fixed this way. A REAL *variable* reaching an OTI dummy
    may be one the callee writes back through, and a promoted copy would
    silently drop that write, so it is raised instead of patched.
    """
    lines = body.splitlines()
    spans = _emitted_routine_spans(lines)
    if not spans:
        return body
    oti_dummies: dict[str, list[bool]] = {}
    for first, last, name, arguments in spans:
        declared_oti, _ = _declared_types_in_span(lines, first, last, type_name)
        oti_dummies[name] = [
            (argument in declared_oti) or
            (argument not in declared_oti and not _is_implicit_integer_name(argument))
            for argument in arguments
        ]
    edits: dict[int, str] = {}
    promotions: dict[int, set[str]] = {}
    for first, last, name, _arguments in spans:
        _declared_oti, constants = _declared_types_in_span(lines, first, last, type_name)
        if not constants:
            continue
        index = first
        while index <= last:
            call = _LIFTED_CALL_RE.match(lines[index])
            if not call:
                index += 1
                continue
            statement, after = _stitched_free_form(lines, index)
            call = _LIFTED_CALL_RE.match(statement)
            callee = call.group(2).upper()
            expected = oti_dummies.get(callee)
            if not expected:
                index = after
                continue
            close = _matching_paren_index("(" + call.group(3), 0)
            inner = call.group(3)[:close - 1] if close > 0 else call.group(3)
            actuals = [a.strip() for a in split_top_level(inner)]
            changed = False
            for position, actual in enumerate(actuals):
                if position >= len(expected) or not expected[position]:
                    continue
                if actual.upper() not in constants:
                    continue
                actuals[position] = f"OTI_CONST_{actual.upper()}"
                promotions.setdefault(first, set()).add(actual.upper())
                changed = True
            if changed:
                for line_number in range(index, after):
                    edits[line_number] = ""
                # The copy is set immediately before the call, which is always
                # in the executable part -- a declaration cannot initialise a
                # derived type from a REAL constant, and an assignment placed
                # among the declarations is not Fortran.
                indent = call.group(1)[:len(call.group(1)) - len(call.group(1).lstrip())]
                setters = "\n".join(
                    f"{indent}OTI_CONST_{actual.upper()} = {actual}"
                    for actual in sorted(promotions.get(first, set())))
                edits[index] = (setters + "\n" if setters else "") + \
                    f"{call.group(1)}{call.group(2)}({', '.join(actuals)})"
            index = after
    if not promotions:
        return body
    output: list[str] = []
    for number, line in enumerate(lines):
        if number in edits:
            if edits[number]:
                output.append(edits[number])
            continue
        output.append(line)
    # The copy is declared and set once, right after the routine's IMPLICIT
    # lines, so it is in scope and has its value before any call can use it.
    result: list[str] = []
    current_span = None
    pending: set[str] = set()
    for number, line in enumerate(output):
        if number in promotions:
            current_span = number
            pending = set(promotions[number])
        result.append(line)
        if pending and re.match(r"^\s*implicit\s+integer", line, re.IGNORECASE):
            for constant in sorted(pending):
                result.append(f"    type({type_name}) :: OTI_CONST_{constant}")
            pending = set()
    return "\n".join(result) + ("\n" if body.endswith("\n") else "")


def lift_helper_set_source(
    parsed: ParsedFortranSource,
    helper_names: Iterable[str],
    *,
    module_name: str,
    type_name: str,
    helper_output_copies: dict[str, list[dict[str, Any]]] | None = None,
    helper_output_surfaces: dict[str, list[dict[str, Any]]] | None = None,
) -> LiftedHelperSet:
    routines = routines_by_name(parsed)
    source_lines = parsed.text.splitlines()
    ordered = tuple(dict.fromkeys(str(name).upper() for name in helper_names if str(name).strip()))
    missing = [name for name in ordered if name not in routines]
    if missing:
        raise HelperLiftingError(f"Helper lifting could not find parsed routines for {missing}.")
    lifted_set = set(ordered)
    lifted_functions = set(ordered) & set(function_names(parsed))
    _refuse_calls_that_need_an_explicit_interface(parsed, routines, lifted_set)
    host_constants = host_constants_for_internal_procedures(parsed)
    hosts = internal_procedure_hosts(parsed)
    body = "\n\n".join(
        _lift_helper_routine(
            routines[name],
            parsed.form,
            source_lines,
            lifted_set,
            module_name,
            type_name,
            source_path=parsed.path,
            lifted_function_names=lifted_functions,
            helper_output_copies=(helper_output_copies or {}).get(name, []),
            helper_output_surfaces=(helper_output_surfaces or {}).get(name, []),
            host_constants=host_constants.get(name, ()),
            typing_host=routines.get(hosts.get(name, "")),
        )
        for name in ordered
    )
    body = reconcile_helper_argument_types(body, type_name)
    # DOUBLE COMPLEX declarations become the complex OTI type (oti_complex);
    # unchanged, byte for byte, for a source that declares nothing complex.
    body = retype_lifted_complex(body, type_name, source_text=parsed.text, form=parsed.form)
    body = _nest_internal_procedures(body, internal_procedure_hosts(parsed))
    return LiftedHelperSet(helper_names=ordered, source=body + ("\n" if body else ""))


def _refuse_calls_that_need_an_explicit_interface(
        parsed: ParsedFortranSource, routines: dict[str, ParsedSubroutine],
        lifted: set[str]) -> None:
    """Refuse a call that omits an OPTIONAL argument of a lifted helper.

    The lifted helpers are external subprograms called through an implicit
    interface (an internal procedure is the exception; see
    _nest_internal_procedures). Omitting an optional argument, or passing one by
    keyword, needs an explicit interface; without it the callee's PRESENT() reads
    whatever is on the stack. The source may well have provided one -- an
    INTERFACE block for ``update`` -- but it describes the REAL routine, not
    UPDATE_OTI, so the transformed call has none. Refused, because the result
    compiles and then crashes or returns a wrong number.
    """
    hosts = internal_procedure_hosts(parsed)
    optional = {name for name in lifted if name in routines and name not in hosts and any(
        "optional" in (attribute.strip().lower() for attribute in declaration.attributes)
        for declaration in routines[name].declarations)}
    if not optional:
        return
    pattern = re.compile(r"\bCALL\s+(" + "|".join(sorted(optional)) + r")\s*\((.*)\)\s*$",
                         re.IGNORECASE)
    for line in parsed.logical_lines:
        match = pattern.search(mask_character_literals(line.text)[0])
        if not match:
            continue
        name = match.group(1).upper()
        actuals = [item for item in split_top_level(match.group(2)) if item.strip()]
        by_keyword = any(re.match(r"^\s*[A-Z_]\w*\s*=(?!=)", item, re.IGNORECASE) for item in actuals)
        if len(actuals) < len(routines[name].args) or by_keyword:
            raise HelperLiftingError(
                f"{name} has OPTIONAL dummy arguments and is called at line "
                f"{line.line_numbers[0]} with {len(actuals)} of its "
                f"{len(routines[name].args)} arguments"
                f"{' (some by keyword)' if by_keyword else ''}. That needs an "
                f"explicit interface, and the lifted {name}_OTI is an external "
                "subprogram with none (an INTERFACE block in the source describes "
                f"the REAL {name}). Not supported. What to do: pass every argument "
                f"of {name} positionally in that call.")


def internal_procedure_hosts(parsed: ParsedFortranSource) -> dict[str, str]:
    """Internal procedure name -> the routine that CONTAINS it."""
    source_lines = parsed.text.splitlines()
    units = routines_by_name(parsed)
    hosts: dict[str, str] = {}
    for host in parsed.subroutines:
        raw = _routine_source_lines(source_lines, host)
        contains_at = next((index for index, line in enumerate(raw[1:-1], start=1)
                            if _CONTAINS_RE.match(_statement_text(line, parsed.form))), None)
        if contains_at is None:
            continue
        first, last = host.lines[0].line_numbers[0], host.lines[-1].line_numbers[-1]
        for name, unit in units.items():
            start = unit.lines[0].line_numbers[0] if unit.lines else 0
            if name != host.upper_name and first + contains_at < start <= last:
                hosts[name] = host.upper_name
    return hosts


def _nest_internal_procedures(body: str, hosts: dict[str, str]) -> str:
    """Put each lifted internal procedure back inside its lifted host.

    The host was lifted without its CONTAINS section and each internal
    procedure on its own (see _without_internal_procedures). As an external
    subprogram it has only an implicit interface at the call, which is not
    enough for an assumed-shape dummy (GuGuaTT's RESID_NPT(npt_i, geom_params)
    with geom_params(:): "Explicit interface required"). Back after CONTAINS
    in the host, the call has the interface it had in the source.
    """
    if not hosts or not body:
        return body
    lines = body.split("\n")
    spans = _emitted_routine_spans(lines)
    by_name = {name: (first, last) for first, last, name, _ in spans}
    moved: dict[str, list[str]] = {}
    taken: set[int] = set()
    for internal, host in hosts.items():
        lifted, lifted_host = f"{internal}_OTI", f"{host}_OTI"
        if lifted not in by_name or lifted_host not in by_name:
            continue
        first, last = by_name[lifted]
        moved.setdefault(lifted_host, []).extend(lines[first:last + 1])
        taken.update(range(first, last + 1))
    if not moved:
        return body
    result: list[str] = []
    host_ends = {by_name[name][1]: name for name in moved}
    for index, line in enumerate(lines):
        if index in taken:
            continue
        if index in host_ends:
            result.append("contains")
            result.extend(moved[host_ends[index]])
        result.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(result))



#: Shapes the Abaqus UMAT interface fixes for its dummy arguments. A source is
#: free to omit a DIMENSION for an argument it never touches -- UMAT4COMSOL's
#: elastoplastic model declares most of them and leaves out COORDS and DROT --
#: and after lifting that argument becomes an implicitly typed scalar. The
#: driver then fails with "Rank mismatch in argument 'coords' (scalar and
#: rank-1)". The shape comes from the interface, not from the source.
UMAT_ARGUMENT_SHAPES: dict[str, str] = {
    "STRESS": "NTENS", "STATEV": "NSTATV", "DDSDDE": "NTENS,NTENS",
    "DDSDDT": "NTENS", "DRPLDE": "NTENS", "STRAN": "NTENS", "DSTRAN": "NTENS",
    "TIME": "2", "PREDEF": "1", "DPRED": "1", "PROPS": "NPROPS",
    "COORDS": "3", "DROT": "3,3", "DFGRD0": "3,3", "DFGRD1": "3,3",
}

def _routine_callees(
    routine: ParsedSubroutine,
    form: str,
    source_lines: list[str],
    *,
    function_names: Iterable[str] = (),
) -> tuple[str, ...]:
    """Program units this routine invokes: CALL targets and function references.

    ``function_names`` is the set of names the *source* defines as function
    subprograms. Only those are looked for, so a reference to something this
    source does not define -- an intrinsic, an Abaqus utility -- stays invisible
    exactly as before and cannot turn into a new "undefined callee" failure.
    """
    candidates = {str(name).upper() for name in function_names}
    candidates.discard(routine.upper_name)
    candidates -= {arg.upper() for arg in routine.args}
    seen: set[str] = set()
    ordered: list[str] = []
    statements = list(_continuation_stitch(_routine_source_lines(source_lines, routine), form))
    arrays = _routine_array_names(statements, form)
    for raw in statements:
        statement = _statement_text(raw, form)
        for match in _CALL_RE.finditer(statement):
            callee = match.group(1).upper()
            if callee not in seen:
                seen.add(callee)
                ordered.append(callee)
        for name in _referenced_function_names(statement, candidates - arrays):
            if name not in seen:
                seen.add(name)
                ordered.append(name)
    return tuple(ordered)


def _referenced_function_names(statement: str, candidates: set[str]) -> tuple[str, ...]:
    """Names from ``candidates`` used as ``NAME(`` in this statement."""
    if not candidates:
        return ()
    masked, _literals = mask_character_literals(statement)
    found = [name for name in candidates
             if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}\s*\(", masked, re.IGNORECASE)]
    return tuple(sorted(found))


def _routine_array_names(statements: Sequence[str], form: str) -> set[str]:
    """Names this routine declares *with a shape*.

    That is exactly what separates ``F(I)`` the array element from ``F(I)`` the
    function reference. A scalar type declaration is not disqualifying: declaring
    the type of an external function is the ordinary way to call one.
    """
    names: set[str] = set()
    for raw in statements[1:]:
        stripped = _statement_text(raw, form)
        if not stripped:
            continue
        for regex in (_DIMENSION_RE, _INTEGER_RE, _REAL_RE, _CHARACTER_RE, _LOGICAL_RE):
            match = regex.match(stripped)
            if match:
                names.update(_declared_array_names(match.group(1)))
                break
    return names


def _declared_array_names(payload: str) -> set[str]:
    return {entry.strip().split("(", 1)[0].strip().upper()
            for entry in split_top_level(payload)
            if "(" in entry and entry.strip().split("(", 1)[0].strip()}


# Nothing is inlined any more. KCLEAR used to be: its calls were rewritten as an
# explicit zeroing loop so no definition was needed. That is a stub standing in
# for an arithmetic helper, and it was wrong. KCLEAR(A,N,M) declares A(N,M) and
# relies on Fortran sequence association, so the same call site legitimately
# passes a rank-1 array, a rank-2 array, or a rank-2 array whose second extent
# is 1. The inliner guessed the rank from whether the third argument was
# literally "1", which produced SINVAR(mclr1) for a variable declared
# SINVAR(1,1) and a rank-mismatch error. No fixed rank can be right for all
# callers; the real routine already handles them all, so it is lifted like any
# other helper and the dependency resolver finds it when it lives in a sibling
# file.
_LIFTED_BODY_INLINED = frozenset()

_KCLEAR_CALL_RE = re.compile(
    r"^\s*CALL\s+KCLEAR\s*\(\s*([A-Za-z_]\w*)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)\s*$",
    re.IGNORECASE,
)



_MODULE_DIRECTIONS_RE = re.compile(r"otim(\d+)n(\d+)", re.IGNORECASE)
_LIFT_IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)")


def direction_renames(module_name: str, statements: Sequence[str]) -> str:
    """USE-clause renames for direction constants the routine uses as its own.

    The OTI module exports E1, E2, ... for its imaginary directions, and those
    are ordinary names for elastic moduli in a UMAT. Importing the module
    unqualified into a routine that assigns to its own E1 makes that assignment
    a write to a named constant, which gfortran rejects. Renaming on import
    keeps the constant reachable under another name while freeing the original.

    Returns "" when nothing collides, so untouched sources keep byte-identical
    output.
    """
    match = _MODULE_DIRECTIONS_RE.search(module_name)
    if not match:
        return ""
    count = int(match.group(1))
    used: set[str] = set()
    for statement in statements:
        # ``1.E1`` is a number, not a mention of a variable named E1. Reading it
        # as one renames a direction constant nothing collides with.
        used.update(name.upper() for name in
                    _LIFT_IDENTIFIER_RE.findall(without_real_literals(statement)))
    from umat_oti.oti.oti_directions import member_name

    collisions = [member_name([index]) for index in range(1, count + 1)
                  if member_name([index]) in used]
    return "".join(f", OTI_{name} => {name}" for name in collisions)


#: The generic names ``oti_intrinsics`` exports. Each is an ordinary Fortran
#: intrinsic, so a UMAT is free to use the same spelling for a variable of its
#: own -- UMAT_HIN's LU decomposition reads a variable called TINY.
_OTI_INTRINSIC_EXPORTS = (
    "MIN", "MAX", "SIGN", "NINT", "INT", "LOG10", "MATMUL", "TINY",
    "SUM", "NORM2",
)


def _constructor_spans(line: str) -> list[tuple[int, int, int]]:
    """(start, inner_start, end) of each ``(/ ... /)`` or ``[ ... ]`` constructor.

    ``end`` is one past the closing delimiter. Character literals are masked
    first so a "/)" inside a string closes nothing. Nested constructors are
    left to the outermost one's elements.
    """
    masked, _ = mask_character_literals(line)
    spans: list[tuple[int, int, int]] = []
    index = 0
    while index < len(masked):
        if masked.startswith("(/", index) and not masked.startswith("(//", index):
            depth, cursor = 0, index + 2
            while cursor < len(masked):
                if masked.startswith("/)", cursor) and depth == 0:
                    spans.append((index, index + 2, cursor + 2))
                    break
                if masked[cursor] in "([":
                    depth += 1
                elif masked[cursor] in ")]":
                    depth -= 1
                cursor += 1
            else:
                return spans
            index = cursor + 2
            continue
        if masked[index] == "[":
            close = _matching_bracket(masked, index)
            if close < 0:
                return spans
            spans.append((index, index + 1, close + 1))
            index = close + 1
            continue
        index += 1
    return spans


def _matching_bracket(text: str, open_index: int) -> int:
    depth = 0
    for cursor in range(open_index, len(text)):
        if text[cursor] in "([":
            depth += 1
        elif text[cursor] in ")]":
            depth -= 1
            if depth == 0:
                return cursor if text[cursor] == "]" else -1
    return -1


def wrap_oti_array_constructors(line: str, is_oti) -> str:
    """Give an array constructor that mixes OTI and real elements one type.

    Every element of a constructor that names a differentiated value is
    wrapped in ``OTI_VALUE`` (oti_intrinsics), the identity on a hypercomplex
    element and the real-to-OTI assignment on a real or integer one. Two
    corpus sources wrote ``S_ISO(1,:) = (/ 1.0D0, -PR, -PR, 0.0D0, ... /)``
    and ``FNORM = (/PLASPAR(1), 0.0D0, -1.0D0/)`` with PR and PLASPAR
    differentiated; neither compiled ("Element in REAL(8) array constructor
    is TYPE(...)"). Left alone: constructors with a type-spec (``::``), with
    an implied DO (a top-level ``=``), and constructors that name nothing
    ``is_oti`` accepts -- an all-real constructor may be filling a REAL array.
    """
    spans = _constructor_spans(line)
    if not spans:
        return line
    result = line
    for start, inner_start, end in reversed(spans):
        closing = 2 if result[end - 2:end] == "/)" else 1
        inner = result[inner_start:end - closing]
        if "::" in inner:
            continue
        elements = split_top_level(inner)
        if any(re.search(r"(?<![=<>/])=(?![=])", element) for element in elements):
            continue
        masked, _ = mask_character_literals(inner)
        names = re.findall(r"(?<![A-Za-z0-9_%.])([A-Za-z_]\w*)", without_real_literals(masked))
        if not any(is_oti(name) for name in names):
            continue
        wrapped = ", ".join(f"OTI_VALUE({element.strip()})" for element in elements)
        result = result[:inner_start] + wrapped + result[end - closing:]
    return result


def intrinsic_collisions(statements: Sequence[str],
                         declared: Iterable[str] = ()) -> set[str]:
    """The ``oti_intrinsics`` exports this scope uses as names of its own.

    Two ways a scope owns a name: it uses it as data (``SUM = SUM + X``, an
    accumulator nobody declared), or it declares it. The second was missed:
    a routine that declares ``double precision, parameter :: TINY`` and never
    mentions it again failed on its declaration with "Cannot change attributes
    of USE-associated symbol", in two viscoplastic Mohr-Coulomb sources.
    Declaring a name shadows the intrinsic of that name in the source too, so
    renaming the import away never takes a call the routine could make.
    """
    collisions: set[str] = set()
    exports = set(_OTI_INTRINSIC_EXPORTS)
    collisions.update(name.upper() for name in declared if name.upper() in exports)
    for statement in statements:
        text, _ = mask_character_literals(statement)
        text = without_real_literals(text)
        for name in _OTI_INTRINSIC_EXPORTS:
            if re.search(rf"\b{name}\b(?!\s*\()", text, re.IGNORECASE):
                collisions.add(name)
    return collisions


def intrinsic_renames(statements: Sequence[str]) -> str:
    """USE-clause renames for ``oti_intrinsics`` names the routine uses as data.

    The same problem :func:`direction_renames` solves for the direction
    constants, one module along. ``oti_intrinsics`` exports generics named
    after Fortran intrinsics, and importing it unqualified into a routine that
    has a variable of the same name makes every mention of that name refer to
    the module's generic: gfortran answers "Cannot assign to a named constant"
    and points at the statement rather than at the name.

    Only a name used as *data* is renamed. A name followed by "(" is a call --
    ``max(a,b)`` is the overload this module exists to provide -- and renaming
    that would take away the very thing the routine needs.

    Returns "" when nothing collides, so untouched sources keep byte-identical
    output.
    """
    collisions: set[str] = set()
    for statement in statements:
        # Character literals first: a WRITE of " - max increment:" is not a
        # mention of a variable called MAX, and renaming on it took away the
        # MAX overload from a routine whose every use of it was a call.
        text, _ = mask_character_literals(statement)
        text = without_real_literals(text)
        for name in _OTI_INTRINSIC_EXPORTS:
            if re.search(rf"\b{name}\b(?!\s*\()", text, re.IGNORECASE):
                collisions.add(name)
    return "".join(f", OTI_{name} => {name}" for name in sorted(collisions))


def _kclear_inline_lines(statement: str) -> list[str] | None:
    """Inline a CALL KCLEAR(target, nr, nc) as an explicit zeroing loop.

    Returns None if the statement is not a KCLEAR call. Loop indices use M-names
    (integer under the lifted body's `implicit integer (i-n)`).
    """
    match = _KCLEAR_CALL_RE.match(statement)
    if not match:
        return None
    target, nr, nc = match.group(1), match.group(2).strip(), match.group(3).strip()
    if nc == "1":
        return [f"    do mclr1 = 1, {nr}", f"      {target}(mclr1) = 0.0d0", "    end do"]
    return [
        f"    do mclr1 = 1, {nr}",
        f"      do mclr2 = 1, {nc}",
        f"        {target}(mclr1,mclr2) = 0.0d0",
        "      end do",
        "    end do",
    ]


def _lift_helper_routine(
    routine: ParsedSubroutine,
    form: str,
    source_lines: list[str],
    lifted_names: set[str],
    module_name: str,
    type_name: str,
    helper_output_copies: list[dict[str, Any]],
    helper_output_surfaces: list[dict[str, Any]],
    lifted_function_names: set[str] | None = None,
    source_path: Path | None = None,
    host_constants: Sequence[str] = (),
    typing_host: ParsedSubroutine | None = None,
) -> str:
    raw_lines = _routine_source_lines(source_lines, routine)
    raw_lines = _without_internal_procedures(
        raw_lines, form, routine,
        set(lifted_names) | set(lifted_function_names or ()))
    if source_path is not None:
        raw_lines = _expand_helper_includes(raw_lines, form, source_path)
    if not raw_lines:
        raise HelperLiftingError(f"Routine {routine.name} is empty.")
    stitched_lines = _continuation_stitch(raw_lines, form)
    if not stitched_lines:
        raise HelperLiftingError(f"Routine {routine.name} did not produce any stitched source lines.")
    for line in stitched_lines[1:-1]:
        entry = re.match(r"^\s*ENTRY\s+([A-Z_]\w*)", _statement_text(line, form), re.IGNORECASE)
        if entry:
            # The lifted copy carried the ENTRY statement through and the
            # alternate entry point came out defined twice (link error; Vera
            # B5 T3 c_entry_plain).
            raise HelperLiftingError(
                f"{routine.name} has an ENTRY statement ({entry.group(1).upper()}). "
                "A lifted helper is emitted as one subprogram with one entry point; "
                "ENTRY is not supported. What to do: make "
                f"{entry.group(1).upper()} a subroutine of its own.")
    if host_constants:
        # An internal procedure lifted on its own: its host's named constants,
        # which it saw by host association, declared in it (see
        # host_constants_for_internal_procedures).
        carried = _carried_host_constants(host_constants, stitched_lines, form, routine)
        stitched_lines = stitched_lines[:1] + carried + stitched_lines[1:]
    lifted_function_names = set(lifted_function_names or ())
    # Binary32 variables keep a binary32 primal: every store to one rounds
    # the real part of its OTI value (Curie-G B-W, Gauss F3). The routine's
    # own declarations and IMPLICIT rules decide which names those are; a
    # name only a module could type is left alone.
    from umat_oti.transform.routine_typing import routine_typing
    # Read off the routine as written, INCLUDEs unexpanded: routine_typing
    # resolves them itself, and knows ABA_PARAM.INC's IMPLICIT REAL*8, which
    # the expansion above leaves out -- typing the expanded text read every
    # implicitly typed name as binary32.
    # An internal procedure has its host's IMPLICIT rules (ABA_PARAM.INC's
    # IMPLICIT REAL*8 included) unless it states its own, so it is typed
    # inside its host's text; read on its own, every implicitly typed name
    # was default REAL and its stores were rounded to binary32 (Vera B5 a3).
    typing_text = _routine_source_lines(source_lines, typing_host or routine)
    routine_types = routine_typing("\n".join(typing_text),
                                   routine.name, form=form,
                                   source_dir=source_path.parent if source_path is not None else None)
    header_text = _statement_text(stitched_lines[0], form)
    header_match = _HEADER_RE.match(header_text)
    function_match = None if header_match else FUNCTION_HEADER_RE.match(header_text)
    if header_match:
        prefixes = header_match.group("prefix").upper().split()
        refused = [word for word in prefixes if word in _UNLIFTABLE_PREFIXES]
        if refused:
            raise HelperLiftingError(
                f"{routine.name} is declared {' '.join(refused)} at "
                f"{stitched_lines[0].strip()!r}. An ELEMENTAL routine is "
                f"applied element by element to array actuals; a lifted "
                f"scalar copy called the same way is a different program, so "
                f"this transform does not lift one.")
        original_name = header_match.group(2).upper()
        raw_args = header_match.group(3)
        result_name = ""
        declared_result_type = ""
    elif function_match:
        original_name = function_match.group("name").upper()
        raw_args = function_match.group("args") or ""
        result_name = (function_match.group("result") or original_name).upper()
        declared_result_type = (function_match.group("type") or "").strip()
    else:
        raise HelperLiftingError(f"Cannot parse helper header for {routine.name}: {stitched_lines[0]!r}")
    args = [arg.strip() for arg in split_top_level(raw_args) if arg.strip()]
    existing_arg_names = {arg.upper() for arg in args}
    args.extend(
        spec["caller_variable"]
        for spec in helper_output_surfaces
        if spec.get("caller_variable") and spec["caller_variable"] not in existing_arg_names
    )
    integer_names: set[str] = set()
    character_names: set[str] = set()
    logical_names: set[str] = set()
    parameter_names: set[str] = set()
    imported_names: set[str] = set()
    parameter_definitions: dict[str, str] = {}
    common_declared_names: set[str] = set()
    common_statements: list[str] = []
    declaration_oti_names: set[str] = set()
    prelude: list[str] = []
    use_lines: list[str] = []
    body: list[str] = []
    data_assignments: list[str] = []
    character_specs: dict[str, str] = {}
    saved_names: set[str] = set()
    save_everything = False
    # The Fortran 77 way to write a named constant is two statements --
    # INTEGER N, then PARAMETER (N = 3) -- and the PARAMETER rewrite below
    # emits a complete typed declaration of its own. Emitting the plain
    # declaration as well declares N twice, which gfortran rejects with
    # "Symbol 'n' already has basic type of INTEGER". The names are read ahead
    # of the pass that emits, because the type declaration comes first.
    named_constants = _parameter_statement_names(stitched_lines[1:-1], form)
    # Read ahead as well, because a DATA statement that gives a whole array its
    # elements needs the array's shape and nothing in the DATA statement says
    # what it is. The declaration is above it in every source seen, but reading
    # the whole routine first does not depend on that being true.
    declared_extents = _declared_literal_extents(stitched_lines[1:-1], form)
    # Read ahead for COMMON as well. A COMMON block is a storage layout agreed
    # between routines, and the main transform already keeps every name in one
    # real for that reason (see core.roles.common_block_names). Lifting a
    # helper that shares the same block used to retype its half of it, so the
    # UMAT declared a shared block as real(8) while the lifted helper
    # declared it type(ONUMM95N1) -- two routines disagreeing about the same
    # storage. gfortran stops earlier than that, because a derived type in
    # COMMON needs SEQUENCE or BIND(C); one such model raised that on 126
    # declarations. Keeping the names real here makes the lifted routine agree
    # with the UMAT, which is what sharing a block requires.
    common_names = common_block_names("\n".join(
        _statement_text(raw, form) for raw in stitched_lines[1:-1]))
    # Locals that only ever hold a literal -- ``m = 0.40`` in a Prout-Tompkins
    # rate law -- carry no derivative, and typing them OTI turned
    # ``(cure/max_cure)**m`` into an OTI-to-OTI power that goes through
    # LOG(0) at cure = 0 and returns a non-finite value where the source
    # returns 0 (Worlthen curing, Curie-G cluster E). Kept REAL(8), the power
    # is OTI**REAL, whose zero base is handled. See _literal_constant_locals
    # for what keeps a name out (arguments, arrays, shared storage, actual
    # arguments of any call).
    stitched_lines = _initialised_reals_as_named_constants(stitched_lines, form, original_name)
    literal_constants = _literal_constant_locals(stitched_lines, form, routine.args, common_names)
    # A function's result is what its callers receive, typed OTI on their
    # side; it is never a constant local (HEAV = 0. / 1.0D0 is a step function).
    literal_constants -= {original_name, result_name}
    constant_real_names: set[str] = set()

    interface_depth = 0
    for raw in stitched_lines[1:-1]:
        stripped = _statement_text(raw, form)
        if not stripped:
            continue
        # An INTERFACE block declares routines defined somewhere else. Copied
        # into the lifted body it produces a second declaration of every dummy
        # argument the interface bodies name -- MohrCoulombStressReturn
        # declares explicit interfaces for the eight routines it calls, and
        # the lifted copy came out with "integer :: nsigma" nine times over
        # and failed to compile on "Symbol 'nsigma' already has basic type of
        # INTEGER". The lifted helpers are external subprograms called through
        # an implicit interface like every other one this emits, so the block
        # is dropped rather than rewritten.
        if _INTERFACE_CLOSE_RE.match(stripped):
            interface_depth = max(0, interface_depth - 1)
            continue
        if _INTERFACE_OPEN_RE.match(stripped):
            interface_depth += 1
            continue
        if interface_depth:
            continue
        if stripped.upper().startswith("INCLUDE "):
            continue
        if re.match(r"^\s*IMPLICIT\s+", stripped, re.IGNORECASE):
            continue
        if re.match(r"^USE\b", stripped, re.IGNORECASE):
            use_lines.append(f"    {stripped}")
            only = re.search(r"\bONLY\s*:\s*(.*)$", stripped, re.IGNORECASE)
            if only:
                imported_names.update(
                    entry.split("=>", 1)[0].strip().upper()
                    for entry in split_top_level(only.group(1)))
            continue
        # An assignment is never a declaration, whatever its first letters
        # spell: ``REALV(1)=0.`` reads as REAL + ``V(1)=0.`` to a pattern that
        # only looks at the start, and became ``type(OTI) :: V(1)=0.``.
        if "::" not in stripped and _ASSIGNMENT_STATEMENT_RE.match(stripped):
            body.append(raw)
            continue
        declaration = parse_declaration_line(stripped)
        if declaration is not None and declaration.attributes and (
            declaration.has_parameter_attribute or declaration.kind in {"integer", "logical", "character"}
        ):
            if declaration.has_parameter_attribute:
                # A routine may both declare a constant itself and INCLUDE a
                # file that declares the same one. One viscoplastic UMAT
                # declares a reference constant inline and then includes a
                # file saying exactly the same thing; expanding the include
                # declares it twice and gfortran stops on "Symbol
                # the name already has a basic type". Repeating a
                # definition verbatim says nothing new, so the repeat is
                # dropped. Two DIFFERENT values for one name is a genuine
                # contradiction and is refused rather than silently resolved.
                kept = []
                for entity in declaration.entities:
                    definition = entity.render()
                    previous = parameter_definitions.get(entity.upper_name)
                    if previous is None:
                        parameter_definitions[entity.upper_name] = definition
                        kept.append(entity)
                    elif _same_constant(previous, definition):
                        continue
                    else:
                        raise HelperLiftingError(
                            f"{routine.name} declares the constant "
                            f"{entity.upper_name} twice with different values, "
                            f"{previous!r} and then {definition!r}. Which one "
                            f"the routine means is not something this "
                            f"transform can decide.")
                parameter_names.update(
                    entity.upper_name for entity in declaration.entities)
                if not kept:
                    continue
                if len(kept) != len(declaration.entities):
                    attributes = "".join(f", {attribute}" for attribute in declaration.attributes)
                    entities = ", ".join(entity.render() for entity in kept)
                    prelude.append(f"    {declaration.raw_type}{attributes} :: {entities}")
                    continue
                prelude.append(f"    {stripped}")
                continue
            prelude.append(f"    {stripped}")
            names = {entity.upper_name for entity in declaration.entities}
            if declaration.kind == "integer":
                integer_names.update(names)
            elif declaration.kind == "logical":
                logical_names.update(names)
            elif declaration.kind == "character":
                character_names.update(names)
            continue
        retyped = _retyped_attributed_declaration(stripped, type_name)
        if retyped is not None:
            entities = retyped.split("::", 1)[1]
            if _only_names(entities, common_names):
                # An attributed declaration of shared storage keeps its own
                # type; the attributes are already written on the statement.
                prelude.append(f"    {stripped}")
                common_declared_names.update(_declared_names(entities))
                continue
            prelude.append(f"    {retyped}")
            declaration_oti_names.update(_declared_names(entities))
            continue
        stripped = _flattened_attributed_declaration(stripped)
        parameter_match = _PARAMETER_RE.match(stripped)
        if parameter_match:
            parameter_lines, names = _rewrite_parameter_line(
                parameter_match.group(1), character_specs,
                constant_kind=lambda name: _named_constant_kind(name, routine_types))
            prelude.extend(parameter_lines)
            parameter_names.update(names)
            continue
        dimension_match = _DIMENSION_RE.match(stripped)
        if dimension_match:
            payload = _without_names(dimension_match.group(1), named_constants)
            if not payload:
                continue
            shared = _only_names(payload, common_names)
            if shared:
                prelude.append(f"    real(8) :: {shared}")
                common_declared_names.update(_declared_names(shared))
                payload = _without_names(payload, common_names)
                if not payload:
                    continue
            lines, oti_names, ints = _rewrite_dimension_line(
                payload, type_name, declaration_oti_names | integer_names)
            prelude.extend(lines)
            declaration_oti_names.update(oti_names)
            integer_names.update(ints)
            continue
        integer_match = _INTEGER_RE.match(stripped)
        if integer_match:
            payload = _without_names(integer_match.group(1), named_constants)
            if not payload:
                continue
            prelude.append(f"    integer :: {payload}")
            integer_names.update(_declared_names(payload))
            continue
        real_match = _REAL_RE.match(stripped)
        if real_match:
            payload = _without_names(real_match.group(1), named_constants)
            if not payload:
                continue
            fixed = _only_names(payload, literal_constants)
            if fixed:
                prelude.append(f"    real(8) :: {fixed}")
                constant_real_names.update(_declared_names(fixed))
                payload = _without_names(payload, literal_constants)
                if not payload:
                    continue
            shared = _only_names(payload, common_names)
            if shared:
                # Shared storage keeps the type the block was laid out with.
                prelude.append(f"    real(8) :: {shared}")
                common_declared_names.update(_declared_names(shared))
                payload = _without_names(payload, common_names)
                if not payload:
                    continue
            prelude.append(f"    type({type_name}) :: {payload}")
            declaration_oti_names.update(_declared_names(payload))
            continue
        character_match = _CHARACTER_RE.match(stripped)
        if character_match:
            # ``CHARACTER(256) DIR1`` then ``PARAMETER (DIR1='fibers.inp')``:
            # the PARAMETER rewrite declares DIR1 itself, with this length,
            # so the plain declaration keeps only the other names (it was
            # emitted twice: "already has basic type of CHARACTER").
            payload = character_match.group(1)
            constant = _only_names(payload, named_constants) if "::" not in stripped else ""
            if not constant:
                prelude.append(f"    {stripped}")
                character_names.update(_declared_names(payload))
                continue
            spec = stripped[:len(stripped) - len(payload)].replace("::", "").strip()
            for name in _declared_names(constant):
                character_specs[name] = spec
            payload = _without_names(payload, named_constants)
            character_names.update(_declared_names(character_match.group(1)))
            if payload:
                prelude.append(f"    {spec} :: {payload}" if "::" in stripped
                               else f"    {spec} {payload}")
            continue
        logical_match = _LOGICAL_RE.match(stripped)
        if logical_match:
            prelude.append(f"    {stripped}")
            logical_names.update(_declared_names(logical_match.group(1)))
            continue
        data_match = _DATA_RE.match(stripped)
        if data_match:
            data_assignments.extend(f"    {assignment}" for assignment in
                                    _data_to_assignments(data_match.group(1), declared_extents))
            continue
        save_match = _SAVE_RE.match(stripped)
        if save_match:
            # SAVE is a specification statement. Falling through to the body
            # put it after the first executable line ("Unexpected attribute
            # declaration statement", Vera's B1 toy a1).
            listed = [entry.strip() for entry in split_top_level(save_match.group(1)) if entry.strip()]
            if listed:
                saved_names.update(entry.strip("/ ").upper() for entry in listed)
                prelude.append(f"    save :: {', '.join(listed)}")
            else:
                save_everything = True
                prelude.append("    save")
            continue
        common_match = _COMMON_RE.match(stripped)
        if common_match:
            # COMMON is a specification statement. It was falling through to
            # the executable body, where gfortran reads it after the first
            # assignment and rejects it as misplaced.
            common_statements.append(f"    {stripped}")
            continue
        external_match = _EXTERNAL_RE.match(stripped)
        if external_match:
            # EXTERNAL is a specification statement, so it belongs in the
            # prelude and not among the executable lines. A name that is being
            # lifted is a module procedure now, not an external one, and its
            # references have been renamed, so it is dropped from the list; a
            # genuinely external name is kept and still declared.
            kept = [entry.strip() for entry in split_top_level(external_match.group(1))
                    if entry.strip() and entry.strip().upper() not in lifted_names]
            if kept:
                prelude.append(f"    external :: {', '.join(kept)}")
            continue
        body.append(raw)

    for spec in helper_output_surfaces:
        caller_variable = str(spec.get("caller_variable") or "").upper()
        declared_shape = str(spec.get("declared_shape") or "").strip()
        if not caller_variable or caller_variable in declaration_oti_names:
            continue
        suffix = f"({declared_shape})" if declared_shape else ""
        prelude.append(f"    type({type_name}) :: {caller_variable}{suffix}")
        declaration_oti_names.add(caller_variable)

    # A COMMON member the source never declared would be typed by this
    # routine's own "implicit type(OTI) (a-h,o-z)" rule, which puts it back in
    # the block as a derived type. Its extent is the one the COMMON statement
    # gives it.
    #
    # Which type it gets back is the source's own implicit rule, not real(8)
    # for everything. Fortran's default types I-N INTEGER, and the lifted
    # prelude says so itself one line above with "implicit integer (i-n)".
    # Four corpus sources -- the theysy MML family -- share a
    # ``COMMON /KSIZE/ NDIM1..NDIM7`` of undeclared array bounds, assigned
    # from NTENS and then used as extents. Declared real(8) they contradict
    # the routine's own implicit rule and gfortran refuses the prelude with
    # "Symbol 'ndim3' already has basic type of INTEGER", so the transform
    # succeeded and the generated Fortran did not build. A real(8) array
    # bound would also be wrong if it compiled.
    for statement in common_statements:
        for entity in _common_entities(statement.strip()):
            name = entity.split("(", 1)[0].strip().upper()
            if (not name or name in common_declared_names
                    or name in integer_names or name in character_names
                    or name in logical_names or name in parameter_names
                    or name in imported_names):
                continue
            if name in declaration_oti_names:
                declaration_oti_names.discard(name)
            if _is_implicit_integer_name(name):
                prelude.append(f"    integer :: {entity}")
                integer_names.add(name)
            else:
                prelude.append(f"    real(8) :: {entity}")
            common_declared_names.add(name)

    # A name the source uses only to index an array is a position, not a
    # value. The source's own implicit rule gave it REAL; the lifted body's
    # "implicit type(OTI) (a-h,o-z)" would give it the differentiated type,
    # which cannot be a subscript. Declaring it the way the source had it
    # reproduces what the source does.
    subscript_names = _subscript_only_names(
        [_split_label_and_statement(raw, form)[1] for raw in body],
        _routine_array_names(stitched_lines, form)
        | declaration_oti_names | common_declared_names)
    index_names: set[str] = set()
    for name in sorted(subscript_names):
        if (name in declaration_oti_names or name in integer_names
                or name in character_names or name in logical_names
                or name in parameter_names or name in imported_names
                or name in common_declared_names
                or name in {arg.upper() for arg in args}
                or _is_implicit_integer_name(name)):
            continue
        prelude.append(f"    real(8) :: {name.lower()}")
        index_names.add(name)

    for name in sorted(literal_constants - constant_real_names - declaration_oti_names
                       - integer_names - character_names - logical_names - parameter_names
                       - imported_names - common_declared_names - index_names):
        if _is_implicit_integer_name(name):
            continue
        prelude.append(f"    real(8) :: {name.lower()}")
        constant_real_names.add(name)
    declared_non_oti = (integer_names | character_names | logical_names
                        | parameter_names | imported_names | common_declared_names
                        | index_names | constant_real_names)
    # The Abaqus UMAT interface fixes CMNAME as a character string, and a source
    # is entitled to leave it undeclared and never use it -- UMAT4COMSOL's
    # neo-Hookean model does exactly that. Under "implicit type(oti) (a-h,o-z)"
    # an undeclared CMNAME becomes an OTI number and the driver then fails to
    # link with "passed CHARACTER(1) to TYPE(onumm2n1)". Its type comes from the
    # interface, not from the source, so it is asserted here.
    if "CMNAME" in {arg.upper() for arg in args}:
        declared_non_oti = declared_non_oti | {"CMNAME"}
        if "CMNAME" not in character_names:
            prelude.append("    character(len=80) :: CMNAME")
    # Supply the interface's shape for any array argument the source left
    # undeclared, so it is lifted as an array rather than a scalar.
    if original_name.upper() == "UMAT":
        for name, shape in UMAT_ARGUMENT_SHAPES.items():
            if name not in {arg.upper() for arg in args}:
                continue
            if name in declaration_oti_names or name in declared_non_oti:
                continue
            prelude.append(f"    type({type_name}) :: {name}({shape})")
            declaration_oti_names.add(name)

    # REAL(z) on a complex z is its real part, not the OTI value the
    # IF-condition rewrite means by REAL(); complex names are left unwrapped.
    complex_names = declared_complex_names(
        _statement_text(raw, form) for raw in stitched_lines[1:-1])
    oti_names = set(declaration_oti_names)
    for arg in args:
        upper = arg.upper()
        if upper not in declared_non_oti and not _is_implicit_integer_name(upper):
            oti_names.add(upper)
    oti_names.update(
        _implicit_oti_names(
            [_split_label_and_statement(raw, form)[1] for raw in body],
            lifted_names,
            declared_non_oti,
            parameter_names,
        )
    )
    # A complex name is differentiated whatever its first letter: J declared
    # DOUBLE COMPLEX is not the implicit integer the I-N rule would make it.
    # The complex intrinsics' generic names are not variables.
    oti_names.update(complex_names)
    if complex_names:
        oti_names -= COMPLEX_INTRINSIC_NAMES

    # Function references to rewrite in this body: every lifted function except
    # one this routine has shadowed with an array or a dummy argument of its own,
    # and except its own name, which inside a function is the result variable.
    # Rank-1 literal extents this routine declares for its own hypercomplex
    # names, which is all SUM needs to be written out term by term.
    helper_oti_shapes: dict[str, str] = {}
    for prelude_line in prelude:
        entities = re.match(r"^\s*type\([^)]*\)\s*::\s*(.+)$", prelude_line,
                            flags=re.IGNORECASE)
        if not entities:
            continue
        for item in split_top_level(entities.group(1)):
            entity = parse_entity(item.strip())
            if len(entity.dimensions) == 1 and entity.dimensions[0].strip().isdigit():
                helper_oti_shapes[entity.upper_name] = entity.dimensions[0].strip()
    body_statements = [_split_label_and_statement(raw, form)[1] for raw in body]
    shadowed = _routine_array_names(stitched_lines, form) | {arg.upper() for arg in args}
    function_call_names = {name for name in lifted_function_names
                           if name != original_name and name not in shadowed}

    _renames = direction_renames(
        module_name,
        body_statements + prelude + list(args))
    # The executable body's data uses, and every name the routine declares:
    # a declared local of an exported name is a USE conflict, not a local
    # that needs nothing (see intrinsic_collisions). The argument list is
    # spelled by the caller and is declared here too, so it is covered.
    _intrinsic_renames = "".join(
        f", OTI_{name} => {name}" for name in sorted(intrinsic_collisions(
            body_statements,
            declared_non_oti | declaration_oti_names | {arg.upper() for arg in args})))
    signature = f"{original_name.lower()}_oti({', '.join(arg.lower() for arg in args)})"
    unit = "function" if function_match else "subroutine"
    if function_match:
        header = f"function {signature} result({result_name.lower()})"
    else:
        header = f"subroutine {signature}"
    lines = [
        header,
        f"    use {module_name}, OTI_HELPER_DP => DP{_renames}",
        f"    use oti_intrinsics{_intrinsic_renames}",
        *use_lines,
        f"    implicit type({type_name}) (a-h,o-z)",
        "    implicit integer (i-n)",
    ]
    lines.extend(prelude)
    lines.extend(common_statements)
    if function_match and result_name not in declaration_oti_names and result_name not in declared_non_oti:
        # The result variable's type comes from the header's type-spec when it
        # has one and from the implicit rule otherwise. It is stated explicitly
        # because the lifted body's implicit rules are not the source's: a REAL
        # function whose name begins with I-N would silently become an integer.
        lines.append(f"    {_result_type_spec(declared_result_type, result_name, type_name)} :: {result_name.lower()}")
    for declared in prelude:
        attribute_save = re.match(r"^\s*[^:]*,\s*save\b[^:]*::\s*(.*)$", declared, re.IGNORECASE)
        if attribute_save:
            saved_names.update(_declared_names(attribute_save.group(1)))
    lines.extend(_data_initialisation_once(data_assignments, saved_names, save_everything,
                                           common_names | common_declared_names))
    from umat_oti.transform.binary32 import (
        BINARY32_CONTEXT, BINARY32_RULE_CONTEXT, BINARY32_WIDENED_SINK)
    binary32_names = frozenset(name for name in oti_names
                               if routine_types.is_single_precision(name)
                               and not (name == result_name and declared_result_type
                                        and not _declared_result_is_binary32(declared_result_type)))
    if BINARY32_RULE_CONTEXT.get() == "widened":
        # The binary32 variables that carry a derivative are carried in plain
        # double: the OTI form of precision.widen's control (binary32 rule
        # 'widened'). Recorded, since they leave no rounding to read off.
        sink = BINARY32_WIDENED_SINK.get()
        if sink is not None:
            sink.extend(sorted(binary32_names))
        binary32_names = frozenset()
    # A literal-constant local the source declares binary32 is declared
    # real(8) here (an OTI operator takes REAL(8) operands only). Its value is
    # still the binary32 one, but every operation on it is now formed in
    # double -- ``9.0/40.0*PI`` with PI REAL (Curie-G B-L). Listed with the
    # OTI shadows, its operations are rounded back to binary32 like theirs,
    # and every store to it is rounded too.
    widened_binary32 = frozenset(name for name in constant_real_names
                                 if routine_types.is_single_precision(name))
    # Binary32 named constants, held as real(8) (see _rewrite_parameter_line),
    # likewise: ``C5*C6`` of two REAL constants is a binary32 product.
    widened_binary32 |= {match.group(1).upper() for line in prelude
                         for match in [re.match(r"^\s*real\(8\), parameter :: (\w+) = REAL\(REAL\(",
                                                line)] if match}
    binary32_token = BINARY32_CONTEXT.set((binary32_names | widened_binary32, "",
                                           frozenset(oti_names) | widened_binary32))
    # Which names hold an INTEGER here, for _integer_division_literals: those
    # declared INTEGER, INTEGER named constants, and undeclared I-N names.
    integer_constants = {match.group(1).upper() for line in prelude
                         for match in [re.match(r"^\s*integer\s*,\s*parameter\s*::\s*(\w+)",
                                                line, re.IGNORECASE)] if match}
    not_integer = (oti_names | declared_non_oti | complex_names) - integer_names - integer_constants

    def integer_name(name: str) -> bool:
        if name in integer_names or name in integer_constants:
            return True
        return (name not in not_integer and _is_implicit_integer_name(name)
                and not routine_types.is_known_real(name))
    try:
        for raw in body:
            label_prefix, statement = _split_label_and_statement(raw, form)
            kclear_lines = None
            if kclear_lines is not None:
                lines.extend(kclear_lines)
                continue
            rewritten = _rewrite_helper_executable_line(
                statement, lifted_names, oti_names, function_call_names,
                oti_shapes=helper_oti_shapes,
                non_numeric_names=logical_names | character_names,
                condition_exempt=complex_names,
                integer_name=integer_name)
            rewritten = wrap_oti_array_constructors(
                rewritten,
                lambda name: name.upper() in oti_names or name.upper().endswith("_OTI"))
            if re.match(r"^\s*RETURN\b", rewritten, re.IGNORECASE) and helper_output_surfaces:
                lines.extend(_helper_output_surface_lines(helper_output_surfaces))
            if re.match(r"^\s*RETURN\b", rewritten, re.IGNORECASE) and helper_output_copies:
                lines.extend(_helper_output_copy_lines(helper_output_copies))
            surviving = _unsupported_intrinsic_over_oti(rewritten, oti_names)
            if surviving in REAL_OTI_INTRINSICS_ADDED and source_declares_complex("\n".join(source_lines)):
                surviving = ""  # oti_complex defines it over the type (see complex_support)
            if surviving in _WHOLE_ARRAY_FORM_ONLY:
                raise HelperLiftingError(
                    f"{routine.name} applies {surviving} with a DIM= or MASK= "
                    f"argument to a differentiated value at "
                    f"{_source_line_label(routine, statement)}: "
                    f"{statement.strip()!r}. oti_intrinsics declares "
                    f"{surviving}(array) over the OTI type and nothing else. "
                    f"What to do: write the reduction over that dimension as a DO "
                    f"loop in the source, or extend oti_intrinsics with the "
                    f"DIM/MASK form.")
            if surviving:
                raise HelperLiftingError(
                    f"{routine.name} applies {surviving} to a differentiated value "
                    f"at {_source_line_label(routine, statement)}: "
                    f"{statement.strip()!r}. The OTI algebra declares no "
                    f"{surviving} over the type and none can be written inside an "
                    f"expression here -- a reduction over a run-time extent needs "
                    f"a loop, which is a statement. Left in, it compiles nowhere; "
                    f"wrapped in REAL it would compile and drop the derivative.")
            lines.append(f"    {label_prefix}{rewritten}")
            stored = _BINARY32_TARGET.match(rewritten)
            if stored and stored.group(1).upper() in binary32_names:
                target = stored.group(1)
                lines.append(f"    {target}%R = REAL(REAL({target}%R, 4), 8)")
            elif stored and stored.group(1).upper() in widened_binary32:
                target = stored.group(1)
                lines.append(f"    {target} = REAL(REAL({target}, 4), 8)")
    finally:
        BINARY32_CONTEXT.reset(binary32_token)
    lines.append(f"end {unit} {original_name.lower()}_oti")
    return "\n".join(lines)


#: What the dependency bundle renames a file to when two staged files share a
#: name: the stem, two underscores, twelve hex characters of a digest, and
#: optionally a serial. Recognising the shape is what lets the runtime header
#: be recognised after it has been renamed.
_BUNDLE_RENAME = re.compile(r"^(?P<stem>.+?)__[0-9a-f]{12}(?:_\d+)?$")


def _is_runtime_header(name: str) -> bool:
    """Whether a staged file is Abaqus's parameter header under any name.

    ``aba_param.inc`` is supplied by the solver's own compile line and must
    not be inlined into a lifted helper, which writes its own implicit rules.
    The dependency bundle may have renamed it -- two sources in one closure
    each shipping a copy collide, and the second becomes
    ``aba_param__83d13fed26c5.inc`` -- and matching only the literal name let
    a renamed copy through, which then failed to resolve and refused two
    Worlthen sources that had transformed the pass before.
    """
    stem = Path(name).stem
    renamed = _BUNDLE_RENAME.match(stem)
    if renamed is not None:
        stem = renamed.group("stem")
    return f"{stem}{Path(name).suffix}".lower() == "aba_param.inc"


def _helper_include_target(name: str, source_path: Path) -> Path:
    """Where an INCLUDE in a (possibly staged) helper actually points.

    A Fortran INCLUDE is relative to the file that carries it, and that is
    the first place looked. A file the dependency bundle staged carries a
    different kind of reference: the bundler rewrites every include it
    resolved to a path relative to the OUTPUT directory --
    ``dependencies/<name>`` -- because that is where the emitted source is
    compiled from. A staged file itself lives one level down, inside
    ``dependencies/``, so resolving its own rewritten include against its own
    directory looks for ``dependencies/dependencies/<name>`` and finds
    nothing.

    Both are tried, in that order, so an ordinary source is unaffected and a
    staged one resolves the reference the bundler actually wrote.
    """
    from umat_oti.transform.dependency_bundle import case_insensitive_file

    direct = (source_path.parent / name).resolve()
    if direct.is_file():
        return direct
    if source_path.parent.name == "dependencies":
        output_relative = (source_path.parent.parent / name).resolve()
        if output_relative.is_file():
            return output_relative
    # A name shipped under another case, as a case-insensitive filesystem
    # would have opened it (see dependency_bundle.case_insensitive_file).
    return case_insensitive_file(source_path.parent / name) or direct


def _expand_helper_includes(
    lines: list[str], form: str, source_path: Path, stack: tuple[Path, ...] = (),
) -> list[str]:
    expanded: list[str] = []
    for raw in lines:
        match = re.match(r"^\s*INCLUDE\s+['\"]([^'\"]+)['\"]", _statement_text(raw, form), re.IGNORECASE)
        if not match:
            expanded.append(raw)
            continue
        if _is_runtime_header(match.group(1)):
            continue
        target = _helper_include_target(match.group(1), source_path)
        if target in stack:
            raise HelperLiftingError(f"Cyclic helper INCLUDE: {target}")
        if not target.is_file():
            raise HelperLiftingError(f"Missing helper INCLUDE {match.group(1)!r} relative to {source_path}")
        expanded.extend(_expand_helper_includes(
            target.read_text(encoding="utf-8").splitlines(), form, target, (*stack, target)))
    return expanded


#: The intrinsics the OTI algebra has no form of, in the lifted body's own
#: spelling. The same four the main pass blocks on
#: (``_INTRINSICS_WITHOUT_AN_OTI_FORM`` in source_transform); MOD and SUM have
#: expanders above and only reach here when the expander could not apply.
_UNSUPPORTED_OVER_OTI = ("SUM", "PRODUCT", "MOD", "ATAN2")

#: Of those, the ones oti_intrinsics now declares for a single whole-array
#: argument. A DIM= or MASK= argument is still refused by name.
_WHOLE_ARRAY_FORM_ONLY = frozenset({"SUM"})


def _unsupported_intrinsic_over_oti(line: str, oti_names: set[str]) -> str:
    """Which unsupported intrinsic this rewritten line applies to an OTI value.

    Asked AFTER the expanders have run, so a SUM that was written out term by
    term does not report itself. The main pass has blocked on these four since
    ahartloper/UVC_MatMod stopped at "'array' argument of 'sum' intrinsic must
    have a numeric type", but it reads the CALLER's stress regions only: a
    lifted helper doing the same thing produced the same compile error with no
    blocker in front of it, and a compile error in a log is not a diagnostic
    anybody asked this transform for.
    """
    if not oti_names:
        return ""
    for intrinsic in _UNSUPPORTED_OVER_OTI:
        for match in re.finditer(rf"(?<![A-Za-z0-9_%]){intrinsic}\s*\(", line,
                                 flags=re.IGNORECASE):
            close = _matching_paren_index(line, match.end() - 1)
            if close < 0:
                continue
            argument = line[match.end():close]
            if (intrinsic in _WHOLE_ARRAY_FORM_ONLY
                    and len(split_top_level(argument)) == 1):
                # oti_intrinsics declares SUM(array) over the type; only the
                # DIM= and MASK= forms remain without one.
                continue
            if any(re.search(rf"\b{re.escape(name)}\b", argument, flags=re.IGNORECASE)
                   for name in oti_names):
                return intrinsic
    return ""


def _source_line_label(routine: ParsedSubroutine, statement: str) -> str:
    """"line N" for the statement, or the routine's span when it is not found."""
    wanted = re.sub(r"\s+", "", statement).upper()
    for line in routine.lines:
        if re.sub(r"\s+", "", line.text).upper() == wanted and line.line_numbers:
            return f"line {line.line_numbers[0]}"
    numbers = [number for line in routine.lines for number in line.line_numbers]
    return (f"a line between {min(numbers)} and {max(numbers)}"
            if numbers else "an unrecorded line")


def _result_type_spec(declared_type: str, result_name: str, type_name: str) -> str:
    """Type-spec for a lifted function's result variable.

    A real-valued result is the differentiated one and becomes the OTI type. An
    integer, logical or character result carries no derivative and keeps the type
    the source gave it, written through verbatim so a legacy ``INTEGER*4`` or
    ``CHARACTER*8`` survives as itself.
    """
    text = declared_type.strip()
    if not text:
        return "integer" if _is_implicit_integer_name(result_name) else f"type({type_name})"
    head = re.match(r"^[A-Za-z]+", text)
    keyword = head.group(0).upper() if head else ""
    if keyword in {"INTEGER", "LOGICAL", "CHARACTER"}:
        return text
    return f"type({type_name})"


def _helper_output_surface_lines(helper_output_surfaces: list[dict[str, Any]]) -> list[str]:
    lines = ["    ! OTIS helper-output surface"]
    for spec in helper_output_surfaces:
        target = str(spec.get("caller_variable") or "").upper()
        source = str(spec.get("source_local") or "").upper()
        for component in spec.get("components") or []:
            target_ref = _helper_indexed_name(target, list(component.get("target_indices") or []))
            source_ref = _helper_indexed_name(source, list(component.get("output_indices") or []))
            if target_ref and source_ref:
                lines.append(f"    {target_ref} = {source_ref}")
    return lines


def _helper_output_copy_lines(helper_output_copies: list[dict[str, Any]]) -> list[str]:
    lines = ["    ! OTIS helper-output copy"]
    for spec in helper_output_copies:
        target = str(spec.get("target_argument") or "").upper()
        source = str(spec.get("source_local") or "").upper()
        for component in spec.get("components") or []:
            target_ref = _helper_indexed_name(target, list(component.get("target_indices") or []))
            source_ref = _helper_indexed_name(source, list(component.get("output_indices") or []))
            if target_ref and source_ref:
                lines.append(f"    {target_ref} = {source_ref}")
    return lines


def _helper_indexed_name(name: str, indices: list[int]) -> str:
    if not name:
        return ""
    if not indices:
        return name
    return f"{name}({', '.join(str(index) for index in indices)})"


#: Attributes a declaration can carry that the lifted form can express by
#: writing the entity out longhand. DIMENSION becomes the entity's own
#: array-spec, INTENT is optional on a module procedure's dummy, and PARAMETER
#: becomes the PARAMETER statement the lifter already rewrites. Anything else
#: -- SAVE, ALLOCATABLE, POINTER, OPTIONAL -- changes what the declaration
#: means, so it is left exactly as written rather than silently dropped, and
#: :func:`_retyped_attributed_declaration` carries it through instead.
_EXPRESSIBLE_ATTRIBUTES = ("dimension", "intent", "parameter")

#: Attributes the longhand form absorbs, so they are not repeated beside the
#: retyped declaration. DIMENSION is folded into each entity's array-spec, and
#: INTENT is dropped because the lifted routine is an external subprogram with
#: no explicit interface, where it constrains nothing and would only have to
#: agree with a caller nobody declares.
_ABSORBED_ATTRIBUTES = ("dimension", "intent")


def _retyped_attributed_declaration(stripped: str, type_name: str) -> str | None:
    """An attributed declaration rewritten to the OTI type, attributes kept.

    ``_flattened_attributed_declaration`` returns the statement untouched when
    it carries an attribute the longhand form cannot say, and the type matcher
    below then reads ``REAL(8)`` and takes ", intent(out), optional :: Dinv(..)"
    as its entity list, emitting

        type(ONUMM6N1) :: intent(out), optional :: Dinv(nsigma,nsigma)

    -- two double-colons in one declaration, which is not Fortran and stops
    the build. MohrCoulombAbaqus.for declares ``real(8), intent(out),
    optional :: Dinv(nsigma,nsigma)`` for its elastic-matrix helper.

    Only the type changes. OPTIONAL stays, because a body that calls
    ``PRESENT(Dinv)`` needs it and a caller is free to omit the argument;
    SAVE, ALLOCATABLE and POINTER stay for the same reason -- each says
    something about the variable that the entity list cannot.

    Returns None when there is nothing here of this shape, so the caller falls
    through to the paths it already had.
    """
    declaration = parse_declaration_line(stripped)
    if declaration is None or not declaration.attributes:
        return None
    if declaration.kind != "real" or declaration.has_parameter_attribute:
        return None
    if all(attribute.strip().lower().startswith(_EXPRESSIBLE_ATTRIBUTES)
           for attribute in declaration.attributes):
        return None
    kept = [attribute.strip() for attribute in declaration.attributes
            if not attribute.strip().lower().startswith(_ABSORBED_ATTRIBUTES)]
    entities = ", ".join(entity.render() for entity in declaration.entities)
    if not entities:
        return None
    prefix = f"type({type_name})"
    if kept:
        prefix += ", " + ", ".join(kept)
    return f"{prefix} :: {entities}"


def _flattened_attributed_declaration(stripped: str) -> str:
    """``TYPE, attrs :: names`` rewritten in the form the lifter reads.

    Every declaration matcher below reads a type keyword and takes the rest of
    the statement as its entity list. That is right for ``REAL*8 A(3,3)`` and
    wrong for ``DOUBLE PRECISION, DIMENSION(3,3), INTENT(IN) :: A``, whose
    rest-of-statement starts with a comma: the attribute list was carried
    through into the emitted declaration, which came out as

        type(ONUMM6N1) :: , DIMENSION(3,3), INTENT(IN)  :: A

    and stopped the build. Folding DIMENSION into each entity says the same
    thing in the form the matchers already handle.
    """
    declaration = parse_declaration_line(stripped)
    if declaration is None or not declaration.attributes:
        return stripped
    if not all(attribute.strip().lower().startswith(_EXPRESSIBLE_ATTRIBUTES)
               for attribute in declaration.attributes):
        return stripped
    entities = ", ".join(entity.render() for entity in declaration.entities)
    if not entities:
        return stripped
    if declaration.has_parameter_attribute:
        return f"PARAMETER({entities})"
    return f"{declaration.raw_type} {entities}"


def _parameter_statement_names(raw_lines: Sequence[str], form: str) -> set[str]:
    """Names given a value by a PARAMETER statement in this routine."""
    names: set[str] = set()
    for raw in raw_lines:
        stripped = _statement_text(raw, form)
        if not stripped:
            continue
        match = _PARAMETER_RE.match(_flattened_attributed_declaration(stripped))
        if not match:
            continue
        for assignment in split_top_level(match.group(1)):
            head = assignment.split("=", 1)[0].strip()
            if head:
                names.add(head.upper())
    return names


def _declared_literal_extents(raw_lines: Sequence[str], form: str) -> dict[str, tuple[int, ...]]:
    """Array names this routine declares, with their literal integer extents.

    Only literal extents. ``TENSOR(N,N)`` is an assumed or automatic shape,
    which no rewrite here can enumerate, and leaving it out means the DATA
    rewrite below refuses it rather than guessing a length.
    """
    extents: dict[str, tuple[int, ...]] = {}
    for raw in raw_lines:
        stripped = _statement_text(raw, form)
        if not stripped:
            continue
        stripped = _flattened_attributed_declaration(stripped)
        payload = ""
        for matcher in (_DIMENSION_RE, _INTEGER_RE, _REAL_RE):
            match = matcher.match(stripped)
            if match:
                payload = match.group(1)
                break
        if not payload:
            continue
        for item in split_top_level(payload):
            entity = parse_entity(item.strip())
            dimensions = [dimension.strip() for dimension in entity.dimensions]
            if not dimensions or not all(dimension.isdigit() for dimension in dimensions):
                continue
            extents[entity.upper_name] = tuple(int(dimension) for dimension in dimensions)
    return extents


def _column_major_subscript(offset: int, extents: tuple[int, ...]) -> str:
    """The subscript list for the ``offset``-th element in array element order.

    Fortran's array element order runs the leftmost subscript fastest, and a
    DATA value list is laid down in exactly that order; so is RESHAPE. Writing
    the subscripts out rather than building an array constructor keeps every
    assignment a scalar one, which is what the OTI type's ASSIGNMENT(=) is
    defined for.
    """
    subscripts: list[int] = []
    for extent in extents:
        subscripts.append(offset % extent + 1)
        offset //= extent
    return ",".join(str(value) for value in subscripts)


def _without_names(payload: str, names: set[str]) -> str:
    """``payload`` with any declared entity whose name is in ``names`` removed."""
    kept = [
        entry.strip() for entry in split_top_level(payload)
        if entry.strip()
        and entry.strip().split("(", 1)[0].split("=", 1)[0].strip().upper() not in names
    ]
    return ", ".join(kept)


_BARE_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")


def _subscript_only_names(statements: Sequence[str], array_names: set[str]) -> set[str]:
    """Names that appear in this routine only as a bare array subscript.

    A subscript is a position in an array, so it carries no derivative, and the
    differentiated type cannot be one: gfortran says "Array index must be of
    INTEGER type, found DERIVED". One UMAT indexes its state array with a name
    that is declared nowhere -- the source's own implicit rule makes
    it REAL, which Fortran accepts as a subscript, while the lifted body's
    ``implicit type(OTI) (a-h,o-z)`` makes it hypercomplex, which it does not.
    Keeping the name real reproduces what the source does.

    Only a subscript written as a bare name counts. ``A(INT(x))`` says nothing
    about ``x``, whose value may well be differentiated, and ``sqrt(x)`` is a
    call rather than a subscript -- which is why the array names are required
    and a name used anywhere else in the routine is left alone.
    """
    subscripts: set[str] = set()
    used_elsewhere: set[str] = set()
    for statement in statements:
        masked = statement
        for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", statement):
            if match.group(1).upper() not in array_names:
                continue
            close = _matching_paren_index(statement, match.end() - 1)
            if close < 0:
                continue
            inside = statement[match.end():close]
            for entry in split_top_level(inside):
                for piece in entry.split(":"):
                    piece = piece.strip()
                    if _BARE_IDENTIFIER.match(piece):
                        subscripts.add(piece.upper())
            masked = masked.replace(statement[match.start():close + 1], " ")
        used_elsewhere.update(
            name.upper() for name in re.findall(r"\b[A-Za-z_]\w*\b", masked))
    return {name for name in subscripts if name not in used_elsewhere}


def _same_constant(first: str, second: str) -> bool:
    """Whether two PARAMETER entity texts define the same constant.

    Compared without blanks and without case, so that "REF=2.5d0" and
    "REF = 2.5D0" are recognised as the one definition they are.
    """
    return ("".join(first.split()).upper() == "".join(second.split()).upper())


def _common_entities(statement: str) -> list[str]:
    """The entity specifications a COMMON statement lists, block names removed.

    ``COMMON /BLK/ A(3,4), B /OTHER/ C`` yields ``["A(3,4)", "B", "C"]``. The
    dimensions come back with the name because an undeclared COMMON member has
    to be declared with the extent the block gives it.
    """
    body = re.sub(r"/[^/]*/", ",", _COMMON_RE.match(statement).group(1))
    return [entry.strip() for entry in split_top_level(body) if entry.strip()]


def _only_names(payload: str, names: set[str]) -> str:
    """``payload`` reduced to the declared entities whose name is in ``names``.

    The complement of :func:`_without_names`. One declaration may name both a
    COMMON member and a local -- ``real(8) :: fld_dia(maxNElements), scratch``
    -- and the two halves are emitted with different types, so the entity list
    has to be split rather than classified as a whole.
    """
    kept = [
        entry.strip() for entry in split_top_level(payload)
        if entry.strip()
        and entry.strip().split("(", 1)[0].split("=", 1)[0].strip().upper() in names
    ]
    return ", ".join(kept)


def _named_constant_kind(name: str, typing: Any) -> str | None:
    """"integer" or "real": the type the source gives a named constant, or None.

    A named constant has the type of its declaration -- ``REAL(8) :: THREE``
    then ``PARAMETER (THREE=3)`` -- or else of the routine's IMPLICIT rule
    (``PARAMETER (TWO=2)`` under ABA_PARAM.INC's IMPLICIT REAL*8), never of
    the form of its value. None when the routine cannot say (IMPLICIT NONE
    with no declaration seen, an unreadable INCLUDE or module).
    """
    upper = name.upper()
    if typing.is_single_precision(upper):
        return "single"
    if upper in typing.declared_real or upper in typing.declared_single:
        return "real"
    if upper in typing.declared_nonreal:
        return "integer"
    if typing.implicit_none or typing.unknown_because or not upper:
        return None
    return "integer" if upper[0] in typing.nonreal_letters else "real"


def _rewrite_parameter_line(payload: str,
                            character_specs: dict[str, str] | None = None,
                            constant_kind: Callable[[str], str | None] | None = None,
                            ) -> tuple[list[str], set[str]]:
    lines: list[str] = []
    names: set[str] = set()
    for assignment in split_top_level(payload):
        if "=" not in assignment:
            raise HelperLiftingError(f"PARAMETER entry missing '=': {assignment!r}")
        name, value = assignment.split("=", 1)
        name = name.strip()
        value = value.strip()
        names.add(name.upper())
        if re.fullmatch(r"\.(?:TRUE|FALSE)\.", value, re.IGNORECASE):
            lines.append(f"    logical, parameter :: {name} = {value}")
        elif value.startswith(("'", '"')):
            declared = (character_specs or {}).get(name.upper(), "")
            kind = declared if declared else "character(len=*)"
            lines.append(f"    {kind}, parameter :: {name} = {value}")
        else:
            # The type is the source's (see _named_constant_kind). Typed from
            # the value's form, ``PARAMETER (TWO=2)`` under IMPLICIT REAL*8
            # became an INTEGER constant and ``1/TWO`` an integer division.
            # A complex value -- a parenthesised pair -- is left to the
            # value's form, as before.
            kind = (None if value.startswith("(") or re.search(r"\.[A-Za-z]+\.", value)
                    else (constant_kind or (lambda _: None))(name))
            if kind is None:
                kind = "integer" if re.fullmatch(r"[+-]?\d+", value) else "real"
            if kind == "integer":
                lines.append(f"    integer, parameter :: {name} = {value}")
            elif kind == "single":
                # Declared REAL / REAL(4) / REAL*4 (or so typed implicitly): the
                # source's constant is the value rounded to binary32 -- REAL C;
                # PARAMETER (C=1.D0/3.D0) is 0.3333333432674408, not 1/3 (Vera
                # B5 T3: primal 4.3e-9). An OTI operator takes REAL(8), so the
                # constant stays real(8) and holds that binary32 value exactly.
                lines.append(f"    real(8), parameter :: {name} = "
                             f"REAL(REAL({_normalize_real_literal(value)}, 4), 8)")
            else:
                lines.append(f"    real(8), parameter :: {name} = {_normalize_real_literal(value)}")
    return lines, names


def _rewrite_dimension_line(
    payload: str, type_name: str, already_typed: set[str] | None = None,
) -> tuple[list[str], set[str], set[str]]:
    """Turn a DIMENSION statement into declarations for the lifted routine.

    A DIMENSION statement carries shape and not type, and a name it mentions
    may already have been typed by a declaration above it. Emitting a second
    ``type(ONUMM6N1) :: tensor(3,3)`` for a name whose ``real*8 vector,tensor``
    was already rewritten declares it twice: "Symbol 'tensor' already has basic
    type of DERIVED". For those names the shape is emitted as what it is, a
    DIMENSION statement, which is what the source said in the first place.
    """
    typed = {name.upper() for name in (already_typed or set())}
    shape_only: list[str] = []
    oti_entries: list[str] = []
    int_entries: list[str] = []
    oti_names: set[str] = set()
    integer_names: set[str] = set()
    for entry in split_top_level(payload):
        clean = entry.strip()
        name = clean.split("(", 1)[0].strip().upper()
        if not name:
            continue
        if name in typed:
            shape_only.append(clean)
        elif _is_implicit_integer_name(name):
            int_entries.append(clean)
            integer_names.add(name)
        else:
            oti_entries.append(clean)
            oti_names.add(name)
    lines: list[str] = []
    if oti_entries:
        lines.append(f"    type({type_name}) :: {', '.join(oti_entries)}")
    if int_entries:
        lines.append(f"    integer :: {', '.join(int_entries)}")
    if shape_only:
        lines.append(f"    dimension {', '.join(shape_only)}")
    return lines, oti_names, integer_names


def _declared_names(payload: str) -> set[str]:
    names: set[str] = set()
    for entry in split_top_level(payload):
        clean = entry.strip()
        if not clean:
            continue
        names.add(clean.split("(", 1)[0].split("=", 1)[0].strip().upper())
    return names


def _implicit_oti_names(
    body: list[str],
    lifted_names: set[str],
    declared_non_oti: set[str],
    parameter_names: set[str],
) -> set[str]:
    result: set[str] = set()
    for line in body:
        # An inline IF's target is the assignment it guards, not the word IF.
        # Reading the whole line left a variable whose only assignment is
        # written that way out of the implicitly-hypercomplex set, so every
        # rewrite keyed on that set skipped it.
        inline_if = _split_inline_if_statement(line)
        guarded = inline_if[1] if inline_if is not None else line
        lhs_match = _LHS_ASSIGN_RE.match(guarded)
        if lhs_match:
            name = lhs_match.group(1).upper()
            if name not in declared_non_oti and name not in parameter_names and not _is_implicit_integer_name(name):
                result.add(name)
        for match in _TOKEN_RE.finditer(line):
            name = match.group(1).upper()
            if name in _KEYWORDS or name in _INTRINSIC_NAMES or name in _TYPED_INTRINSIC_MAP:
                continue
            if name in _INQUIRY_INTRINSICS and re.search(
                    rf"\b{name}\s*\(", line, flags=re.IGNORECASE):
                continue
            if name in lifted_names or name in declared_non_oti or name in parameter_names:
                continue
            if _is_implicit_integer_name(name):
                continue
            result.add(name)
    return result


def _split_inline_if_statement(line: str) -> tuple[str, str] | None:
    """``IF (cond) stmt`` split into the IF and the statement it guards.

    Returns None when the line does not open with IF, and (prefix, rest) when
    it does -- including for a block ``IF (cond) THEN``, whose ``rest`` is
    " THEN" and matches no assignment, so callers need no separate test.

    Without this split, every assignment-shaped rewrite below read the
    statement as an assignment to a variable called ``IF``: the regexes take a
    name, an optional parenthesised subscript and an ``=``, and ``[^=]*`` is
    greedy enough to swallow ``(NSHR .GE. 1) STRESS_OUT(4)`` whole as the
    subscript. The consequence was silent and numerical.
    ``_wrap_oti_rhs_assigned_to_a_plain_variable`` then saw a target named IF,
    which is not hypercomplex, and wrapped the right-hand side in REAL():

        IF(NSHR .GE. 1) STRESS_OUT(4) = REAL(SIGMA(1,2))

    for keisuke58/pde-fem-biofilm's umat_biofilm_visco_phase2.f. The shear
    stresses kept their values and lost every derivative, so the converted
    build returned a DDSDDE whose rows 4, 5 and 6 were identically zero
    against an author's DDSDDE(4,4) of 1.021165e+02 -- with the normal rows,
    whose assignments are not guarded by an inline IF, correct throughout.
    """
    if not re.match(r"^\s*(?:ELSE\s*)?IF\b", line, flags=re.IGNORECASE):
        return None
    open_paren = line.find("(")
    if open_paren < 0:
        return None
    depth = 0
    for index in range(open_paren, len(line)):
        char = line[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return line[: index + 1], line[index + 1:]
    return None


def _wrap_oti_rhs_assigned_to_a_plain_variable(
    line: str, oti_names: set[str], non_numeric_names: set[str] | None = None,
) -> str:
    """``NSS = STAT_VAR(3)`` takes the real part when the target is not OTI.

    The source stored a count in a real array and read it back into an
    integer, and that real-to-integer conversion is what it always did. Once
    the array is hypercomplex the assignment has no meaning to the compiler --
    "Cannot convert TYPE(onumm6n1) to INTEGER(4)" -- and the real part is the
    value the original converted, so nothing is lost that the source kept.

    Only when the target is a name this routine does NOT hold as
    hypercomplex. An OTI target keeps the whole number, derivative and all.
    """
    if not oti_names:
        return line
    guard = ""
    statement = line
    inline_if = _split_inline_if_statement(line)
    if inline_if is not None:
        guard, statement = inline_if
    match = re.match(r"^(\s*)([A-Za-z_]\w*)\s*(\([^=]*\))?\s*=(?!=)(.*)$", statement)
    if not match:
        return line
    indent, target, subscript, rhs = match.groups()
    if target.upper() in oti_names or not rhs.strip():
        return line
    # REAL() of a logical or a character is not a conversion, it is a type
    # error, and ifort says so. The target being "not hypercomplex" is not
    # enough to make it numeric: the author declared some of these LOGICAL.
    if target.upper() in (non_numeric_names or set()):
        return line
    if not any(token.upper() in oti_names
               for token in re.findall(r"[A-Za-z_]\w*", rhs)):
        return line
    if re.match(r"^\s*REAL\s*\(.*\)\s*$", rhs.strip(), flags=re.IGNORECASE):
        return line
    return f"{guard}{indent}{target}{subscript or ''} = REAL({rhs.strip()})"


def _expand_sum_over_oti(line: str, oti_names: set[str],
                         shapes: dict[str, str] | None = None) -> str:
    """``SUM(PSIG)`` written out term by term when the extent is a literal.

    The OTI library has no SUM, and there is nothing to take the real part of
    here -- a sum of hypercomplex numbers is hypercomplex, and its derivative
    is the sum of theirs. Writing PSIG(1)+PSIG(2)+PSIG(3) is the same value by
    definition and carries every derivative through untouched.

    Only for a whole-array reference whose extent this routine declares as a
    literal. A sum over a run-time extent would need a loop, and a loop cannot
    be written inside an expression; that case keeps the SUM and the compiler
    reports it, which is a refusal rather than a wrong number.
    """
    if not oti_names or not shapes:
        return line
    result = line
    search_from = 0
    while True:
        match = re.search(r"(?<![A-Za-z0-9_%])SUM\s*\(", result[search_from:],
                          flags=re.IGNORECASE)
        if not match:
            return result
        open_paren = search_from + match.end() - 1
        close_paren = _matching_paren_index(result, open_paren)
        if close_paren < 0:
            return result
        parts = split_top_level(result[open_paren + 1:close_paren])
        name = parts[0].strip().upper() if len(parts) == 1 else ""
        extent = str(shapes.get(name, "")).strip() if name in oti_names else ""
        if not name.isidentifier() or not extent.isdigit() or int(extent) < 1:
            search_from = open_paren + 1
            continue
        terms = " + ".join(f"{parts[0].strip()}({index})"
                           for index in range(1, int(extent) + 1))
        rebuilt = f"({terms})"
        result = result[:search_from + match.start()] + rebuilt + result[close_paren + 1:]
        search_from = search_from + match.start() + len(rebuilt)


def _matching_paren_index(text: str, open_paren: int) -> int:
    """Index of the ")" closing the "(" at ``open_paren``, or -1."""
    depth = 0
    for index in range(open_paren, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _expand_mod_over_oti(line: str, oti_names: set[str]) -> str:
    """``MOD(A, P)`` written out, so the derivative survives it.

    The OTI library has no MOD, and wrapping the argument in REAL would make
    it compile while silently zeroing a derivative that is not zero: unlike
    FLOOR or NINT, MOD is not piecewise constant in its first argument -- it
    has slope one almost everywhere.

    Fortran defines MOD(a, p) as ``a - INT(a/p)*p``, and that form is exact in
    hypercomplex arithmetic. The truncation is piecewise constant, so it is
    the only part that needs the real value; the ``a`` in front carries the
    derivative through unchanged.
    """
    if not oti_names:
        return line
    result = line
    search_from = 0
    while True:
        match = re.search(r"(?<![A-Za-z0-9_%])(D?MOD)\s*\(",
                          result[search_from:], flags=re.IGNORECASE)
        if not match:
            return result
        open_paren = search_from + match.end() - 1
        close_paren = _matching_paren_index(result, open_paren)
        if close_paren < 0:
            return result
        parts = split_top_level(result[open_paren + 1:close_paren])
        stem = re.match(r"[A-Za-z_]\w*", parts[0].strip()) if parts else None
        if (len(parts) != 2 or not stem
                or stem.group(0).upper() not in oti_names):
            search_from = open_paren + 1
            continue
        a, q = parts[0].strip(), parts[1].strip()
        rebuilt = f"(({a}) - REAL(INT(REAL({a})/({q})))*({q}))"
        result = result[:search_from + match.start()] + rebuilt + result[close_paren + 1:]
        search_from = search_from + match.start() + len(rebuilt)


#: Intrinsics whose result is a whole number, so their value is fixed by the
#: real part of the argument and is piecewise constant in it. Reading the real
#: part there is exact rather than an approximation, and it is what lets them
#: type-check against a hypercomplex operand.
_INTEGER_VALUED_INTRINSICS = ("FLOOR", "CEILING", "NINT", "IDNINT", "IDINT",
                              "INT", "IFIX")


def _real_argument_to_integer_intrinsics(line: str, oti_names: set[str]) -> str:
    """``FLOOR(HARD_PAR)`` reads the real part when HARD_PAR is hypercomplex.

    A lifted helper keeps the source's own names and changes only their
    declared type, so the argument carries no suffix to recognise it by -- the
    set of names this routine declares OTI is what says so.

        Error: 'a' argument of 'floor' intrinsic at (1) must be REAL
    """
    if not oti_names:
        return line
    result = line
    search_from = 0
    names = "|".join(_INTEGER_VALUED_INTRINSICS)
    while True:
        match = re.search(rf"(?<![A-Za-z0-9_%])({names})\s*\(",
                          result[search_from:], flags=re.IGNORECASE)
        if not match:
            return result
        open_paren = search_from + match.end() - 1
        close_paren = _matching_paren_index(result, open_paren)
        if close_paren < 0:
            return result
        parts = split_top_level(result[open_paren + 1:close_paren])
        first = parts[0].strip() if parts else ""
        # The whole argument, not just its leading name: after MOD is written
        # out the argument is an expression -- FLOOR(((VAL1) - ...)) -- and it
        # is hypercomplex if any name in it is.
        mentions_oti = any(token.upper() in oti_names
                           for token in re.findall(r"[A-Za-z_]\w*", first))
        if (not parts or not mentions_oti
                or re.match(r"^\s*REAL\s*\(.*\)\s*$", first, flags=re.IGNORECASE)):
            search_from = open_paren + 1
            continue
        rebuilt = ",".join([f"REAL({first})"] + [p.strip() for p in parts[1:]])
        result = result[:open_paren + 1] + rebuilt + result[close_paren:]
        search_from = open_paren + 1


#: ``DO var = start, end [, step]``, labelled or not. ``DO WHILE (...)`` has
#: no ``name =`` after the keyword and so cannot match.
_DO_BOUNDS_RE = re.compile(
    r"^(\s*(?:\d+\s+)?DO\s+(?:\d+\s*,?\s*)?[A-Za-z_]\w*\s*=\s*)(.+)$",
    re.IGNORECASE)


def _integer_do_bounds_over_oti(line: str, oti_names: set[str]) -> str:
    """``DO I = 1, X`` with X hypercomplex asks the loop for an OTI trip count.

    A helper that computes a count into a name the implicit rules give the OTI
    type -- ``X = N/2`` under ``IMPLICIT DOUBLE PRECISION (A-H,O-Z)``, which is
    how two viscoplastic Mohr-Coulomb sources split a tensor into its normal
    and shear halves -- is legal Fortran before the lift and

        Error: End expression in DO loop at (1) must be INTEGER

    after it. The loop wanted an integer, the source gave it a real, and the
    compiler did the conversion; here the conversion has to be written, and
    INT() of an OTI value is what oti_intrinsics defines. The derivative is
    dropped deliberately: a trip count is piecewise constant, so it has none.

    Only bounds that mention a name this routine made hypercomplex are
    touched, so an ordinary integer loop comes out byte-identical.
    """
    if not oti_names:
        return line
    match = _DO_BOUNDS_RE.match(line)
    if not match:
        return line
    parts = split_top_level(match.group(2))
    if not 2 <= len(parts) <= 3:
        return line
    rebuilt: list[str] = []
    changed = False
    for part in parts:
        bound = part.strip()
        mentions_oti = any(token.upper() in oti_names
                           for token in re.findall(r"[A-Za-z_]\w*", bound))
        if not mentions_oti or re.match(r"^INT\s*\(.*\)$", bound, re.IGNORECASE):
            rebuilt.append(bound)
            continue
        rebuilt.append(f"INT({bound})")
        changed = True
    if not changed:
        return line
    return match.group(1) + ", ".join(rebuilt)


def _rewrite_helper_executable_line(
    line: str,
    lifted_names: set[str],
    oti_names: set[str],
    function_call_names: set[str] | None = None,
    oti_shapes: dict[str, str] | None = None,
    non_numeric_names: set[str] | None = None,
    condition_exempt: set[str] | None = None,
    integer_name: Callable[[str], bool] | None = None,
) -> str:
    rewritten = _rewrite_lifted_call(line, lifted_names)
    rewritten = _wrap_condition_with_real_tokens(rewritten, oti_names - (condition_exempt or set()))
    rewritten = _normalize_typed_intrinsics(rewritten, oti_names)
    rewritten = _expand_sum_over_oti(rewritten, oti_names, oti_shapes)
    rewritten = _expand_mod_over_oti(rewritten, oti_names)
    rewritten = _real_argument_to_integer_intrinsics(rewritten, oti_names)
    rewritten = _integer_do_bounds_over_oti(rewritten, oti_names)
    rewritten = _normalize_numeric_literals(rewritten, oti_names, integer_name)
    rewritten = _wrap_oti_rhs_assigned_to_a_plain_variable(
        rewritten, oti_names, non_numeric_names or set())
    # Last, so every rewrite above still sees the source's own names.
    return _rewrite_lifted_function_references(rewritten, function_call_names or set())


def _rewrite_lifted_function_references(line: str, function_call_names: set[str]) -> str:
    """Point ``NAME(`` at the lifted ``NAME_OTI``.

    Literals are masked first: a name inside a FORMAT string or an error
    message is text, not a reference, and the letters inside a real literal are
    not a name at all.
    """
    if not function_call_names:
        return line
    masked, literals = mask_character_literals(line)
    masked, reals = mask_real_literals(masked)
    pattern = re.compile(
        r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(name) for name in sorted(function_call_names, key=len, reverse=True))
        + r")(?=\s*\()",
        re.IGNORECASE,
    )
    rewritten = unmask_real_literals(pattern.sub(lambda m: f"{m.group(1).upper()}_OTI", masked), reals)
    return unmask_character_literals(rewritten, literals)


def _rewrite_lifted_call(line: str, lifted_names: set[str]) -> str:
    match = re.match(r"^(\s*(?:\d+\s+)?CALL\s+)([A-Z_][A-Z0-9_]*)(\s*\(.*)$", line, re.IGNORECASE)
    if not match:
        return line
    callee = match.group(2).upper()
    if callee not in lifted_names:
        return line
    return f"{match.group(1)}{callee}_OTI{match.group(3)}"


def _wrap_condition_with_real_tokens(line: str, oti_names: set[str]) -> str:
    if not oti_names:
        return line
    match = _IF_RE.match(line)
    if not match:
        return line
    line, character_literals = mask_character_literals(line)
    condition_start = match.end()
    depth = 1
    condition_end = -1
    for index in range(condition_start, len(line)):
        char = line[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                condition_end = index
                break
    if condition_end < 0:
        return unmask_character_literals(line, character_literals)
    condition = line[condition_start:condition_end]
    wrapped = _real_wrapped_tokens(condition, oti_names)
    result = f"{match.group(1)}({wrapped}){line[condition_end + 1:]}"
    return unmask_character_literals(result, character_literals)


def _real_wrapped_tokens(condition: str, oti_names: set[str]) -> str:
    if not oti_names:
        return condition
    # A promoted variable can share a name with an exponent letter -- models do
    # declare variables called D and D0 -- so mask literals before substituting
    # identifiers, or ``1.D-12`` becomes ``1.REAL(D)-12``.
    condition, literals = mask_real_literals(condition)
    condition, inquiries = _mask_inquiry_calls(condition)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(name) for name in sorted(oti_names, key=len, reverse=True)) + r")\b(?:\([^()]*\))?",
        re.IGNORECASE,
    )

    def replacement(match: re.Match[str]) -> str:
        token = match.group(0)
        before = condition[: match.start()].upper()
        if before.endswith("REAL("):
            return token
        return f"REAL({token})"

    wrapped = pattern.sub(replacement, condition)
    for index, call in enumerate(inquiries):
        wrapped = wrapped.replace(f"\x00INQ{index}\x00", call)
    return unmask_real_literals(wrapped, literals)


def _mask_inquiry_calls(text: str) -> tuple[str, list[str]]:
    """Each inquiry-intrinsic call, whole, replaced by a placeholder.

    See _INQUIRY_INTRINSICS: neither the call's result nor its arguments are
    real values, so the condition wrapper must not touch any of it.
    """
    calls: list[str] = []
    while True:
        match = _INQUIRY_CALL_RE.search(text)
        if not match:
            return text, calls
        close = _matching_paren_index(text, match.end() - 1)
        if close < 0:
            return text, calls
        calls.append(text[match.start():close + 1])
        text = text[:match.start()] + f"\x00INQ{len(calls) - 1}\x00" + text[close + 1:]


def _normalize_typed_intrinsics(line: str, oti_names: set[str]) -> str:
    if not _contains_oti_name(line, oti_names):
        return line
    return _TYPED_INTRINSIC_RE.sub(lambda match: _TYPED_INTRINSIC_MAP[match.group(1).upper()], line)


def _normalize_numeric_literals(line: str, oti_names: set[str],
                                integer_name: Callable[[str], bool] | None = None) -> str:
    if not _contains_oti_name(line, oti_names):
        return line
    if re.match(r"^\s*STOP\b", line, re.IGNORECASE):
        return line
    if _LABEL_REFERENCE_STATEMENT_RE.match(line):
        return line
    if _FORMAT_STATEMENT_RE.match(line):
        return line
    # Literal-only subexpressions are folded in binary32 first, the way the
    # source's compiler folds them (Curie-G B-L); lifted statements are whole
    # statements, so nothing continues past the end of the text.
    from umat_oti.transform.binary32 import (
        fold_binary32_constants, round_binary32_operations_in_context)
    line = round_binary32_operations_in_context(line)
    line = fold_binary32_constants(line, at_line_end_is_open=False)
    # A literal that already carries an explicit kind -- ``1.0e-10_8`` -- is
    # left exactly as the author wrote it. Its precision is stated, so there
    # is nothing here to widen, and rewriting the exponent letter produces
    # ``1.0D-10_8``: two kind markers on one literal, which gfortran rejects
    # with "Real number has a 'd' exponent and an explicit kind". 141 literals
    # in MohrCoulombAbaqus.for are written that way. The lookahead has to
    # exclude every identifier character, not just the underscore: a bare
    # ``(?!_)`` backtracks -- 1.0e-10_8 then matches as 1.0e-1 with "0_8" left
    # standing -- and produces the same illegal literal by a longer route.
    # A default-REAL literal is a single-precision value, and the original
    # program uses that value: ENU=0.4999 under IMPLICIT REAL*8 stores
    # 0.49990001320838928, not 0.4999. Appending D0 changed the number, and
    # the lifted build's primal drifted from the original's by 3e-8 to 8e-2
    # on 32 corpus sources (Gauss, B1 F3). The literal is rewritten as the
    # double it actually denotes -- the single-rounded value, written exactly
    # -- which is what the store transform already does.
    normalized = re.sub(
        r"(?<!\w)(\d+\.\d*|\.\d+|\d+)[eE]([+-]?\d+)(?![\w.])",
        lambda match: _single_literal_as_double(match.group(0)),
        line,
    )
    normalized = re.sub(
        r"(?<![A-Za-z0-9_])((?:\d+\.\d*)|(?:\d+\.))(?![A-Za-z0-9_.dDeE])",
        lambda match: _single_literal_as_double(
            match.group(1).rstrip(".") + (".0" if match.group(1).endswith(".") else "")),
        normalized,
    )
    # From here on only *bare integers* are promoted. Mask the complete real
    # literals first so their exponent digits are not mistaken for one.
    normalized, literals = mask_real_literals(normalized)
    kept = _integer_division_literals(normalized, integer_name) if integer_name else set()
    normalized = _promote_bare_integers_for_oti(normalized, kept)
    return unmask_real_literals(normalized, literals)


_INTEGER_RESULT_INTRINSICS = frozenset({
    "INT", "NINT", "IDINT", "IFIX", "IDNINT", "FLOOR", "CEILING", "SIZE", "LEN",
    "LEN_TRIM", "ICHAR", "IACHAR", "INDEX"})
#: Generic intrinsics whose result is INTEGER when every argument is.
_INTEGER_IF_ARGUMENTS = frozenset({"MOD", "MAX", "MIN", "ABS", "IABS", "MAX0", "MIN0",
                                   "ISIGN", "SIGN"})
_DIVISION_TOKEN_RE = re.compile(
    r"(?P<name>[A-Za-z_]\w*)|(?P<int>\d+)|(?P<dot>\.[A-Za-z]+\.)"
    r"|(?P<op>\*\*|//|/=|==|<=|>=|[-+*/<>=(),])|(?P<other>\S)")


def _integer_division_literals(line: str, integer_name: Callable[[str], bool]) -> set[int]:
    """Positions of the bare integer literals that are operands of an INTEGER division.

    ``4/DTHREE`` with DTHREE an INTEGER PARAMETER is 1 in the source; promoted
    to ``4.0D0/DTHREE`` it was 1.333 (Vera B5 a5x: primal 1.6e-2, DDSDDE 3 %).
    Promotion exists because an OTI operand has no operator for an INTEGER
    one, but oti_intrinsics defines OTI-with-INTEGER operators and assignment,
    so an integer quotient is left exactly as the source wrote it. Only a
    division both of whose operands are integer -- literals, integer names,
    integer intrinsic results, parenthesised integer expressions -- is kept;
    one with a real or unknown operand is real division either way.
    ``line`` has its real literals masked (private-use characters).
    """
    masked = list(line)
    quote = ""
    for index, char in enumerate(line):
        if quote:
            masked[index] = "\ue7ff"
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
            masked[index] = "\ue7ff"
    tokens = [(m.lastgroup, m.group(), m.start())
              for m in _DIVISION_TOKEN_RE.finditer("".join(masked))]

    def closing(i: int) -> int:
        depth = 0
        for j in range(i, len(tokens)):
            if tokens[j][1] == "(":
                depth += 1
            elif tokens[j][1] == ")":
                depth -= 1
                if depth == 0:
                    return j
        return -1

    def arguments(i: int, j: int) -> list[tuple[int, int]]:
        spans, start, depth = [], i, 0
        for k in range(i, j):
            if tokens[k][1] == "(":
                depth += 1
            elif tokens[k][1] == ")":
                depth -= 1
            elif tokens[k][1] == "," and depth == 0:
                spans.append((start, k))
                start = k + 1
        spans.append((start, j))
        return spans

    def primary(i: int) -> tuple[int, bool, list[int]]:
        """(end, integer?, literal positions) of the primary at i, with any ** chain."""
        if i >= len(tokens):
            return i, False, []
        kind, text, position = tokens[i]
        end, integer, positions = i + 1, False, []
        if kind == "int":
            integer, positions = True, [position]
        elif kind == "name":
            if i + 1 < len(tokens) and tokens[i + 1][1] == "(":
                close = closing(i + 1)
                if close < 0:
                    return len(tokens), False, []
                end = close + 1
                upper = text.upper()
                if upper in _INTEGER_RESULT_INTRINSICS:
                    integer = True
                elif upper in _INTEGER_IF_ARGUMENTS:
                    integer = all(expression(a, b)[0] for a, b in arguments(i + 2, close))
                else:
                    integer = integer_name(upper)  # an element of an INTEGER array
            else:
                integer = integer_name(text.upper())
        elif text == "(":
            close = closing(i)
            if close < 0:
                return len(tokens), False, []
            end = close + 1
            integer, positions = expression(i + 1, close)
        if end < len(tokens) and tokens[end][1] == "**":
            end, right, more = primary(end + 1)
            integer = integer and right
            positions = positions + more
        return end, integer, positions if integer else []

    def expression(i: int, j: int) -> tuple[bool, list[int]]:
        positions: list[int] = []
        expect_operand = True
        while i < j:
            text = tokens[i][1]
            if expect_operand:
                if text in "+-" and tokens[i][0] == "op":
                    i += 1
                    continue
                i, integer, more = primary(i)
                if not integer or i > j:
                    return False, []
                positions += more
                expect_operand = False
            else:
                if text not in ("+", "-", "*", "/"):
                    return False, []
                i += 1
                expect_operand = True
        return not expect_operand, positions

    kept: set[int] = set()
    for k, (kind, text, _) in enumerate(tokens):
        if text != "/" or kind != "op":
            continue
        # The left operand is the multiplicative term ending here: back to the
        # nearest + - , = ( or relational at this depth.
        start, depth = k, 0
        while start > 0:
            previous = tokens[start - 1][1]
            if previous == ")":
                depth += 1
            elif previous == "(":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and previous not in ("*", "/", "**") \
                    and tokens[start - 1][0] not in ("name", "int"):
                break
            start -= 1
        left, left_positions = expression(start, k)
        if not left:
            continue
        _, right, right_positions = primary(k + 1)
        if right:
            kept.update(left_positions)
            kept.update(right_positions)
    return kept


def _contains_oti_name(line: str, oti_names: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(name)}\b", line, re.IGNORECASE) for name in oti_names)


_LITERAL_RHS = re.compile(
    r"^[+-]?\s*(?:\d+\.\d*|\.\d+|\d+)(?:[eEdD][+-]?\d+)?(?:_\w+)?$")


def _initialised_reals_as_named_constants(stitched_lines, form: str, routine_name: str):
    """A REAL local given its value in its declaration, and never written, becomes a PARAMETER.

    ``DOUBLE PRECISION :: ZERO=0.D0, ONE=1.D0`` declares variables (with an
    implied SAVE) that start from those values. Retyped to the OTI type it
    came out as ``type(ONUMM6N1) :: ZERO=0.D0``, which gfortran rejects
    ("Incompatible initialization between a derived type entity and an entity
    with REAL(8) type"): MechMater's UMAT_visco_FGJD_2026.for and
    UMAT_viscohybrid_FGJD_2026.for declare their constants that way in
    DAMAGEVAR. A name that nothing in the routine writes -- no assignment, no
    DO, READ or DATA, no CALL actual -- holds that value for the whole run,
    so declaring it ``PARAMETER`` changes nothing it computes and keeps it
    REAL, as every other named constant is kept. One that is written is
    refused by name: its shadow would need the declared value carried in at
    the first call only, which this lifter does not emit.
    """
    statements = [_statement_text(raw, form) for raw in stitched_lines[1:-1]]
    arrays = _routine_array_names(stitched_lines, form)
    written: set[str] = set()
    for statement in statements:
        text = re.sub(r"^\d+\s+", "", statement.strip())
        upper = text.upper()
        if "::" in text:
            continue
        if re.match(r"^(?:DATA|READ|EQUIVALENCE|NAMELIST)\b", upper):
            written.update(re.findall(r"[A-Z_]\w*", upper))
            continue
        call = re.match(r"^(?:IF\s*\(.*\)\s*)?CALL\s+\w+\s*\((.*)\)\s*$", text, re.IGNORECASE)
        if call:
            written.update(name.upper() for name in re.findall(r"[A-Za-z_]\w*", call.group(1)))
            continue
        loop = re.match(r"^(?:\w+\s*:\s*)?DO\s+(?:\d+\s*,?\s*)?([A-Za-z_]\w*)\s*=", text, re.IGNORECASE)
        if loop:
            written.add(loop.group(1).upper())
            continue
        target = re.match(r"^(?:IF\s*\(.*\)\s*)?([A-Za-z_]\w*)\s*(?:\(.*?\))?\s*=(?!=)", text, re.IGNORECASE)
        if target:
            written.add(target.group(1).upper())
        # A name handed to a function reference can be written through it
        # (``X = BUMP(TEN)`` with BUMP assigning its argument): as a PARAMETER
        # that write crashes under gfortran and may vanish under ifort (Vera,
        # B8 re-review C1). Every identifier inside the argument list of a
        # reference that is neither an intrinsic nor one of this routine's
        # arrays counts as written, as in _literal_constant_locals.
        for match in re.finditer(r"([A-Za-z_]\w*)\s*\(", text):
            if match.group(1).upper() in _INTRINSIC_NAMES or match.group(1).upper() in arrays:
                continue
            depth, start = 0, match.end() - 1
            for position in range(start, len(text)):
                if text[position] == "(":
                    depth += 1
                elif text[position] == ")":
                    depth -= 1
                    if depth == 0:
                        written.update(n.upper() for n in re.findall(r"[A-Za-z_]\w*", text[start:position]))
                        break
    result = list(stitched_lines)
    for index, raw in enumerate(stitched_lines[1:-1], start=1):
        stripped = _statement_text(raw, form)
        if "::" not in stripped:
            continue
        declaration = parse_declaration_line(stripped)
        if (declaration is None or declaration.kind != "real"
                or declaration.has_parameter_attribute
                or any(not a.strip().lower().startswith(("dimension", "save"))
                       for a in declaration.attributes)):
            continue
        initialised = [e for e in declaration.entities if e.initializer is not None]
        if not initialised:
            continue
        clash = sorted(e.upper_name for e in initialised if e.upper_name in written)
        if clash:
            raise HelperLiftingError(
                f"{routine_name} gives {', '.join(clash)} a value in its declaration "
                f"({stripped!r}) and also writes it. That value is an implied "
                f"SAVE initial value, set once before the first call; a "
                f"hypercomplex shadow would need it carried in at the first "
                f"call only, which this lifter does not emit. Not supported.")
        plain = [e for e in declaration.entities if e.initializer is None]
        attributes = [a.strip() for a in declaration.attributes
                      if not a.strip().lower().startswith("save")]
        prefix = ", ".join([declaration.raw_type, *attributes, "PARAMETER"])
        lines = [f"      {prefix} :: {', '.join(e.render() for e in initialised)}"]
        if plain:
            plain_prefix = ", ".join([declaration.raw_type, *attributes])
            lines.append(f"      {plain_prefix} :: {', '.join(e.render() for e in plain)}")
        result[index] = "\n".join(lines)
    return [line for chunk in result for line in str(chunk).split("\n")]


def _literal_constant_locals(stitched_lines, form: str, args, common_names) -> set[str]:
    """Scalar locals whose every assignment is a numeric literal.

    Excluded: dummy arguments, anything with a shape, COMMON/EQUIVALENCE/DATA
    members, names read by a READ, and any name that appears inside the
    argument list of a CALL or of a reference that is not obviously an
    intrinsic -- a lifted callee may type that dummy OTI, and a REAL actual
    against it is exactly the leak the transform refuses elsewhere.
    """
    statements = [_statement_text(raw, form) for raw in stitched_lines[1:-1]]
    dummies = {str(arg).upper() for arg in args}
    arrays = _routine_array_names(stitched_lines, form)
    assigned: dict[str, bool] = {}
    excluded: set[str] = set(dummies) | set(arrays) | {str(n).upper() for n in common_names}
    for statement in statements:
        text = re.sub(r"^\d+\s+", "", statement.strip())
        upper = text.upper()
        if re.match(r"^(?:EQUIVALENCE|DATA|COMMON|NAMELIST|READ)\b", upper):
            excluded.update(re.findall(r"[A-Z_]\w*", upper))
            continue
        call = re.match(r"^CALL\s+\w+\s*\((.*)\)\s*$", text, re.IGNORECASE)
        if call:
            excluded.update(name.upper() for name in re.findall(r"[A-Za-z_]\w*", call.group(1)))
            continue
        target = re.match(r"^(?:IF\s*\(.*\)\s*)?([A-Za-z_]\w*)\s*=(?!=)\s*(.*)$", text, re.IGNORECASE)
        if target:
            name = target.group(1).upper()
            literal = bool(_LITERAL_RHS.match(target.group(2).strip()))
            assigned[name] = assigned.get(name, True) and literal
            rhs = target.group(2)
        else:
            rhs = text
        for match in re.finditer(r"([A-Za-z_]\w*)\s*\(", rhs):
            if match.group(1).upper() in _INTRINSIC_NAMES or match.group(1).upper() in arrays:
                continue
            depth, start = 0, match.end() - 1
            for index in range(start, len(rhs)):
                if rhs[index] == "(":
                    depth += 1
                elif rhs[index] == ")":
                    depth -= 1
                    if depth == 0:
                        excluded.update(n.upper() for n in re.findall(r"[A-Za-z_]\w*", rhs[start:index]))
                        break
    return {name for name, literal in assigned.items() if literal and name not in excluded}


def _data_initialisation_once(assignments: list[str], saved_names: set[str],
                              save_everything: bool, common_names: set[str]) -> list[str]:
    """DATA, as executable statements that still run once.

    DATA gives a variable its value before the first call and implies SAVE; it
    is not executed on every call. A lifted body cannot keep the DATA
    statement itself -- a DATA value cannot initialise the OTI derived type --
    so the values are assigned under a flag that is true only on the first
    call, and every DATA'd name is SAVEd. Assigning them on every call, as
    this used to, reset a SAVEd first-call switch (``DATA INIT /.FALSE./``)
    each time and re-ran the initialisation it guards.
    """
    if not assignments:
        return []
    names = []
    for line in assignments:
        target = re.match(r"^\s*([A-Za-z_]\w*)", line)
        if target and target.group(1).upper() not in names:
            names.append(target.group(1).upper())
    out = []
    to_save = [name for name in names
               if name not in saved_names and name not in common_names]
    if to_save and not save_everything:
        out.append(f"    save :: {', '.join(name.lower() for name in to_save)}")
    # Initialised in its declaration, which implies SAVE without the attribute
    # (an attribute would conflict with a bare SAVE statement).
    out.append("    logical :: oti_data_done = .false.")
    out.append("    if (.not. oti_data_done) then")
    out.extend("  " + line for line in assignments)
    out.append("      oti_data_done = .true.")
    out.append("    end if")
    return out


def _declared_result_is_binary32(type_spec: str) -> bool:
    """A function header's type-spec of default REAL or kind 4."""
    from umat_oti.transform.routine_typing import _is_single_spec

    return _is_single_spec(type_spec)


def _single_literal_as_double(text: str) -> str:
    """A default-REAL literal written as the double value it denotes.

    ``0.4999`` -> ``0.49990001320838928D0``; ``0.5`` -> ``0.5D0``; ``1.5e-3``
    -> the single-rounded value with a D exponent. Exact, so a lifted body
    computes with the same constants as the source it came from.
    """
    from umat_oti.transform.source_transform import _as_written_in_double

    return _as_written_in_double(text)


def _normalize_real_literal(value: str) -> str:
    promoted = re.sub(r"(?<!\w)(\d+\.\d*|\.\d+|\d+)[eE]([+-]?\d+)(?![\w.])",
                      lambda match: _single_literal_as_double(match.group(0)), value)
    return re.sub(r"(?<![A-Za-z0-9_])(\d+\.\d*|\.\d+)(?![A-Za-z0-9_.dDeE])",
                  lambda match: _single_literal_as_double(match.group(1)), promoted)


def _data_to_assignments(payload: str,
                         declared_extents: dict[str, tuple[int, ...]] | None = None) -> list[str]:
    groups: list[tuple[str, str]] = []
    current: list[str] = []
    names = ""
    in_values = False
    for char in payload:
        if char == "/":
            if not in_values:
                names = "".join(current).strip().rstrip(",")
                current = []
                in_values = True
            else:
                groups.append((names, "".join(current).strip()))
                current = []
                names = ""
                in_values = False
            continue
        current.append(char)
    assignments: list[str] = []
    for names_text, values_text in groups:
        name_entries = [entry.strip() for entry in split_top_level(names_text) if entry.strip()]
        value_entries: list[str] = []
        for entry in split_top_level(values_text):
            clean = entry.strip()
            repeat = re.match(r"^(\d+)\s*\*\s*(.+)$", clean)
            if repeat:
                value_entries.extend([repeat.group(2).strip()] * int(repeat.group(1)))
            else:
                value_entries.append(clean)
        if len(value_entries) == 1 and len(name_entries) > 1:
            value_entries = value_entries * len(name_entries)
        # One bare array name against many values is the Fortran 77 way to
        # initialise a whole array: DATA AMPLITUDE_FACTOR/ 0.08, 0.22, ... /
        # for a DIMENSION AMPLITUDE_FACTOR(12,12). Counting names against
        # values called that a shape mismatch and refused the source. The
        # values are laid down in array element order, which is what
        # _column_major_subscript writes out, so each one becomes a scalar
        # assignment to the element it was always going to initialise.
        if len(name_entries) == 1 and len(value_entries) > 1:
            extents = (declared_extents or {}).get(
                name_entries[0].split("(", 1)[0].strip().upper())
            expected = 1
            for extent in extents or ():
                expected *= extent
            if extents and expected == len(value_entries):
                for offset, value in enumerate(value_entries):
                    subscript = _column_major_subscript(offset, extents)
                    assignments.append(
                        f"{name_entries[0]}({subscript}) = {_normalize_real_literal(value)}")
                continue
        if len(value_entries) != len(name_entries):
            raise HelperLiftingError(
                f"Unsupported DATA statement shape: {payload!r}. A lifted "
                f"helper turns DATA into assignments and handles whole "
                f"arrays and name/value lists, not array sections. What to "
                f"do: write that DATA as assignments (or one whole-array "
                f"DATA) in the source.")
        for name, value in zip(name_entries, value_entries):
            assignments.append(f"{name} = {_normalize_real_literal(value)}")
    return assignments


def _is_implicit_integer_name(name: str) -> bool:
    return bool(name) and name[0].upper() in _IMPLICIT_INTEGER_FIRST_LETTERS


#: Statements whose integers are statement labels, not values. Promoting one
#: turns ``GOTO 999`` into ``GOTO 999.0D0``, which is not a label and not a
#: number: eight sources failed to compile on exactly this.
_LABEL_BEARING_STATEMENT = re.compile(
    r"(?:^|[);,]\s*|\bTHEN\s+)\s*(?:GO\s*TO\b|ASSIGN\b)|"
    r"^\s*(?:\d+\s+)?IF\s*\(.*\)\s*\d+\s*,\s*\d+\s*,\s*\d+\s*$",
    re.IGNORECASE)


def _promote_bare_integers_for_oti(line: str, kept: set[int] | frozenset[int] = frozenset()) -> str:
    if not line.strip() or not any(char.isdigit() for char in line):
        return line
    if re.match(r"^\s*DO\b", line, re.IGNORECASE):
        return line
    # A GOTO target, an ASSIGN target and the three branches of an arithmetic
    # IF are labels. There is no value in them to promote.
    if _LABEL_BEARING_STATEMENT.search(line):
        return line
    out: list[str] = []
    paren_stack: list[bool] = []
    index = 0
    while index < len(line):
        char = line[index]
        if char == "(":
            cursor = len(out) - 1
            while cursor >= 0 and out[cursor] == " ":
                cursor -= 1
            paren_stack.append(cursor >= 0 and bool(re.match(r"[A-Za-z0-9_]", out[cursor])))
            out.append(char)
            index += 1
            continue
        if char == ")":
            if paren_stack:
                paren_stack.pop()
            out.append(char)
            index += 1
            continue
        if char.isdigit():
            previous = line[index - 1] if index > 0 else ""
            if previous.isalnum() or previous in {"_", "."}:
                out.append(char)
                index += 1
                continue
            # The digits after an exponent's sign belong to the literal that
            # opened it. ``1.0D-6`` came out as ``1.0D-6.0D0``: the minus sign
            # reads as an operator, and the exponent reads as a bare integer
            # standing next to it.
            if previous in {"+", "-"} and index >= 2 and line[index - 2] in "dDeE" \
                    and index >= 3 and (line[index - 3].isdigit() or line[index - 3] == "."):
                out.append(char)
                index += 1
                continue
            end = index
            while end < len(line) and line[end].isdigit():
                end += 1
            if end < len(line) and line[end] in ".eEdD":
                out.append(line[index:end])
                index = end
                continue
            literal = line[index:end]
            if index in kept:
                # An operand of an INTEGER division: see _integer_division_literals.
                out.append(literal)
                index = end
                continue
            left = index - 1
            while left >= 0 and line[left] == " ":
                left -= 1
            right = end
            while right < len(line) and line[right] == " ":
                right += 1
            prev_char = line[left] if left >= 0 else ""
            next_char = line[right] if right < len(line) else ""
            # ``next_char in "+-*/"`` reads as "is it an operator", and for
            # an empty string Python answers yes -- so every integer that
            # ended a line was promoted, whatever it meant, and that is how
            # ``GOTO 999`` became ``GOTO 999.0D0``. The end of a line is a
            # real case and it is kept, but as itself: an integer that ends a
            # statement is the value being assigned, and an OTI variable has
            # no overload that takes an integer.
            neighbours_an_operator = ((prev_char and prev_char in "+-*/")
                                      or (next_char and next_char in "+-*/")
                                      or (not next_char and "=" in line))
            if not any(paren_stack) and neighbours_an_operator:
                out.append(f"{literal}.0D0")
            else:
                out.append(literal)
            index = end
            continue
        out.append(char)
        index += 1
    return "".join(out)


_CONTAINS_RE = re.compile(r"^\s*CONTAINS\s*$", re.IGNORECASE)
_INTERNAL_HEADER_RE = re.compile(
    r"^\s*(?:(?:PURE|IMPURE|ELEMENTAL|RECURSIVE)\s+|(?:REAL|INTEGER|LOGICAL|COMPLEX|"
    r"DOUBLE\s+PRECISION|CHARACTER|TYPE\s*\([^)]*\))(?:\s*\([^)]*\)|\s*\*\s*\d+)?\s+)*"
    r"(SUBROUTINE|FUNCTION)\s+([A-Z_]\w*)\s*(?:\(([^)]*)\))?"
    r"(?:\s*RESULT\s*\(\s*([A-Z_]\w*)\s*\))?", re.IGNORECASE)
_INTERNAL_END_RE = re.compile(r"^\s*END\s*(?:SUBROUTINE|FUNCTION)\b", re.IGNORECASE)
#: Words of the language (statement keywords, attributes and the intrinsics a
#: model routine commonly calls) that are never a host entity. Only used to
#: decide whether an internal procedure reads its host; a word missing here
#: makes that check refuse more, never less.
_FORTRAN_WORDS = frozenset("""
REAL INTEGER LOGICAL CHARACTER DOUBLE PRECISION COMPLEX TYPE INTENT IN OUT INOUT
PARAMETER DIMENSION IMPLICIT NONE USE ONLY SAVE DATA WHILE EXIT CYCLE SELECT CASE
DEFAULT WHERE ELSEWHERE FORALL ALLOCATE DEALLOCATE ALLOCATABLE OPTIONAL PURE
ELEMENTAL RECURSIVE RESULT FUNCTION SUBROUTINE CONTAINS STOP PRINT WRITE READ FORMAT
OPEN CLOSE ELSEIF ENDDO ENDIF ENDSELECT ENDWHERE MATMUL TRANSPOSE SUM PRODUCT MAXVAL
MINVAL MAXLOC MINLOC DBLE FLOAT SNGL INT NINT IFIX IDINT FLOOR CEILING DSQRT DEXP
DLOG DLOG10 DABS DSIN DCOS DTAN DASIN DACOS DATAN DATAN2 DSINH DCOSH DTANH DMAX1
DMIN1 AMAX1 AMIN1 MAX0 MIN0 DSIGN ISIGN IABS MERGE RESHAPE SPREAD PACK UNPACK COUNT
CSHIFT EOSHIFT TRIM ADJUSTL ADJUSTR INDEX SCAN VERIFY CHAR ICHAR ACHAR IACHAR
NORM2 DPROD AINT ANINT DINT DNINT CMPLX DCMPLX AIMAG CONJG
""".split())


def _without_internal_procedures(raw_lines: list[str], form: str, routine: ParsedSubroutine,
                                 lifted: set[str]) -> list[str]:
    """The host routine up to its CONTAINS, and its END.

    The parser keeps internal procedures inside their host, and the lifter
    read their specification statements as the host's: GuGuaTT's UMAT2 holds
    ``pure function dotprod6(A, B) result(C)`` after CONTAINS, and the lifted
    UMAT2_OTI declared A(6), B(6) and C beside its own scalar A ("Symbol 'a'
    already has basic type"). Every internal procedure is lifted on its own as
    an external subprogram (routines_by_name finds function subprograms
    wherever they are written), so the host's lifted copy calls that one, and
    the CONTAINS section is dropped from it.

    That is only the same program when the internal procedure reads nothing of
    its host but named constants (carried, see
    host_constants_for_internal_procedures): the lifted copy is typed from its
    own text, and a host variable it read could become an uninitialised local
    of its own. That case is refused, as is an internal procedure the closure
    did not lift. The lifted copies go back after CONTAINS in the lifted host
    (_nest_internal_procedures).
    """
    contains_at = None
    for index, raw in enumerate(raw_lines[1:-1], start=1):
        if _CONTAINS_RE.match(_statement_text(raw, form)):
            contains_at = index
            break
    if contains_at is None:
        return raw_lines
    host_names = {arg.upper() for arg in routine.args}
    for declaration in routine.declarations:
        host_names.update(entity.upper_name for entity in declaration.entities)
    host_text = "\n".join(_statement_text(raw, form) for raw in raw_lines[1:contains_at])
    # Implicitly typed locals are declared nowhere; every name the host's
    # statements mention is a host entity unless it is Fortran's own.
    host_names.update(
        token.upper() for token in _TOKEN_RE.findall(
            mask_real_literals(mask_character_literals(host_text)[0])[0])
        if token.upper() not in _KEYWORDS | _INTRINSIC_NAMES | _INQUIRY_INTRINSICS | _FORTRAN_WORDS
        and token.upper() not in _TYPED_INTRINSIC_MAP)
    internal = [_statement_text(raw, form) for raw in _continuation_stitch(raw_lines[contains_at + 1:-1], form)]
    procedures: list[tuple[str, set[str], list[str]]] = []
    for statement in internal:
        header = _INTERNAL_HEADER_RE.match(statement)
        if header and not _INTERNAL_END_RE.match(statement):
            own = {header.group(2).upper()}
            own.update(a.strip().upper() for a in (header.group(3) or "").split(",") if a.strip())
            if header.group(4):
                own.add(header.group(4).upper())
            procedures.append((header.group(2).upper(), own, []))
        elif procedures and not _INTERNAL_END_RE.match(statement):
            procedures[-1][2].append(statement)
    # The host's arrays: ``A(I)=...`` in an internal procedure is an element
    # of one of them, not a statement function.
    host_arrays = {entity.upper_name for declaration in routine.declarations
                   for entity in declaration.entities if entity.dimensions}
    for statement in host_text.splitlines():
        dimension = re.match(r"^\s*DIMENSION\b(.*)$", statement, re.IGNORECASE)
        if dimension:
            host_arrays.update(entity.strip().split("(", 1)[0].strip().upper()
                               for entity in split_top_level(dimension.group(1)) if "(" in entity)
    for name, own, body in procedures:
        arrays: set[str] = set()
        for statement in body:
            declared_shape = re.match(r"^\s*(?:DIMENSION\b|[^=]*::)(.*)$", statement, re.IGNORECASE)
            if declared_shape:
                arrays.update(entity.strip().split("(", 1)[0].strip().upper()
                              for entity in split_top_level(declared_shape.group(1))
                              if "(" in entity.split("=", 1)[0])
        for statement in body:
            function = re.match(r"^\s*([A-Z_]\w*)\s*\(\s*(?:[A-Z_]\w*\s*(?:,\s*[A-Z_]\w*\s*)*)?\)\s*=(?!=)",
                                statement, re.IGNORECASE)
            if function and function.group(1).upper() not in arrays | host_arrays:
                # Lifted, it was written as an assignment to an undeclared
                # array and did not compile, while the transform reported
                # success (Vera B5 T3 i_sf_dummy, i_sf_name).
                raise HelperLiftingError(
                    f"The internal procedure {name} of {routine.name} defines the "
                    f"statement function {function.group(1).upper()}. A statement "
                    "function in an internal procedure is not supported by the "
                    "lifter. What to do: write it as an internal FUNCTION, or "
                    "inline it.")
        if re.search(rf"\b{name}\b", host_text, flags=re.IGNORECASE) and name not in lifted:
            raise HelperLiftingError(
                f"{routine.name} contains the internal procedure {name}, which "
                "it calls but which was not lifted with it. What to do: move "
                f"{name} out of {routine.name} (after its END) so it can be "
                "lifted as a helper of its own.")
        declared = set(own)
        for statement in body:
            match = re.match(r"^\s*(?:REAL|INTEGER|LOGICAL|DOUBLE\s+PRECISION|CHARACTER|COMPLEX|TYPE\s*\()"
                             r"[^:]*::\s*(.*)$", statement, flags=re.IGNORECASE)
            if match:
                declared.update(_declared_names(match.group(1)))
        used = {token.upper() for statement in body
                for token in _TOKEN_RE.findall(
                    mask_real_literals(mask_character_literals(statement)[0])[0])}
        procedure_names = {other for other, _, _ in procedures} | lifted
        borrowed = sorted((used & host_names) - declared - procedure_names
                          - _host_named_constants(raw_lines[1:contains_at], form))
        if borrowed:
            raise HelperLiftingError(
                f"The internal procedure {name} of {routine.name} reads "
                f"{', '.join(borrowed[:5])} from its host. The lifter types "
                "and declares each procedure from its own text, so a host "
                "variable read by host association could become a local of the "
                "lifted copy, uninitialised, with nothing to show for it. Not "
                "supported. What to do: pass them to "
                f"{name} as arguments (host PARAMETERs are carried and need nothing).")
    return raw_lines[:contains_at] + raw_lines[-1:]


_PARAMETER_DECLARATION_RE = re.compile(
    r"^\s*(?:[A-Z][\w\s*()=,]*?,\s*PARAMETER\b[^:]*::|PARAMETER\s*\()", re.IGNORECASE)


def _host_constant_statements(host_lines: list[str], form: str) -> list[str]:
    """The host's named-constant statements, stitched, in source order."""
    return [statement for statement in _continuation_stitch(host_lines, form)
            if _PARAMETER_DECLARATION_RE.match(_statement_text(statement, form))]


def _host_named_constants(host_lines: list[str], form: str) -> set[str]:
    names: set[str] = set()
    for statement in _host_constant_statements(host_lines, form):
        text = _statement_text(statement, form)
        payload = text.split("::", 1)[1] if "::" in text else text[text.index("(") + 1:text.rindex(")")]
        names.update(_declared_names(payload))
    return names


def _carried_host_constants(host_constants: Sequence[str], stitched_lines: list[str],
                            form: str, routine: ParsedSubroutine) -> list[str]:
    """The host's named constants an internal procedure sees, one statement each.

    Carried per NAME. A name the procedure declares itself -- a dummy, its
    result, a local -- hides the host's constant of that name and only that
    one: dropping the whole host statement because one of its names was
    hidden left ``TWO`` of ``PARAMETER(..., TWO=2.0D0, THREE=3.0D0, ...)``
    undeclared in a DOTPROD6 that declared a local THREE, an uninitialised
    local in the lifted copy (UVCmultiaxial; Vera B5: stress 4-6 %, DDSDDE
    43 % off). A carried value that refers to a hidden name would be
    evaluated against the procedure's own entity, not the host's constant:
    refused.
    """
    hidden = {arg.upper() for arg in routine.args} | {routine.upper_name}
    for declaration in routine.declarations:
        hidden.update(entity.upper_name for entity in declaration.entities)
    header = _INTERNAL_HEADER_RE.match(_statement_text(stitched_lines[0], form))
    if header:
        hidden.update(a.strip().upper() for a in (header.group(3) or "").split(",") if a.strip())
        if header.group(4):
            hidden.add(header.group(4).upper())
    for line in stitched_lines[1:-1]:
        text = _statement_text(line, form)
        for payload in re.findall(r"::\s*(.*)$", text):
            hidden.update(_declared_names(payload))
        dimension = _DIMENSION_RE.match(text)
        if dimension:
            hidden.update(_declared_names(dimension.group(1)))
        declaration = parse_declaration_line(text)
        if declaration is not None:
            hidden.update(entity.upper_name for entity in declaration.entities)
    # Its own named constants hide the host's just as well.
    hidden |= _parameter_statement_names(stitched_lines[1:-1], form)
    carried: list[str] = []
    for statement in host_constants:
        text = _statement_text(statement, form)
        payload = (text.split("::", 1)[1] if "::" in text
                   else text[text.index("(") + 1:text.rindex(")")])
        for entity in split_top_level(payload):
            if "=" not in entity:
                continue
            name, value = (part.strip() for part in entity.split("=", 1))
            if name.upper() in hidden:
                continue
            uses = {token.upper() for token in _TOKEN_RE.findall(
                mask_real_literals(mask_character_literals(value)[0])[0])}
            if uses & hidden:
                raise HelperLiftingError(
                    f"The host constant {name} = {value}, which the internal "
                    f"procedure {routine.name} sees by host association, is "
                    f"defined through {', '.join(sorted(uses & hidden))}, a name "
                    f"{routine.name} declares for itself. Declared in the lifted "
                    f"copy, the definition would read {routine.name}'s own entity "
                    "instead of the host's constant. Not supported. What to do: "
                    f"rename that entity in {routine.name}.")
            if "::" in text:
                carried.append(f"      {text.split('::', 1)[0].strip()} :: {entity.strip()}")
            else:
                carried.append(f"      PARAMETER ({entity.strip()})")
    return carried


def host_constants_for_internal_procedures(parsed: ParsedFortranSource) -> dict[str, list[str]]:
    """For each internal procedure, the named constants of its host.

    An internal procedure sees its host's PARAMETERs by host association; the
    lifted external copy does not (GuGuaTT's DOTPROD6 multiplies by the
    host's TWO, and its lifted copy read an uninitialised local TWO). A named
    constant cannot change, so declaring the same constant in the copy is the
    same program. Variables of the host are a different matter and are refused
    by _without_internal_procedures.
    """
    source_lines = parsed.text.splitlines()
    hosts = {routine.upper_name: routine for routine in parsed.subroutines}
    result: dict[str, list[str]] = {}
    for internal, host_name in internal_procedure_hosts(parsed).items():
        raw = _routine_source_lines(source_lines, hosts[host_name])
        contains_at = next(index for index, line in enumerate(raw[1:-1], start=1)
                           if _CONTAINS_RE.match(_statement_text(line, parsed.form)))
        constants = _host_constant_statements(raw[1:contains_at], parsed.form)
        if constants:
            result[internal] = constants
    return result


def _routine_source_lines(source_lines: list[str], routine: ParsedSubroutine) -> list[str]:
    if not routine.lines:
        return []
    start = routine.lines[0].line_numbers[0]
    end = routine.lines[-1].line_numbers[-1]
    return source_lines[max(start - 1, 0) : min(end, len(source_lines))]


def _statement_text(raw: str, form: str) -> str:
    if form != "fixed":
        return strip_inline_comment(raw).strip()
    return _split_label_and_statement(raw, form)[1]


def _split_label_and_statement(raw: str, form: str) -> tuple[str, str]:
    if form != "fixed":
        return "", strip_inline_comment(raw).strip()
    clean = _strip_fixed_form_comment(raw)
    if not clean:
        return "", ""
    expanded = _expand_fixed_form_tabs(clean)
    label_field = expanded[:5].strip() if len(expanded) >= 5 else ""
    statement = expanded[6:] if len(expanded) > 6 else ""
    label_prefix = f"{label_field} " if label_field else ""
    return label_prefix, statement.strip()


def _strip_fixed_form_comment(line: str) -> str:
    """Drop a trailing comment, leaving character literals intact.

    A bang inside a quoted string does not start a comment. Splitting on the
    first bang regardless truncated ``'...slip planes!'`` mid-literal and the
    lifted source then failed with "Unterminated character constant". The
    quote-aware scanner in :mod:`umat_oti.fortran.normalize` is the one the
    logical-line parser already uses, so both see the same statement text.
    """
    if not line:
        return ""
    if line[0] in {"C", "c", "*", "!"}:
        return ""
    return strip_inline_comment(line)


def _expand_fixed_form_tabs(raw: str) -> str:
    """A tab anywhere in the label field puts the statement in column 7.

    This read only a tab in column 1. SinglePointSimulator's MODIFIED_JC.f
    writes `` <TAB>  if (noel.eq.1) then`` -- a blank, then the tab -- which
    ifort and gfortran read as a statement, and the lifter read as a
    continuation (column 6 held an 'f'), stitching it onto the previous line
    as ``temp = tempsv (noel.eq.1) then``. The parser's rule is the one both
    compilers follow, so it is used here.
    """
    from umat_oti.fortran.parser import expand_fixed_form_tabs

    return expand_fixed_form_tabs(raw)


#: The widest source line the emitted free-form Fortran may contain.
#: gfortran is given ``-ffree-line-length-none`` and does not care, but Abaqus
#: compiles user subroutines with ifort, which truncates at 7200 characters and
#: then fails on the wreckage. A source whose fixed-form continuations are
#: stitched into one free-form statement can exceed that easily: a symbolic
#: 6x6 determinant came out as a single line of 14858 characters. 120 is well
#: inside every limit and keeps the output readable.
FREE_FORM_LINE_WIDTH = 120


def wrap_free_form(source: str, width: int = FREE_FORM_LINE_WIDTH) -> str:
    """Re-wrap over-long free-form statements onto continuation lines.

    Splits only outside character literals, and only after a character that
    can legally end a fragment, so a name, a number or a string is never cut
    in half. A line that cannot be split safely is left as it is: emitting it
    whole and letting the compiler complain is better than emitting something
    subtly different.
    """
    out: list[str] = []
    for line in source.splitlines():
        if len(line) <= width or line.lstrip().startswith("!"):
            out.append(line)
            continue
        out.extend(_split_statement(line, width))
    return "\n".join(out) + ("\n" if source.endswith("\n") else "")


#: Two-character tokens a break must not fall inside. Splitting "**" across
#: a free-form continuation leaves "* &" / "*2.0D0", which is two operators:
#: keisuke58/pde-fem-biofilm's two-channel model came out as
#: "BE(2,3)* &" + "*2.0D0" and stopped at "Expected a right parenthesis".
_UNSPLITTABLE_PAIRS = frozenset({"**", "//", "/)", "==", "/=", "<=", ">=", "=>"})
_EXPONENT_TAIL = re.compile(r"(?<![A-Za-z_])\d+\.?\d*[EeDd]$")


def _break_after_is_safe(body: str, index: int) -> bool:
    """Whether a continuation may start right after ``body[index]``."""
    pair = body[index:index + 2]
    if len(pair) == 2 and pair in _UNSPLITTABLE_PAIRS:
        return False
    if index > 0 and body[index - 1:index + 1] in _UNSPLITTABLE_PAIRS:
        # The second character of a pair is a safe end ("**" then operand).
        return True
    # The sign of a literal's exponent: 1.0D-3 is one token.
    return not (body[index] in "+-" and _EXPONENT_TAIL.search(body[:index]))


def _split_statement(line: str, width: int) -> list[str]:
    indent = line[: len(line) - len(line.lstrip())]
    body = line[len(indent):]
    continuation_indent = indent + "  "
    pieces: list[str] = []
    current = indent
    quote: str | None = None
    last_break = -1          # index in `current` just past the last safe split
    for index, char in enumerate(body):
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        current += char
        # Safe to break after an operator or separator at depth-agnostic level;
        # breaking after ")" or a name would risk splitting a keyword pair.
        if quote is None and char in "+-*/,=)" and _break_after_is_safe(body, index):
            last_break = len(current)
        if len(current) >= width and last_break > len(indent) + 1:
            pieces.append(current[:last_break].rstrip() + " &")
            current = continuation_indent + current[last_break:].lstrip()
            last_break = -1
    if current.strip():
        pieces.append(current)
    elif pieces and pieces[-1].endswith(" &"):
        # The last safe break was the statement's own last character, so the
        # remainder is nothing but the continuation indent. Leaving the "&" on
        # the piece before it promises a continuation line that is never
        # emitted, and gfortran then reads whatever statement follows as part
        # of this one: a lifted header wrapped this way was joined to its own
        # "use otim6n1" line and reported as "Syntax error in SUBROUTINE
        # statement". Nothing continues, so nothing says it does.
        pieces[-1] = pieces[-1][: -len(" &")].rstrip()
    return pieces or [line]


def _free_form_continuation_stitch(lines: list[str]) -> list[str]:
    """Free-form lines joined at their trailing ``&`` into whole statements.

    Free form was previously passed through a filter and nothing else, so a
    statement written across several lines reached the lifter as several
    fragments. The first fragment of

        subroutine j2_isotropic_3d(E, nu, sigma_y0, H, &
                                   stress, statev, ddsdde)

    is not a subroutine header any regular expression can read, and the lift
    stopped with "Cannot parse helper header"; a PARAMETER statement split the
    same way handed ``&`` to the entry splitter as if it were a named
    constant. Five corpus sources -- two ``.for`` files written in free form
    with tab indentation, three ``.f90`` -- were refused for one of those two
    reasons alone.

    This is the rule :func:`umat_oti.fortran.parser._free_logical_lines`
    already applies, kept in step with it: the ``&`` is dropped, a leading
    ``&`` on the continuation is dropped as well, and the halves are joined
    with one space. Comment and blank lines between continuations do not break
    the statement, which is what the standard says and what sources in the
    wild do.
    """
    merged: list[str] = []
    pending = ""
    for raw in lines:
        clean = strip_inline_comment(raw).rstrip()
        if not clean.strip():
            continue
        continued = clean.endswith("&")
        if continued:
            clean = clean[:-1].rstrip()
        if pending:
            part = clean.lstrip()
            if part.startswith("&"):
                part = part[1:].lstrip()
            pending = f"{pending} {part}".rstrip() if part else pending
        else:
            pending = clean.strip()
        if not continued:
            if pending:
                merged.append(pending)
            pending = ""
    if pending:
        merged.append(pending)
    return merged


def _continuation_stitch(lines: list[str], form: str) -> list[str]:
    if form != "fixed":
        return _free_form_continuation_stitch(lines)
    merged: list[str] = []
    for raw in lines:
        raw = _expand_fixed_form_tabs(raw)
        clean = _strip_fixed_form_comment(raw)
        if not clean.strip():
            continue
        if merged and len(raw) >= 6 and raw[5] not in {" ", "0"} and raw[0] not in {"C", "c", "*", "!"}:
            merged[-1] = _joined_fixed_continuation(merged[-1], clean[6:])
            continue
        merged.append(clean)
    # Blanks are insignificant in fixed form, so ``double precision : : x``
    # (MechMater's UMAT_viscohybrid_FGJD_2026.for) is ``::``. Emitted free
    # form, where blanks matter, it came out ``type(ONUMM6N1) :: : : damping``.
    # Outside character literals ``: :`` can only ever be ``::`` -- an array
    # section ``A(1: :2)`` is ``A(1::2)`` too -- so the collapse is exact.
    return [_colons_joined(line) for line in merged]


#: Words after which a fixed-form continuation starts a new token. Joined
#: without a blank, ``CALL`` + ``FOO(X)`` would come out ``CALLFOO(X)``, which
#: free form -- the lifted helpers' form -- does not read as a CALL.
_KEYWORDS_BEFORE_A_BREAK = frozenset({
    "CALL", "GOTO", "GO", "TO", "DO", "IF", "THEN", "ELSE", "ELSEIF", "END",
    "RETURN", "STOP", "PAUSE", "CONTINUE", "REAL", "DOUBLE", "PRECISION",
    "INTEGER", "LOGICAL", "CHARACTER", "COMPLEX", "DIMENSION", "COMMON",
    "DATA", "EXTERNAL", "INTRINSIC", "SAVE", "PARAMETER", "IMPLICIT", "NONE",
    "READ", "WRITE", "PRINT", "FORMAT", "ENTRY", "INCLUDE", "TYPE", "USE",
    "FUNCTION", "SUBROUTINE", "RESULT", "ALLOCATE", "DEALLOCATE", "WHERE",
    "FORALL", "SELECT", "CASE", "INTENT", "OPTIONAL", "ALLOCATABLE", "CYCLE",
    "EXIT", "WHILE", "AND", "OR", "NOT", "EQ", "NE", "LT", "LE", "GT", "GE",
    "EQV", "NEQV", "TRUE", "FALSE", "PROCEDURE", "INTERFACE", "MODULE",
})


def _joined_fixed_continuation(left: str, right: str) -> str:
    """One fixed-form statement from a line and its continuation, for free-form output.

    Blanks are insignificant in fixed form, so a break can fall inside a
    name or a number: Jeff97's shell sources end a line ``...G12*G23*G3`` and
    continue ``1+G13*G21*G32...``, and the name is ``G31``. Joined with a
    blank, the lifted (free-form) helper read ``G3 1+...``, and the Petal and
    SeaShell provider builds failed on "G3 1.0D0" once the literal pass had
    rewritten the 1 (Noether's B8 RA run). The emitter's own join
    (source_transform._join_continuations) already omits the blank.

    So: inside an open character literal the line is padded to column 72
    and the continuation's columns 7-72 appended, as the compilers read it; a break between two name or number characters is closed up,
    unless the word before it is a keyword (``CALL`` / ``FOO(X)``), where the
    blank separates two tokens; everywhere else one blank is put, which no
    free-form token boundary minds.
    """
    masked, _ = mask_character_literals(left)
    if masked.count("'") % 2 or masked.count('"') % 2:
        # Inside a character literal every column counts: the compilers pad
        # a short line with blanks to column 72 and take the continuation
        # from column 7, so the text is laid out on that grid.
        width = 72 if len(left) <= 72 else 72 + 66 * -(-(len(left) - 72) // 66)
        return left.ljust(width) + right[:66]
    head, tail = left.rstrip(), right.strip()
    if not head or not tail:
        return (head + " " + tail).strip()
    word = re.search(r"[A-Za-z0-9_]+$", head)
    if (word and re.match(r"[A-Za-z0-9_]", tail)
            and word.group(0).upper() not in _KEYWORDS_BEFORE_A_BREAK):
        return head + tail
    return head + " " + tail


def _colons_joined(line: str) -> str:
    if ":" not in line or not re.search(r":\s+:", line):
        return line
    masked, store = mask_character_literals(line)
    return unmask_character_literals(re.sub(r":\s+:", "::", masked), store)