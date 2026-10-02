"""What type an undeclared name has inside one routine -- or that nobody can say.

A UMAT written against ABA_PARAM.INC declares almost nothing: ``TAU0=PROPS(3)``
types TAU0 through ``IMPLICIT REAL*8 (A-H,O-Z)``, which lives in the include.
The parameter-direction taint therefore has to follow implicitly typed names,
or every parameter derivative of such a model is cut off at PROPS. But a name
the scanner could not type is not thereby REAL. It is INTEGER when

* an INCLUDE'd file declares it (``INCLUDE 'mytypes.inc'`` holding
  ``INTEGER CNT``) or carries the IMPLICIT rule that makes it one,
* the routine's own IMPLICIT statement says so -- including in free form, where
  the statement need not start in column 7,
* a module the routine USEs declares it.

Promoting such a name gives an integer a derivative: ``CNT=PROPS(3)`` with CNT
INTEGER truncates in the original and carries ``dCNT/dPROPS(3) = 1`` in the
transform, so dSIGMA/dPROPS(3) comes back nonzero where the truth is zero (and
the primal moves too as soon as PROPS(3) is not integral).

This module reads the *selected routine* -- not the whole file, because IMPLICIT
rules are per scoping unit -- together with everything that scoping unit can
see: the INCLUDE files it names (resolved next to the source, case-insensitively,
recursively), the specification part of a host module when the routine is a
module procedure, and the specification part of every module it USEs that the
same text defines. Where any of those cannot be read -- an INCLUDE that is not on
disk, a USE of a module whose source is not in the text -- the type of an
undeclared name is *unknown*, and :attr:`RoutineTyping.unknown_because` says
why. Callers must then not guess.

ABA_PARAM.INC is the one include whose content is fixed by the solver:
``implicit real*8(a-h,o-z)`` plus ``parameter (nprecd=2)``. When it is not on
disk it is read as that text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

ABA_PARAM_TEXT = "      implicit real*8(a-h,o-z)\n      parameter (nprecd=2)\n"

#: Modules supplied by the compiler. They export procedures and named
#: constants, never a user variable a UMAT could copy a parameter into.
INTRINSIC_MODULES = frozenset({
    "ISO_C_BINDING", "ISO_FORTRAN_ENV", "IEEE_ARITHMETIC", "IEEE_EXCEPTIONS",
    "IEEE_FEATURES", "OMP_LIB", "OMP_LIB_KINDS", "MPI", "MPI_F08"})

_DEFAULT_INTEGER = frozenset("IJKLMN")
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

_INCLUDE_RE = re.compile(r"^\s*INCLUDE\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_IMPLICIT_RE = re.compile(r"^\s*IMPLICIT\s+(.*)$", re.IGNORECASE)
_IMPLICIT_SPEC_RE = re.compile(
    r"(?P<type>DOUBLE\s*PRECISION|DOUBLE\s*COMPLEX|REAL(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|INTEGER(?:\s*\*\s*\d+|\s*\([^)]*\))?|LOGICAL(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|COMPLEX(?:\s*\*\s*\d+|\s*\([^)]*\))?|CHARACTER(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|TYPE\s*\([^)]*\))\s*\((?P<letters>[^)]*)\)",
    re.IGNORECASE)
_USE_RE = re.compile(r"^\s*USE\b\s*(?:,\s*(?:NON_)?INTRINSIC\s*)?(?:::)?\s*([A-Za-z_]\w*)",
                     re.IGNORECASE)
_TYPE_DECL_RE = re.compile(
    r"^\s*(?P<type>DOUBLE\s*PRECISION|DOUBLE\s*COMPLEX"
    r"|REAL(?:\s*\*\s*\d+|\s*\([^)]*\))?|INTEGER(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|LOGICAL(?:\s*\*\s*\d+|\s*\([^)]*\))?|COMPLEX(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|CHARACTER(?:\s*\*\s*(?:\d+|\(\s*\*\s*\))|\s*\([^)]*\))?|TYPE\s*\([^)]*\)|CLASS\s*\([^)]*\))"
    r"(?P<rest>(?:\s*,.*?)?\s*(?:::)?\s*[A-Za-z_].*)$",
    re.IGNORECASE)
_UNIT_HEADER_RE = re.compile(
    r"^\s*(?:(?:RECURSIVE|PURE|IMPURE|ELEMENTAL|MODULE)\s+)*"
    r"(?:(?:DOUBLE\s*PRECISION|REAL(?:\s*\*\s*\d+|\s*\([^)]*\))?|INTEGER(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|LOGICAL|COMPLEX|CHARACTER(?:\s*\*\s*\d+)?|TYPE\s*\([^)]*\))\s+)?"
    r"(?:(?:RECURSIVE|PURE|IMPURE|ELEMENTAL)\s+)*"
    r"(?P<kind>SUBROUTINE|FUNCTION)\s+(?P<name>[A-Za-z_]\w*)",
    re.IGNORECASE)
_MODULE_RE = re.compile(r"^\s*MODULE\s+(?!PROCEDURE\b)([A-Za-z_]\w*)\s*$", re.IGNORECASE)
_END_UNIT_RE = re.compile(r"^\s*END\s*(?:(SUBROUTINE|FUNCTION|MODULE|PROGRAM)\b.*)?$",
                          re.IGNORECASE)
_CONTAINS_RE = re.compile(r"^\s*CONTAINS\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class RoutineTyping:
    """The typing facts one scoping unit gives an undeclared name.

    ``nonreal_letters`` are the first letters whose implicit type is not REAL
    (INTEGER by default for I-N, or whatever the routine's IMPLICIT rules say).
    ``declared_nonreal`` and ``declared_real`` are names given a type by a
    declaration the scanner of the routine body does not see: one in an
    INCLUDE'd file, a host module or a USEd module. ``unknown_because`` is
    non-empty when something the routine can see could not be read; then an
    undeclared name's type is not known and must not be guessed.
    """

    implicit_none: bool = False
    nonreal_letters: frozenset[str] = _DEFAULT_INTEGER
    declared_nonreal: frozenset[str] = frozenset()
    declared_real: frozenset[str] = frozenset()
    unknown_because: tuple[str, ...] = ()
    #: Letters whose implicit type is default REAL (binary32): every letter
    #: outside I-N when no IMPLICIT statement or ABA_PARAM.INC says otherwise.
    single_letters: frozenset[str] = frozenset()
    #: Names declared REAL, REAL*4, REAL(4) or REAL(KIND=4) -- binary32.
    declared_single: frozenset[str] = frozenset()

    def is_single_precision(self, name: str, *, declared_in_body: str = "") -> bool:
        """Whether ``name`` holds a binary32 REAL in this routine.

        ``declared_in_body`` is the scanner's type for a name the routine body
        declares ("real", "real*4", "double precision", ...); "" when none.
        """
        upper = name.upper()
        if upper in self.declared_single:
            return True
        if upper in self.declared_real or upper in self.declared_nonreal:
            return False
        if declared_in_body:
            return _is_single_spec(declared_in_body)
        if self.implicit_none or self.unknown_because:
            return False
        return bool(upper) and upper[0] in self.single_letters

    def is_known_real(self, name: str) -> bool:
        """Whether ``name``, undeclared in the routine body, is certainly REAL."""
        upper = name.upper()
        if upper in self.declared_nonreal:
            return False
        if upper in self.declared_real or upper in self.declared_single:
            return True
        if self.implicit_none or self.unknown_because:
            return False
        return bool(upper) and upper[0] not in self.nonreal_letters

    def is_possibly_nonreal(self, name: str) -> bool:
        """Whether ``name`` might be INTEGER/LOGICAL/... -- i.e. not known real."""
        return not self.is_known_real(name)


@dataclass
class _Statements:
    lines: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def _statements(text: str, form: str) -> list[str]:
    """Logical statements with comments, labels and continuations resolved."""
    from umat_oti.fortran.parser import logical_lines_from_text

    out = []
    for line in logical_lines_from_text(text, form):
        statement = line.text.strip()
        statement = re.sub(r"^\d+\s+", "", statement)
        for part in _split_semicolons(statement):
            if part:
                out.append(part)
    return out


def _split_semicolons(statement: str) -> list[str]:
    parts, current, quote = [], [], ""
    for char in statement:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in "'\"":
            quote = char
        if char == ";":
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return parts


def _guess_form(text: str, path: Optional[Path] = None) -> str:
    if path is not None and path.suffix.lower() in {".f90", ".f95", ".f03", ".f08"}:
        return "free"
    for raw in text.splitlines():
        if not raw.strip() or raw[:1] in "Cc*!":
            continue
        if raw[:1] not in " \t0123456789":
            return "free"
    return "fixed"


def _find_include(name: str, directories: Iterable[Path]) -> Optional[Path]:
    for directory in directories:
        if directory is None:
            continue
        candidate = Path(directory) / name
        if candidate.is_file():
            return candidate
        try:
            for entry in Path(directory).iterdir():
                if entry.name.lower() == Path(name).name.lower() and entry.is_file():
                    return entry
        except OSError:
            continue
    return None


def _expand(statements: list[str], form: str, directories: list[Path],
            depth: int = 0) -> _Statements:
    result = _Statements()
    for statement in statements:
        include = _INCLUDE_RE.match(statement)
        if not include:
            result.lines.append(statement)
            continue
        target = include.group(1)
        found = _find_include(target, directories)
        if found is None and Path(target).name.upper() == "ABA_PARAM.INC":
            inner = _statements(ABA_PARAM_TEXT, "fixed")
        elif found is None:
            result.unknown.append(f"INCLUDE '{target}' is not available, so the "
                                  f"declarations and IMPLICIT rules it carries cannot be read")
            continue
        elif depth > 8:
            result.unknown.append(f"INCLUDE '{target}' nests deeper than 8 levels")
            continue
        else:
            text = found.read_text(errors="replace")
            inner = _statements(text, _guess_form(text, found))
        nested = _expand(inner, form, [found.parent if found else None, *directories], depth + 1)
        result.lines.extend(nested.lines)
        result.unknown.extend(nested.unknown)
    return result


def _units(statements: list[str]) -> dict[str, tuple[str, int, int, Optional[str]]]:
    """name -> (kind, first, last, host module) over a statement list."""
    units: dict[str, tuple[str, int, int, Optional[str]]] = {}
    stack: list[tuple[str, str, int]] = []
    module: Optional[str] = None
    for index, statement in enumerate(statements):
        module_match = _MODULE_RE.match(statement)
        header = _UNIT_HEADER_RE.match(statement)
        if module_match and not header:
            stack.append(("MODULE", module_match.group(1).upper(), index))
            module = module_match.group(1).upper()
            continue
        if header and not statement.upper().lstrip().startswith("END"):
            stack.append((header.group("kind").upper(), header.group("name").upper(), index))
            continue
        if _END_UNIT_RE.match(statement) and stack:
            kind, name, first = stack.pop()
            # The unit this one is contained in: the module of a module
            # procedure, or the subprogram an internal procedure follows the
            # CONTAINS of -- whose IMPLICIT rules and declarations it sees by
            # host association just the same.
            host = stack[-1][1] if kind != "MODULE" and stack else None
            units.setdefault(name, (kind, first, index, host))
            if kind == "MODULE":
                module = None
    del module
    return units


def _specification_part(statements: list[str], first: int, last: int) -> list[str]:
    """Statements of a unit up to CONTAINS (or its END), header excluded."""
    out = []
    depth = 0
    for statement in statements[first + 1:last]:
        if _CONTAINS_RE.match(statement) and depth == 0:
            break
        if _UNIT_HEADER_RE.match(statement) and not statement.upper().lstrip().startswith("END"):
            depth += 1
            continue
        if depth and _END_UNIT_RE.match(statement):
            depth -= 1
            continue
        if not depth:
            out.append(statement)
    return out


def _letters(spec: str) -> set[str]:
    covered: set[str] = set()
    for group in spec.split(","):
        bounds = [b.strip().upper() for b in group.split("-") if b.strip()]
        if not bounds:
            continue
        start, end = bounds[0][0], bounds[-1][0]
        if start in _LETTERS and end in _LETTERS:
            covered |= {chr(c) for c in range(ord(start), ord(end) + 1)}
    return covered


def _is_single_spec(type_text: str) -> bool:
    """A REAL type spec of default kind or kind 4 (binary32)."""
    compact = re.sub(r"\s+", "", type_text.upper())
    if not compact.startswith("REAL"):
        return False
    rest = compact[4:]
    return rest in ("", "*4", "(4)", "(KIND=4)")


def _apply_implicit(statements: Iterable[str], nonreal: set[str],
                    single: set[str] | None = None) -> bool:
    """Apply IMPLICIT statements in order; True when one is IMPLICIT NONE."""
    none = False
    for statement in statements:
        match = _IMPLICIT_RE.match(statement)
        if not match:
            continue
        remainder = match.group(1).strip()
        if remainder.upper().startswith("NONE"):
            none = True
            continue
        for spec in _IMPLICIT_SPEC_RE.finditer(remainder):
            kind = re.sub(r"\s+", "", spec.group("type").upper())
            covered = _letters(spec.group("letters"))
            if kind.startswith("REAL") or kind == "DOUBLEPRECISION":
                nonreal -= covered
                if single is not None:
                    if _is_single_spec(kind):
                        single |= covered
                    else:
                        single -= covered
            else:
                nonreal |= covered
                if single is not None:
                    single -= covered
    return none


def _declared_single(statements: Iterable[str]) -> set[str]:
    """Names declared with a binary32 REAL type spec."""
    from umat_oti.fortran.parser import split_top_level

    single = set()
    for statement in statements:
        if _UNIT_HEADER_RE.match(statement):
            continue
        match = _TYPE_DECL_RE.match(statement)
        if not match or not _is_single_spec(match.group("type")):
            continue
        rest = match.group("rest")
        if "::" in rest:
            rest = rest.split("::", 1)[1]
        elif rest.lstrip().startswith(","):
            continue
        for entity in split_top_level(rest):
            name = re.match(r"\s*([A-Za-z_]\w*)", entity)
            if name:
                single.add(name.group(1).upper())
    return single


def _declared(statements: Iterable[str]) -> tuple[set[str], set[str]]:
    """(names declared REAL, names declared with any other type)."""
    from umat_oti.fortran.parser import split_top_level

    real, other = set(), set()
    for statement in statements:
        if _UNIT_HEADER_RE.match(statement):
            continue
        match = _TYPE_DECL_RE.match(statement)
        if not match:
            continue
        kind = re.sub(r"\s+", "", match.group("type").upper())
        rest = match.group("rest")
        if "::" in rest:
            rest = rest.split("::", 1)[1]
        elif rest.lstrip().startswith(","):
            continue
        for entity in split_top_level(rest):
            name = re.match(r"\s*([A-Za-z_]\w*)", entity)
            if not name:
                continue
            target = real if (kind.startswith("REAL") or kind == "DOUBLEPRECISION") else other
            target.add(name.group(1).upper())
    return real, other


def routine_typing(source_text: str, routine: str, *, source_dir: Optional[Path] = None,
                   form: Optional[str] = None) -> RoutineTyping:
    """The typing facts for undeclared names in ``routine`` of ``source_text``."""
    form = form or _guess_form(source_text)
    directories = [Path(source_dir)] if source_dir else []
    raw = _statements(source_text, form)
    units = _units(raw)
    target = units.get(str(routine).upper())
    if target is None:
        return RoutineTyping(unknown_because=(f"routine {routine} was not found in the text",))
    _kind, first, last, host = target
    unknown: list[str] = []
    # Every host, outermost first: an internal procedure of a module procedure
    # sees the module and the procedure. Each scope's IMPLICIT rules apply on
    # top of its host's, and a name a scope declares hides its host's.
    chain: list[str] = []
    while host and host in units and host not in chain:
        chain.insert(0, host)
        host = units[host][3]
    scopes: list[list[str]] = []
    for name in chain:
        _k, hfirst, hlast, _h = units[name]
        expanded = _expand(_specification_part(raw, hfirst, hlast), form, directories)
        scopes.append(expanded.lines)
        unknown.extend(expanded.unknown)
    scope = [line for lines in scopes for line in lines]
    own = _expand(_specification_part(raw, first, last), form, directories)
    unknown.extend(own.unknown)

    nonreal = set(_DEFAULT_INTEGER)
    single = set(_LETTERS) - set(_DEFAULT_INTEGER)
    implicit_none = False
    for lines in scopes:
        if _apply_implicit(lines, nonreal, single):
            implicit_none = True
            nonreal, single = set(), set()
    if _apply_implicit(own.lines, nonreal, single):
        implicit_none = True

    real_names: set[str] = set()
    other_names: set[str] = set()
    for lines in [*scopes, own.lines]:
        inner_real, inner_other = _declared(lines)
        hidden = inner_real | inner_other | _declared_single(lines)
        real_names = (real_names - hidden) | inner_real
        other_names = (other_names - hidden) | inner_other
    seen_modules: set[str] = set()
    pending = [m.group(1).upper() for s in [*scope, *own.lines] for m in [_USE_RE.match(s)] if m]
    while pending:
        module = pending.pop()
        if module in seen_modules or module in INTRINSIC_MODULES:
            continue
        seen_modules.add(module)
        found = units.get(module)
        if found is None or found[0] != "MODULE":
            unknown.append(f"USE {module}: that module's source is not in this text, so a "
                           f"name it declares cannot be told from an implicitly typed local")
            continue
        _k, mfirst, mlast, _h = found
        spec = _expand(_specification_part(raw, mfirst, mlast), form, directories)
        unknown.extend(spec.unknown)
        module_real, module_other = _declared(spec.lines)
        real_names |= module_real
        other_names |= module_other
        pending.extend(m.group(1).upper() for s in spec.lines for m in [_USE_RE.match(s)] if m)
    single_names: set[str] = set()
    for lines in [*scopes, own.lines]:
        inner_real, inner_other = _declared(lines)
        single_names = (single_names - inner_real - inner_other) | _declared_single(lines)
    # A typed FUNCTION header types the function's name (its result).
    header = re.match(r"^\s*(?:(?:RECURSIVE|PURE|IMPURE|ELEMENTAL)\s+)*"
                      r"(?P<type>DOUBLE\s*PRECISION|REAL(?:\s*\*\s*\d+|\s*\([^)]*\))?"
                      r"|INTEGER(?:\s*\*\s*\d+|\s*\([^)]*\))?|LOGICAL|COMPLEX|CHARACTER\S*)"
                      r"\s+(?:(?:RECURSIVE|PURE|IMPURE|ELEMENTAL)\s+)*FUNCTION\s+(?P<name>\w+)",
                      raw[first], re.IGNORECASE)
    if header:
        name = header.group("name").upper()
        kind = re.sub(r"\s+", "", header.group("type").upper())
        if _is_single_spec(kind):
            single_names.add(name)
        elif kind.startswith("REAL") or kind == "DOUBLEPRECISION":
            real_names.add(name)
        else:
            other_names.add(name)
    return RoutineTyping(implicit_none=implicit_none,
                         nonreal_letters=frozenset(nonreal),
                         declared_nonreal=frozenset(other_names),
                         declared_real=frozenset(real_names - other_names - single_names),
                         unknown_because=tuple(dict.fromkeys(unknown)),
                         single_letters=frozenset(single),
                         declared_single=frozenset(single_names))
