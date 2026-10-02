"""DOUBLE COMPLEX on the stress path: shadowing it with the complex OTI type.

The OTI algebra is real. A source that computes with ``DOUBLE COMPLEX`` needs
a value that is complex and carries derivatives; :mod:`umat_oti.oti.complex_oti`
supplies one (``TYPE(Z<T>)``, a pair of real OTI numbers) in the module
``oti_complex``. This module is the transform's side of it:

* :func:`plan_complex` reads the ORIGINAL source: which names are declared
  complex and where, which complex constructs are outside what the complex OTI
  type supports (these are refused, by name), and whether the author computes
  a derivative by the complex step (reported, see below).
* :func:`retype_lifted_complex` is applied to the lifted helper set: every
  ``DOUBLE COMPLEX`` declaration becomes ``type(Z<T>)``, the caller-side type
  of a lifted complex FUNCTION is declared, and ``use oti_complex`` is added.
* :func:`retype_umat_complex_shadows` is applied to the transformed UMAT: the
  shadow of a complex name is declared ``TYPE(Z<T>)`` instead of ``TYPE(T)``
  and ``USE oti_complex`` follows ``USE oti_intrinsics``.
* :func:`real_part_wraps_added` is the guard behind both: the transform wraps
  differentiated tokens in ``REAL(...)`` in some places to mean "the value of
  the OTI number". On a complex token ``REAL(z)`` means the REAL PART, so such a
  wrap would turn ``ABS(z)`` into ``ABS(Re z)`` without a word. The guard
  counts ``REAL(`` applied directly to a complex name before and after; any
  increase refuses the transform.

The author's complex step. Every corpus source that declares DOUBLE COMPLEX on
the stress path today (the abaqus_ufl / CoupFE lineage) is a complex-step
UMAT: it perturbs an input by ``DCMPLX(0, h)`` and reads a tangent as
``AIMAG(f)/h``. Under the complex OTI type that ``i`` is the complex unit and
nothing else -- it is never an OTI direction -- so the author's tangent is
computed as the author wrote it (in OTI arithmetic, so it also carries its own
derivative), and DDSDDE is still extracted from the OTI parts of STRESS. The
idiom is detected and reported (:func:`complex_step_idioms`) so a reader can
see that a second, author-computed tangent exists and that it is not the one
the transform returns.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from umat_oti.fortran.parser import (
    logical_lines_from_text,
    parse_declaration_line,
    split_top_level,
)
from umat_oti.oti.complex_oti import (
    COMPLEX_MODULE_FILE,
    COMPLEX_MODULE_NAME,
    EXPORTED_GENERICS,
    complex_type_name,
    write_complex_oti_module,
)

#: Kind spellings that name double precision outright.
_DOUBLE_KIND_LITERALS = {"8", "KIND(1D0)", "KIND(1.D0)", "KIND(1.0D0)", "KIND(0D0)",
                         "KIND(0.D0)", "KIND(0.0D0)", "REAL64", "C_DOUBLE_COMPLEX",
                         "C_DOUBLE"}

_HEADER_RE = re.compile(
    r"^\s*(?:(?:RECURSIVE|PURE|ELEMENTAL|IMPURE)\s+)*"
    r"(?P<type>(?:DOUBLE\s+PRECISION|DOUBLE\s+COMPLEX|COMPLEX(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|REAL(?:\s*\*\s*\d+|\s*\([^)]*\))?|INTEGER(?:\s*\*\s*\d+|\s*\([^)]*\))?"
    r"|LOGICAL(?:\s*\*\s*\d+|\s*\([^)]*\))?)\s+)?"
    r"(?P<unit>SUBROUTINE|FUNCTION)\s+(?P<name>[A-Za-z_]\w*)",
    re.IGNORECASE)
_END_RE = re.compile(r"^\s*END\s*(?:SUBROUTINE|FUNCTION)?\b(?!\s*(?:IF|DO|SELECT|WHERE|INTERFACE|TYPE|MODULE|ASSOCIATE|BLOCK|FORALL))",
                     re.IGNORECASE)

#: Intrinsics the complex OTI type does not define. Applied to a complex
#: value they would not compile; refused up front with a named reason.
_UNSUPPORTED_OVER_COMPLEX = ("ACOS", "ASIN", "ATAN", "ACOSH", "ASINH", "ATANH",
                             "LOG10", "SUM", "PRODUCT", "MATMUL", "DOT_PRODUCT",
                             "MAXVAL", "MINVAL", "NORM2")

#: GNU/legacy specific names for complex intrinsics, and the generic each is.
_SPECIFIC_COMPLEX_INTRINSICS = {
    "CDABS": "ABS", "ZABS": "ABS", "CABS": "ABS",
    "CDSQRT": "SQRT", "ZSQRT": "SQRT", "CSQRT": "SQRT",
    "CDEXP": "EXP", "ZEXP": "EXP", "CEXP": "EXP",
    "CDLOG": "LOG", "ZLOG": "LOG", "CLOG": "LOG",
    "CDSIN": "SIN", "ZSIN": "SIN", "CSIN": "SIN",
    "CDCOS": "COS", "ZCOS": "COS", "CCOS": "COS",
    "DCONJG": "CONJG", "DIMAG": "AIMAG", "DREAL": "DBLE",
}
_SPECIFIC_RE = re.compile(
    r"(?<![A-Za-z0-9_%])(" + "|".join(sorted(_SPECIFIC_COMPLEX_INTRINSICS, key=len, reverse=True))
    + r")(?=\s*\()", re.IGNORECASE)


# ---------------------------------------------------------------------------
# reading the original source
# ---------------------------------------------------------------------------

@dataclass
class Routine:
    name: str
    unit: str                       # SUBROUTINE | FUNCTION
    header_type: str                # FUNCTION type-spec on the header, if any
    statements: list[tuple[str, tuple[int, ...]]] = field(default_factory=list)


def split_routines(source_text: str, form: str) -> list[Routine]:
    """The source's program units as statement lists (logical lines)."""
    routines: list[Routine] = []
    current: Routine | None = None
    depth = 0
    for line in logical_lines_from_text(source_text, form):
        text = line.text.strip()
        if not text:
            continue
        header = _HEADER_RE.match(text)
        if header and not re.match(r"^\s*END\b", text, re.IGNORECASE):
            if current is None:
                current = Routine(header.group("name").upper(), header.group("unit").upper(),
                                  (header.group("type") or "").strip())
                current.statements.append((text, line.line_numbers))
                depth = 0
                continue
            depth += 1          # an internal procedure; keep it with its host
        if current is None:
            continue
        current.statements.append((text, line.line_numbers))
        if _END_RE.match(text) and re.match(r"^\s*END\s*($|SUBROUTINE|FUNCTION)", text, re.IGNORECASE):
            if depth:
                depth -= 1
                continue
            routines.append(current)
            current = None
    if current is not None:
        routines.append(current)
    return routines


def _kind_class(raw_type: str, named_double_kinds: set[str]) -> str:
    """'double', 'single' or 'unknown' for a complex type-spec."""
    spec = re.sub(r"\s+", "", raw_type.upper())
    if spec in {"DOUBLECOMPLEX", "COMPLEX*16"}:
        return "double"
    if spec in {"COMPLEX", "COMPLEX*8"}:
        return "single"
    match = re.match(r"^COMPLEX\((?:KIND=)?(.+)\)$", spec)
    if match:
        kind = match.group(1)
        if kind in _DOUBLE_KIND_LITERALS or kind in named_double_kinds:
            return "double"
        if kind in {"4", "KIND(1.0)", "KIND(1E0)", "REAL32"}:
            return "single"
    return "unknown"


def _named_double_kinds(source_text: str) -> set[str]:
    """Named constants the source defines as the double-precision kind."""
    names: set[str] = set()
    for match in re.finditer(
            r"(?im)\b([A-Za-z_]\w*)\s*=\s*(8|KIND\s*\(\s*[01]\.?0*D0\s*\)|"
            r"SELECTED_REAL_KIND\s*\(\s*(?:P\s*=\s*)?(?:1[5-9]|[2-9]\d)\b[^)]*\)|REAL64)", source_text):
        names.add(match.group(1).upper())
    return names


@dataclass
class ComplexDeclaration:
    routine: str
    name: str
    kind: str                     # double | single | unknown
    raw_type: str
    is_parameter: bool
    statement: str
    line_numbers: tuple[int, ...]


def complex_declarations(source_text: str, form: str) -> list[ComplexDeclaration]:
    """Every name the source declares COMPLEX, by routine, with its kind."""
    double_kinds = _named_double_kinds(source_text)
    found: list[ComplexDeclaration] = []
    for routine in split_routines(source_text, form):
        if routine.unit == "FUNCTION" and re.search(r"COMPLEX", routine.header_type, re.IGNORECASE):
            found.append(ComplexDeclaration(
                routine.name, routine.name, _kind_class(routine.header_type, double_kinds),
                routine.header_type, False, routine.statements[0][0],
                routine.statements[0][1]))
        for text, numbers in routine.statements[1:]:
            if not re.match(r"^\s*(DOUBLE\s+COMPLEX|COMPLEX)\b", text, re.IGNORECASE):
                continue
            if re.search(r"\bFUNCTION\b", text, re.IGNORECASE):
                continue
            declaration = parse_declaration_line(text)
            if declaration is None or declaration.kind != "complex":
                continue
            kind = _kind_class(declaration.raw_type, double_kinds)
            for entity in declaration.entities:
                found.append(ComplexDeclaration(
                    routine.name, entity.upper_name, kind, declaration.raw_type,
                    declaration.has_parameter_attribute, text, numbers))
    return found


def _names_in(text: str) -> set[str]:
    return {token.upper() for token in re.findall(r"[A-Za-z_]\w*", text)}


def complex_step_idioms(source_text: str, form: str) -> list[dict[str, Any]]:
    """Where the author computes a derivative by the complex step.

    A routine is reported when it perturbs a value by a purely imaginary
    step (``+ DCMPLX(0, h)``, ``+ CMPLX(0, h)``, ``+ (0, h)``; h not +-1);
    ``extractions`` lists where it divides an imaginary part by that step
    (``AIMAG(...)/h``), when it is written that way. The names written from the
    extraction are the author's tangent; ``consumers`` lists the statements
    elsewhere in the file that read them, so a reader can see where the
    author's tangent goes. The transform does not use it for DDSDDE.
    """
    routines = split_routines(source_text, form)
    parameters: dict[str, str] = {}
    for match in re.finditer(r"(?im)\b([A-Za-z_]\w*)\s*=\s*([-+]?\d+\.?\d*(?:[dDeE][-+]?\d+)?)",
                             source_text):
        parameters.setdefault(match.group(1).upper(), match.group(2))
    step_re = re.compile(
        r"(?:D?CMPLX\s*\(\s*0(?:\.0*)?(?:[dDeE]0)?(?:_\w+)?\s*,\s*(?P<a>[^,()]+(?:\([^()]*\))?)\s*[,)])"
        r"|(?:\(\s*0(?:\.0*)?(?:[dDeE][-+]?0+)?\s*,\s*(?P<b>[A-Za-z_]\w*|\d+\.?\d*[dDeE][-+]?\d+)\s*\))",
        re.IGNORECASE)
    found: list[dict[str, Any]] = []
    for routine in routines:
        perturbations: list[dict[str, Any]] = []
        steps: set[str] = set()
        for text, numbers in routine.statements:
            if not re.search(r"(?<![<>=/])=(?!=)", text):
                continue
            for match in step_re.finditer(text):
                step = (match.group("a") or match.group("b") or "").strip()
                if not step or re.fullmatch(r"[-+]?0*\.?0*(?:[dDeE][-+]?\d+)?", step):
                    continue
                if step.upper().lstrip("+-") in {"1", "1.", "1.0", "1.0D0", "1D0", "1.D0", "1.E0", "1.0E0"}:
                    continue          # the unit i itself, not a step
                steps.add(step.upper())
                perturbations.append({"line": numbers[0] if numbers else None,
                                      "statement": text.strip(), "step": step})
        if not steps:
            continue
        extractions: list[dict[str, Any]] = []
        written: set[str] = set()
        for text, numbers in routine.statements:
            for step in steps:
                if re.search(r"\b(?:AIMAG|DIMAG|IMAG)\s*\(.*\)\s*/\s*" + re.escape(step) + r"\b",
                             text, re.IGNORECASE):
                    target = re.match(r"^\s*([A-Za-z_]\w*)", text)
                    if target:
                        written.add(target.group(1).upper())
                    extractions.append({"line": numbers[0] if numbers else None,
                                        "statement": text.strip(), "step": step})
        # The perturbation alone identifies the idiom. The extraction may be
        # written in a form not matched above -- AIMAG(F)*HINV with HINV =
        # 1/h (Vera's t5d) -- and requiring it switched the imaginary-part
        # guard off for exactly such a source.
        values = {step: parameters.get(step, step) for step in sorted(steps)}
        consumers: list[dict[str, Any]] = []
        for other in routines:
            for text, numbers in other.statements:
                if other.name == routine.name:
                    continue
                if written & _names_in(text) and re.match(r"^\s*CALL\b", text, re.IGNORECASE):
                    consumers.append({"routine": other.name,
                                      "line": numbers[0] if numbers else None,
                                      "statement": text.strip()})
        found.append({
            "routine": routine.name,
            "kind": "author_complex_step_derivative",
            "steps": values,
            "perturbations": perturbations,
            "extractions": extractions,
            "tangent_names": sorted(written),
            "consumers_of_the_routine": _call_sites(routines, routine.name),
            "statement": ("The author computes a derivative by the complex step in "
                          f"{routine.name}. Under the complex OTI type its imaginary unit is "
                          "the complex unit, never an OTI direction: the routine runs as "
                          "written and its tangent is not the one returned. DDSDDE is "
                          "extracted from the OTI parts of STRESS, i.e. it is the derivative "
                          "of whatever STRESS actually computes."),
        })
    return found


def _call_sites(routines: list[Routine], callee: str) -> list[dict[str, Any]]:
    sites = []
    pattern = re.compile(rf"^\s*CALL\s+{re.escape(callee)}\b", re.IGNORECASE)
    for routine in routines:
        for text, numbers in routine.statements:
            if pattern.match(text):
                sites.append({"routine": routine.name, "line": numbers[0] if numbers else None,
                              "statement": text.strip()})
    return sites


@dataclass
class ComplexPlan:
    """What the transform does about complex values in one source."""
    declarations: list[ComplexDeclaration] = field(default_factory=list)
    umat_complex_names: set[str] = field(default_factory=set)
    umat_complex_on_path: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    complex_step: list[dict[str, Any]] = field(default_factory=list)
    original_real_wraps: dict[str, int] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return any(not d.is_parameter for d in self.declarations)

    def report(self) -> dict[str, Any]:
        by_routine: dict[str, list[str]] = {}
        for declaration in self.declarations:
            by_routine.setdefault(declaration.routine, []).append(declaration.name)
        return {
            "complex_oti_type_used": self.active and not self.blockers,
            "module": COMPLEX_MODULE_FILE if self.active else "",
            "complex_names_by_routine": {k: sorted(set(v)) for k, v in sorted(by_routine.items())},
            "umat_complex_names_on_stress_path": list(self.umat_complex_on_path),
            "author_complex_step": self.complex_step,
            "derivative_semantics": (
                "Complex values are pairs of real OTI numbers (C x OTI). Holomorphic "
                "operations differentiate exactly; REAL/DBLE, AIMAG, CONJG and ABS are "
                "differentiated as real maps. SQRT, LOG and non-integer powers use the "
                "principal branch (cut on the negative real axis); ABS, SQRT and powers "
                "at 0 return zero derivative (not differentiable there)."),
            "blockers": list(self.blockers),
        }


def plan_complex(source_text: str, form: str, selected_umat: str,
                 roles: dict[str, set[str]] | None = None,
                 routines: Iterable[str] | None = None) -> ComplexPlan:
    """Read the original source and decide what to do about COMPLEX in it.

    ``routines``, when given, are the routines that will be differentiated --
    the selected UMAT and the helper-lifting closure. Only their constructs
    are refused: a complex EQUIVALENCE in an eigen-solver the stress path
    never calls is none of this transform's business.
    """
    differentiated = ({str(r).upper() for r in routines} if routines is not None else None)
    plan = ComplexPlan(declarations=complex_declarations(source_text, form))
    if not plan.declarations:
        # Nothing declared complex -- unless a name is complex through
        # IMPLICIT, which the lifted body's own implicit rule would silently
        # make a real OTI number.
        for routine in split_routines(source_text, form):
            for text, numbers in routine.statements:
                if re.match(r"^\s*IMPLICIT\b.*\bCOMPLEX\b", text, re.IGNORECASE):
                    where = f"line {numbers[0]}" if numbers else routine.name
                    plan.blockers.append(
                        f"{routine.name} types names COMPLEX through IMPLICIT at {where}: "
                        f"{text.strip()!r}. The lifted body writes its own implicit rule (the "
                        f"real OTI type), so an implicitly complex name would lose its "
                        f"imaginary part. Declare the complex names explicitly. Not supported "
                        f"by this transform.")
        return plan
    selected = (selected_umat or "UMAT").upper()
    plan.umat_complex_names = {d.name for d in plan.declarations
                               if d.routine == selected and not d.is_parameter}
    on_path = set()
    if roles:
        on_path = (set(roles.get("seed", set())) | set(roles.get("promote", set())))
    plan.umat_complex_on_path = sorted(plan.umat_complex_names & {n.upper() for n in on_path})
    routines = {r.name: r for r in split_routines(source_text, form)}
    complex_by_routine: dict[str, set[str]] = {}
    for declaration in plan.declarations:
        complex_by_routine.setdefault(declaration.routine, set()).add(declaration.name)
        if declaration.is_parameter:
            continue
        if differentiated is not None and declaration.routine not in differentiated:
            continue
        if declaration.kind != "double":
            plan.blockers.append(
                f"{declaration.name} in {declaration.routine} is declared "
                f"{declaration.raw_type.upper()}, which is not double precision (kind "
                f"{declaration.kind}). The complex OTI type carries REAL(8) parts, so "
                f"shadowing it would change the primal arithmetic; a single-precision or "
                f"unresolved-kind COMPLEX is not supported by this transform.")
    for name, routine in routines.items():
        if differentiated is not None and name not in differentiated:
            continue
        names = complex_by_routine.get(name, set())
        constants = {d.name for d in plan.declarations if d.routine == name and d.is_parameter}
        for text, numbers in routine.statements:
            call = re.match(r"^\s*CALL\s+\w+\s*\((.*)\)\s*$", text, re.IGNORECASE)
            if call and constants:
                passed = {a.strip().upper() for a in split_top_level(call.group(1))} & constants
                if passed:
                    plan.blockers.append(
                        f"{name} passes the complex PARAMETER {', '.join(sorted(passed))} as an "
                        f"actual argument: {text.strip()!r}. A lifted callee receives a complex "
                        f"OTI dummy and an implicit interface would hand it a plain COMPLEX. "
                        f"Not supported by this transform.")
            upper = text.upper()
            where = f"line {numbers[0]}" if numbers else name
            if re.match(r"^\s*IMPLICIT\b.*\bCOMPLEX\b", upper):
                plan.blockers.append(
                    f"{name} types names COMPLEX through IMPLICIT at {where}: {text.strip()!r}. "
                    f"The lifted body writes its own implicit rule (the real OTI type), so "
                    f"an implicitly complex name would lose its imaginary part. Declare the "
                    f"complex names explicitly. Not supported by this transform.")
            if not names:
                continue
            if re.match(r"^\s*(COMMON|EQUIVALENCE)\b", upper) and names & _names_in(text):
                plan.blockers.append(
                    f"{name} puts complex names ({', '.join(sorted(names & _names_in(text)))}) "
                    f"in {upper.split()[0]} at {where}. That fixes a storage layout the "
                    f"complex OTI type cannot occupy. Not supported by this transform.")
            for intrinsic in _UNSUPPORTED_OVER_COMPLEX:
                for match in re.finditer(rf"(?<![A-Za-z0-9_%]){intrinsic}\s*\(", upper):
                    close = _matching_paren(upper, match.end() - 1)
                    argument = upper[match.end():close] if close > 0 else upper[match.end():]
                    if names & _names_in(argument):
                        plan.blockers.append(
                            f"{name} applies {intrinsic} to a complex value at {where}: "
                            f"{text.strip()!r}. The complex OTI type defines no {intrinsic}. "
                            f"Not supported by this transform.")
        declared = {d.upper_name for t, _ in routine.statements[1:] for d in _entities(t)}
        for generic in sorted(declared & set(EXPORTED_GENERICS)):
            plan.blockers.append(
                f"{name} declares a variable named {generic}, which oti_complex "
                f"exports as a generic. Not supported by this transform.")
    plan.blockers = list(dict.fromkeys(plan.blockers))
    plan.complex_step = complex_step_idioms(source_text, form)
    return plan


def _entities(statement: str):
    declaration = parse_declaration_line(statement)
    return declaration.entities if declaration is not None else ()


def _matching_paren(text: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


# ---------------------------------------------------------------------------
# rewriting the lifted helpers
# ---------------------------------------------------------------------------

_LIFTED_HEADER_RE = re.compile(r"^(subroutine|function)\s+([A-Za-z_]\w*)_oti\s*\(", re.IGNORECASE)
_LIFTED_END_RE = re.compile(r"^end\s+(subroutine|function)\s+([A-Za-z_]\w*)_oti\s*$", re.IGNORECASE)
_SPEC_RE = re.compile(
    r"^\s*(type\s*\(|integer\b|real\b|double\s+precision\b|double\s+complex\b|complex\b|"
    r"character\b|logical\b|dimension\b|parameter\b|external\b|intrinsic\b|common\b|"
    r"save\b|equivalence\b|implicit\b|use\b|namelist\b|data\b)", re.IGNORECASE)


#: Generic intrinsics of complex arithmetic. The lifter's own intrinsic list
#: does not know them, so it files them as implicitly typed OTI variables; in
#: a routine that declares complex names they are taken back out of that set.
COMPLEX_INTRINSIC_NAMES = frozenset({
    "DBLE", "DCMPLX", "CMPLX", "AIMAG", "DIMAG", "IMAG", "CONJG", "DCONJG",
    "DREAL", "REAL", "ATAN2"})

#: Intrinsics over the real OTI type that oti_complex adds, so a lifted
#: routine of a source that declares complex values may use them.
REAL_OTI_INTRINSICS_ADDED = frozenset({"ATAN2"})


def source_declares_complex(source_text: str) -> bool:
    """Whether any statement declares a non-PARAMETER complex name."""
    for match in re.finditer(r"(?im)^[ \t]*(?:\d+[ \t]+)?(DOUBLE[ \t]+COMPLEX|COMPLEX)\b(.*)$",
                             source_text or ""):
        rest = match.group(2)
        if re.search(r"\bFUNCTION\b", rest, re.IGNORECASE):
            return True
        if not re.search(r"\bPARAMETER\b", rest, re.IGNORECASE):
            return True
    return False


def declared_complex_names(statements: Iterable[str]) -> set[str]:
    """Names a routine's statements declare complex (PARAMETER constants excluded).

    Used by the lifter so that its IF-condition rewrite does not wrap a complex
    token in REAL(): that wrap means "value of the OTI number" on a real
    shadow and "real part" on a complex one.
    """
    names: set[str] = set()
    for statement in statements:
        text = statement.strip()
        if not re.match(r"^(DOUBLE\s+COMPLEX|COMPLEX)\b", text, re.IGNORECASE):
            continue
        if re.search(r"\bFUNCTION\b", text, re.IGNORECASE):
            continue
        declaration = parse_declaration_line(text)
        if declaration is None or declaration.kind != "complex" or declaration.has_parameter_attribute:
            continue
        names.update(entity.upper_name for entity in declaration.entities)
    return names


def _retyped_complex_line(line: str, ztype: str) -> tuple[str, set[str]] | None:
    stripped = line.strip()
    if not re.match(r"^(DOUBLE\s+COMPLEX|COMPLEX)\b", stripped, re.IGNORECASE):
        return None
    if re.search(r"\bFUNCTION\b", stripped, re.IGNORECASE):
        return None
    declaration = parse_declaration_line(stripped)
    if declaration is None or declaration.kind != "complex" or declaration.has_parameter_attribute:
        return None
    attributes = [a.strip() for a in declaration.attributes if a.strip()]
    # DIMENSION is folded into the entities by the parser. INTENT is dropped:
    # it changes nothing about the values, and the transform reads the lifted
    # artifact's dummy types from plain ``type(...) :: names`` lines
    # (oti_typed_dummies_of_lifted_helpers), so a complex dummy whose name
    # starts with I-N must be declared in that form to be seen as
    # differentiated.
    attributes = [a for a in attributes
                  if not a.upper().startswith(("DIMENSION", "INTENT"))]
    entities = ", ".join(entity.render() for entity in declaration.entities)
    prefix = f"type({ztype})" + "".join(f", {a}" for a in attributes)
    indent = line[: len(line) - len(line.lstrip())]
    return f"{indent}{prefix} :: {entities}", {e.upper_name for e in declaration.entities}


def complex_function_names(source_text: str, form: str) -> set[str]:
    """Functions whose result is complex: header-typed, or result declared complex."""
    names: set[str] = set()
    for routine in split_routines(source_text, form):
        if routine.unit != "FUNCTION":
            continue
        if re.search(r"COMPLEX", routine.header_type, re.IGNORECASE):
            names.add(routine.name)
            continue
        header = routine.statements[0][0]
        result = re.search(r"\bRESULT\s*\(\s*([A-Za-z_]\w*)\s*\)", header, re.IGNORECASE)
        result_name = (result.group(1) if result else routine.name).upper()
        if result_name in declared_complex_names(t for t, _ in routine.statements[1:]):
            names.add(routine.name)
    return names


def retype_lifted_complex(lifted_source: str, type_name: str, *,
                          source_text: str = "", form: str = "free") -> str:
    """Give the lifted helpers' complex names the complex OTI type.

    Applied to the text ``lift_helper_set_source`` produced, before it is
    wrapped. A source with no complex declaration comes back unchanged, byte
    for byte. Per lifted routine:

    * each ``DOUBLE COMPLEX``/``COMPLEX*16``/``COMPLEX(8)`` declaration (not a
      PARAMETER) becomes ``type(Z<T>)`` with its attributes, placed in the
      specification part (ahead of any assignment the lifter wrote from DATA);
    * a ``type(T)`` declaration the lifter wrote for a name the routine also
      declares complex -- a function's result variable -- is removed;
    * a lifted FUNCTION whose result is complex is declared ``type(Z<T>)``
      under its lifted name ``<name>_oti`` in every routine that references it;
    * GNU specific names (CDABS, DIMAG, ...) become the generics;
    * ``use oti_complex`` is added after ``use oti_intrinsics``.
    """
    if not source_declares_complex(source_text or lifted_source):
        return lifted_source
    ztype = complex_type_name(type_name)
    complex_functions = complex_function_names(source_text, form) if source_text else set()
    lines = lifted_source.split("\n")
    out: list[str] = []
    index = 0
    while index < len(lines):
        header = _LIFTED_HEADER_RE.match(lines[index])
        if not header:
            out.append(lines[index])
            index += 1
            continue
        end = index + 1
        while end < len(lines) and not _LIFTED_END_RE.match(lines[end]):
            end += 1
        block = lines[index:end + 1]
        out.extend(_retype_block(block, header.group(2).upper(), type_name, ztype, complex_functions))
        index = end + 1
    return "\n".join(out)


def _retype_block(block: list[str], routine: str, type_name: str, ztype: str,
                  complex_functions: set[str]) -> list[str]:
    retyped: list[str] = []
    complex_names: set[str] = set()
    keep: list[str] = []
    for line in block:
        result = _retyped_complex_line(line, ztype)
        if result is None:
            keep.append(line)
            continue
        text, names = result
        retyped.append(text)
        complex_names |= names
    body_text = "\n".join(keep)
    referenced = {name for name in complex_functions
                  if name != routine
                  and re.search(rf"\b{re.escape(name)}_OTI\s*\(", body_text, re.IGNORECASE)}
    for name in sorted(referenced):
        if not re.search(rf"::.*\b{re.escape(name)}_oti\b", body_text, re.IGNORECASE):
            retyped.append(f"    type({ztype}) :: {name.lower()}_oti")
    # The function's own result, when the header typed the function complex.
    if routine in complex_functions:
        header = block[0]
        result = re.search(r"\bresult\s*\(\s*([A-Za-z_]\w*)\s*\)", header, re.IGNORECASE)
        result_name = (result.group(1) if result else routine).upper()
        if result_name not in complex_names:
            retyped.append(f"    type({ztype}) :: {result_name.lower()}")
            complex_names.add(result_name)
    # Drop real-OTI declarations of names now declared complex.
    cleaned: list[str] = []
    type_decl = re.compile(rf"^(\s*)type\(\s*{re.escape(type_name)}\s*\)\s*::\s*(.+)$", re.IGNORECASE)
    for line in keep:
        match = type_decl.match(line)
        if match and complex_names:
            items = [item.strip() for item in split_top_level(match.group(2)) if item.strip()]
            kept = [item for item in items
                    if re.match(r"^([A-Za-z_]\w*)", item).group(1).upper() not in complex_names]
            if not kept:
                continue
            if len(kept) != len(items):
                line = f"{match.group(1)}type({type_name}) :: {', '.join(kept)}"
        cleaned.append(line)
    # Place: after the last specification statement that precedes the first
    # executable one (the header is never a specification statement).
    insert_at = 1
    for position in range(1, len(cleaned)):
        if _SPEC_RE.match(cleaned[position]) or not cleaned[position].strip():
            insert_at = position + 1
            continue
        if _LIFTED_END_RE.match(cleaned[position]):
            break
        break
    with_use: list[str] = []
    for position, line in enumerate(cleaned):
        if position == insert_at:
            with_use.extend(retyped)
        with_use.append(line)
        if re.match(r"^\s*use\s+oti_intrinsics\b", line, re.IGNORECASE):
            with_use.append(f"    use {COMPLEX_MODULE_NAME}")
    if insert_at >= len(cleaned):
        with_use[-1:-1] = retyped
    if not any(re.match(r"^\s*use\s+oti_intrinsics\b", l, re.IGNORECASE) for l in cleaned):
        with_use.insert(1, f"    use {COMPLEX_MODULE_NAME}")
    return [_SPECIFIC_RE.sub(lambda m: _SPECIFIC_COMPLEX_INTRINSICS[m.group(1).upper()], line)
            if not _SPEC_RE.match(line) else line for line in with_use]


# ---------------------------------------------------------------------------
# rewriting the transformed UMAT
# ---------------------------------------------------------------------------

def retype_umat_complex_shadows(transformed_source: str, plan: ComplexPlan,
                                type_name: str, form: str) -> str:
    """Declare complex shadows with the complex OTI type; USE oti_complex.

    Unchanged, byte for byte, when the plan is not active or nothing in the
    text refers to the complex type.
    """
    if not plan.active:
        return transformed_source
    ztype = complex_type_name(type_name)
    names = plan.umat_complex_names
    lines = transformed_source.split("\n")
    pattern = None
    if names:
        pattern = re.compile(
            rf"^(\s*)TYPE\(\s*{re.escape(type_name)}\s*\)(\s*(?:,\s*[A-Z]+\s*)*::\s*)"
            rf"((?:{'|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True))})_OTI\b.*)$",
            re.IGNORECASE)
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if pattern is not None:
            match = pattern.match(line)
            if match:
                line = f"{match.group(1)}TYPE({ztype}){match.group(2)}{match.group(3)}"
        out.append(line)
        index += 1
        if re.match(r"^\s*USE\s+oti_intrinsics\b", line, re.IGNORECASE):
            while index < len(lines) and _is_continuation(lines[index], form, lines[index - 1]):
                out.append(lines[index])
                index += 1
            out.append(("      " if form == "fixed" else "") + f"USE {COMPLEX_MODULE_NAME}")
    return "\n".join(out)


def _is_continuation(line: str, form: str, previous: str) -> bool:
    if form == "fixed":
        return len(line) > 5 and line[:5].strip() == "" and line[5] not in " 0" and not line[:1] in "cC*!"
    return previous.rstrip().endswith("&")


_REAL_OF = r"\bREAL\s*\(\s*{name}\b"


def real_part_wraps(text: str, names: Iterable[str], suffix: str = "") -> int:
    """How many times ``REAL(`` is applied directly to one of ``names``.

    A wrap that is itself the argument of DBLE( or REAL( is not counted: the
    real part of the real part is the real part, so it changes nothing.
    """
    total = 0
    for name in names:
        for match in re.finditer(_REAL_OF.format(name=re.escape(name + suffix)), text, re.IGNORECASE):
            before = re.sub(r"\s+", "", text[:match.start()]).upper()
            if before.endswith(("DBLE(", "REAL(")):
                continue
            total += 1
    return total


def real_part_wraps_added(original_text: str, transformed_text: str,
                          names: Iterable[str]) -> list[str]:
    """Names the transform wrapped in REAL() more often than the source did.

    ``REAL(z)`` on a complex z is its real part. The transform wraps
    differentiated tokens in REAL() to mean the value of an OTI number, which
    on a complex token silently discards the imaginary part. A source that
    writes ``REAL(z)`` itself is counted on both sides and is not flagged.
    """
    names = list(names)
    flagged = []
    for name in names:
        before = real_part_wraps(original_text, [name])
        after = real_part_wraps(transformed_text, [name]) + real_part_wraps(transformed_text, [name], "_OTI")
        if after > before:
            flagged.append(name)
    return flagged


def real_wrap_issues(plan: ComplexPlan, source_text: str, form: str,
                     transformed_source: str, lifted_text: str) -> list[str]:
    """Blockers for every complex name a REAL() wrap was added to.

    Compared routine by routine: each lifted ``X_oti`` against the source's X,
    and the transformed file (which carries the rewritten UMAT beside the
    source's other routines) against the whole source.
    """
    if not plan.active:
        return []
    issues: list[str] = []
    by_routine: dict[str, set[str]] = {}
    for declaration in plan.declarations:
        if not declaration.is_parameter:
            by_routine.setdefault(declaration.routine, set()).add(declaration.name)
    for name in real_part_wraps_added(source_text, transformed_source,
                                      sorted(plan.umat_complex_names)):
        issues.append(
            f"The transformed UMAT applies REAL() to the complex value {name} more often "
            f"than the source does. On a complex value REAL() is the real part, so the "
            f"wrap would drop the imaginary part without a word. Refused.")
    originals = {r.name: "\n".join(t for t, _ in r.statements)
                 for r in split_routines(source_text, form)}
    for block_name, block in _lifted_blocks(lifted_text):
        original = originals.get(block_name, "")
        for name in real_part_wraps_added(original, block, sorted(by_routine.get(block_name, ()))):
            issues.append(
                f"The lifted {block_name.lower()}_oti applies REAL() to the complex value "
                f"{name} more often than the source's {block_name} does. On a complex value "
                f"REAL() is the real part, so the wrap would drop the imaginary part "
                f"without a word. Refused.")
    return issues


_CALL_RE = re.compile(r"^\s*(?:\d+\s+)?CALL\s+([A-Za-z_]\w*)_OTI\s*\((.*)\)\s*$", re.IGNORECASE)


def _declared_with(text: str, type_spec: str) -> set[str]:
    names: set[str] = set()
    pattern = re.compile(rf"^\s*TYPE\s*\(\s*{re.escape(type_spec)}\s*\)\s*(?:,[^:]*)?::\s*(.+)$",
                         re.IGNORECASE)
    for line in text.split("\n"):
        match = pattern.match(line)
        if match:
            for item in split_top_level(match.group(1)):
                found = re.match(r"\s*([A-Za-z_]\w*)", item)
                if found:
                    names.add(found.group(1).upper())
    return names


def argument_type_mismatches(transformed_source: str, form: str, lifted_text: str,
                             type_name: str) -> list[str]:
    """CALLs where a real-OTI value meets a complex-OTI dummy, or the reverse.

    The lifted helpers are external subprograms reached through an implicit
    interface, so a TYPE(T) array handed to a TYPE(Z<T>) dummy compiles and
    the callee reads two real OTI numbers as one complex one. The existing
    leak checks only know "OTI or not"; this one knows which OTI.
    """
    ztype = complex_type_name(type_name)
    dummies: dict[str, list[str]] = {}
    scopes: list[tuple[str, str]] = []
    for name, block in _lifted_blocks(lifted_text):
        header = re.match(r"^(?:subroutine|function)\s+\w+\s*\((.*?)\)", block, re.IGNORECASE)
        arguments = [a.strip().upper() for a in split_top_level(header.group(1))] if header else []
        complex_names = _declared_with(block, ztype)
        dummies[name] = ["Z" if a in complex_names else "T" for a in arguments]
        scopes.append((name, block))
    if not any("Z" in kinds for kinds in dummies.values()):
        return []
    # The transformed file is read as one scope; its complex shadows are
    # declared with the complex type, everything else differentiated is T.
    transformed_lines = [line.text for line in logical_lines_from_text(transformed_source, form)]
    scopes.append(("<transformed>", "\n".join(transformed_lines)))
    issues: list[str] = []
    for scope_name, text in scopes:
        complex_here = _declared_with(text, ztype)
        real_here = _declared_with(text, type_name)
        for line in text.split("\n"):
            call = _CALL_RE.match(line)
            if not call:
                continue
            callee = call.group(1).upper()
            expected = dummies.get(callee)
            if not expected:
                continue
            for position, actual in enumerate(split_top_level(call.group(2))):
                if position >= len(expected):
                    break
                base = re.match(r"\s*([A-Za-z_]\w*)\s*(\(|$)", actual)
                if not base:
                    continue
                name = base.group(1).upper()
                kind = "Z" if name in complex_here else ("T" if name in real_here else "")
                if kind and kind != expected[position]:
                    issues.append(
                        f"{name} ({'complex' if kind == 'Z' else 'real'} OTI) is passed to "
                        f"{callee}_OTI at position {position + 1}, whose dummy is "
                        f"{'complex' if expected[position] == 'Z' else 'real'} OTI "
                        f"(in {scope_name.lower()}: {line.strip()!r}). Through an implicit "
                        f"interface the callee would reinterpret the memory. Refused.")
    return list(dict.fromkeys(issues))


_IMAG_RE = re.compile(r"(?<![A-Za-z0-9_%])(?:AIMAG|DIMAG|IMAG)\s*\(", re.IGNORECASE)
_ASSIGN_RE = re.compile(r"^\s*(?:\d+\s+)?([A-Za-z_]\w*)\s*(?:\([^=]*\))?\s*=(?!=)(.*)$")
_CONDITION_RE = re.compile(r"^\s*(?:\d+\s+)?(?:ELSE\s*IF|IF|DO\s+WHILE)\s*\(", re.IGNORECASE)


def _condition_and_rest(statement: str) -> tuple[str, str] | None:
    match = _CONDITION_RE.match(statement)
    if not match:
        return None
    close = _matching_paren(statement, match.end() - 1)
    if close < 0:
        return None
    return statement[match.end():close], statement[close + 1:]


_PART_OF_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9_%])(?:DBLE|DREAL|REAL|ABS|CDABS|ZABS|CABS)\s*\(\s*([A-Za-z_]\w*)\s*"
    r"(?:\((?:[^()]|\([^()]*\))*\)\s*)?(?:,\s*(?:KIND\s*=\s*)?\w+\s*)?\)",
    re.IGNORECASE)
_CONSTRUCTOR_RE = re.compile(r"(?<![A-Za-z0-9_%])D?CMPLX\s*\(", re.IGNORECASE)


def _reads_an_imaginary_part(rhs: str, complex_here: set[str], tainted: set[str]) -> bool:
    """Whether a REAL value assigned from ``rhs`` can carry an imaginary part.

    AIMAG and a tainted name do. So does any complex name or complex
    constructor that is not simply taken apart by DBLE/REAL/ABS of the bare
    name: ``DBLE(DCMPLX(0,-1)*Z)`` is Im(Z) written without AIMAG (Vera's
    t5b). When it cannot be told, it is counted as one.
    """
    if _IMAG_RE.search(rhs) or tainted & _names_in(rhs):
        return True
    remainder = _PART_OF_NAME_RE.sub(
        lambda m: " " if m.group(1).upper() in complex_here else m.group(0), rhs)
    return bool(complex_here & _names_in(remainder) or _CONSTRUCTOR_RE.search(remainder))


def _dummies(statements: list[str]) -> list[str]:
    if not statements:
        return []
    header = re.search(r"\(([^()]*)\)", statements[0])
    if not header or not _HEADER_RE.match(statements[0]):
        return []
    return [a.strip().upper() for a in header.group(1).split(",") if a.strip()]


def imaginary_part_branches(transformed_source: str, form: str,
                            lifted_text: str) -> list[dict[str, Any]]:
    """Conditions in a differentiated scope that depend on an imaginary part.

    A scope is differentiated when it is a lifted helper or a routine of the
    transformed file that USEs oti_complex. A condition depends on an
    imaginary part when it reads AIMAG/DIMAG/IMAG directly or a REAL name
    that may hold one: assigned (transitively) from AIMAG, from a complex
    expression not reduced to its real part or modulus, or returned through
    a CALL argument by a callee whose matching dummy is so tainted -- or by
    any callee that cannot be read, when the CALL passes a complex value
    (Vera's t5c: ``CALL IMPART(Z, XIM)``).
    """
    scopes: list[tuple[str, list[str]]] = []
    for routine in split_routines(lifted_text or "", "free"):
        scopes.append((routine.name, [t for t, _ in routine.statements]))
    readable = {name for name, _ in scopes}
    for routine in split_routines(transformed_source or "", form):
        statements = [t for t, _ in routine.statements]
        readable.add(routine.name)
        if any(re.match(rf"^\s*USE\s+{COMPLEX_MODULE_NAME}\b", t, re.IGNORECASE) for t in statements):
            scopes.append((routine.name, statements))
    complex_by_scope = {name: _complex_names_in_scope(statements) for name, statements in scopes}
    dummies_by_scope = {name: _dummies(statements) for name, statements in scopes}
    tainted_by_scope: dict[str, set[str]] = {name: set() for name, _ in scopes}
    # Only REAL-valued names are tainted: a real variable that holds an
    # imaginary part (MAX_IMAG = ABS(AIMAG(..)), MREAL = AIMAG(ZDEV)). A
    # complex value rebuilt from its own parts -- R = DCMPLX(clamp(DBLE(R)),
    # AIMAG(R)) -- is value arithmetic, not a test of the derivative carrier.
    for _ in range(12):
        changed = False
        for name, statements in scopes:
            complex_here = complex_by_scope[name]
            tainted = tainted_by_scope[name]
            before = len(tainted)
            for text in statements:
                split = _condition_and_rest(text)
                body = split[1] if split else text
                call = re.match(r"^\s*(?:\d+\s+)?CALL\s+([A-Za-z_]\w*)\s*\((.*)\)\s*$", body, re.IGNORECASE)
                if call:
                    callee = call.group(1).upper()
                    arguments = split_top_level(call.group(2))
                    callee_dummies = dummies_by_scope.get(callee)
                    if callee_dummies is not None:
                        for position, argument in enumerate(arguments):
                            target = re.match(r"\s*([A-Za-z_]\w*)", argument)
                            if (target and position < len(callee_dummies)
                                    and callee_dummies[position] in tainted_by_scope[callee]
                                    and target.group(1).upper() not in complex_here):
                                tainted.add(target.group(1).upper())
                    elif callee not in readable and complex_here & _names_in(call.group(2)):
                        for argument in arguments:
                            target = re.match(r"\s*([A-Za-z_]\w*)\s*(?:\(.*\))?\s*$", argument)
                            if target and target.group(1).upper() not in complex_here:
                                tainted.add(target.group(1).upper())
                    continue
                assignment = _ASSIGN_RE.match(body)
                if not assignment:
                    continue
                target = assignment.group(1).upper()
                if target in complex_here:
                    continue
                if _reads_an_imaginary_part(assignment.group(2), complex_here, tainted):
                    tainted.add(target)
            changed |= len(tainted) != before
        if not changed:
            break
    found: list[dict[str, Any]] = []
    for name, statements in scopes:
        tainted = tainted_by_scope[name]
        for text in statements:
            split = _condition_and_rest(text)
            if split is None:
                continue
            condition = split[0]
            if _IMAG_RE.search(condition) or tainted & _names_in(condition):
                found.append({"routine": name, "condition": text.strip()[:200],
                              "imaginary_names": sorted(tainted & _names_in(condition))})
    return found


def _complex_names_in_scope(statements: list[str]) -> set[str]:
    names: set[str] = set()
    for text in statements:
        match = re.match(r"^\s*(TYPE\s*\(\s*Z[A-Za-z0-9_]*\s*\)|(?:DOUBLE\s+COMPLEX|COMPLEX)\b)(.*)$",
                         text, re.IGNORECASE)
        if not match or re.search(r"\bFUNCTION\b", text, re.IGNORECASE):
            continue
        rest = match.group(2)
        entities = rest.split("::", 1)[1] if "::" in rest else re.sub(r"^\s*(\*\s*\d+|\([^)]*\))", "", rest)
        for item in split_top_level(entities):
            found = re.match(r"\s*([A-Za-z_]\w*)", item)
            if found:
                names.add(found.group(1).upper())
    return names


def complex_step_branch_issues(plan: ComplexPlan, transformed_source: str, form: str,
                               lifted_text: str) -> list[str]:
    """Refuse a complex-step source whose differentiated code branches on Im.

    In a source that computes its own complex-step derivative the imaginary
    part is the derivative carrier, and a branch on it is logic written for
    the complex step: typically a different algorithm for the derivative at a
    point where the value algorithm is not differentiable (a repeated
    eigenvalue). Under the complex OTI type the primal's imaginary part is
    identically zero, so that branch is never taken and the OTI derivative is
    that of the value algorithm -- wrong exactly where the author needed the
    other branch. Measured on tengzhang48/abaqus_ufl ogden_umat.for: DDSDDE
    disagrees with FD of the original (and with the author's own complex-step
    tangent) at repeated principal stretches. A source without the idiom may
    branch on imaginary parts freely (e.g. selecting the real roots of a cubic).
    """
    if not plan.complex_step:
        return []
    branches = imaginary_part_branches(transformed_source, form, lifted_text)
    if not branches:
        return []
    routines = sorted({b["routine"] for b in branches})
    example = branches[0]
    return [
        f"The source computes its own complex-step derivative "
        f"({', '.join(sorted({c['routine'] for c in plan.complex_step}))}) and the differentiated "
        f"code branches on an imaginary part in {', '.join(routines)} "
        f"({len(branches)} condition(s), e.g. {example['routine']}: {example['condition']!r}). "
        f"Those branches are written for the complex step; under the complex OTI type the "
        f"imaginary part of every primal value is zero, so they are never taken and DDSDDE "
        f"would be the derivative of the value algorithm, which is not differentiable where "
        f"the author switches (repeated eigenvalues). Refused."]


def complex_consistency_issues(plan: ComplexPlan, source_text: str, form: str,
                               transformed_source: str, lifted_text: str,
                               type_name: str) -> list[str]:
    """Every reason the complex rewrite of this source cannot be trusted."""
    if not plan.active:
        return []
    return (real_wrap_issues(plan, source_text, form, transformed_source, lifted_text)
            + argument_type_mismatches(transformed_source, form, lifted_text, type_name)
            + complex_step_branch_issues(plan, transformed_source, form, lifted_text))


def _lifted_blocks(lifted_text: str):
    lines = (lifted_text or "").split("\n")
    index = 0
    while index < len(lines):
        header = _LIFTED_HEADER_RE.match(lines[index])
        if not header:
            index += 1
            continue
        end = index + 1
        while end < len(lines) and not _LIFTED_END_RE.match(lines[end]):
            end += 1
        yield header.group(2).upper(), "\n".join(lines[index:end + 1])
        index = end + 1


# ---------------------------------------------------------------------------
# emitting the module
# ---------------------------------------------------------------------------

def uses_complex_type(*texts: str, type_name: str) -> bool:
    """Whether any output declares the complex type or USEs its module."""
    ztype = complex_type_name(type_name)
    return any(re.search(rf"\b{re.escape(ztype)}\b|^\s*use\s+{COMPLEX_MODULE_NAME}\b",
                         text or "", re.IGNORECASE | re.MULTILINE) for text in texts)


def write_module(output_dir: Path, module_name: str, type_name: str) -> Path:
    return write_complex_oti_module(Path(output_dir), module_name, type_name)


def compile_line() -> str:
    return (f'gfortran -c -ffree-form -ffree-line-length-none -I"$OBJDIR" {COMPLEX_MODULE_FILE} '
            f'-J"$OBJDIR" -o "$OBJDIR/{COMPLEX_MODULE_NAME}.o"')
