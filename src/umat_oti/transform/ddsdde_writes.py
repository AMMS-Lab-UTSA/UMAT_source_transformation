"""Every statement form that writes an array, not only ``NAME(...) = ...``.

The source scanner records assignments whose target is the array. Fortran has
other ways to write one, and a write the transform does not see is a write it
does not disable: matmodlab's umat_neohooke.f90 ends with

    forall(i=1:ntens,j=1:ntens,j<i) ddsdde(i,j) = ddsdde(j,i)

after the transform's OTI extraction, so the author's symmetrisation overwrote
the lower triangle of the extracted (unsymmetric) tangent -- DDSDDE(6,5) wrong
by up to 17% -- while ``old_ddsdde_assignments_disabled`` passed, because the
statement was never on its list (Vera, B1 review Q1).

:func:`array_writes` returns the statements that write ``name`` in any of these
forms; :func:`live_writes_after` asks the question the semantic check needs on
the emitted text: does any live statement after a given line write it?
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

_LABEL = re.compile(r"^\d+\s+")


def _strip_parenthesised_prefix(statement: str, keyword: str) -> str | None:
    """Text after ``KEYWORD ( ... )`` with balanced parentheses, or None."""
    match = re.match(rf"^{keyword}\s*\(", statement, re.IGNORECASE)
    if not match:
        return None
    depth = 0
    for index in range(match.end() - 1, len(statement)):
        char = statement[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return statement[index + 1:].strip()
    return None


def _assigns(statement: str, name: str) -> bool:
    return bool(re.match(rf"^{re.escape(name)}\s*(?:\([^=]*\))?\s*=(?!=)", statement, re.IGNORECASE))


def write_kind(statement: str, name: str) -> str:
    """How ``statement`` writes ``name``: "", "assignment", "forall", "where", "if", "read"."""
    text = _LABEL.sub("", statement.strip())
    if _assigns(text, name):
        return "assignment"
    for keyword, kind in (("FORALL", "forall"), ("WHERE", "where"), ("IF", "if")):
        rest = _strip_parenthesised_prefix(text, keyword)
        if rest and _assigns(rest, name):
            return kind
    if re.match(r"^READ\s*\(", text, re.IGNORECASE):
        rest = _strip_parenthesised_prefix(text, "READ") or ""
        if re.search(rf"(?<![\w%]){re.escape(name)}\b", rest, re.IGNORECASE):
            return "read"
    return ""


def array_writes(source_text: str, form: str, name: str = "DDSDDE",
                 span: tuple[int, int] | None = None) -> list[dict]:
    """Statements writing ``name``, as scanner-style rows with a ``kind``."""
    from umat_oti.fortran.parser import logical_lines_from_text

    rows = []
    for line in logical_lines_from_text(source_text, form):
        if span and not (span[0] <= line.line_numbers[0] <= span[1]):
            continue
        kind = write_kind(line.text, name)
        if kind:
            rows.append({"line_numbers": list(line.line_numbers), "text": line.text, "kind": kind})
    return rows


def missed_by_the_scanner(rows: Iterable[dict], scanner_rows: Sequence[dict]) -> list[dict]:
    """Rows whose first line no scanner row covers."""
    covered = {int(n) for row in scanner_rows if isinstance(row, dict)
               for n in row.get("line_numbers", []) if str(n).strip().isdigit()}
    return [row for row in rows if int(row["line_numbers"][0]) not in covered]


def live_writes_after(transformed_source: str, form: str, name: str, after_line: int,
                      span: tuple[int, int], *, generated_index_names=("OTI_I", "OTI_J")) -> list[dict]:
    """Live statements in ``span`` after ``after_line`` that write ``name``.

    The extraction's own statements index with the transform's loop variables
    (OTI_I, OTI_J) and are not counted.
    """
    generated = re.compile(r"\b(?:" + "|".join(generated_index_names) + r")\b", re.IGNORECASE)
    rows = []
    for row in array_writes(transformed_source, form, name, span):
        if row["line_numbers"][0] <= after_line:
            continue
        if generated.search(row["text"]):
            continue
        rows.append(row)
    return rows
