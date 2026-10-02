"""Block structure of a routine: which IF / DO / SELECT / WHERE / FORALL encloses a line.

The DDSDDE and STRESS extractions are statements the transform *inserts*, and
where it inserts them decides on which paths they run. Inserted inside a branch
they run only on that branch: czmHealing.f had both extractions emitted inside
the ELSE of ``IF (Da0.LE.0.99999)``, so an undamaged material point returned
STRESS = 0 and DDSDDE = 0 -- and every semantic check passed, because each of
them asks *whether* an extraction is there and after which line, never under
which condition (Vera, B1 review Q4).

:func:`block_spans` reads the routine's logical statements and returns every
block with its first and last physical line. :func:`hoisted_insertion_line`
moves an insertion point out of every block that encloses it, to the line that
closes the outermost one, so the inserted statements run on every path that
reaches the end of that block. A routine-level exit (RETURN, STOP) inside the
block after the insertion point means some path leaves the routine without
passing the hoisted point either; that is reported, not papered over.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

_IF_THEN = re.compile(r"^(?:[A-Za-z_]\w*\s*:\s*)?IF\s*\(.*\)\s*THEN$", re.IGNORECASE)
_ELSE = re.compile(r"^ELSE(?:\s*IF\s*\(.*\)\s*THEN)?(?:\s+[A-Za-z_]\w*)?$", re.IGNORECASE)
_END_IF = re.compile(r"^END\s*IF\b", re.IGNORECASE)
_DO_LABEL = re.compile(r"^(?:[A-Za-z_]\w*\s*:\s*)?DO\s*(\d+)\b", re.IGNORECASE)
_DO = re.compile(r"^(?:[A-Za-z_]\w*\s*:\s*)?DO(?:\s+(?:WHILE\b|CONCURRENT\b|[A-Za-z_]\w*\s*=)|\s*$|\s*,)",
                 re.IGNORECASE)
_END_DO = re.compile(r"^END\s*DO\b", re.IGNORECASE)
_SELECT = re.compile(r"^(?:[A-Za-z_]\w*\s*:\s*)?SELECT\s*(?:CASE|TYPE)\b", re.IGNORECASE)
_END_SELECT = re.compile(r"^END\s*SELECT\b", re.IGNORECASE)
_WHERE_BLOCK = re.compile(r"^WHERE\s*\(.*\)$", re.IGNORECASE)
_END_WHERE = re.compile(r"^END\s*WHERE\b", re.IGNORECASE)
_FORALL_BLOCK = re.compile(r"^FORALL\s*\(.*\)$", re.IGNORECASE)
_END_FORALL = re.compile(r"^END\s*FORALL\b", re.IGNORECASE)
_ASSOCIATE = re.compile(r"^(?:[A-Za-z_]\w*\s*:\s*)?(?:ASSOCIATE\s*\(|BLOCK$|CRITICAL$)", re.IGNORECASE)
_END_ASSOCIATE = re.compile(r"^END\s*(?:ASSOCIATE|BLOCK|CRITICAL)\b", re.IGNORECASE)
_EXIT = re.compile(r"^(?:RETURN|STOP|ERROR\s+STOP|CALL\s+XIT)\b", re.IGNORECASE)
_LABEL = re.compile(r"^(\d+)\s+(.*)$")


@dataclass(frozen=True)
class Block:
    kind: str
    start: int   # first physical line of the opening statement
    end: int     # last physical line of the closing statement


def _balanced_if_then(text: str) -> bool:
    """``IF (cond) THEN`` with the condition's parentheses balanced."""
    match = re.match(r"^(?:[A-Za-z_]\w*\s*:\s*)?IF\s*\(", text, re.IGNORECASE)
    if not match:
        return False
    depth = 0
    for index in range(match.end() - 1, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return bool(re.match(r"^\s*THEN\s*$", text[index + 1:], re.IGNORECASE))
    return False


def _statements(lines: Sequence[str], form: str, span: tuple[int, int]):
    from umat_oti.fortran.parser import logical_lines_from_text

    first, last = span
    text = "\n".join(lines[first - 1:last])
    for logical in logical_lines_from_text(text, form):
        numbers = tuple(n + first - 1 for n in logical.line_numbers)
        yield logical.text.strip(), numbers


def block_spans(lines: Sequence[str], form: str, span: tuple[int, int]) -> list[Block]:
    """Every executable block inside ``span`` (1-based, inclusive physical lines)."""
    blocks: list[Block] = []
    stack: list[tuple[str, int, Optional[str]]] = []   # kind, start line, DO label
    for text, numbers in _statements(lines, form, span):
        label = None
        labelled = _LABEL.match(text)
        if labelled:
            label, text = labelled.group(1), labelled.group(2).strip()
        else:
            # Fixed-form logical lines arrive without their label field; a
            # labelled DO's terminal statement was never seen to close it.
            raw = re.match(r"^\s*(\d+)\s", lines[numbers[0] - 1])
            label = raw.group(1) if raw else None
        first, last = numbers[0], numbers[-1]
        upper = text.upper()
        if _balanced_if_then(text):
            stack.append(("IF", first, None))
        elif _END_IF.match(upper):
            _close(stack, blocks, "IF", last)
        elif _END_DO.match(upper):
            _close(stack, blocks, "DO", last)
        elif _END_SELECT.match(upper):
            _close(stack, blocks, "SELECT", last)
        elif _END_WHERE.match(upper):
            _close(stack, blocks, "WHERE", last)
        elif _END_FORALL.match(upper):
            _close(stack, blocks, "FORALL", last)
        elif _END_ASSOCIATE.match(upper):
            _close(stack, blocks, "ASSOCIATE", last)
        elif _DO_LABEL.match(text):
            stack.append(("DO", first, _DO_LABEL.match(text).group(1)))
        elif _DO.match(text):
            stack.append(("DO", first, None))
        elif _SELECT.match(text):
            stack.append(("SELECT", first, None))
        elif _WHERE_BLOCK.match(text) and not re.search(r"\)\s*[A-Za-z_]", text):
            stack.append(("WHERE", first, None))
        elif _FORALL_BLOCK.match(text) and not re.search(r"\)\s*[A-Za-z_]", _strip_forall_header(text)):
            stack.append(("FORALL", first, None))
        elif _ASSOCIATE.match(text):
            stack.append(("ASSOCIATE", first, None))
        if label is not None:
            # A labelled statement closes every DO that names its label; nested
            # DOs may share one terminal statement.
            while stack and stack[-1][0] == "DO" and stack[-1][2] == label:
                kind, start, _ = stack.pop()
                blocks.append(Block(kind, start, last))
    return blocks


def _strip_forall_header(text: str) -> str:
    match = re.match(r"^FORALL\s*\(", text, re.IGNORECASE)
    if not match:
        return text
    depth = 0
    for index in range(match.end() - 1, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[index:]
    return text


def _close(stack, blocks, kind, last):
    for position in range(len(stack) - 1, -1, -1):
        if stack[position][0] == kind and stack[position][2] is None:
            _, start, _ = stack.pop(position)
            # Anything opened inside and never closed is dropped with it.
            del stack[position:]
            blocks.append(Block(kind, start, last))
            return


def enclosing_blocks(blocks: Sequence[Block], line: int) -> list[Block]:
    """Blocks that strictly contain ``line`` (opening < line <= closing-1)."""
    return sorted((b for b in blocks if b.start < line < b.end),
                  key=lambda b: (b.start, -b.end))


def hoisted_insertion_line(lines: Sequence[str], form: str, span: tuple[int, int],
                           insert_after: int) -> tuple[int, str]:
    """Where to insert "after ``insert_after``" so the insertion runs on every path.

    Returns ``(line, problem)``. ``line`` is ``insert_after`` when no block
    encloses it, else the closing line of the outermost enclosing block.
    ``problem`` is non-empty when the hoist cannot be made safe: a routine exit
    sits inside the hoisted-over part of the block.
    """
    if not insert_after:
        return insert_after, ""
    blocks = block_spans(lines, form, span)
    enclosing = enclosing_blocks(blocks, insert_after)
    if not enclosing:
        return insert_after, _jump_past(lines, form, span, insert_after)
    outer = enclosing[0]
    jumped = _jump_past(lines, form, span, outer.end)
    if jumped:
        return insert_after, jumped
    for text, numbers in _statements(lines, form, (insert_after + 1, outer.end)):
        body = _LABEL.match(text)
        statement = body.group(2) if body else text
        bare = re.sub(r"^IF\s*\(.*\)\s*", "", statement, flags=re.IGNORECASE)
        if _EXIT.match(statement) or _EXIT.match(bare):
            return insert_after, (
                f"the insertion point after line {insert_after} lies inside the {outer.kind} "
                f"block of lines {outer.start}-{outer.end}, and line {numbers[0]} leaves the "
                f"routine from inside that block, so no single point after the stress update "
                f"is reached on every path")
    return outer.end, ""


def depth_at(lines: Sequence[str], form: str, span: tuple[int, int], line: int) -> list[Block]:
    """The blocks enclosing physical ``line`` within ``span``."""
    return enclosing_blocks(block_spans(lines, form, span), line)


_GOTO = re.compile(r"^GO\s*TO\s*(.*)$", re.IGNORECASE)


def _jump_targets(statement: str) -> Optional[set[str]]:
    """Labels ``statement`` may transfer control to; None when it cannot be told.

    Unconditional, computed and assigned GO TO, arithmetic IF, and the
    ERR=/END=/EOR= specifiers of an I/O statement. A logical IF's action
    statement is read through.
    """
    text = statement.strip()
    while True:
        match = re.match(r"^IF\s*\(", text, re.IGNORECASE)
        if not match:
            break
        depth, index = 0, match.end() - 1
        for index in range(match.end() - 1, len(text)):
            depth += {"(": 1, ")": -1}.get(text[index], 0)
            if depth == 0:
                break
        rest = text[index + 1:].strip()
        arithmetic = re.match(r"^(\d+)\s*,\s*(\d+)\s*,\s*(\d+)$", rest)
        if arithmetic:
            return set(arithmetic.groups())
        if not rest or re.match(r"^THEN\b", rest, re.IGNORECASE):
            return set()
        text = rest
    targets = set(re.findall(r"\b(?:ERR|END|EOR)\s*=\s*(\d+)", text, re.IGNORECASE)) \
        if re.match(r"^(?:READ|WRITE|OPEN|CLOSE|INQUIRE|BACKSPACE|REWIND)\b", text, re.IGNORECASE) else set()
    goto = _GOTO.match(text)
    if not goto:
        return targets
    rest = goto.group(1).strip()
    if re.fullmatch(r"\d+", rest):
        return targets | {rest}
    listed = re.match(r"^\(([\d\s,]+)\)", rest)
    if listed:                          # computed GO TO
        return targets | {label.strip() for label in listed.group(1).split(",") if label.strip()}
    assigned = re.match(r"^[A-Za-z_]\w*\s*,?\s*\(([\d\s,]+)\)$", rest)
    if assigned:                        # assigned GO TO with its list
        return targets | {label.strip() for label in assigned.group(1).split(",") if label.strip()}
    return None                         # assigned GO TO without a list


def _jump_past(lines: Sequence[str], form: str, span: tuple[int, int], point: int) -> str:
    """Why a jump from at or before ``point`` lands after it, or "".

    A statement inserted after ``point`` runs only on the paths that pass
    it. ``IF (..) GOTO 200`` inside the hoisted-over block, to a label after
    the block, skipped the hoisted extraction altogether (Vera's t2d: primal
    relative error 1.0, DDSDDE 0 against FD ~100). Such a routine is given
    one exit instead.
    """
    labels: dict[str, int] = {}
    jumps: list[tuple[int, Optional[set[str]], str]] = []
    for text, numbers in _statements(lines, form, span):
        labelled = _LABEL.match(text)
        statement = labelled.group(2).strip() if labelled else text
        # Fixed-form logical lines arrive without their label field.
        raw = re.match(r"^\s*(\d+)\s", lines[numbers[0] - 1]) if not labelled else None
        label = labelled.group(1) if labelled else (raw.group(1) if raw else None)
        if label is not None:
            labels.setdefault(label.lstrip("0") or "0", numbers[0])
        if numbers[0] <= point:
            targets = _jump_targets(statement)
            if targets is None or targets:
                jumps.append((numbers[0], targets, statement))
    for line, targets, statement in jumps:
        if targets is None:
            return (f"line {line} transfers control to a label that cannot be read "
                    f"({statement!r}), so it may jump past the insertion point after line {point}")
        for label in targets:
            where = labels.get(label.lstrip("0") or "0")
            if where is not None and where > point:
                return (f"line {line} ({statement!r}) jumps to label {label} at line {where}, "
                        f"past the insertion point after line {point}")
    return ""
