from __future__ import annotations

import re

from umat_oti.core.model import CallSite, ParsedFortranSource, ParsedSubroutine


def build_call_graph(parsed: ParsedFortranSource, entry_name: str) -> tuple[CallSite, ...]:
    calls: list[CallSite] = []
    for routine in parsed.subroutines:
        if routine.upper_name != entry_name.upper():
            continue
        for line in routine.lines:
            match = re.search(r"\bcall\s+(\w+)\s*\(", line.text, flags=re.IGNORECASE)
            if match:
                calls.append(CallSite(routine.name, match.group(1), line.line_numbers))
    return tuple(sorted(calls, key=lambda item: (item.caller.upper(), item.callee.upper(), item.line_numbers)))


#: Statements that carry no computation and so do not stop a routine from
#: being a pure delegation.
_TRANSPARENT_STATEMENT = re.compile(
    r"^(?:include\b|implicit\b|dimension\b|common\b|parameter\b|character\b"
    r"|real\b|double\s*precision\b|integer\b|logical\b|complex\b|type\b"
    r"|external\b|intrinsic\b|save\b|data\b|equivalence\b|entry\b"
    r"|return\b|end\b|continue\b|use\b"
    # The routine's own header is part of the body the parser hands over.
    r"|subroutine\b|function\b|program\b)",
    re.IGNORECASE)


def delegated_material_routine(
    parsed: ParsedFortranSource, entry_name: str
) -> str | None:
    """The routine an Abaqus entry point hands its whole job to, if there is one.

    Keeping the Abaqus interface separate from the constitutive model is an
    ordinary way to write a UMAT: ``subroutine umat(...)`` declares the
    interface Abaqus insists on, calls the model routine with the arguments
    that model actually needs, and returns. Fifteen of the discovered
    finite-strain sources are written that way.

    Transforming the routine named UMAT then transforms a routine that
    contains no stress update and no tangent, and the report says so
    accurately while missing the point -- the material is one call below.
    This follows that call, and only that one: a routine qualifies only if
    its executable body is a single CALL to a subroutine defined in this same
    source, and that call passes through the output arrays the contract is
    written against. Anything else -- two calls, a call plus arithmetic, a
    call to an external -- is a routine doing work of its own, and its own
    body is what should be transformed.

    Returns the callee's upper-case name, or None when the entry routine is
    not a pure delegation. The chain is followed to its end, so a wrapper
    around a wrapper resolves to the model routine; a cycle stops the walk.
    """
    routines = {routine.upper_name: routine for routine in parsed.subroutines}
    current = entry_name.upper()
    seen: set[str] = set()
    resolved: str | None = None
    while current in routines and current not in seen:
        seen.add(current)
        callee = _sole_delegated_call(routines[current], routines)
        if callee is None:
            break
        resolved = callee
        current = callee
    return resolved


def _sole_delegated_call(
    routine: ParsedSubroutine, routines: dict[str, ParsedSubroutine]
) -> str | None:
    """The single locally defined routine this one delegates its whole body to."""
    callee: str | None = None
    arguments: tuple[str, ...] = ()
    for line in routine.lines:
        text = line.text.strip()
        if not text or text.startswith("!") or _TRANSPARENT_STATEMENT.match(text):
            continue
        match = re.match(r"^call\s+([A-Za-z_]\w*)\s*\((.*)\)\s*$", text,
                         flags=re.IGNORECASE | re.DOTALL)
        if not match or callee is not None:
            # A second statement of any kind means this routine computes
            # something itself, so it is the routine to transform.
            return None
        callee = match.group(1).upper()
        arguments = tuple(
            argument.strip().upper() for argument in match.group(2).split(","))
    if callee is None or callee not in routines:
        return None
    # The delegate has to receive the arrays the transform reads and writes.
    # Without them it is a subordinate calculation, not the material routine.
    passed = {argument.split("(")[0] for argument in arguments}
    if not {"STRESS", "DDSDDE"} <= passed:
        return None
    return callee
