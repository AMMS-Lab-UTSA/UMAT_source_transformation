"""Declaration-aware retyper: turn `real` declarations into the OTI type.

General across declaration styles (this is the part that must not be tuned to
one repo): it recognises every common real type-spec form and only rewrites the
*leading* type-spec of a declaration statement, so real literals (`0.0_rk`), the
`real(...)` conversion intrinsic in expressions, and `real, parameter` constants
are all left alone. It also strips `pure` (OTI ops are impure) and renames the
derived types that have OTI variants.
"""
from __future__ import annotations

import re

from fparser.common.readfortran import FortranStringReader
from fparser.common.sourceinfo import FortranFormat
from fparser.two import Fortran2003 as F
from fparser.two.parser import ParserFactory
from fparser.two.utils import walk

_AST_PARSER = ParserFactory().create(std="f2008")
_REAL4_KIND = re.compile(r"(?i)kind\s*=\s*4\b|\(\s*4\s*\)|\br4\b|\bsp\b|\breal4\b")
# strip pure/elemental (OTI ops are impure) but KEEP recursive (needed for recursion)
_STRIP_PREFIX = re.compile(r"(?im)^(\s*)((?:(?:pure|elemental|recursive)\s+)+)(?=(?:function|subroutine)\b)")


def _keep_recursive(m):
    return m.group(1) + ("RECURSIVE " if "recursive" in m.group(2).lower() else "")


# legacy `IMPLICIT REAL*8(A-H,O-Z)` -> implicit OTI for those letter ranges, so
# implicitly-typed reals become OTI too (I-N stay integer). IMPLICIT NONE untouched.
_IMPLICIT_REAL = re.compile(
    r"(?im)^(\s*)implicit\s+(?:real\s*\*\s*8|real\s*\(\s*(?:kind\s*=\s*)?8\s*\)|double\s+precision|real)\s*\(([^)]*)\)")


def _implicit_oti(text: str, oti_type: str) -> str:
    converted = _IMPLICIT_REAL.sub(lambda m: f"{m.group(1)}IMPLICIT TYPE({oti_type})({m.group(2)})", text)
    if converted == text:
        return text
    # Under the implicit rule, names in the A-H/O-Z range that are PARAMETER or DATA
    # initialised would become OTI -- but they are real constants (ZERO=0.D0,
    # TOLER=1.D-6) and an OTI cannot be a compile-time constant. Declare those names
    # REAL*8 so they stay real; the operator overloads promote them where they meet
    # OTI values. (I-N names are integer and are left alone.)
    names, seen = [], set()

    def _add(nm):
        if nm[0].upper() not in "IJKLMN" and nm.lower() not in seen:
            seen.add(nm.lower()); names.append(nm)
    for m in re.finditer(r"(?i)\bparameter\s*\(([^)]*)\)", converted):
        for pair in m.group(1).split(","):
            g = re.match(r"\s*([A-Za-z]\w*)\s*=", pair)
            if g:
                _add(g.group(1))
    for m in re.finditer(r"(?im)^\s*data\s+([^/]+)/", converted):     # DATA name list (before first /)
        for g in re.findall(r"[A-Za-z]\w*", m.group(1)):
            _add(g)
    if names:
        decl = f"      REAL*8 :: {', '.join(names)}\n"
        anchor = r"(?im)^(\s*IMPLICIT\s+INTEGER\([^\n]*\)\s*\n)" if "IMPLICIT INTEGER" in converted.upper() \
            else r"(?im)^(\s*IMPLICIT\s+TYPE\([^\n]*\)\s*\n)"
        converted = re.sub(anchor, r"\1" + decl, converted, count=1)
    return converted


def retype_declarations_ast(src: str, oti_type: str = "ONUMM6N1",
                            variant_types: set[str] | None = None,
                            only_vars: set[str] | None = None, fixed: bool = False) -> str | None:
    """AST-level retyper: parse the procedure, swap the type-spec NODE of every real
    declaration to TYPE(oti_type), regenerate source. Robust across all declaration
    forms (the parser classifies them, not regex) and across fixed/free form (emits
    free form). Returns None if parsing fails, so the caller can fall back to text."""
    variants = {t.lower() for t in (variant_types or set())}
    only = {v.lower() for v in only_vars} if only_vars is not None else None
    try:
        reader = FortranStringReader(src)
        reader.set_format(FortranFormat(not fixed, False))
        tree = _AST_PARSER(reader)
    except Exception:
        return None
    try:
        for d in walk(tree, F.Type_Declaration_Stmt):
            tspec = d.items[0]
            ts = str(tspec)
            tsu = ts.upper().replace(" ", "")
            # derived-type variant: TYPE(name) -> TYPE(name_OTI)
            if tsu.startswith("TYPE(") and "(" in ts:
                inner = ts[ts.find("(") + 1: ts.rfind(")")].strip().lower()
                if inner in variants:
                    d.items = (F.Declaration_Type_Spec(f"TYPE({inner}_OTI)"),) + tuple(d.items[1:])
                continue
            is_real = tsu.startswith("REAL") or tsu.startswith("DOUBLEPRECISION")
            if not is_real or _REAL4_KIND.search(ts):           # keep single precision real(4)
                continue
            attrs = str(d.items[1]) if d.items[1] is not None else ""
            if "PARAMETER" in attrs.upper():                     # constants stay real
                continue
            ents = walk(d.items[2], F.Entity_Decl)

            def _nm(e):
                n = walk(e, F.Name)
                return str(n[0]).lower() if n else ""
            if only is not None:
                tainted = [e for e in ents if _nm(e) in only]
                if not tainted:                                  # no tainted name here
                    continue
                untainted = [e for e in ents if _nm(e) not in only]
                if untainted:
                    # SPLIT a multi-name line: OTI for the tainted names, keep the
                    # original real type for the rest (e.g. `:: props, statev, param`
                    # where only statev/param are tainted -> props stays real). This is
                    # what stops the over-taint cascade across procedure boundaries.
                    attrs = str(d.items[1]) if d.items[1] is not None else ""
                    suffix = (", " + attrs if attrs else "")
                    oti_stmt = F.Type_Declaration_Stmt(
                        f"TYPE({oti_type}){suffix} :: " + ", ".join(str(e) for e in tainted))
                    sib = F.Type_Declaration_Stmt(
                        f"{str(d.items[0])}{suffix} :: " + ", ".join(str(e) for e in untainted))
                    try:
                        par = d.parent
                        par.content.insert(par.content.index(d) + 1, sib)
                        sib.parent = par
                    except (ValueError, AttributeError):
                        pass
                    d.items = oti_stmt.items
                    continue
            d.items = (F.Declaration_Type_Spec(f"TYPE({oti_type})"),) + tuple(d.items[1:])
        out = str(tree)
    except Exception:
        return None
    return _STRIP_PREFIX.sub(_keep_recursive, out)                # drop pure/elemental, keep recursive

# Leading real type-spec, all common forms:
#   real(rk) / real(dp) / real(8) / real(kind=8) / real(kind=rk) / real*8 / double precision
_REAL_TYPESPEC = re.compile(
    r"^(?P<indent>\s*)(?P<spec>"
    r"real\s*\(\s*kind\s*=\s*[^)]*\)"
    r"|real\s*\(\s*[^)]*\)"
    r"|real\s*\*\s*\d+"
    r"|double\s+precision"
    r")(?=\s|,|::|$)",
    re.IGNORECASE,
)
_PURE = re.compile(r"(?i)\bpure\s+(?=elemental\b|function\b|subroutine\b)")
_PARAMETER = re.compile(r"(?i)\bparameter\b")
# single-precision specs are left as real: codes carry real(4)/real(8) portability
# overloads, and retyping both to one OTI type collapses them into ambiguous generics.
_REAL4 = re.compile(r"(?i)^\s*real\s*\(\s*(kind\s*=\s*)?4\s*\)")


def _decl_names(line: str) -> set[str] | None:
    """Names declared on a `... :: a, b(3), c` line (None if not parseable)."""
    if "::" not in line:
        return None
    names = set()
    for part in line.split("::", 1)[1].split(","):
        m = re.match(r"\s*([A-Za-z_]\w*)", part)
        if m:
            names.add(m.group(1).lower())
    return names


def retype_declarations(src: str, oti_type: str = "ONUMM6N1",
                        variant_types: set[str] | None = None,
                        only_vars: set[str] | None = None) -> str:
    """Rewrite real declarations in `src` to `type(oti_type)`.

    `variant_types` is the set of derived-type names that have OTI variants; any
    `type(name)` declaration of one of them becomes `type(name_OTI)`.
    `only_vars`, when given, restricts retyping to declarations of those names
    (the taint set) - so real constant inputs (props, integers) keep their type.

    Tries the AST retyper first (robust across all declaration forms and fixed/free
    form); falls back to the line/regex retyper if the snippet doesn't parse.
    """
    ast = retype_declarations_ast(src, oti_type, variant_types, only_vars)
    if ast is not None:
        return _implicit_oti(ast, oti_type)
    variants = {t.lower() for t in (variant_types or set())}
    only = {v.lower() for v in only_vars} if only_vars is not None else None
    out: list[str] = []
    for line in src.splitlines():
        l = _PURE.sub("", line)
        for t in variants:
            l = re.sub(rf"(?i)\btype\s*\(\s*{re.escape(t)}\s*\)", f"type({t}_OTI)", l)
        m = _REAL_TYPESPEC.match(l)
        if m and not _PARAMETER.search(l) and not _REAL4.match(l):
            names = _decl_names(l)
            if only is None or names is None or (names & only):
                l = l[: m.start("spec")] + f"type({oti_type})" + l[m.end("spec"):]
        out.append(l)
    return _implicit_oti("\n".join(out), oti_type)
