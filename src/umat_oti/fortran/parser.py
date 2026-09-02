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


def parse_subroutines(logical_lines: tuple[FortranLogicalLine, ...]) -> tuple[ParsedSubroutine, ...]:
    routines: list[ParsedSubroutine] = []
    index = 0
    while index < len(logical_lines):
        line = logical_lines[index]
        match = re.match(r"^\s*subroutine\s+(\w+)\s*\((.*)\)\s*$", line.text, flags=re.IGNORECASE)
        if not match:
            index += 1
            continue
        name = match.group(1)
        args = tuple(arg.strip() for arg in split_top_level(match.group(2)) if arg.strip())
        routine_lines = [line]
        index += 1
        while index < len(logical_lines):
            routine_lines.append(logical_lines[index])
            if re.match(
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
    index = 0
    while index < len(logical_lines):
        line = logical_lines[index]
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
            if re.match(
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
