from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from umat_oti.core.model import (
    Declaration,
    DeclaredEntity,
    FortranLogicalLine,
    ParsedFortranSource,
    ParsedSubroutine,
)
from umat_oti.fortran.normalize import detect_source_form, strip_inline_comment


#: ``double complex`` and ``complex`` are listed with the rest because a
#: declaration the grammar does not know is not a declaration at all: the name
#: it declares comes out with no recorded type and no recorded shape, which
#: downstream is indistinguishable from a name this source never mentions. A
#: complex variable is not promotable -- the OTI algebra is built over the
#: reals -- and saying so needs the declaration to have been read first.
TYPE_PATTERN = (
    r"double\s+precision"
    r"|double\s+complex"
    r"|complex(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|real(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|integer(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|character(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|logical(?:\s*\*\s*\d+|\s*\([^)]*\))?"
)


def parse_fortran_file(path: Path) -> ParsedFortranSource:
    text = path.read_text(encoding="utf-8")
    form = detect_source_form(path, text)
    logical_lines = logical_lines_from_text(text, form)
    subroutines = parse_subroutines(logical_lines)
    return ParsedFortranSource(path, form, text, logical_lines, subroutines)


def logical_lines_from_text(text: str, form: str) -> tuple[FortranLogicalLine, ...]:
    if form == "fixed":
        return _fixed_logical_lines(text)
    return _free_logical_lines(text)


def _free_logical_lines(text: str) -> tuple[FortranLogicalLine, ...]:
    result: list[FortranLogicalLine] = []
    pending = ""
    numbers: list[int] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = strip_inline_comment(raw).rstrip()
        if not stripped.strip():
            continue
        continuation = stripped.rstrip().endswith("&")
        part = stripped.rstrip()
        if continuation:
            part = part[:-1].rstrip()
        if pending:
            part = part.lstrip()
            if part.startswith("&"):
                part = part[1:].lstrip()
            pending = pending + " " + part
            numbers.append(number)
        else:
            pending = part.strip()
            numbers = [number]
        if not continuation:
            result.append(FortranLogicalLine(_collapse_spaces(pending), tuple(numbers)))
            pending = ""
            numbers = []
    if pending:
        result.append(FortranLogicalLine(_collapse_spaces(pending), tuple(numbers)))
    return tuple(result)


def expand_fixed_form_tabs(raw: str) -> str:
    """A tab in the label field advances to column 7.

    Both ifort -- which is what Abaqus uses -- and gfortran accept a tab there
    as a vendor extension, and sources in the wild are written that way:

        \t   SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,

    Column arithmetic on the raw text reads that as a statement beginning
    somewhere inside the word, so the file appears to declare nothing at all.
    A digit 1-9 immediately after the tab is the other half of the convention:
    it marks a continuation line, so the digit is placed in column 6 rather
    than column 7.

    Only a tab inside the label field is touched. A tab later in the line is
    ordinary whitespace within a statement and is left exactly where it is.
    """
    index = raw.find("\t")
    if index < 0 or index >= 6:
        return raw
    rest = raw[index + 1:]
    if rest[:1].isdigit() and rest[0] != "0":
        return raw[:index].ljust(5) + rest[0] + rest[1:]
    return raw[:index].ljust(6) + rest


def _fixed_logical_lines(text: str) -> tuple[FortranLogicalLine, ...]:
    result: list[FortranLogicalLine] = []
    pending = ""
    numbers: list[int] = []
    for number, original in enumerate(text.splitlines(), start=1):
        if not original:
            continue
        raw = expand_fixed_form_tabs(original)
        marker = raw[0]
        if marker in {"c", "C", "*", "!"}:
            continue
        body = strip_inline_comment(raw[6:] if len(raw) > 6 else "").rstrip()
        if not body.strip():
            continue
        is_continuation = len(raw) >= 6 and raw[5].strip() not in {"", "0"}
        if is_continuation and pending:
            # No space at the join, because fixed form does not insert one --
            # the same rule _logical_statements_with_numbers states and
            # follows. An identifier may straddle a continuation, and a real
            # source in this corpus writes G31 as "...G12*G23*G3" then
            # "     &  1+G13*G21*G32...". gfortran reads G31; a space-join
            # reads G3 and 1, and the transform then renamed a variable that
            # does not exist, declared it, zeroed it, and dropped the whole
            # G12*G23*G31 term out of a determinant. It compiled and ran.
            pending = pending.rstrip() + body.strip()
            numbers.append(number)
        else:
            if pending:
                result.append(FortranLogicalLine(_collapse_spaces(pending), tuple(numbers)))
            pending = body.strip()
            numbers = [number]
    if pending:
        result.append(FortranLogicalLine(_collapse_spaces(pending), tuple(numbers)))
    return tuple(result)


def _collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


#: An INTERFACE block opener. ``interface``, ``abstract interface``, a named
#: generic ``interface swap``, and the operator forms ``interface operator(+)``
#: / ``interface assignment(=)`` are all of them.
INTERFACE_OPEN_RE = re.compile(
    r"^\s*(?:abstract\s+)?interface\b"
    r"(?:\s*(?:\w+|operator\s*\(.*\)|assignment\s*\(\s*=\s*\)))?\s*$",
    flags=re.IGNORECASE,
)
#: Its closer. ``endinterface`` is the no-space spelling fixed form allows.
INTERFACE_CLOSE_RE = re.compile(
    r"^\s*end\s*interface(\s+.*)?$", flags=re.IGNORECASE)

#: The prefixes a subprogram header may carry before the keyword. Fortran
#: allows them in any order and Fortran 2008 adds ``module``; a header that
#: carries one is a definition exactly like a header that does not.
SUBPROGRAM_PREFIX = r"(?:(?:recursive|pure|impure|elemental|non_recursive|module)\s+)*"

#: ``[prefix] SUBROUTINE name(args)``.
#:
#: The argument list stays REQUIRED, and the reason is fixed-form column
#: arithmetic rather than Fortran: ``  end subroutine umat`` indented two
#: columns has its first six characters read as the label field, so the
#: statement text handed to this pattern is the bare ``subroutine umat``.
#: Accepting that spelling made four sahmotaman sources report a UMAT whose
#: whole body was one line long -- a routine invented out of a line that ends
#: one. An argument-less SUBROUTINE is legal and is not found here; finding it
#: needs the form detection fixed first, not a looser pattern.
SUBROUTINE_HEADER_RE = re.compile(
    rf"^\s*{SUBPROGRAM_PREFIX}subroutine\s+(?P<name>\w+)\s*\((?P<args>.*)\)\s*$",
    flags=re.IGNORECASE,
)


def _interface_body_line_indexes(
    logical_lines: tuple[FortranLogicalLine, ...],
) -> frozenset[int]:
    """Indexes of the lines that sit inside an INTERFACE block.

    An interface body states the signature of a procedure defined SOMEWHERE
    ELSE -- usually not in this file at all -- and it is written with the same
    words as a definition:

        interface
            pure subroutine MohrCoulombStressReturn(Sigma, nsigma, ...)
                ...declarations only...
            end subroutine MohrCoulombStressReturn
        end interface

    Read as source, that ``end subroutine`` closes whatever program unit is
    open. In MohrCoulombAbaqus.for the open unit is UMAT itself, whose
    interface block sits in its declaration section, so UMAT was recorded as
    spanning lines 1-141 when its body runs to 245. Every anchor the transform
    looks for -- the stress update, the tangent output, both extraction points
    -- lives after line 141 and was discarded for being outside the routine,
    and the refusal named four missing anchors rather than the one parse that
    lost them.

    Blocks nest: an interface body may not contain another interface, but a
    routine may open one, so the depth counter is what ends the outer block.
    """
    inside: set[int] = set()
    depth = 0
    for index, line in enumerate(logical_lines):
        if INTERFACE_CLOSE_RE.match(line.text):
            if depth:
                depth -= 1
                inside.add(index)
            continue
        if INTERFACE_OPEN_RE.match(line.text):
            depth += 1
            inside.add(index)
            continue
        if depth:
            inside.add(index)
    return frozenset(inside)


#: A procedure header as it is written inside an interface body: the same
#: words as a definition, with or without prefixes, subroutine or function.
_INTERFACE_PROCEDURE_RE = re.compile(
    rf"^\s*(?:(?:{TYPE_PATTERN})\s+)?{SUBPROGRAM_PREFIX}"
    r"(?:subroutine|function)\s+(?P<name>\w+)\s*(?:\(|$)",
    flags=re.IGNORECASE,
)
#: ``module procedure NAME`` / ``procedure NAME``, the other way a generic
#: interface names a real procedure.
_INTERFACE_MODULE_PROCEDURE_RE = re.compile(
    r"^\s*(?:module\s+)?procedure\s*(?:::)?\s*(?P<names>[\w\s,]+?)\s*$",
    flags=re.IGNORECASE,
)


def interface_declared_procedures(
    logical_lines: tuple[FortranLogicalLine, ...],
) -> frozenset[str]:
    """Upper-case names an INTERFACE block declares to be procedures.

    These are not definitions -- :func:`parse_subroutines` and
    :func:`parse_function_subprograms` skip them, and the lifter must not be
    offered a body that is not there -- but they are still proof about the
    NAME: ``Convert_array_to_tensor(stress, 1.0_DP)`` is a call, not a
    subscript. The submodule idiom is where it matters, because the interface
    body is the only place the argument list appears at all: the
    implementation is written ``module procedure convert_array_to_tensor``
    with no signature. Reading the call as a subscript reported a promoted
    array with no confirmed shape and refused a source that was fine.
    """
    return frozenset(
        str(row["name"]) for row in interface_declared_procedure_sites(logical_lines))


def interface_declared_procedure_sites(
    logical_lines: tuple[FortranLogicalLine, ...],
) -> list[dict[str, object]]:
    """:func:`interface_declared_procedures`, with the line each was declared on.

    The lines are what makes a refusal a diagnostic rather than a verdict: a
    file whose only UMAT is an interface body can be told apart, in the message
    itself, from a file that has no UMAT anywhere.
    """
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for index in sorted(_interface_body_line_indexes(logical_lines)):
        line = logical_lines[index]
        names: list[str] = []
        match = _INTERFACE_PROCEDURE_RE.match(line.text)
        if match:
            names = [match.group("name").upper()]
        else:
            match = _INTERFACE_MODULE_PROCEDURE_RE.match(line.text)
            if match:
                names = [name.strip().upper()
                         for name in match.group("names").split(",") if name.strip()]
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            rows.append({"name": name, "line_numbers": list(line.line_numbers)})
    return rows


def parse_subroutines(logical_lines: tuple[FortranLogicalLine, ...]) -> tuple[ParsedSubroutine, ...]:
    routines: list[ParsedSubroutine] = []
    interface_lines = _interface_body_line_indexes(logical_lines)
    index = 0
    while index < len(logical_lines):
        line = logical_lines[index]
        if index in interface_lines:
            index += 1
            continue
        match = SUBROUTINE_HEADER_RE.match(line.text)
        if not match:
            index += 1
            continue
        name = match.group("name")
        args = tuple(arg.strip() for arg in split_top_level(match.group("args") or "") if arg.strip())
        routine_lines = [line]
        index += 1
        while index < len(logical_lines):
            routine_lines.append(logical_lines[index])
            if index not in interface_lines and re.match(
                r"^\s*end\s*(subroutine(\s+\w+)?)?\s*$",
                logical_lines[index].text,
                flags=re.IGNORECASE,
            ):
                break
            index += 1
        declarations = tuple(
            declaration
            for declaration in (parse_declaration_line(item) for item in routine_lines)
            if declaration is not None
        )
        routines.append(ParsedSubroutine(name, args, tuple(routine_lines), declarations))
        index += 1
    return tuple(routines)


#: A function subprogram header, with or without a leading type-spec and with
#: or without a RESULT clause. Fortran's other program units are found by
#: :func:`parse_subroutines`; functions are parsed separately so that adding
#: them here cannot change what any existing caller of ``subroutines`` sees.
FUNCTION_HEADER_RE = re.compile(
    rf"^\s*(?:(?P<type>{TYPE_PATTERN})\s+)?"
    # "module" among the prefixes: a submodule interface writes
    # "module function Convert_array_to_tensor(array, scalar) result(tensor)",
    # and a header this pattern does not match is not a function as far as
    # everything downstream is concerned -- so the call to it read as an
    # index into an array nothing declares.
    r"(?:(?:recursive|pure|impure|elemental|module)\s+)*"
    r"function\s+(?P<name>\w+)\s*"
    r"(?:\(\s*(?P<args>[^)]*)\)\s*)?"
    r"(?:result\s*\(\s*(?P<result>\w+)\s*\)\s*)?$",
    flags=re.IGNORECASE,
)


def parse_function_subprograms(
    logical_lines: tuple[FortranLogicalLine, ...],
) -> tuple[ParsedSubroutine, ...]:
    """Function subprograms, in the same shape as :class:`ParsedSubroutine`.

    A UMAT is free to put part of its constitutive law in a FUNCTION rather than
    a SUBROUTINE -- the Huang/Kysar crystal-plasticity lineage puts the flow
    rule and both hardening moduli there -- and a closure walk that only follows
    CALL statements never sees them. They are returned as ordinary routines so
    the lifter can treat them uniformly; the header text carries the FUNCTION
    keyword, so a consumer that needs the distinction still has it.
    """
    routines: list[ParsedSubroutine] = []
    interface_lines = _interface_body_line_indexes(logical_lines)
    index = 0
    while index < len(logical_lines):
        line = logical_lines[index]
        if index in interface_lines:
            index += 1
            continue
        match = FUNCTION_HEADER_RE.match(line.text)
        if not match:
            index += 1
            continue
        name = match.group("name")
        raw_args = match.group("args") or ""
        args = tuple(arg.strip() for arg in split_top_level(raw_args) if arg.strip())
        routine_lines = [line]
        index += 1
        while index < len(logical_lines):
            routine_lines.append(logical_lines[index])
            if index not in interface_lines and re.match(
                r"^\s*end\s*(function(\s+\w+)?)?\s*$",
                logical_lines[index].text,
                flags=re.IGNORECASE,
            ):
                break
            index += 1
        declarations = tuple(
            declaration
            for declaration in (parse_declaration_line(item) for item in routine_lines)
            if declaration is not None
        )
        routines.append(ParsedSubroutine(name, args, tuple(routine_lines), declarations))
        index += 1
    return tuple(routines)


def parse_declaration_line(line: FortranLogicalLine | str) -> Declaration | None:
    if isinstance(line, FortranLogicalLine):
        text = line.text
        line_numbers = line.line_numbers
    else:
        text = line
        line_numbers = ()
    stripped = text.strip()
    with_colons = _split_attributed_declaration(stripped)
    if with_colons:
        raw_type = _normalize_type(with_colons[0])
        attribute_text, variable_text = with_colons[1], with_colons[2]
        # ``split_top_level`` rather than ``str.split(",")``: an attribute
        # carries its own parentheses, and ``DIMENSION(3, 3)`` split on every
        # comma yields the two fragments "DIMENSION(3" and "3)", neither of
        # which is an attribute.
        attributes = split_top_level(attribute_text)
        entities = tuple(parse_entity(item) for item in split_top_level(variable_text))
        entities = _with_dimension_attribute(entities, attributes)
        return Declaration(_kind(raw_type), raw_type, attributes, entities, text, line_numbers)
    old_style = re.match(
        rf"^(?P<type>{TYPE_PATTERN})\s+(?P<vars>.+)$",
        stripped,
        flags=re.IGNORECASE,
    )
    if not old_style:
        return None
    raw_type = _normalize_type(old_style.group("type"))
    entities = tuple(parse_entity(item) for item in split_top_level(old_style.group("vars")))
    return Declaration(_kind(raw_type), raw_type, (), entities, text, line_numbers)


TYPE_PREFIX_RE = re.compile(rf"^(?P<type>{TYPE_PATTERN})", flags=re.IGNORECASE)


def _split_attributed_declaration(stripped: str) -> tuple[str, str, str] | None:
    """``(type, attributes, entities)`` of a ``TYPE, attrs :: names`` statement.

    The ``::`` is located by scanning outside parentheses instead of by a regex
    that forbids a colon in the attribute list. A colon is exactly what a
    deferred shape is written with, so

        REAL(8), DIMENSION(:, :), ALLOCATABLE :: alpha_k

    matched nothing and the whole statement was not a declaration at all: the
    name it declares had no recorded type, no recorded shape, and no record
    that this source declares it anywhere.
    """
    type_match = TYPE_PREFIX_RE.match(stripped)
    if not type_match:
        return None
    rest = stripped[type_match.end():]
    depth = 0
    in_single = False
    in_double = False
    for index, char in enumerate(rest):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif in_single or in_double:
            continue
        elif char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == ":" and depth == 0 and rest[index : index + 2] == "::":
            attributes = rest[:index].strip()
            if attributes and not attributes.startswith(","):
                return None
            entities = rest[index + 2 :].strip()
            if not entities:
                return None
            return type_match.group("type"), attributes.lstrip(",").strip(), entities
    return None


DIMENSION_ATTRIBUTE_RE = re.compile(r"^dimension\s*\((?P<dims>.*)\)$", flags=re.IGNORECASE)


def _with_dimension_attribute(
    entities: tuple[DeclaredEntity, ...], attributes: tuple[str, ...]
) -> tuple[DeclaredEntity, ...]:
    """``entities`` with the declaration's DIMENSION attribute applied.

    ``REAL(8), DIMENSION(6, 6) :: ID4, C_MAT`` declares two 6x6 arrays, and the
    extent is written once, on the declaration, rather than after each name.
    Reading only the per-entity array-spec sees two entities with no shape at
    all, which downstream is indistinguishable from a name this source never
    declared -- so a promoted variable declared this way was refused with
    "indexed in a stress region but has no confirmed shape" while its extent
    sat in plain sight one comma to the left.

    Fortran gives the entity's own array-spec precedence: in
    ``REAL, DIMENSION(6) :: A, B(3)``, B is the 3-vector it says it is. So the
    attribute fills in only where the entity declares no shape of its own.
    """
    dimensions: tuple[str, ...] = ()
    for attribute in attributes:
        match = DIMENSION_ATTRIBUTE_RE.match(attribute.strip())
        if match:
            dimensions = split_top_level(match.group("dims"))
            break
    if not dimensions:
        return entities
    return tuple(
        entity if entity.dimensions else replace(entity, dimensions=dimensions)
        for entity in entities
    )


def parse_entity(text: str) -> DeclaredEntity:
    raw = text.strip()
    before_init, initializer = split_initializer(raw)
    match = re.match(r"^(?P<name>\w+)\s*(?:\((?P<dims>.*)\))?$", before_init.strip())
    if not match:
        return DeclaredEntity(before_init.strip(), (), initializer, raw)
    dims = match.group("dims")
    dimensions = tuple(item.strip() for item in split_top_level(dims)) if dims else ()
    return DeclaredEntity(match.group("name"), dimensions, initializer, raw)


def split_initializer(text: str) -> tuple[str, str | None]:
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == "=" and depth == 0:
            return text[:index].strip(), text[index + 1 :].strip()
    return text.strip(), None


def split_top_level(text: str | None) -> tuple[str, ...]:
    if not text:
        return ()
    result: list[str] = []
    start = 0
    depth = 0
    in_single = False
    in_double = False
    for index, char in enumerate(text):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if char == "(":
                depth += 1
            elif char == ")" and depth:
                depth -= 1
            elif char == "," and depth == 0:
                result.append(text[start:index].strip())
                start = index + 1
    result.append(text[start:].strip())
    return tuple(item for item in result if item)


def _normalize_type(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip().lower())


def _kind(raw_type: str) -> str:
    lowered = raw_type.lower()
    if lowered.startswith("complex") or lowered.startswith("double complex"):
        return "complex"
    if lowered.startswith("real") or lowered.startswith("double precision"):
        return "real"
    if lowered.startswith("integer"):
        return "integer"
    if lowered.startswith("character"):
        return "character"
    if lowered.startswith("logical"):
        return "logical"
    return "unknown"
