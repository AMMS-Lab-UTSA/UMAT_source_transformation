from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Sequence

from umat_oti.core.model import ParsedFortranSource, ParsedSubroutine
from umat_oti.fortran.literals import (
    mask_character_literals,
    mask_real_literals,
    unmask_character_literals,
    unmask_real_literals,
    without_real_literals,
)
from umat_oti.fortran.normalize import strip_inline_comment
from umat_oti.fortran.parser import (
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


_HEADER_RE = re.compile(r"^\s*SUBROUTINE\s+([A-Z_][A-Z0-9_]*)\s*\((.*)\)\s*$", re.IGNORECASE)
_CALL_RE = re.compile(r"\bCALL\s+([A-Z_][A-Z0-9_]*)\s*\(", re.IGNORECASE)
_PARAMETER_RE = re.compile(r"^\s*PARAMETER\s*\((.*)\)\s*$", re.IGNORECASE)
_DIMENSION_RE = re.compile(r"^\s*DIMENSION\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_INTEGER_RE = re.compile(r"^\s*INTEGER(?:\s*\*\s*\d+|\s*\([^)]*\))?\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_REAL_RE = re.compile(r"^\s*(?:REAL(?:\s*\*\s*\d+|\s*\([^)]*\))?|DOUBLE\s+PRECISION)\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_CHARACTER_RE = re.compile(r"^\s*CHARACTER(?:\s*\*\s*\d+|\s*\([^)]*\))?\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_LOGICAL_RE = re.compile(r"^\s*LOGICAL(?:\s*\*\s*\d+|\s*\([^)]*\))?\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_DATA_RE = re.compile(r"^\s*DATA\s+(.*)$", re.IGNORECASE)
_EXTERNAL_RE = re.compile(r"^\s*EXTERNAL\s*(?:::)?\s*(.*)$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"\b([A-Z_][A-Z0-9_]*)\b", re.IGNORECASE)
_LHS_ASSIGN_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*(?:\([^=]*\))?\s*=", re.IGNORECASE)
_IF_RE = re.compile(r"^(\s*(?:\d+\s+)?(?:ELSE\s+)?IF\s*)\(", re.IGNORECASE)
#: Statements whose integers are statement labels, not values. Promoting a bare
#: integer to a real literal is right for ``X = 1`` and wrong for ``GO TO 1000``,
#: which became ``GO TO 1000.0D0`` and stopped the build with "Syntax error in
#: GOTO statement". No arithmetic appears in these statements -- a computed GO
#: TO's selector is an integer expression -- so the whole statement is left
#: alone rather than trying to tell a label from a value inside it.
_LABEL_REFERENCE_STATEMENT_RE = re.compile(r"^\s*(?:GO\s*TO|ASSIGN)\b", re.IGNORECASE)
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
    "ASIN",
    "ATAN",
    "ATAN2",
    "COS",
    "COSH",
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
    missing = sorted({name for name in pending if name not in routines})
    if missing:
        raise HelperLiftingError(
            f"Helper lifting requires source definitions for {missing}. The completed JSON rewrites those calls, so pass-through is unsafe."
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
            if callee not in routines:
                raise HelperLiftingError(
                    f"Helper lifting for {current} reached external or undefined callee {callee}. Add lifting support for that dependency before rewriting the call through OTI."
                )
            if callee not in seen:
                pending.append(callee)
    return tuple(ordered)


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
    body = "\n\n".join(
        _lift_helper_routine(
            routines[name],
            parsed.form,
            source_lines,
            lifted_set,
            module_name,
            type_name,
            lifted_function_names=lifted_functions,
            helper_output_copies=(helper_output_copies or {}).get(name, []),
            helper_output_surfaces=(helper_output_surfaces or {}).get(name, []),
        )
        for name in ordered
    )
    return LiftedHelperSet(helper_names=ordered, source=body + ("\n" if body else ""))



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
    collisions = [f"E{index}" for index in range(1, count + 1)
                  if f"E{index}" in used]
    return "".join(f", OTI_{name} => {name}" for name in collisions)


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
) -> str:
    raw_lines = _routine_source_lines(source_lines, routine)
    if not raw_lines:
        raise HelperLiftingError(f"Routine {routine.name} is empty.")
    stitched_lines = _continuation_stitch(raw_lines, form)
    if not stitched_lines:
        raise HelperLiftingError(f"Routine {routine.name} did not produce any stitched source lines.")
    lifted_function_names = set(lifted_function_names or ())
    header_text = _statement_text(stitched_lines[0], form)
    header_match = _HEADER_RE.match(header_text)
    function_match = None if header_match else FUNCTION_HEADER_RE.match(header_text)
    if header_match:
        original_name = header_match.group(1).upper()
        raw_args = header_match.group(2)
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
    declaration_oti_names: set[str] = set()
    prelude: list[str] = []
    body: list[str] = []
    data_assignments: list[str] = []
    # The Fortran 77 way to write a named constant is two statements --
    # INTEGER N, then PARAMETER (N = 3) -- and the PARAMETER rewrite below
    # emits a complete typed declaration of its own. Emitting the plain
    # declaration as well declares N twice, which gfortran rejects with
    # "Symbol 'n' already has basic type of INTEGER". The names are read ahead
    # of the pass that emits, because the type declaration comes first.
    named_constants = _parameter_statement_names(stitched_lines[1:-1], form)

    for raw in stitched_lines[1:-1]:
        stripped = _statement_text(raw, form)
        if not stripped:
            continue
        if stripped.upper().startswith("INCLUDE "):
            continue
        if re.match(r"^\s*IMPLICIT\s+", stripped, re.IGNORECASE):
            continue
        stripped = _flattened_attributed_declaration(stripped)
        parameter_match = _PARAMETER_RE.match(stripped)
        if parameter_match:
            parameter_lines, names = _rewrite_parameter_line(parameter_match.group(1))
            prelude.extend(parameter_lines)
            parameter_names.update(names)
            continue
        dimension_match = _DIMENSION_RE.match(stripped)
        if dimension_match:
            payload = _without_names(dimension_match.group(1), named_constants)
            if not payload:
                continue
            lines, oti_names, ints = _rewrite_dimension_line(payload, type_name)
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
            prelude.append(f"    type({type_name}) :: {payload}")
            declaration_oti_names.update(_declared_names(payload))
            continue
        character_match = _CHARACTER_RE.match(stripped)
        if character_match:
            prelude.append(f"    {stripped}")
            character_names.update(_declared_names(character_match.group(1)))
            continue
        logical_match = _LOGICAL_RE.match(stripped)
        if logical_match:
            prelude.append(f"    {stripped}")
            logical_names.update(_declared_names(logical_match.group(1)))
            continue
        data_match = _DATA_RE.match(stripped)
        if data_match:
            data_assignments.extend(f"    {assignment}" for assignment in _data_to_assignments(data_match.group(1)))
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

    declared_non_oti = integer_names | character_names | logical_names | parameter_names
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

    # Function references to rewrite in this body: every lifted function except
    # one this routine has shadowed with an array or a dummy argument of its own,
    # and except its own name, which inside a function is the result variable.
    body_statements = [_split_label_and_statement(raw, form)[1] for raw in body]
    shadowed = _routine_array_names(stitched_lines, form) | {arg.upper() for arg in args}
    function_call_names = {name for name in lifted_function_names
                           if name != original_name and name not in shadowed}

    _renames = direction_renames(
        module_name,
        body_statements + list(args))
    signature = f"{original_name.lower()}_oti({', '.join(arg.lower() for arg in args)})"
    unit = "function" if function_match else "subroutine"
    if function_match:
        header = f"function {signature} result({result_name.lower()})"
    else:
        header = f"subroutine {signature}"
    lines = [
        header,
        f"    use {module_name}, OTI_HELPER_DP => DP{_renames}",
        "    use oti_intrinsics",
        f"    implicit type({type_name}) (a-h,o-z)",
        "    implicit integer (i-n)",
    ]
    lines.extend(prelude)
    if function_match and result_name not in declaration_oti_names and result_name not in declared_non_oti:
        # The result variable's type comes from the header's type-spec when it
        # has one and from the implicit rule otherwise. It is stated explicitly
        # because the lifted body's implicit rules are not the source's: a REAL
        # function whose name begins with I-N would silently become an integer.
        lines.append(f"    {_result_type_spec(declared_result_type, result_name, type_name)} :: {result_name.lower()}")
    lines.extend(data_assignments)
    for raw in body:
        label_prefix, statement = _split_label_and_statement(raw, form)
        kclear_lines = None
        if kclear_lines is not None:
            lines.extend(kclear_lines)
            continue
        rewritten = _rewrite_helper_executable_line(statement, lifted_names, oti_names,
                                                   function_call_names)
        if re.match(r"^\s*RETURN\b", rewritten, re.IGNORECASE) and helper_output_surfaces:
            lines.extend(_helper_output_surface_lines(helper_output_surfaces))
        if re.match(r"^\s*RETURN\b", rewritten, re.IGNORECASE) and helper_output_copies:
            lines.extend(_helper_output_copy_lines(helper_output_copies))
        lines.append(f"    {label_prefix}{rewritten}")
    lines.append(f"end {unit} {original_name.lower()}_oti")
    return "\n".join(lines)


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
#: -- SAVE, ALLOCATABLE, POINTER -- changes what the declaration means, so it
#: is left exactly as written rather than silently dropped.
_EXPRESSIBLE_ATTRIBUTES = ("dimension", "intent", "parameter")


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


def _without_names(payload: str, names: set[str]) -> str:
    """``payload`` with any declared entity whose name is in ``names`` removed."""
    kept = [
        entry.strip() for entry in split_top_level(payload)
        if entry.strip()
        and entry.strip().split("(", 1)[0].split("=", 1)[0].strip().upper() not in names
    ]
    return ", ".join(kept)


def _rewrite_parameter_line(payload: str) -> tuple[list[str], set[str]]:
    lines: list[str] = []
    names: set[str] = set()
    for assignment in split_top_level(payload):
        if "=" not in assignment:
            raise HelperLiftingError(f"PARAMETER entry missing '=': {assignment!r}")
        name, value = assignment.split("=", 1)
        name = name.strip()
        value = value.strip()
        names.add(name.upper())
        if re.fullmatch(r"[+-]?\d+", value):
            lines.append(f"    integer, parameter :: {name} = {value}")
        else:
            lines.append(f"    real(8), parameter :: {name} = {_normalize_real_literal(value)}")
    return lines, names


def _rewrite_dimension_line(payload: str, type_name: str) -> tuple[list[str], set[str], set[str]]:
    oti_entries: list[str] = []
    int_entries: list[str] = []
    oti_names: set[str] = set()
    integer_names: set[str] = set()
    for entry in split_top_level(payload):
        clean = entry.strip()
        name = clean.split("(", 1)[0].strip().upper()
        if not name:
            continue
        if _is_implicit_integer_name(name):
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
        lhs_match = _LHS_ASSIGN_RE.match(line)
        if lhs_match:
            name = lhs_match.group(1).upper()
            if name not in declared_non_oti and name not in parameter_names and not _is_implicit_integer_name(name):
                result.add(name)
        for match in _TOKEN_RE.finditer(line):
            name = match.group(1).upper()
            if name in _KEYWORDS or name in _INTRINSIC_NAMES or name in _TYPED_INTRINSIC_MAP:
                continue
            if name in lifted_names or name in declared_non_oti or name in parameter_names:
                continue
            if _is_implicit_integer_name(name):
                continue
            result.add(name)
    return result


def _rewrite_helper_executable_line(
    line: str,
    lifted_names: set[str],
    oti_names: set[str],
    function_call_names: set[str] | None = None,
) -> str:
    rewritten = _rewrite_lifted_call(line, lifted_names)
    rewritten = _wrap_condition_with_real_tokens(rewritten, oti_names)
    rewritten = _normalize_typed_intrinsics(rewritten, oti_names)
    rewritten = _normalize_numeric_literals(rewritten, oti_names)
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
        return line
    condition = line[condition_start:condition_end]
    wrapped = _real_wrapped_tokens(condition, oti_names)
    return f"{match.group(1)}({wrapped}){line[condition_end + 1:]}"


def _real_wrapped_tokens(condition: str, oti_names: set[str]) -> str:
    if not oti_names:
        return condition
    # A promoted variable can share a name with an exponent letter -- models do
    # declare variables called D and D0 -- so mask literals before substituting
    # identifiers, or ``1.D-12`` becomes ``1.REAL(D)-12``.
    condition, literals = mask_real_literals(condition)
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

    return unmask_real_literals(pattern.sub(replacement, condition), literals)


def _normalize_typed_intrinsics(line: str, oti_names: set[str]) -> str:
    if not _contains_oti_name(line, oti_names):
        return line
    return _TYPED_INTRINSIC_RE.sub(lambda match: _TYPED_INTRINSIC_MAP[match.group(1).upper()], line)


def _normalize_numeric_literals(line: str, oti_names: set[str]) -> str:
    if not _contains_oti_name(line, oti_names):
        return line
    if re.match(r"^\s*STOP\b", line, re.IGNORECASE):
        return line
    if _LABEL_REFERENCE_STATEMENT_RE.match(line):
        return line
    normalized = re.sub(
        r"(?<!\w)(\d+\.\d*|\.\d+|\d+)[eE]([+-]?\d+)",
        lambda match: f"{match.group(1)}D{match.group(2)}",
        line,
    )
    normalized = re.sub(
        r"(?<![A-Za-z0-9_])((?:\d+\.\d*)|(?:\d+\.))(?![A-Za-z0-9_.dDeE])",
        lambda match: match.group(1).rstrip(".") + (".0" if match.group(1).endswith(".") else "") + "D0",
        normalized,
    )
    # From here on only *bare integers* are promoted. Mask the complete real
    # literals first so their exponent digits are not mistaken for one.
    normalized, literals = mask_real_literals(normalized)
    normalized = re.sub(r"(?<![A-Za-z0-9_.)])(\d+)(?![A-Za-z0-9_.])(?=\s*[*\/])", r"\1.0D0", normalized)
    normalized = re.sub(r"([*\/])\s*(\d+)(?![A-Za-z0-9_.])", r"\1\2.0D0", normalized)
    normalized = _promote_bare_integers_for_oti(normalized)
    return unmask_real_literals(normalized, literals)


def _contains_oti_name(line: str, oti_names: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(name)}\b", line, re.IGNORECASE) for name in oti_names)


def _normalize_real_literal(value: str) -> str:
    promoted = re.sub(r"(?<!\w)(\d+\.\d*|\.\d+|\d+)[eE]([+-]?\d+)", lambda match: f"{match.group(1)}D{match.group(2)}", value)
    return re.sub(r"(?<![A-Za-z0-9_])(\d+\.\d*|\.\d+)(?![A-Za-z0-9_.dDeE])", lambda match: match.group(1) + "D0", promoted)


def _data_to_assignments(payload: str) -> list[str]:
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
        if len(value_entries) != len(name_entries):
            raise HelperLiftingError(f"Unsupported DATA statement shape: {payload!r}")
        for name, value in zip(name_entries, value_entries):
            assignments.append(f"{name} = {_normalize_real_literal(value)}")
    return assignments


def _is_implicit_integer_name(name: str) -> bool:
    return bool(name) and name[0].upper() in _IMPLICIT_INTEGER_FIRST_LETTERS


def _promote_bare_integers_for_oti(line: str) -> str:
    if not line.strip() or not any(char.isdigit() for char in line):
        return line
    if re.match(r"^\s*DO\b", line, re.IGNORECASE):
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
            end = index
            while end < len(line) and line[end].isdigit():
                end += 1
            if end < len(line) and line[end] in ".eEdD":
                out.append(line[index:end])
                index = end
                continue
            literal = line[index:end]
            left = index - 1
            while left >= 0 and line[left] == " ":
                left -= 1
            right = end
            while right < len(line) and line[right] == " ":
                right += 1
            prev_char = line[left] if left >= 0 else ""
            next_char = line[right] if right < len(line) else ""
            if not any(paren_stack) and (prev_char in "+-*/" or next_char in "+-*/"):
                out.append(f"{literal}.0D0")
            else:
                out.append(literal)
            index = end
            continue
        out.append(char)
        index += 1
    return "".join(out)


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
    if not raw or raw[0] != "\t":
        return raw
    if len(raw) >= 2 and raw[1].isdigit() and raw[1] != "0":
        return "     " + raw[1:]
    return "      " + raw[1:]


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
        if quote is None and char in "+-*/,=)":
            last_break = len(current)
        if len(current) >= width and last_break > len(indent) + 1:
            pieces.append(current[:last_break].rstrip() + " &")
            current = continuation_indent + current[last_break:].lstrip()
            last_break = -1
    if current.strip():
        pieces.append(current)
    return pieces or [line]


def _continuation_stitch(lines: list[str], form: str) -> list[str]:
    if form != "fixed":
        return [line for line in lines if _statement_text(line, form)]
    merged: list[str] = []
    for raw in lines:
        raw = _expand_fixed_form_tabs(raw)
        clean = _strip_fixed_form_comment(raw)
        if not clean.strip():
            continue
        if merged and len(raw) >= 6 and raw[5] not in {" ", "0"} and raw[0] not in {"C", "c", "*", "!"}:
            merged[-1] = merged[-1].rstrip() + " " + clean[6:].strip()
            continue
        merged.append(clean)
    return merged