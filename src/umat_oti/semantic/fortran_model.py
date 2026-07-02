"""Minimal semantic model of a Fortran project, for the OTI source transform.

Goal (see docs/contract_generalization.md): give the retype-and-lift closure the
*structural facts* it needs and nothing more - the type of every name, the
components of every derived type, what each ``USE`` brings in, and the call
graph. It does NOT try to understand what the code computes.

Design notes:
  * Built on fparser2 (parses Fortran 2008, free and fixed form by extension).
  * Robust: each file is parsed independently; a file that fails to parse is
    recorded in ``failed`` and skipped, never crashing the whole build.
  * Small: four record types (Decl, Procedure, DerivedType, Module) and one
    resolver. Easy to extend with one more uniform rule, not a decision tree.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_MODULE_DEF = re.compile(r"(?im)^\s*module\s+(?!procedure\b)(\w+)")
_FORT_EXTS = ("*.f90", "*.f", "*.for", "*.ftn", "*.F90", "*.F", "*.FOR")

from fparser.common.readfortran import FortranStringReader
from fparser.common.sourceinfo import FortranFormat
from fparser.two import Fortran2003 as F
from fparser.two.parser import ParserFactory
from fparser.two.utils import walk

_PARSER = ParserFactory().create(std="f2008")

_CPP_LINE = re.compile(r"(?m)^\s*#")
_CPP_INCLUDE_SQ = re.compile(r"(?mi)^(\s*#\s*include\s*)'([^']+)'")


def preprocess(path: str, include_dirs: list[str], defines: dict[str, str] | None = None) -> str:
    """Return Fortran text ready to parse, running the C preprocessor only when
    the file actually has directives (so plain Fortran is never mangled).

    Real UMATs are compiled with the preprocessor (#include / #ifdef / #define),
    so we mirror that. Fortran-style single-quote includes are normalised to the
    double-quote form the preprocessor expects. If preprocessing fails, the raw
    text is returned and the parse step decides whether it is usable."""
    text = open(path, encoding="utf-8", errors="replace").read()
    # Legacy F77 constructs the modern-standard parser rejects: PAUSE was deleted in
    # Fortran 95 (common in embedded Numerical-Recipes LU solvers). Neutralise it so
    # the file parses; it is a diagnostic halt, irrelevant to the tangent.
    text = re.sub(r"(?i)\bPAUSE\b[ \t]*(?:'[^']*'|\"[^\"]*\"|\d+)?", "CONTINUE", text)
    # Strip Fortran INCLUDE statements whose target we can't find (e.g. Abaqus
    # headers like SMAAspUserArrays.hdr / ABA_PARAM.INC) so the file still parses;
    # those declarations are external and resolved in the real Abaqus build.
    dirs = list(include_dirs) + [os.path.dirname(path) or "."]

    def _resolvable(fn):
        return any(os.path.exists(os.path.join(d, fn)) for d in dirs)

    def _fix_include(ln):
        m = re.match(r"(?i)\s*include\s+['\"]([^'\"]+)['\"]", ln)
        if not m or _resolvable(m.group(1)):
            return ln                                   # keep: resolvable, or not an include
        # ABA_PARAM.INC is the Abaqus default-typing header (IMPLICIT REAL*8(A-H,O-Z));
        # classic single-file UMATs rely on it for their typing. Restore that statement
        # instead of dropping it, so implicitly-typed reals are still real (then the
        # IMPLICIT->OTI retyper carries them). Other unresolvable headers are dropped.
        if re.search(r"(?i)aba_param", m.group(1)):
            # the module wrapper is IMPLICIT NONE, so we must restore BOTH ranges the
            # Abaqus default implies: real for A-H/O-Z (the retyper turns these into
            # OTI) and integer for I-N (NTENS, NDI, ... stay integer).
            return "      IMPLICIT REAL*8(A-H,O-Z)\n      IMPLICIT INTEGER(I-N)"
        return None
    if re.search(r"(?im)^\s*include\s+['\"]", text):
        text = "\n".join(x for x in (_fix_include(ln) for ln in text.splitlines()) if x is not None)
    # Under the emitted module's IMPLICIT NONE, an `IMPLICIT REAL*8(A-H,O-Z)` (whether
    # from ABA_PARAM or written directly in a helper) implies the default integer
    # typing for I-N -- which is killed. Pair each such statement with an explicit
    # IMPLICIT INTEGER(I-N) so dummies like N, M, NTENS stay integer (else UNKNOWN).
    if re.search(r"(?im)^\s*implicit\s+(?:real|double)", text):
        _real_ahoz = re.compile(r"(?i)^\s*implicit\s+(?:real\s*\*\s*8|real\s*\([^)]*\)|real|double\s+precision)\s*"
                                r"\(\s*a\s*-\s*h\s*,\s*o\s*-\s*z\s*\)\s*$")
        lines, out = text.split("\n"), []
        for i, ln in enumerate(lines):
            out.append(ln)
            if _real_ahoz.match(ln) and not re.match(r"(?i)\s*implicit\s+integer",
                                                     lines[i + 1] if i + 1 < len(lines) else ""):
                out.append("      IMPLICIT INTEGER(I-N)")
        text = "\n".join(out)
    if not _CPP_LINE.search(text):
        return text
    text = _CPP_INCLUDE_SQ.sub(r'\1"\2"', text)
    fixed = path.lower().endswith((".f", ".for", ".ftn"))
    with tempfile.NamedTemporaryFile("w", suffix=(".F" if fixed else ".F90"), delete=False) as tf:
        tf.write(text)
        tmp = tf.name
    cmd = ["gfortran", "-E", "-cpp", "-P"]
    for d in include_dirs:
        cmd += ["-I", d]
    for k, v in (defines or {}).items():
        cmd.append(f"-D{k}={v}" if v != "" else f"-D{k}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return r.stdout if r.returncode == 0 and r.stdout.strip() else text
    except Exception:
        return text
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


@dataclass
class Decl:
    """A declared name: a variable, a dummy argument, or a type component."""
    name: str
    type_spec: str            # surface text, e.g. "REAL(rk)" or "TYPE(state_variables)"
    base: str                 # REAL | INTEGER | LOGICAL | CHARACTER | COMPLEX | TYPE | CLASS
    derived: Optional[str]    # derived-type name when base in (TYPE, CLASS), else None
    dims: Optional[str]       # dimension text if any, else None
    intent: Optional[str] = None   # 'in' | 'out' | 'inout' for dummy args, else None


@dataclass
class Procedure:
    name: str
    kind: str                 # "subroutine" | "function"
    file: str
    container: Optional[str]  # enclosing module name, or None for a global/program unit
    dummy_args: list[str] = field(default_factory=list)
    decls: dict[str, Decl] = field(default_factory=dict)        # name(lower) -> Decl
    uses: list[tuple[str, list[str]]] = field(default_factory=list)  # (module, only-names)
    calls: list[str] = field(default_factory=list)             # subroutine callee names (lower)
    call_sites: list[tuple[str, list[str]]] = field(default_factory=list)  # (callee, [actual-arg base names])
    bound_calls: list[tuple[str, str, list[str]]] = field(default_factory=list)  # (object, method, [actual args])
    assigns: dict[str, list[tuple[int, int]]] = field(default_factory=dict)  # lhs-name -> line spans


@dataclass
class DerivedType:
    name: str
    file: str
    container: Optional[str]
    components: dict[str, Decl] = field(default_factory=dict)
    bindings: dict[str, str] = field(default_factory=dict)  # binding-name(lower) -> impl proc (lower)


@dataclass
class Module:
    name: str
    file: str
    procedures: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)


def _spec_base(spec_text: str) -> tuple[str, Optional[str]]:
    """Classify a declaration-type-spec into (base, derived-type-name)."""
    t = spec_text.strip().upper()
    for b in ("REAL", "INTEGER", "LOGICAL", "CHARACTER", "COMPLEX", "DOUBLE PRECISION"):
        if t.startswith(b):
            return ("REAL" if b == "DOUBLE PRECISION" else b, None)
    if t.startswith("TYPE") or t.startswith("CLASS"):
        # TYPE(name) / CLASS(name)
        inside = spec_text[spec_text.find("(") + 1: spec_text.rfind(")")].strip() if "(" in spec_text else ""
        return ("TYPE" if t.startswith("TYPE") else "CLASS", inside or None)
    return (t.split("(")[0].split()[0], None)


def _name_text(node) -> Optional[str]:
    n = walk(node, F.Name)
    return str(n[0]) if n else None


def _decls_from_spec(spec_part) -> dict[str, Decl]:
    """Pull every Type_Declaration_Stmt in a specification part into Decl records."""
    out: dict[str, Decl] = {}
    if spec_part is None:
        return out
    for stmt in walk(spec_part, F.Type_Declaration_Stmt):
        try:
            spec_text = str(stmt.children[0])
            base, derived = _spec_base(spec_text)
            attr_text = str(stmt.children[1]) if stmt.children[1] is not None else ""
            dims = None
            if "DIMENSION" in attr_text.upper():
                dims = attr_text
            mi = re.search(r"(?i)intent\s*\(\s*(in\s*out|out|in)\s*\)", attr_text)
            intent = mi.group(1).replace(" ", "").lower() if mi else None
            for ent in walk(stmt.children[2], F.Entity_Decl):
                nm = _name_text(ent)
                if not nm:
                    continue
                ent_text = str(ent)
                edims = dims
                if "(" in ent_text and edims is None:
                    edims = ent_text[ent_text.find("("):]
                out[nm.lower()] = Decl(nm, spec_text.strip(), base, derived, edims, intent)
        except Exception:
            continue
    return out


class FortranProject:
    def __init__(self) -> None:
        self.files: list[str] = []
        self.failed: dict[str, str] = {}
        self.procedures: dict[str, Procedure] = {}
        self.types: dict[str, DerivedType] = {}
        self.modules: dict[str, Module] = {}
        self.generics: dict[str, list[str]] = {}   # generic name -> specific procedure names
        self.proc_nodes: dict[str, object] = {}    # name(lower) -> fparser2 AST node (for free-form re-emit)
        self.type_nodes: dict[str, object] = {}

    # ---- ingest ----
    def add_file(self, path: str | Path, include_dirs: list[str] | None = None,
                 defines: dict[str, str] | None = None) -> bool:
        path = str(path)
        self.files.append(path)
        inc = include_dirs if include_dirs is not None else [os.path.dirname(path) or "."]
        # Set the form explicitly from the extension (.f/.for = fixed) and turn
        # OFF strict mode, so macro-expanded lines past column 72 are tolerated.
        # This is deterministic, unlike the reader's content-based guess.
        fixed = path.lower().endswith((".f", ".for", ".ftn"))
        try:
            src = preprocess(path, inc, defines)
            reader = FortranStringReader(src)
            reader.set_format(FortranFormat(not fixed, False))  # (is_free, is_strict)
            tree = _PARSER(reader)
        except Exception as exc:  # robust: record and move on, never crash the build
            self.failed[path] = f"{type(exc).__name__}: {exc}"
            return False
        for mod in walk(tree, F.Module):
            self._ingest_module(mod, path)
        # program units not inside a module (global subroutines, e.g. the Abaqus umat)
        for sub in walk(tree, (F.Subroutine_Subprogram, F.Function_Subprogram)):
            if self._enclosing_module(sub) is None:
                self._ingest_procedure(sub, path, container=None)
        return True

    def add_with_deps(self, entry_file: str | Path, search_dirs: list[str] | None = None,
                      defines: dict[str, str] | None = None) -> "FortranProject":
        """Add the entry file and, by following USE edges, every other file in
        `search_dirs` that defines a used module - transitively. This is what lets
        the contract name only the entry file; the dependency set is discovered."""
        entry_file = str(entry_file)
        search_dirs = search_dirs or [os.path.dirname(entry_file) or "."]
        # index module-name -> defining file across the search dirs (cheap scan)
        idx: dict[str, str] = {}
        for d in search_dirs:
            for ext in _FORT_EXTS:
                for path in glob.glob(os.path.join(d, ext)):
                    try:
                        txt = open(path, encoding="utf-8", errors="replace").read()
                    except OSError:
                        continue
                    for m in _MODULE_DEF.finditer(txt):
                        idx.setdefault(m.group(1).lower(), path)
        added: set[str] = set()

        def add(path):
            if path not in added:
                added.add(path)
                self.add_file(path, include_dirs=search_dirs, defines=defines)

        add(entry_file)
        changed = True
        while changed:
            changed = False
            used = {mod.lower() for proc in self.procedures.values() for mod, _o in proc.uses}
            for mod in used:
                f = idx.get(mod)
                if f and f not in added:
                    add(f); changed = True
        return self

    # ---- helpers ----
    def _enclosing_module(self, node) -> Optional[str]:
        p = node.parent
        while p is not None:
            if isinstance(p, F.Module):
                return _name_text(walk(p, F.Module_Stmt)[0])
            p = getattr(p, "parent", None)
        return None

    def _ingest_module(self, mod, path) -> None:
        name = _name_text(walk(mod, F.Module_Stmt)[0]) or "?"
        m = Module(name=name, file=path)
        self.modules[name.lower()] = m
        for tdef in walk(mod, F.Derived_Type_Def):
            self._ingest_type(tdef, path, container=name, into=m)
        for sub in walk(mod, (F.Subroutine_Subprogram, F.Function_Subprogram)):
            self._ingest_procedure(sub, path, container=name, into=m)
        # named generic interfaces: `interface gname ; module procedure a, b ; end interface`
        for iblock in walk(mod, F.Interface_Block):
            istmt = walk(iblock, F.Interface_Stmt)
            gnm = walk(istmt[0], F.Name) if istmt else []
            gname = str(gnm[0]).lower() if gnm else None
            if not gname:
                continue
            specs = [str(n).lower() for pst in walk(iblock, F.Procedure_Stmt) for n in walk(pst, F.Name)]
            if specs:
                self.generics.setdefault(gname, []).extend(specs)

    def _ingest_type(self, tdef, path, container, into=None) -> None:
        tname = _name_text(walk(tdef, F.Derived_Type_Stmt)[0]) or "?"
        dt = DerivedType(name=tname, file=path, container=container)
        for comp in walk(tdef, F.Data_Component_Def_Stmt):
            try:
                spec_text = str(comp.children[0])
                base, derived = _spec_base(spec_text)
                for ent in walk(comp.children[2], F.Component_Decl):
                    nm = _name_text(ent)
                    if nm:
                        dt.components[nm.lower()] = Decl(nm, spec_text.strip(), base, derived, None)
            except Exception:
                continue
        # type-bound procedure bindings: `procedure[,attrs] :: bind [=> impl]`
        for m in re.finditer(r"(?im)^\s*procedure\b[^\n:]*::\s*(\w+)\s*(?:=>\s*(\w+))?", str(tdef)):
            bname = m.group(1).lower()
            dt.bindings[bname] = (m.group(2) or m.group(1)).lower()
        self.types[tname.lower()] = dt
        self.type_nodes[tname.lower()] = tdef        # AST node for free-form re-emit
        if into is not None:
            into.types.append(tname)

    def _ingest_procedure(self, sub, path, container, into=None) -> None:
        is_func = isinstance(sub, F.Function_Subprogram)
        stmt = walk(sub, F.Function_Stmt if is_func else F.Subroutine_Stmt)
        if not stmt:
            return
        name = _name_text(stmt[0]) or "?"
        proc = Procedure(name=name, kind="function" if is_func else "subroutine",
                         file=path, container=container)
        # dummy args
        for argl in walk(stmt[0], (F.Dummy_Arg_List,)):
            for nm in walk(argl, F.Name):
                proc.dummy_args.append(str(nm).lower())
        # declarations (dummies + locals)
        spec = walk(sub, F.Specification_Part)
        proc.decls = _decls_from_spec(spec[0] if spec else None)
        # use statements
        for use in walk(sub, F.Use_Stmt):
            mod_name = None
            for nm in walk(use, F.Name):
                mod_name = str(nm); break
            only = [str(n) for n in walk(use, F.Only_List)] if walk(use, F.Only_List) else []
            proc.uses.append((mod_name or "?", only))
        # calls: resolve the callee (handling type-bound obj%method) and capture
        # the actual-argument base names, so the boundary variables can be mapped
        # to the callee's dummy arguments (e.g. ddsdde -> dds_dde).
        for call in walk(sub, F.Call_Stmt):
            cs = str(call)
            # type-bound call `obj%method(args)` - fparser nests the args inside
            # the Data_Ref, so parse the surface string for a reliable obj/method.
            mb = re.match(r"(?is)\s*call\s+(\w+)\s*%\s*(\w+)\s*(?:\((.*)\))?\s*$", cs)
            if mb:
                obj, callee = mb.group(1).lower(), mb.group(2).lower()
                args = []
                for a in (mb.group(3) or "").split(","):
                    am = re.match(r"\s*([A-Za-z_]\w*)", a)
                    args.append(am.group(1).lower() if am else "")
                proc.calls.append(callee)
                proc.bound_calls.append((obj, callee, args))   # call_sites stays plain-only
                continue
            callee = (_name_text(call) or "").lower() or None
            if not callee:
                continue
            args = []
            arglist = call.children[1] if len(call.children) > 1 else None
            if arglist is not None:
                items = getattr(arglist, "children", [arglist])
                for a in items:
                    # Keyword args (`param=Fnew`) keep full `kw=value` text so the
                    # value's taint reaches the named dummy; positional args keep just
                    # the leading base name (so a function-call actual like
                    # `f(T,n)` taints by the callee, not by T -- matching legacy
                    # behaviour the rest of the taint relies on).
                    if isinstance(a, F.Actual_Arg_Spec):
                        args.append(re.sub(r"\s+", "", str(a)).lower())
                    else:
                        nm = walk(a, F.Name)
                        args.append(str(nm[0]).lower() if nm else "")
            proc.calls.append(callee)
            proc.call_sites.append((callee, args))
        # assignments: record the base name written on each LHS, with line span.
        # This is what lets the tool *locate* where the target (e.g. DDSDDE) is
        # written, so `replace` can be auto-found and file-qualified.
        for asn in walk(sub, F.Assignment_Stmt):
            lhs = _name_text(asn.children[0])
            if not lhs:
                continue
            span = None
            item = getattr(asn, "item", None)
            if item is not None and getattr(item, "span", None):
                span = tuple(item.span)
            proc.assigns.setdefault(lhs.lower(), []).append(span or (0, 0))
        self.procedures[name.lower()] = proc
        self.proc_nodes[name.lower()] = sub          # keep the AST node for free-form re-emit
        if into is not None:
            into.procedures.append(name)

    # ---- resolution ----
    def find_assignments(self, var: str, within: list[str] | None = None) -> list[tuple[str, str, list[tuple[int, int]]]]:
        """Locate where `var` is assigned: returns (procedure, file, line-spans).

        Restrict to `within` (a list of procedure names, e.g. the reachable set)
        to find the assignment site that matters for this transform. This is how
        the tool turns a target variable into a concrete, file-qualified replace
        location instead of asking the user for a line range."""
        var = var.lower()
        scope = set(within) if within else None
        hits = []
        for name, proc in self.procedures.items():
            if scope is not None and name not in scope:
                continue
            if var in proc.assigns:
                hits.append((proc.name, proc.file, proc.assigns[var]))
        return hits

    def reachable(self, entry: str) -> list[str]:
        """Procedures reachable from `entry` via CALLs (resolved across files)."""
        seen, order, stack = set(), [], [entry.lower()]
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in self.procedures:
                continue
            seen.add(cur); order.append(cur)
            stack.extend(self.procedures[cur].calls)
        return order
