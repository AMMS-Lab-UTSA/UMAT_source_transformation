"""Match a UMAT's dummy arguments to the Abaqus interface by POSITION.

Abaqus calls ``UMAT`` with one fixed list of 37 arguments and matches them to
the routine's dummies by position, never by name. A UMAT whose author spelled
every dummy his own way (``subroutine umat(sigma, sv, C, sse, ...)``) is
therefore a perfectly good Abaqus UMAT, and the transform, which finds STRESS,
DSTRAN, DDSDDE and the rest by their Abaqus names, could not read it.

The rule (written before it was implemented, see the B17 notes): when the
routine named UMAT has exactly 37 dummies and neither STRESS nor DDSDDE is
among them, dummy ``k`` is the ``k``-th Abaqus argument. Inside that routine
only, each author dummy is renamed to the Abaqus name, and any other
identifier that already carries an Abaqus name is first moved to ``NAME_USR``.
It is a consistent alpha-renaming of one routine, so no value changes.
A source that already names STRESS or DDSDDE is returned untouched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The Abaqus UMAT argument list, in the order Abaqus passes it.
ABAQUS_UMAT_ARGUMENTS: tuple[str, ...] = (
    "STRESS", "STATEV", "DDSDDE", "SSE", "SPD", "SCD", "RPL", "DDSDDT",
    "DRPLDE", "DRPLDT", "STRAN", "DSTRAN", "TIME", "DTIME", "TEMP", "DTEMP",
    "PREDEF", "DPRED", "CMNAME", "NDI", "NSHR", "NTENS", "NSTATV", "PROPS",
    "NPROPS", "COORDS", "DROT", "PNEWDT", "CELENT", "DFGRD0", "DFGRD1",
    "NOEL", "NPT", "LAYER", "KSPT", "KSTEP", "KINC",
)

_TOKEN = re.compile(
    r"(?P<dotted>\.[A-Za-z]+\.)"
    r"|(?P<number>(?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?(?:_\w+)?)"
    r"|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)"
)
_FORMAT_STATEMENT = re.compile(r"^\s*\d*\s*format\s*\(", re.IGNORECASE)


@dataclass
class PositionRewrite:
    """What the rewrite did, or why it did not."""

    applied: bool = False
    text: str = ""
    refused: str = ""
    dummy_map: dict[str, str] = field(default_factory=dict)
    clash_map: dict[str, str] = field(default_factory=dict)


def _split_code(line: str, fixed: bool, in_string: str) -> tuple[list[tuple[str, bool]], str]:
    """Split one physical line into (text, is_code) pieces; returns the string state kept."""
    pieces: list[tuple[str, bool]] = []
    start = 0
    limit = len(line)
    if fixed:
        if line[:1] in ("c", "C", "*", "!") or not line.strip():
            return [(line, False)], ""
        pieces.append((line[:6], False))
        start = 6
        limit = min(len(line), 72)
    i = start
    buf = start
    quote = in_string
    while i < limit:
        ch = line[i]
        if quote:
            if ch == quote:
                if i + 1 < limit and line[i + 1] == quote:
                    i += 2
                    continue
                pieces.append((line[buf:i + 1], False))
                buf = i + 1
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            pieces.append((line[buf:i], True))
            buf = i
            quote = ch
        elif ch == "!":
            pieces.append((line[buf:i], True))
            pieces.append((line[i:], False))
            return pieces, ""
        i += 1
    if quote:
        pieces.append((line[buf:limit], False))
    else:
        pieces.append((line[buf:limit], True))
    if limit < len(line):
        pieces.append((line[limit:], False))
    return pieces, quote


def _rename_code(code: str, rename: dict[str, str], depth: int,
                 seen_keyword: set[str]) -> tuple[str, int]:
    out: list[str] = []
    pos = 0
    last_sig = ""
    for m in _TOKEN.finditer(code):
        between = code[pos:m.start()]
        for ch in between:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            if not ch.isspace():
                last_sig = ch
        out.append(between)
        pos = m.end()
        text = m.group(0)
        if m.lastgroup == "ident":
            upper = text.upper()
            target = rename.get(upper)
            if target is not None and last_sig != "%":
                rest = code[m.end():].lstrip()
                if depth > 0 and last_sig in ("(", ",") and rest.startswith("=") \
                        and not rest.startswith("=="):
                    seen_keyword.add(upper)
                text = target
        out.append(text)
        last_sig = "a"
    tail = code[pos:]
    for ch in tail:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
    out.append(tail)
    return "".join(out), depth


def _identifiers(lines: list[str], fixed: bool) -> set[str]:
    found: set[str] = set()
    quote = ""
    for line in lines:
        pieces, quote = _split_code(line, fixed, quote)
        for piece, is_code in pieces:
            if is_code:
                for m in _TOKEN.finditer(piece):
                    if m.lastgroup == "ident":
                        found.add(m.group(0).upper())
    return found


def rewrite_umat_interface_by_position(text: str, form: str, parsed_routine) -> PositionRewrite:
    """Rename the author's UMAT dummies to the Abaqus names by position.

    ``parsed_routine`` is the parsed ``UMAT`` routine (its ``arguments`` and
    logical lines with physical line numbers). Returns ``applied=False`` with
    an empty ``refused`` when the rule does not apply, and a non-empty
    ``refused`` when it applies but cannot be done safely.
    """
    result = PositionRewrite(text=text)
    if parsed_routine is None:
        return result
    arguments = [str(a).strip().upper() for a in parsed_routine.args]
    if len(arguments) != len(ABAQUS_UMAT_ARGUMENTS):
        return result
    if "STRESS" in arguments or "DDSDDE" in arguments:
        return result
    if len(set(arguments)) != len(arguments):
        result.refused = "the UMAT dummy argument names are not distinct"
        return result
    numbers = [n for line in parsed_routine.lines for n in line.line_numbers]
    first, last = min(numbers), max(numbers)
    fixed = form == "fixed"
    lines = text.split("\n")
    span = lines[first - 1:last]
    if any(re.match(r"^\s*\d*\s*contains\s*$", line.split("!")[0], re.IGNORECASE)
           for line in span if not fixed or line[:1] not in "cC*"):
        result.refused = "the UMAT contains internal procedures; the rename is not attempted"
        return result
    dummy_map = {a: c for a, c in zip(arguments, ABAQUS_UMAT_ARGUMENTS) if a != c}
    used = _identifiers(lines, fixed)
    clash_map: dict[str, str] = {}
    for name in sorted(_identifiers(span, fixed)):
        if name in ABAQUS_UMAT_ARGUMENTS and name not in arguments:
            new = f"{name}_USR"
            while new in used or new in clash_map.values():
                new += "_USR"
            clash_map[name] = new
    rename = {**clash_map, **dummy_map}
    seen_keyword: set[str] = set()
    out_span: list[str] = []
    quote = ""
    depth = 0
    for offset, line in enumerate(span):
        if _FORMAT_STATEMENT.match(line) and not quote:
            out_span.append(line)
            continue
        pieces, new_quote = _split_code(line, fixed, quote)
        quote = new_quote
        parts = []
        for piece, is_code in pieces:
            if is_code:
                piece, depth = _rename_code(piece, rename, depth, seen_keyword)
            parts.append(piece)
        new_line = "".join(parts)
        if fixed and len(new_line.rstrip()) > 72 and new_line.rstrip() != line.rstrip():
            result.refused = (f"renaming line {first + offset} passes column 72 in fixed form")
            return result
        out_span.append(new_line)
        if not line.rstrip().endswith("&") and not fixed:
            depth = 0
    if seen_keyword:
        result.refused = (
            "a name to be renamed is also used as a keyword argument ("
            + ", ".join(sorted(seen_keyword)) + "); the rename is ambiguous")
        return result
    lines[first - 1:last] = out_span
    result.applied = True
    result.text = "\n".join(lines)
    result.dummy_map = dummy_map
    result.clash_map = clash_map
    return result
