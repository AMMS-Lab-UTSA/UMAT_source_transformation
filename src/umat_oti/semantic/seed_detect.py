"""Auto-detect the strain *seed* variable of a UMAT for the OTI transform.

The OTI transform differentiates STRESS with respect to one input "seed":

  * small-strain UMATs perturb the strain increment   -> seed = DSTRAN
    (numgeo spells it DSTRAIN; both are handled here)
  * finite-strain UMATs perturb the deformation gradient -> seed = DFGRD1
    (typically converted first, e.g. ``Fnew = m3x3_2_v9(dfgrd1)``)

Today the caller must state which one by hand. This module decides it from the
*structure* of the entry UMAT alone, so the pipeline can default it.

Strategy (deliberately conservative, no semantics of the math):

  1. From the entry procedure's dummy args, find the candidate seeds actually
     present: deformation-gradient candidates (DFGRD1, DFGRD0) and strain-increment
     candidates (DSTRAN/DSTRAIN/DEPS...).
  2. Find the *stress-producing* call sites: the calls in the entry body whose
     actual arguments include a variable that the entry then writes into STRESS
     (the UMAT's stress output) -- e.g. ``call elastic(...,stressi,...)`` followed
     by ``stress = stressi``. Fall back to a name heuristic (callee/arg looks like
     "stress"/"elastic"/"plastic") so a one-liner UMAT is still covered.
  3. Taint: starting from each candidate seed, follow simple body assignments
     (``Fnew = f(dfgrd1)``) to see which *derived* variables carry it, then ask
     whether any tainted variable is passed into a stress-producing call.
  4. A deformation gradient that reaches the stress update wins (finite strain);
     otherwise a strain increment that reaches it wins (small strain). If only one
     family is even *present* in the body, pick it. This makes the common UMAT
     header -- which declares DFGRD1 *and* DSTRAN as dummies but uses only one --
     resolve correctly: the unused dummy never reaches the stress update.

Returns ``(seed, confidence, reason)`` so callers can log *why*.

Only the public FortranProject API is used (procedures, dummy_args, call_sites,
assigns, reachable, .file/.kind) plus a self-contained read of the entry body
text -- nothing private to emit_lift / retype, which other engineers own.
"""
from __future__ import annotations

import re

# Candidate dummy-argument names, by family. Matched case-insensitively against
# the entry procedure's dummy args. Order within a family = preference.
_DFGRD_CANDIDATES = ("dfgrd1", "dfgrd0")
# Strain-increment spellings seen in the wild: Abaqus DSTRAN, numgeo DSTRAIN,
# and a few common aliases. DSTRAN/DSTRAIN are the load-bearing ones.
_STRAIN_CANDIDATES = ("dstran", "dstrain", "deps", "dstrn", "depsilon")

# Names that, as a callee or an actual argument, mark a call as part of the
# stress update when we cannot prove it via the STRESS write (a robustness net).
_STRESS_HINT = re.compile(r"(?i)(stress|elastic|plastic|sigma|cauchy|^t_|_t$|^thyp|stiff)")


def _extract_body(proc) -> str:
    """Return the source text of `proc`'s body (best effort, comments stripped).

    Self-contained so this module never imports emit_lift internals. Reads the
    procedure's own file and slices out its subprogram by name; if that fails we
    return "" and the caller falls back to the structural (call_sites) signals,
    which alone already classify the five known UMATs."""
    try:
        text = open(proc.file, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    kw = "function" if proc.kind == "function" else "subroutine"
    m = re.search(rf"\n(\s*(?:pure\s+|elemental\s+|recursive\s+)*{kw}\s+{re.escape(proc.name)}\s*\(.*?"
                  rf"end\s+{kw}\s+{re.escape(proc.name)}\b)", text, re.S | re.I)
    if not m:
        m = re.search(rf"\n(\s*(?:pure\s+|elemental\s+|recursive\s+)*{kw}\s+{re.escape(proc.name)}\s*\(.*?"
                      rf"\n\s*end\s+{kw}\b[^\n]*)", text, re.S | re.I)
    if not m:
        return ""
    # strip full-line and trailing comments so a commented `dfgrd1` never taints
    out = []
    for ln in m.group(1).splitlines():
        out.append(ln.split("!", 1)[0])
    return "\n".join(out)


def _assignment_taint(body: str, seeds: set[str]) -> set[str]:
    """Set of lowercased var names that carry any of `seeds`, via plain
    assignments ``lhs = ... rhs-uses-a-tainted-name ...``. Fixed-point so a chain
    ``a = f(dfgrd1) ; b = g(a)`` taints both a and b. Conservative: any tainted
    token appearing as a whole word on the RHS taints the LHS."""
    tainted = {s.lower() for s in seeds}
    # candidate assignment statements: `name = rhs` (skip ==, >=, /=, declarations)
    assigns: list[tuple[str, str]] = []
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        # skip declarations / keywords that contain '='
        if re.match(r"(?i)(use|implicit|type|real|integer|logical|character|complex|"
                    r"double|class|dimension|parameter|end|module|contains|interface|"
                    r"if|do|else|select|case|where|call|subroutine|function|return)\b", s):
            continue
        m = re.match(r"(?i)\s*([A-Za-z_]\w*)\s*(?:\([^=]*\))?\s*=\s*([^=].*)$", s)
        if not m:
            continue
        lhs, rhs = m.group(1).lower(), m.group(2)
        if rhs.lstrip().startswith(("=", ">", "<", "/")):  # ==, =>, etc. -- not an assignment
            continue
        assigns.append((lhs, rhs))
    changed = True
    while changed:
        changed = False
        for lhs, rhs in assigns:
            if lhs in tainted:
                continue
            toks = set(re.findall(r"[A-Za-z_]\w*", rhs.lower()))
            if toks & tainted:
                tainted.add(lhs)
                changed = True
    return tainted


def _stress_producing_calls(proc, body: str) -> list[tuple[str, list[str]]]:
    """Call sites of `proc` that participate in computing STRESS.

    Proven path: the call writes into a local (one of its actual args) that the
    entry body then assigns into STRESS (the umat stress output). Heuristic net:
    the callee name or an argument looks stress/elastic/plastic-related. Returns
    the subset of proc.call_sites that qualify (callee, [arg base names])."""
    # which locals end up written into STRESS? `stress = stressi(1:ntens)` -> stressi
    stress_feeders: set[str] = set()
    for ln in body.splitlines():
        m = re.match(r"(?i)\s*(stress|sig|t)\b[^=]*=\s*([A-Za-z_]\w*)", ln)
        if m and re.fullmatch(r"(?i)(stress|sig|t)", m.group(1)):
            stress_feeders.add(m.group(2).lower())
    # also treat the umat's own STRESS dummy as a feeder name, in case it is passed
    # straight into a routine that updates it in place.
    stress_feeders.add("stress")

    out = []
    for callee, args in proc.call_sites:
        argset = {re.split(r"=", a, 1)[-1].lower() for a in args}  # strip kw= prefix
        proven = bool(argset & stress_feeders)
        hinted = bool(_STRESS_HINT.search(callee)) or any(_STRESS_HINT.search(a) for a in argset)
        if proven or hinted:
            out.append((callee, list(argset)))
    return out


def detect_seed(proj, entry_proc: str):
    """Decide the strain seed of `entry_proc` in `proj`.

    Returns ``(seed, confidence, reason)``:
      * seed       -- the actual dummy-arg name to perturb (e.g. "dfgrd1",
                      "dstran", or numgeo's "dstrain"); lowercased.
      * confidence -- "high" | "medium" | "low".
      * reason     -- human-readable explanation of the decision.
    """
    entry = entry_proc.lower()
    proc = proj.procedures.get(entry)
    if proc is None:
        return (None, "low", f"entry procedure '{entry_proc}' not found in project")

    dummies = [d.lower() for d in proc.dummy_args]
    dset = set(dummies)
    dfgrd = [c for c in _DFGRD_CANDIDATES if c in dset]
    strain = [c for c in _STRAIN_CANDIDATES if c in dset]

    body = _extract_body(proc)

    # Which candidate seeds actually appear (used) anywhere in the body? A bare
    # dummy from the Abaqus header that is never referenced does not count.
    def used(name: str) -> bool:
        if not body:
            return True  # no body text -> don't exclude on this signal
        return re.search(rf"(?i)\b{re.escape(name)}\b", body) is not None

    dfgrd_used = [c for c in dfgrd if used(c)]
    strain_used = [c for c in strain if used(c)]

    # Stress-producing calls and the variables tainted by each candidate family.
    stress_calls = _stress_producing_calls(proc, body) if body else list(proc.call_sites)
    stress_call_args: set[str] = set()
    for _callee, args in stress_calls:
        stress_call_args.update(args)

    df_taint = _assignment_taint(body, set(dfgrd)) if (body and dfgrd) else set(dfgrd)
    st_taint = _assignment_taint(body, set(strain)) if (body and strain) else set(strain)

    df_reaches = bool(df_taint & stress_call_args)
    st_reaches = bool(st_taint & stress_call_args)

    pick_df = dfgrd_used[0] if dfgrd_used else (dfgrd[0] if dfgrd else None)
    pick_st = strain_used[0] if strain_used else (strain[0] if strain else None)

    # ---- decide -------------------------------------------------------------
    # 1. Strongest signal: a candidate, via body taint, reaches a stress call.
    #    Deformation gradient wins when both reach (finite strain dominates).
    if df_reaches and pick_df:
        # report only the body-derived variables that actually carry the gradient
        # (e.g. Fnew = m3x3_2_v9(dfgrd1)), not the other unused seed candidates.
        via = sorted((df_taint & stress_call_args) - set(dfgrd))
        via_txt = f" via {via}" if via else ""
        return (pick_df, "high",
                f"deformation gradient '{pick_df}'{via_txt} reaches a "
                f"stress-producing call -> finite-strain")
    if st_reaches and pick_st:
        return (pick_st, "high",
                f"strain increment '{pick_st}' feeds a stress-producing call -> small-strain")

    # 2. No proven stress-call path (e.g. body text unavailable). Fall back to
    #    "which family is actually USED in the body".
    if dfgrd_used and not strain_used:
        return (pick_df, "medium",
                f"'{pick_df}' is used in the body and no strain-increment arg is "
                f"-> finite-strain")
    if strain_used and not dfgrd_used:
        return (pick_st, "medium",
                f"'{pick_st}' is used in the body and no deformation-gradient arg is "
                f"-> small-strain")

    # 3. Both families used but neither proven to reach stress: prefer dfgrd
    #    (finite-strain) per the contract, else fall back to the strain arg.
    if dfgrd_used and strain_used:
        return (pick_df, "low",
                f"both '{pick_df}' and '{pick_st}' used; neither proven to reach the "
                f"stress update -> defaulting to finite-strain '{pick_df}'")

    # 4. Only declared (not used) candidates, or nothing at all.
    if pick_df:
        return (pick_df, "low", f"only deformation-gradient candidate present: '{pick_df}'")
    if pick_st:
        return (pick_st, "low", f"only strain-increment candidate present: '{pick_st}'")
    return (None, "low",
            f"no strain seed candidate among entry dummy args: {dummies}")
