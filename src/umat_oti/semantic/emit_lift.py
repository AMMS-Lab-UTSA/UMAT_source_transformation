"""Plan-driven emitter for the multi-file OTI lift transform.

Given a parsed FortranProject and an entry procedure, this derives — purely from
the semantic model, with no hand-named routines — the closure of procedures,
helper functions, derived types and module constants that must be lifted, then
emits a single compilable OTI module (plus the intrinsic overloads).

Everything that the earlier hand-written script "knew" is computed here:
  * closure   = CALL graph + USE-only imports + textual function references
                (functions are referenced in expressions, so the call graph
                alone misses them; we also scan bodies for project proc names).
  * type role = a derived type becomes an OTI variant iff some variable of that
                type is *assigned* somewhere in the lift set; otherwise it is a
                read-only input (material params / controls) and stays real.
  * constants = USE-only names that resolve to module PARAMETERs (kept real).
  * stubs     = procedures the contract marks inactive (e.g. sibling material
                modes); their signatures are regenerated from the model so the
                active path still compiles, and they are never executed.
"""
from __future__ import annotations

import re
from umat_oti.fortran.literals import rewrite_outside_real_literals
from .retype import retype_declarations as RT
from .fortran_model import FortranProject


def _file_text(cache: dict, path: str) -> str:
    if path not in cache:
        cache[path] = open(path, encoding="utf-8", errors="replace").read()
    return cache[path]


_IMPLICIT_ANY = re.compile(r"(?im)^\s*implicit\b")
_PROC_HEADER = re.compile(r"(?i)^\s*(?:pure\s+|elemental\s+|recursive\s+)*(?:subroutine|function)\b")


def _proc_text(proj, p, cache) -> str:
    """Procedure source. For FREE-form files use faithful regex text extraction
    (fparser2's str() round-trip can drop F77 constructs like statement functions).
    For FIXED-form files use the AST node's str() to convert fixed -> free form,
    which text extraction cannot do."""
    proc = proj.procedures[p]
    fixed = proc.file.lower().endswith((".f", ".for", ".ftn"))
    txt = ""
    if fixed and proj.proc_nodes.get(p) is not None:
        try:
            txt = str(proj.proc_nodes[p])
        except Exception:
            txt = ""
    if not txt:
        txt = extract_proc(_file_text(cache, proc.file), proc.name, proc.kind) or ""
    # Legacy fixed-form procedures (incl. helper subroutines) rely on default implicit
    # typing; the emitted module wrapper is IMPLICIT NONE, which would leave their
    # variables untyped. Restore the Abaqus default per procedure when it has no
    # IMPLICIT of its own: real for A-H/O-Z (the retyper turns the active ones into
    # OTI), integer for I-N. Free-form files (modern, explicitly typed) are untouched.
    if fixed and txt and not _IMPLICIT_ANY.search(txt):
        lines = txt.split("\n")
        for i, l in enumerate(lines):
            if _PROC_HEADER.match(l):
                lines[i + 1:i + 1] = ["      IMPLICIT REAL*8(A-H,O-Z)", "      IMPLICIT INTEGER(I-N)"]
                break
        txt = "\n".join(lines)
    return txt


def extract_proc(text: str, name: str, kind: str) -> str | None:
    kw = "function" if kind == "function" else "subroutine"
    m = re.search(rf"\n(\s*(?:pure\s+|elemental\s+|recursive\s+)*{kw}\s+{name}\s*\(.*?end\s+{kw}\s+{name}\b)",
                  text, re.S | re.I)
    if m:
        return m.group(1)
    # fallback: bare END SUBROUTINE/FUNCTION (no name repeated)
    m = re.search(rf"\n(\s*(?:pure\s+|elemental\s+|recursive\s+)*{kw}\s+{name}\s*\(.*?\n\s*end\s+{kw}\b[^\n]*)",
                  text, re.S | re.I)
    return m.group(1) if m else None


def extract_typedef(text: str, name: str) -> str | None:
    m = re.search(rf"\n(\s*type(?:\s*,\s*\w+)?\s*(?:::)?\s*{name}\b.*?end\s+type\s+{name}\b)", text, re.S | re.I)
    if not m:
        return None
    t = m.group(1)
    return re.sub(r"(?is)\n\s*contains\b.*?(?=\n\s*end\s+type)", "", t)  # drop type-bound bindings


def extract_param(text: str, name: str) -> str | None:
    """Pull a module PARAMETER declaration (with multi-line continuations).

    A leading `!` comments out the WHOLE line in Fortran, so a commented-out
    declaration (a leftover like `!... :: I2 = ...`) must never be picked: it
    would emit a dead comment and leave the symbol undeclared. Match only on the
    code part (everything before the first `!`)."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        code = ln.split("!", 1)[0]
        if re.search(rf"(?i)::\s*{name}\s*=", code) and re.search(r"(?i)\bparameter\b", code):
            out = [ln]
            j = i
            while lines[j].split("!", 1)[0].rstrip().endswith("&") and j + 1 < len(lines):
                j += 1
                out.append(lines[j])
            return "\n".join(out)
    return None


_IDENT = re.compile(r"[A-Za-z_]\w*")
_KEPT_MODULES = {"precision_", "master_parameters"}


def _parse_literal(s):
    s = s.strip()
    sm = re.match(r"""^['"]([^'"]*)['"]$""", s)
    if sm:
        return sm.group(1)
    nm = re.match(r"^[-+]?[\d.]+(?:[deDE][-+]?\d+)?(?:_\w+)?$", s)
    if nm:
        return float(re.sub(r"_\w+$", "", s).replace("d", "e").replace("D", "e"))
    return None


def _eval_cond(cond, config):
    """Evaluate a branch condition against the config facts. Returns True/False, or
    None when it can't be decided (then the branch is kept). Handles a single
    comparison and .and./.or. of comparisons; LHS may be `obj%field` (matched on
    `field`)."""
    cond = cond.strip()
    for op_word, reducer in ((r"\.or\.", any), (r"\.and\.", all)):
        if re.search(rf"(?i){op_word}", cond):
            vals = [_eval_cond(p, config) for p in re.split(rf"(?i){op_word}", cond)]
            if reducer is any:
                return True if any(v is True for v in vals) else (False if all(v is False for v in vals) else None)
            return False if any(v is False for v in vals) else (True if all(v is True for v in vals) else None)
    m = re.match(r"^\(?\s*([\w%]+)\s*(==|/=|>=|<=|>|<)\s*(.+?)\s*\)?$", cond)
    if not m:
        return None
    field = m.group(1).split("%")[-1].lower()
    if field not in config:
        return None
    cv, rv = config[field], _parse_literal(m.group(3))
    if rv is None:
        return None
    try:
        if isinstance(cv, str) or isinstance(rv, str):
            a, b = str(cv).strip().lower(), str(rv).strip().lower()
        else:
            a, b = float(cv), float(rv)
    except (TypeError, ValueError):
        return None
    return {"==": a == b, "/=": a != b, ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[m.group(2)]


def _fold_branches(body, config):
    """Drop statically-dead branches (per config). Dead block bodies are removed
    but their `if … end if` scaffolding is kept (an empty if compiles); dead inline
    `if (cond) stmt` lines are dropped. This both removes dead calls (so their
    targets never enter the closure) and empties inert routines (so their heavy
    dependencies disappear)."""
    if not config:
        return body
    cfg = {k.lower(): v for k, v in config.items()}
    out, stack = [], []   # stack frame: {base, taken, live}

    def enclosing_live():
        return all(f["live"] for f in stack)

    for line in body.split("\n"):
        s = line.strip()
        m_then = re.match(r"(?i)if\s*\((.*)\)\s*then\s*$", s)
        m_elif = re.match(r"(?i)else\s*if\s*\((.*)\)\s*then\s*$", s)
        m_else = re.match(r"(?i)else\s*$", s)
        m_end = re.match(r"(?i)end\s*if\b", s)
        m_inline = re.match(r"(?i)if\s*\((.*?)\)\s*(?!then\s*$)(\S.*)$", s)
        if m_then:
            base = enclosing_live()
            c = _eval_cond(m_then.group(1), cfg)
            stack.append({"base": base, "taken": c is True, "live": base and c is not False})
            if base:
                out.append(line)
        elif m_elif and stack:
            f = stack[-1]
            if f["taken"]:
                f["live"] = False
            else:
                c = _eval_cond(m_elif.group(1), cfg)
                f["live"] = f["base"] and c is not False
                if c is True:
                    f["taken"] = True
            if f["base"]:
                out.append(line)
        elif m_else and stack:
            f = stack[-1]
            f["live"] = f["base"] and not f["taken"]
            if f["base"]:
                out.append(line)
        elif m_end and stack:
            f = stack.pop()
            if f["base"]:
                out.append(line)
        elif m_inline and not m_then:
            c = _eval_cond(m_inline.group(1), cfg)
            if enclosing_live() and c is not False:
                out.append(line)
        else:
            if enclosing_live():
                out.append(line)
    return "\n".join(out)


def _normint(t: str) -> str:
    """`180_rk` is an INTEGER literal (no OTI*int overload); make it real. The
    lookbehind avoids matching the digits of an existing real (1.0_rk, 1e-2_rk)
    or an identifier (var2_rk)."""
    return re.sub(r"(?<![-+.\w])(\d+)_rk\b", r"\1.0_rk", t)


# legacy F77 double-precision specific intrinsics -> generic (the OTI library
# overloads the generics, so this makes any UMAT's dexp/dsqrt/... resolve).
_LEGACY_INTRIN = {"dexp": "exp", "dsqrt": "sqrt", "dabs": "abs", "dlog": "log",
                  "dlog10": "log10", "dsin": "sin", "dcos": "cos", "dtan": "tan",
                  "dasin": "asin", "dacos": "acos", "datan": "atan", "datan2": "atan2",
                  "dsinh": "sinh", "dcosh": "cosh", "dtanh": "tanh",
                  "dmax1": "max", "dmin1": "min", "dsign": "sign", "dmod": "mod"}


def _norm_intrinsics(t: str) -> str:
    for old, new in _LEGACY_INTRIN.items():
        t = re.sub(rf"(?i)\b{old}\s*\(", f"{new}(", t)
    return t


# legacy F77 writes real literals with no kind (`0.5`, `240.`, `1.5e-6`) -> these are
# SINGLE precision, and the OTI overloads are double, so `oti = 0.5` / `oti*2.0` fail.
# Promote them to double (which they should be in numerical code anyway). Quote- and
# FORMAT-aware so format descriptors (`F10.4`) and strings are never touched.
_REAL_EXP = re.compile(r"(?<![\w.])(\d+\.?\d*|\.\d+)[eE]([+-]?\d+)(?![\w.])")
_REAL_DEC = re.compile(r"(?<![\w.])(\d+\.\d*|\.\d+)(?![\deEdD_.])")


def _promote_reals(t: str) -> str:
    out = []
    for ln in t.split("\n"):
        if ln.lstrip().startswith("!") or re.search(r"(?i)\bformat\s*\(", ln):
            out.append(ln); continue
        parts = re.split(r"('[^']*'|\"[^\"]*\")", ln)      # promote only outside strings
        for i in range(0, len(parts), 2):
            parts[i] = _REAL_DEC.sub(r"\1d0", _REAL_EXP.sub(r"\1d\2", parts[i]))
        out.append("".join(parts))
    return "\n".join(out)


# LAPACK is real-only; a local solver carrying the derivative as OTI must route its
# linear algebra through the OTI shims (module oti_lapack). Reroute the calls; the
# `external` declarations of these names become harmlessly unused.
_LAPACK_REROUTE = {"dgesv": "oti_gesv", "dgetrf": "oti_getrf",
                   "dgetri": "oti_getri", "dgetrs": "oti_getrs"}


def _reroute_lapack(t: str) -> tuple[str, bool]:
    used = False
    for old, new in _LAPACK_REROUTE.items():
        t2 = re.sub(rf"(?i)\bcall\s+{old}\s*\(", f"call {new}(", t)
        if t2 != t:
            used = True
        t = t2
    return t, used


def _fix_interface_imports(text: str) -> str:
    """An INTERFACE block is its own scoping unit: a derived type host-associated in
    the enclosing module (e.g. ONUMM6N1) is NOT visible inside it. After retyping a
    dummy-procedure interface to carry OTI args, inject `import` so the host type is
    seen (F2003). Bare `import` (all host entities) is harmless where unneeded."""
    out, depth = [], 0
    for ln in text.split("\n"):
        out.append(ln)
        if re.match(r"(?i)^\s*end\s+interface\b", ln):
            depth = max(0, depth - 1)
        elif re.match(r"(?i)^\s*interface\b", ln):
            depth += 1
        elif depth > 0 and re.match(
                r"(?i)^\s*(?:pure\s+|elemental\s+|recursive\s+)*(?:subroutine|function)\b", ln):
            indent = ln[:len(ln) - len(ln.lstrip())]
            out.append(indent + "  import")
    return "\n".join(out)


def _only_names(only_list) -> list[str]:
    """Split a USE only-list into the real entity names, dereferencing renames
    (`local => actual` -> actual). fparser hands the list back as one string."""
    names = []
    for chunk in only_list:
        for part in str(chunk).split(","):
            part = part.strip()
            if "=>" in part:               # rename: the module-side name is what we lift
                part = part.split("=>")[1].strip()
            m = _IDENT.match(part)
            if m:
                names.append(m.group(0))
    return names


def _activeness(proj, work, seed, lift, cache, config=None):
    """Inter-procedural taint from the seed; returns (active_procs, oti_types).

    Taint flows forward into a callee's input dummies and back out of its output
    dummies (a dummy is an output iff the callee assigns it). A derived type is
    OTI iff one of its components is assigned from a tainted RHS somewhere -- so a
    params type filled only from a constants array (props) is never tainted and
    stays real. A proc is active (retype) iff it holds a tainted var or an
    OTI-type dummy; functions are seeded math helpers and are always active."""
    av = {p: set() for p in lift}
    if work in av:
        av[work].add(seed.lower())
    asg_cache = {}

    def assigns_of(p):
        if p in asg_cache:
            return asg_cache[p]
        proc = proj.procedures[p]
        body = _fold_branches(_proc_text(proj, p, cache), config or {})
        out = []
        for line in body.splitlines():
            l = line.split("!", 1)[0]
            if re.match(r"(?i)\s*(use|implicit|type|real|integer|logical|character|complex|"
                        r"double|class|dimension|parameter|end|module|contains)\b", l):
                continue
            ls = l.lstrip()                                  # unwrap inline `if (cond) x = ...`
            if re.match(r"(?i)if\s*\(", ls):
                depth, k0 = 0, ls.find("(")
                for k in range(k0, len(ls)):
                    depth += (ls[k] == "(") - (ls[k] == ")")
                    if depth == 0:
                        l = ls[k + 1:]
                        break
            m = re.match(r"\s*([A-Za-z_]\w*)\s*(%\s*\w+|\([^=]*\))?\s*(%\s*\w+)?\s*=(?![=>])", l)
            if not m or "==" in l[:l.find("=") + 1]:
                continue
            out.append((m.group(1).lower(), {t.lower() for t in _IDENT.findall(l.split('=', 1)[1])}))
        asg_cache[p] = out
        return out

    # bind procedures passed as actual args to the callee's procedure-dummy, so a
    # call to that dummy *inside* the callee resolves to the real passed procedure
    # (higher-order: e.g. a Newton solver calling its `residual_function` argument).
    pbind = {}
    for pp in lift:
        for callee, args in proj.procedures[pp].call_sites:
            cp = proj.procedures.get(callee)
            if cp is None:
                continue
            for i, act in enumerate(args):
                if i < len(cp.dummy_args) and act in proj.procedures:
                    pbind[(callee, cp.dummy_args[i].lower())] = act

    def calls_of(proc):
        res = [(pbind.get((proc.name.lower(), callee), callee), args) for callee, args in proc.call_sites]
        for obj, method, args in proc.bound_calls:
            od = proc.decls.get(obj)
            tn = od.derived.lower() if od and od.derived else None
            if tn and tn in proj.types:
                impl = proj.types[tn].bindings.get(method)
                if impl:
                    res.append((impl, [obj] + list(args)))
        return res

    def resolve_args(args, dm):
        """Map each call actual to its dummy, handling keyword args (`param=Fnew`)
        positionally-then-by-name as Fortran requires. Yields (dummy, actual_expr)."""
        dmset = {d.lower() for d in dm}
        pos = 0
        for act in args:
            mkw = re.match(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+)$", act)
            if mkw and "==" not in act and mkw.group(1).lower() in dmset:
                yield mkw.group(1).lower(), mkw.group(2).strip()
            else:
                if pos < len(dm):
                    yield dm[pos].lower(), act.strip()
                pos += 1

    iface_sig_cache: dict = {}

    def iface_sig(p, dummyproc):
        """[(argname, intent)] for a dummy procedure declared in an INTERFACE block
        of p -- lets taint cross calls to an UNBOUND dummy procedure (no actual
        procedure passed in this path) using the interface's own intents."""
        key = (p, dummyproc)
        if key in iface_sig_cache:
            return iface_sig_cache[key]
        src = _proc_text(proj, p, cache)
        sig = None
        for ib in re.finditer(r"(?is)\binterface\b(.*?)\bend\s+interface\b", src):
            m = re.search(rf"(?is)\b(?:subroutine|function)\s+{re.escape(dummyproc)}\s*\(([^)]*)\)"
                          r"(.*?)\bend\s+(?:subroutine|function)\b", ib.group(1))
            if not m:
                continue
            arglist = [x.strip().lower() for x in m.group(1).split(",") if x.strip()]
            intents: dict = {}
            for dm in re.finditer(r"(?im)intent\s*\(\s*(in\s*out|out|in)\s*\)[^:]*::\s*(.+)$", m.group(2)):
                it = dm.group(1).replace(" ", "").lower()
                for nm in re.findall(r"[A-Za-z_]\w*", dm.group(2)):
                    intents[nm.lower()] = it
            sig = [(x, intents.get(x)) for x in arglist]
            break
        iface_sig_cache[key] = sig
        return sig

    changed = True
    while changed:
        changed = False
        for p in lift:
            proc, a = proj.procedures[p], av[p]
            for base, toks in assigns_of(p):
                if base not in a and (toks & a):
                    a.add(base); changed = True
            for callee, args in calls_of(proc):
                cp = proj.procedures.get(callee)
                if cp is None:
                    # unbound dummy-procedure call: use its interface-block intents
                    # to taint output actuals (the proc is external to the lift).
                    sig = iface_sig(p, callee)
                    if sig:
                        dmn = [x for x, _ in sig]
                        intents = {x: it for x, it in sig}
                        oti_call = any({t.lower() for t in _IDENT.findall(expr)} & a
                                       for _, expr in resolve_args(args, dmn))
                        if oti_call:
                            for dummy, expr in resolve_args(args, dmn):
                                if intents.get(dummy) in ("out", "inout"):
                                    mv = re.match(r"^([A-Za-z_]\w*)", expr)
                                    if mv and mv.group(1).lower() not in a:
                                        a.add(mv.group(1).lower()); changed = True
                        continue
                    # pure external call with NO interface block (e.g. AceGen-generated
                    # RF*/dRdX* residual/Jacobian kernels not in the parsed model). We
                    # have no per-arg intents; but if the call consumes an OTI input,
                    # its derivative flows into the writable actuals. Taint only actuals
                    # that are WRITABLE here -- a local var or an intent(out/inout) dummy
                    # of p -- never a read-only input, so props/config stay real.
                    # LAPACK is excluded: its real-only scratch (work, ...) is handled by
                    # the OTI shims (oti_getri keeps a real(8) work), so tainting a passed
                    # workspace here would mistype it.
                    if callee.lower() in _LAPACK_REROUTE:
                        continue
                    if any({t.lower() for t in _IDENT.findall(expr)} & a for expr in args):
                        for expr in args:
                            mv = re.match(r"^\s*([A-Za-z_]\w*)\s*$", expr)
                            if not mv:
                                continue
                            nm = mv.group(1).lower()
                            if nm in a:
                                continue
                            d = proc.decls.get(nm)
                            is_dummy = nm in {x.lower() for x in proc.dummy_args}
                            writable = (not is_dummy) or (d is not None and d.intent in ("out", "inout"))
                            if writable:
                                a.add(nm); changed = True
                    continue
                dm = cp.dummy_args
                in_tainted = False
                for dummy, expr in resolve_args(args, dm):       # forward: actual -> input dummy
                    toks = {t.lower() for t in _IDENT.findall(expr)}
                    fn_arg = expr in proj.procedures and proj.procedures[expr].kind == "function"
                    if (toks & a) or fn_arg:                      # any tainted token in the actual
                        in_tainted = True
                        if dummy not in av.setdefault(callee, set()):
                            av[callee].add(dummy); changed = True
                if in_tainted or av.get(callee):                 # backward: output dummy -> actual
                    cav = av.get(callee, set())
                    for dummy, expr in resolve_args(args, dm):
                        cd = cp.decls.get(dummy)
                        # a dummy is an OTI output if it is intent(out/inout) and
                        # carries taint inside the callee, or is directly assigned --
                        # this catches values written via inner call args (e.g.
                        # `call jacobian(..,ajacobian)`) that `assigns` alone misses.
                        is_out = dummy in cp.assigns or (
                            cd is not None and cd.intent in ("out", "inout") and dummy in cav)
                        if is_out:
                            mv = re.match(r"^([A-Za-z_]\w*)", expr)
                            if mv and mv.group(1).lower() not in a:
                                a.add(mv.group(1).lower()); changed = True

    oti = set()
    for p in lift:
        proc = proj.procedures[p]
        for base, toks in assigns_of(p):
            if (toks & av[p]):                       # base assigned from a tainted RHS
                d = proc.decls.get(base)
                if d and d.derived:
                    oti.add(d.derived.lower())
    active = {work}
    for p in lift:
        proc = proj.procedures[p]
        if av[p] or proc.kind == "function" or any(
                d.derived and d.derived.lower() in oti for d in proc.decls.values()):
            active.add(p)
    return active, oti, av, pbind


def derive_config(proj, collect_name, driver_file, options_array="opt_props", mode=None):
    """Read the runtime config from the UMAT's OWN source instead of the contract.

    Generic two-step: (1) the options `collect` routine maps `self%field = arr(i)`,
    giving field->index; (2) the driver/wrapper sets `arr(i) = value`, giving
    index->value. Compose them. `mode` (the model-variant string the wrapper passes,
    e.g. 'IGS') is added directly. So a multi-config UMAT needs only a pointer to its
    driver + the model name, never a hand-written list of internal flags."""
    cache: dict = {}
    field_idx = {}
    cproc = proj.procedures.get(collect_name.lower()) if collect_name else None
    if cproc:
        body = extract_proc(_file_text(cache, cproc.file), cproc.name, cproc.kind) or ""
        for m in re.finditer(r"(?im)^\s*self\s*%\s*(\w+)\s*=\s*(?:int\s*\(\s*)?\w+\s*\(\s*(\d+)\s*\)", body):
            field_idx.setdefault(m.group(1).lower(), int(m.group(2)))
    idx_val = {}
    if driver_file:
        dtext = _file_text(cache, driver_file)
        for m in re.finditer(rf"(?im)^\s*{re.escape(options_array)}\s*\(\s*(\d+)\s*\)\s*=\s*([^!\n]+)", dtext):
            v = _parse_literal(m.group(2).strip())
            if v is not None:
                idx_val[int(m.group(1))] = v
    config = {f: idx_val[i] for f, i in field_idx.items() if i in idx_val}
    if mode:
        config["ismode"] = mode
    return config


def _library_provided(library_files):
    """Names the OTI library already supplies (overloaded intrinsics/utilities like
    det3x3, inv3x3, matmul) - these must not be re-lifted or they collide."""
    provided = set()
    for lf in (library_files or []):
        try:
            txt = open(lf, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        provided |= {m.group(1).lower() for m in re.finditer(r"(?im)^\s*interface\s+(\w+)", txt)}
        provided |= {m.group(1).lower() for m in re.finditer(
            r"(?im)^\s*(?:pure\s+|elemental\s+|recursive\s+)*(?:function|subroutine)\s+(\w+)", txt)}
    return provided


def emit_oti_lift(proj: FortranProject, entry: str, *, oti_type: str, seed: str = "",
                  stub_procs: set[str] | None = None, config: dict | None = None,
                  library_files: list[str] | None = None, advisor=None, llm_decide: bool = False,
                  manual_helpers: str = "", reroute_module: str = "compat_oti",
                  full_oti: bool = False) -> dict:
    """Return {'source': <f90 text>, 'lift':..., 'stubs':..., 'helpers':...,
    'constants':..., 'oti_types':..., 'real_types':...} — all derived."""
    entry = entry.lower()
    stub_procs = {s.lower() for s in (stub_procs or set())}
    config = config or {}
    provided = _library_provided(library_files)   # names the OTI library already supplies
    cache: dict = {}

    def body_of(p):                       # folded body (dead config branches removed)
        return _fold_branches(_proc_text(proj, p, cache), config)

    # generic interface -> the double-precision specific to lift, emitted under
    # the generic's name (so `macaulay(x)` resolves without a hand-written body).
    emit_as: dict[str, str] = {}

    def pick_specific(specs):
        for s in specs:                       # prefer a non-single-precision specific
            sp = proj.procedures.get(s)
            d = sp.decls.get(sp.dummy_args[0]) if sp and sp.dummy_args else None
            ts = (d.type_spec.lower() if d else "")
            if not re.search(r"r4|\(\s*4\s*\)|kind\s*=\s*4|_4\b", ts):
                return s
        return specs[0] if specs else None

    # ---- closure: calls + USE-only procs + textual function references ----
    closure: set[str] = set()
    stack = [entry]
    while stack:
        cur = stack.pop()
        if cur in closure or cur not in proj.procedures:
            continue
        closure.add(cur)
        proc = proj.procedures[cur]
        if cur in stub_procs:
            continue  # don't descend into a stubbed body's dependencies
        # Drive the closure from the FOLDED body only, so dead-branch call targets
        # (euler_richards, matinv, ...) and now-unused USE imports don't get pulled
        # back in. Renames map an aliased token (deviator -> deviator_voigt) to the
        # real procedure; bound calls are resolved if their method survives folding.
        renames: dict[str, str] = {}
        for _mod, only in proc.uses:
            for chunk in only:
                for part in str(chunk).split(","):
                    if "=>" in part:
                        loc, act = part.split("=>", 1)
                        renames[loc.strip().lower()] = act.strip().lower()
        body_toks = {t.lower() for t in _IDENT.findall(body_of(cur))}
        nxt = [renames.get(t, t) for t in body_toks]
        for obj, method, _args in proc.bound_calls:
            if method.lower() not in body_toks:
                continue
            od = proc.decls.get(obj)
            tn = od.derived.lower() if od and od.derived else None
            if tn and tn in proj.types:
                impl = proj.types[tn].bindings.get(method)
                if impl:
                    nxt.append(impl)
        for n in nxt:
            if n in provided:                                        # supplied by the OTI library
                continue
            if n in proj.procedures and n not in closure:
                stack.append(n)
            elif n in proj.generics and n not in emit_as.values():   # resolve generic -> specific
                spec = pick_specific(proj.generics[n])
                if spec and spec in proj.procedures and spec not in closure:
                    emit_as[spec] = n
                    stack.append(spec)

    lift = {p for p in closure if p not in stub_procs}
    stubs = {p for p in closure if p in stub_procs}

    # ---- partition: a proc that touches a derived type is a constitutive routine
    # (numgeo_rate, which uses numgeo_types); pure array/scalar tensor utilities go
    # to compat_oti. This keeps a utility and everything it calls in one module. ----
    def _touches_type(p):
        return any(d.base in ("TYPE", "CLASS") and d.derived and d.derived.lower() in proj.types
                   for d in proj.procedures[p].decls.values())
    subs = sorted(p for p in lift if _touches_type(p))            # -> numgeo_rate
    funcs = sorted(p for p in lift if not _touches_type(p))       # -> compat_oti

    # ---- derived types referenced anywhere in the lift set ----
    types_seen: set[str] = set()
    for p in lift:
        proc = proj.procedures[p]
        for d in proc.decls.values():
            if d.base in ("TYPE", "CLASS") and d.derived and d.derived.lower() in proj.types:
                types_seen.add(d.derived.lower())
    # ---- taint analysis over the WHOLE closure (incl. stubs, so their dummy
    # types match the callers) -> active (retype) set + which types are OTI ----
    active, oti_set, taint, pbind = _activeness(proj, entry, seed or "", closure, cache, config)
    # FULL-OTI mode: retype EVERYTHING real -> OTI (every proc fully, every derived
    # type a variant). Generic numerical solvers mix OTI (unknowns/residual/Jacobian)
    # and real (props/config) through procedure arguments and interface blocks in ways
    # selective taint can't separate cleanly, producing OTI<->real boundary mismatches.
    # Over-typing removes the boundaries; it stays correct (props/config carry zero
    # derivative, branches use the real part). This is the robust mode for the
    # solver-based UMATs that the selective taint can't crack.
    if full_oti:
        active = set(closure)
        oti_set = set(types_seen)
    # Optional LLM tie-breaker for the OTI-vs-real type decision. OFF by default:
    # empirically a local model is UNRELIABLE here (it misclassified numgeo's
    # material_properties_ty and broke a clean transform), and a wrong type
    # decision can't be fixed by local repair. The deterministic taint is the
    # authority; this is opt-in (`llm_decide=True`) for genuinely ambiguous cases.
    if llm_decide and advisor is not None and advisor.available():
        for t in sorted(types_seen):
            dt = proj.types[t]
            comps = ", ".join(list(dt.components)[:12])
            verdict = advisor.decide(
                f"Does derived type '{dt.name}' carry the strain/stress derivative "
                f"(answer 'oti') or is it read-only material parameters / solver config "
                f"(answer 'real')?", ["oti", "real"],
                context=f"Components: {comps}\nHeuristic guess: "
                        f"{'oti' if t in oti_set else 'real'}")
            if verdict == "oti":
                oti_set.add(t)
            elif verdict == "real":
                oti_set.discard(t)
    oti_types = sorted(oti_set & types_seen)
    real_types = sorted(types_seen - oti_set)

    # ---- discover the runtime config the contract must request: fields of
    # REAL-typed (controls/material) vars compared to literals in branch guards.
    # State (OTI) guards like `if (sv%rho > 1)` are NOT config and are excluded. ----
    config_needed: dict[str, set] = {}
    for p in lift:
        proc = proj.procedures[p]
        raw = _proc_text(proj, p, cache)
        for cm in re.finditer(r"(?im)\bif\s*\((.*)\)\s*(?:then\s*$|\S)", raw):
            for fm in re.finditer(r"(\w+)\s*%\s*(\w+)\s*(?:==|/=|>=|<=|>|<)\s*([^\s.)]+)", cm.group(1)):
                obj, fld, val = fm.group(1).lower(), fm.group(2).lower(), fm.group(3).strip("'\"")
                d = proc.decls.get(obj)
                if d and d.derived and d.derived.lower() in set(real_types):
                    config_needed.setdefault(fld, set()).add(val)

    def iface_extra(p):
        """Names to additionally retype in p that appear in an INTERFACE block for a
        dummy procedure (higher-order). The interface signature must match how the
        dummy procedure is CALLED inside p: interface arg is OTI iff the actual passed
        at that position (in p's local call to the dummy proc) carries taint. This is
        general -- it needs no cross-procedure binding, so it also fixes interfaces in
        emitted-but-uncalled solver variants (numjac) whose dummy-proc calls pass
        tainted locals."""
        extra: set = set()
        proc = proj.procedures[p]
        src = _proc_text(proj, p, cache)
        iface_args: dict = {}                       # dummy-proc -> [interface arg names]
        for ib in re.finditer(r"(?is)\binterface\b(.*?)\bend\s+interface\b", src):
            for sm in re.finditer(r"(?is)\b(?:subroutine|function)\s+(\w+)\s*\(([^)]*)\)", ib.group(1)):
                iface_args[sm.group(1).lower()] = [a.strip().lower()
                                                   for a in sm.group(2).split(",") if a.strip()]
        if not iface_args:
            return extra
        tp = taint.get(p, set())
        for callee, args in proc.call_sites:
            ia = iface_args.get(callee.lower())
            if not ia:
                continue
            pos = 0
            for act in args:
                mkw = re.match(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+)$", act)
                if mkw and "==" not in act and mkw.group(1).lower() in ia:
                    nm, expr = mkw.group(1).lower(), mkw.group(2)
                elif pos < len(ia):
                    nm, expr, pos = ia[pos], act, pos + 1
                else:
                    pos += 1
                    continue
                if {t.lower() for t in _IDENT.findall(expr)} & tp:
                    extra.add(nm)
        return extra

    def RTv(p):                       # taint-selective retype of proc p's source
        if full_oti:
            only = None               # full_oti -> retype every real
        else:
            only = set(taint.get(p) or set()) | iface_extra(p)   # + interface-block args
        return _normint(RT(src_of(p), only_vars=only))

    # ---- constants: USE-only names that are module PARAMETERs ----
    consts: dict[str, str] = {}
    for p in lift:
        proc = proj.procedures[p]
        for mod, only in proc.uses:
            if mod.lower() in _KEPT_MODULES:           # precision_ etc. stay as external use
                continue
            for nm in _only_names(only):
                k = nm.lower()
                if k in proj.procedures or k in proj.types or k in consts:
                    continue
                modrec = proj.modules.get(mod.lower())
                if modrec is None:
                    continue
                decl = extract_param(_file_text(cache, modrec.file), nm)
                if decl:
                    consts[k] = decl.strip()

    # host-associated module PARAMETERs referenced in lifted bodies (e.g. a 3x3
    # delta used by a helper without a USE) - scan bodies against module params.
    modparams: dict[str, tuple[str, str]] = {}
    for m in inlined if (inlined := {x for x in proj.modules} - _KEPT_MODULES) else set():
        modrec = proj.modules.get(m)
        if modrec is None:
            continue
        mtext = _file_text(cache, modrec.file)
        for line in re.findall(r"(?im)^[^!\n]*\bparameter\b[^\n]*::[^\n]*$", mtext):
            for nm in re.findall(r"(\w+)\s*=", line.split("::", 1)[1]):
                modparams.setdefault(nm.lower(), (nm, modrec.file))
    for p in lift:
        proc = proj.procedures[p]
        body = extract_proc(_file_text(cache, proc.file), proc.name, proc.kind) or ""
        for tok in {t.lower() for t in _IDENT.findall(body)}:
            if tok in modparams and tok not in consts and tok not in proj.procedures and tok not in proj.types:
                realnm, mfile = modparams[tok]
                decl = extract_param(_file_text(cache, mfile), realnm)
                if decl:
                    consts[tok] = decl.strip()

    # transitive PARAMETER closure: a kept parameter's initializer may reference
    # other module parameters (e.g. `IoI = reshape([I2,...])`, `I4dev = reshape([p23,m13,...])`).
    # Those operands must be carried too, or the kept decl references an undeclared
    # symbol. Iterate to a fixpoint over the RHS of every const currently held.
    changed = True
    while changed:
        changed = False
        for decl in list(consts.values()):
            rhs = decl.split("=", 1)[1] if "=" in decl else ""
            for tok in {t.lower() for t in _IDENT.findall(rhs)}:
                if tok in modparams and tok not in consts and tok not in proj.procedures \
                        and tok not in proj.types:
                    realnm, mfile = modparams[tok]
                    d = extract_param(_file_text(cache, mfile), realnm)
                    if d:
                        consts[tok] = d.strip()
                        changed = True

    # module-scope MUTABLE variables (not parameters) - shared solver/config state
    # like SME_maxiter, nvar. Carry their declarations so lifted procs that
    # host-associated them still see them (emitted verbatim, kept real/integer).
    modvars: dict[str, str] = {}
    for m in inlined:
        modrec = proj.modules.get(m)
        if modrec is None:
            continue
        mm = re.search(r"(?is)\bmodule\s+\w+\b(.*?)\n\s*contains\b", _file_text(cache, modrec.file))
        in_type = 0
        for line in (mm.group(1) if mm else "").split("\n"):
            s = line.split("!", 1)[0].strip()
            # skip type-definition bodies: their components are NOT module variables
            if re.match(r"(?i)type\s*(,|::|\s+\w)", s) and not re.match(r"(?i)type\s*\(", s) \
                    and "end type" not in s.lower():
                in_type += 1
                continue
            if re.match(r"(?i)end\s+type\b", s):
                in_type = max(0, in_type - 1)
                continue
            if in_type or "::" not in s:
                continue
            if re.match(r"(?i)(integer|real|double\s+precision|logical|character|complex)\b", s) \
                    and not re.search(r"(?i)\bparameter\b", s):
                for nm in re.findall(r"([A-Za-z_]\w*)", s.split("::", 1)[1]):
                    modvars.setdefault(nm.lower(), s)
    # A module var is genuine shared state only where a lifted proc uses it WITHOUT
    # a local declaration. Names that are always local (loop indices i, j, ...) are
    # never carried - carrying them as public module vars would collide everywhere.
    needed = set()
    for p in lift:
        proc = proj.procedures[p]
        local = {d.lower() for d in proc.decls} | {a.lower() for a in proc.dummy_args}
        body = _proc_text(proj, p, cache)
        needed |= {t.lower() for t in _IDENT.findall(body)} - local
    # loop indices are never module state; carrying them as public module vars
    # would collide with every local i/j (and they're often implicitly typed).
    _LOOP = {"i", "j", "k", "l", "m", "n", "ii", "jj", "kk", "i1", "i2", "j1", "k1", "k2", "kk1"}
    emitted = set(consts.values())                # dedup multi-name decls (integer :: i, j)
    for nm, decl in modvars.items():
        if nm in needed and nm not in _LOOP and nm not in consts and nm not in proj.procedures \
                and nm not in proj.types and decl not in emitted:
            consts[nm] = decl
            emitted.add(decl)

    # ---- assemble ----
    # modules whose contents are inlined here (everything except the kept leaf,
    # precision_); imports of these get rerouted (rate) or stripped (helpers).
    inlined = {m for m in proj.modules} - {"precision_", "master_parameters"}
    inl_pat = "|".join(re.escape(m) for m in inlined) if inlined else r"\bZZZNONE\b"

    def src_of(p):
        text = body_of(p) or f"! MISSING {p}"
        if p in emit_as:                       # emit a generic's specific under the generic name
            g = emit_as[p]
            text = re.sub(rf"(?i)\b(function|subroutine)\s+{re.escape(p)}\b", rf"\1 {g}", text)
            text = re.sub(rf"(?i)(end\s+(?:function|subroutine))\s+{re.escape(p)}\b", rf"\1 {g}", text)
        return text

    def drop_provided_only(t):
        # library-provided names (det3x3, inv3x3, ...) come from `use otim6n1`, so
        # remove them from rerouted only-lists. Only rewrite a line that actually
        # names a provided symbol, to avoid disturbing multi-line continuations.
        if not provided:
            return t
        out = []
        for line in t.split("\n"):
            m = re.match(r"(?i)(\s*use\s+\w+\s*,\s*only\s*:\s*)(.+?)(\s*&)?\s*$", line)
            if m and "compat_oti" in m.group(1).lower():
                raw = m.group(2).split(",")
                nms = [re.match(r"\s*(?:\w+\s*=>\s*)?(\w+)", it) for it in raw]
                if any(nm and nm.group(1).lower() in provided for nm in nms):
                    items = [it.strip() for it, nm in zip(raw, nms)
                             if not (nm and nm.group(1).lower() in provided)]
                    cont = " &" if m.group(3) else ""
                    line = (m.group(1) + ", ".join(items) + ((", " + cont.strip()) if cont else "")) \
                        if items else "    ! (use line dropped: all library-provided)"
            out.append(line)
        return "\n".join(out)

    def reroute_rate(t):
        # change the inlined module name to compat_oti but KEEP the only-list
        # (its rename clauses like `deviator => deviator_voigt` are essential).
        return drop_provided_only(re.sub(rf"(?i)use\s+(?:{inl_pat})\b", f"use {reroute_module}", t))

    def strip_inlined_use(t):
        # helpers live IN compat_oti, so imports of inlined names are host-assoc.
        return re.sub(rf"(?im)^\s*use\s+(?:{inl_pat})\b.*?(?<!&)$\n?", "", t)

    def proc_renames(proc):
        rmap = {}
        for _mod, only in proc.uses:
            for chunk in only:
                for part in str(chunk).split(","):
                    if "=>" in part:
                        loc, act = part.split("=>", 1)
                        rmap[loc.strip()] = act.strip()
        return rmap

    def desugar_bound(t, proc):
        # rewrite type-bound calls `call obj%method(args)` -> `call impl(obj, args)`
        # since the emitted types carry no type-bound bindings.
        for obj, method, _args in proc.bound_calls:
            od = proc.decls.get(obj)
            tn = od.derived.lower() if od and od.derived else None
            impl = proj.types[tn].bindings.get(method) if tn and tn in proj.types else None
            if impl:
                t = re.sub(rf"(?i)\bcall\s+{re.escape(obj)}\s*%\s*{re.escape(method)}\s*\(",
                           f"call {impl}({obj}, ", t)
        return t

    def apply_renames(t, rmap):
        # helpers can't carry a USE-rename into their own host module, so fold the
        # alias into the body (deviator -> deviator_voigt). Skip 1-char aliases
        # (e.g. I => Isym) to never clobber a loop index.
        for loc, act in rmap.items():
            if len(loc) >= 2:
                # Outside real literals: a two-character alias is exactly the
                # length that collides with the tail of one (D0 in 2.D0, E1 in
                # 1.E1), and a literal is a single token.
                t = rewrite_outside_real_literals(
                    t, lambda masked, loc=loc, act=act: re.sub(rf"\b{re.escape(loc)}\b", act, masked))
        return t

    def emit_body(p):
        proc = proj.procedures[p]
        if proc.kind == "function":          # referenced in expressions; taint can't
            t = _normint(RT(src_of(p)))      # reach the dummies -> retype fully
        elif p in active:
            t = RTv(p)                       # selective (only tainted vars -> OTI)
        else:
            t = src_of(p)                    # pure real setup routine
        t = _norm_intrinsics(t)              # dexp/dsqrt/... -> generic (library overloads)
        # Reroute MIN(/MAX( to non-intrinsic oti_min/oti_max for ALL forms (avoids the
        # "generic not consistent with intrinsic" conflict once an arg is OTI; oti_min/
        # oti_max handle real/int/OTI combos, and AMIN1/DMIN1/MIN0 are left alone).
        t = re.sub(r"(?i)\bmin\s*\(", "oti_min(", re.sub(r"(?i)\bmax\s*\(", "oti_max(", t))
        if proc.file.lower().endswith((".f", ".for", ".ftn")):
            # legacy fixed-form only: promote single-precision real literals to double
            t = _promote_reals(t)
        return t

    helper_src = "\n".join(
        strip_inlined_use(apply_renames(
            desugar_bound(emit_body(p), proj.procedures[p]), proc_renames(proj.procedures[p])))
        for p in funcs)
    rate_src = "\n".join(
        reroute_rate(desugar_bound(emit_body(p), proj.procedures[p])) for p in subs)
    rate_src, _lap_rate = _reroute_lapack(rate_src)     # LAPACK -> OTI shims
    helper_src, _lap_help = _reroute_lapack(helper_src)
    rate_src = _fix_interface_imports(rate_src)          # OTI visible in interface blocks
    helper_src = _fix_interface_imports(helper_src)
    lapack_use = "  use oti_lapack\n" if (_lap_rate or _lap_help) else ""

    # stub signatures regenerated from the model (retyped dummies, zeroed outputs).
    # A stub that touches an OTI/real derived type must sit in numgeo_rate (which
    # uses numgeo_types); a pure-array/scalar stub can live in compat_oti.
    def dim_spec(dims):
        """Extract the rank-preserving dimension '(...)' from a captured dims str
        ('dimension(ntens), intent(in)' or '(ntens)')."""
        if not dims:
            return ""
        m = re.search(r"(?i)dimension\s*(\([^)]*\))", dims)
        if m:
            return m.group(1)
        s = dims.strip()
        if s.startswith("("):
            depth, out = 0, ""
            for ch in s:
                out += ch
                depth += (ch == "(") - (ch == ")")
                if depth == 0:
                    break
            return out
        return ""

    def stub_text(p):
        proc = proj.procedures[p]
        tp = taint.get(p, set())
        decls, uses_type = [], False
        for dn in proc.dummy_args:
            d = proc.decls.get(dn)
            if d is None:
                continue
            if d.base in ("TYPE", "CLASS"):
                uses_type = True
            # function stubs are referenced in expressions (no call-site taint), so
            # retype all their dummies; subroutine stubs follow the caller's taint.
            spec = RT(d.type_spec) if (proc.kind == "function" or dn in tp) else d.type_spec
            ds = dim_spec(d.dims)
            decls.append(f"    {spec}{', dimension' + ds if ds else ''} :: {d.name}")
        if proc.kind == "function":
            txt = (f"  function {proc.name}({', '.join(proc.dummy_args)}) result({proc.name}_r)\n"
                   + "\n".join(decls) + f"\n    type({oti_type}) :: {proc.name}_r\n"
                   + f"    {proc.name}_r = 0.0d0\n  end function")
        else:
            txt = (f"  subroutine {proc.name}({', '.join(proc.dummy_args)})\n"
                   + "\n".join(decls) + "\n  end subroutine")
        return txt, uses_type

    stub_compat, stub_rate = [], []
    for p in sorted(stubs):
        txt, uses_type = stub_text(p)
        (stub_rate if uses_type else stub_compat).append(txt)

    def typedef_src(t, as_oti):
        raw = extract_typedef(_file_text(cache, proj.types[t].file), proj.types[t].name) or f"! MISSING type {t}"
        return RT(raw) if as_oti else raw

    types_block = "\n".join(typedef_src(t, True) for t in oti_types) + "\n" + \
                  "\n".join(typedef_src(t, False) for t in real_types)
    # Emit PARAMETERs in dependency order: a param whose initializer references
    # another param (IoI = reshape([I2,...])) must be declared AFTER its operands.
    # Topo-sort consts on intra-consts RHS references; cycles/ties keep insertion order.
    def _order_consts(cd):
        deps = {}
        for k, decl in cd.items():
            rhs = decl.split("=", 1)[1] if "=" in decl else ""
            deps[k] = {t.lower() for t in _IDENT.findall(rhs)} & set(cd) - {k}
        ordered, seen = [], set()

        def visit(k, stack):
            if k in seen or k in stack:
                return
            stack.add(k)
            for d in deps[k]:
                visit(d, stack)
            stack.discard(k)
            seen.add(k)
            ordered.append(k)
        for k in cd:
            visit(k, set())
        return [cd[k] for k in ordered]
    consts_block = "\n".join("  " + c for c in _order_consts(consts))

    source = f"""! AUTO-EMITTED by emit_lift.py from the semantic plan (entry: {entry})
module compat_oti
  use otim6n1
  use oti_intrinsics
{lapack_use}  use precision_, only: rk, ik
  implicit none
{consts_block}
contains
{helper_src}
{chr(10).join(stub_compat)}
{manual_helpers}
end module compat_oti

module numgeo_types
  use otim6n1
  use precision_, only: rk, ik
  implicit none
{types_block}
end module numgeo_types

module numgeo_rate
  use otim6n1
  use oti_intrinsics
{lapack_use}  use compat_oti
  use numgeo_types
  use precision_, only: rk, ik
  implicit none
contains
{chr(10).join(stub_rate)}
{rate_src}
end module numgeo_rate
"""
    return {"source": source, "lift": sorted(lift), "stubs": sorted(stubs),
            "helpers": funcs, "subs": subs, "constants": sorted(consts),
            "oti_types": oti_types, "real_types": real_types,
            "active_subs": sorted(p for p in subs if p in active),
            "real_subs": sorted(p for p in subs if p not in active),
            "config_needed": {k: sorted(v) for k, v in sorted(config_needed.items())}}
