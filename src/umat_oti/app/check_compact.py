"""The compact default view of what ``umat-oti check`` read from the files.

``check`` used to print every intake item with its quoted lines (about 60
lines) before the verdict. The default view is now one short block: which
files, the constants with their values and where they came from, the loading,
what was assumed, and what is still needed from the user. The full table is
behind ``--details`` and always written to ``intake.md``.

This module only builds text from the scanner's result (``Intake`` from
``tools/intake_scan.py``); it prints nothing and runs nothing. Wiring is in
``check_command.py``: print :func:`compact_intake` instead of
``found.to_text()`` unless ``--details`` is given.
"""
from __future__ import annotations

from typing import Any

__all__ = ["compact_intake", "amber_notes", "DETAILS_HINT", "ASK_ORDER"]

DETAILS_HINT = ("The full list, with the lines quoted: add --details, or read "
                "intake.md in the input folder.")

#: Items whose value is a plain fact the reader wants to see at a glance when
#: it was not found in the files (so it is an assumption they may change).
_ASSUMED_KEYS = ("ntens", "element", "kinematics", "nstatv", "temperature")
_SHORT = {"ntens": "stress values per point", "element": "element",
          "kinematics": "small strain", "nstatv": "state variables",
          "temperature": "temperature", "quantity": "differentiate"}


#: The routine before the material: the order in which a blocking item is asked, one at a time.
ASK_ORDER = ("routine", "element", "helpers", "includes", "modules", "ntens")


def _item(found: Any, key: str):
    return next((i for i in found.items if i.key == key), None)


def _where(item) -> str:
    ev = (item.evidence or [None])[0] if item is not None else None
    if not ev:
        return ""
    return f" ({ev['file']}:{ev['line']})" if ev.get("line") else f" ({ev['file']})"


def _number(x) -> str:
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def _labels(found: Any, count: int) -> list:
    """The name of each constant by its slot number; "constant k" where the routine names none."""
    names = _item(found, "props_names")
    by_slot = {}
    if names is not None and isinstance(names.value, dict):
        for key, name in names.value.items():
            slot = key[6:-1]
            if slot.isdigit():
                by_slot[int(slot)] = str(name)
    return [by_slot.get(i + 1, f"constant {i + 1}") for i in range(count)]


def _unwritten(found: Any) -> list:
    """Names of the constants the deck does not write (Abaqus fills a short data line with 0)."""
    values = _item(found, "props_values")
    if values is None or values.value is None:
        return []
    vals = list(values.value)
    return [name for name, v in zip(_labels(found, len(vals)), vals) if v is None]


def _constants_line(found: Any) -> str:
    values = _item(found, "props_values")
    if values is None or values.value is None:
        return "Constants: not found (see below)."
    vals = list(values.value)
    pairs = [f"{name} not written (Abaqus uses 0)" if v is None else f"{name}={_number(v)}"
             for name, v in zip(_labels(found, len(vals)), vals)]
    return f"Constants ({len(vals)}): " + ", ".join(pairs) + _where(values)


def amber_notes(found: Any) -> list:
    """Amber notes: where the pipeline's own deck reader disagrees with the card-by-card reader.

    The check uses the card-by-card reader (Abaqus's own rule); the pipeline's
    reader joins the numbers of a block, so the two can differ. Said in words,
    naming the constants, so the disagreement is not only a fact in the record.
    """
    facts = getattr(found, "facts", None) or {}
    differ = facts.get("props_values_differ") or []
    if facts.get("props_values_agree_with_pipeline") is not False:
        return []
    if differ:
        labels = _labels(found, max(d["slot"] for d in differ))
    if differ and all(d["card_reader"] is None for d in differ) and not facts.get("props_values_found"):
        shown = ", ".join(f"{labels[d['slot'] - 1]} = {_number(d['pipeline_reader'])}" for d in differ[:6])
        more = f" and {len(differ) - 6} more" if len(differ) > 6 else ""
        return ["Amber note: Abaqus does not accept this constants block as written, but the pipeline's own deck reader "
                f"returns numbers for it ({shown}{more}). No constants are taken from it; they differ from what Abaqus would use."]
    if differ:
        shown = []
        for d in differ[:6]:
            card = "not written" if d["card_reader"] is None else _number(d["card_reader"])
            pipe = "not written" if d["pipeline_reader"] is None else _number(d["pipeline_reader"])
            shown.append(f"{labels[d['slot'] - 1]} (as Abaqus reads it: {card}; the pipeline's reader: {pipe})")
        more = f" and {len(differ) - 6} more" if len(differ) > 6 else ""
        return ["Amber note: the pipeline's own deck reader and the card-by-card reader (Abaqus's rule) disagree on "
                + ", ".join(shown) + more + ". This check uses the card-by-card values."]
    return ["Amber note: the pipeline's own deck reader reads this constants block differently from Abaqus; "
            "the check uses the card-by-card reading."]


def compact_intake(found: Any) -> str:
    """At most about eight lines: files, constants, loading, assumptions, needs."""
    lines = ["Files: " + found.umat + (f"  +  {found.deck}" if found.deck else "  (no deck)")]
    lines.append(_constants_line(found))
    loading = _item(found, "loading")
    if loading is not None:
        lines.append(f"Loading: {loading.value if loading.value is not None else 'not found'}"
                     + ("" if loading.status == "FOUND" else f"  [{loading.status.lower()}]"))
    assumed = []
    for key in _ASSUMED_KEYS:
        item = _item(found, key)
        if item is None or item.value is None:
            continue
        if item.status in ("DEFAULT", "INFERRED"):
            value = str(item.value)
            if key == "kinematics":
                value = "small strain" if value.startswith("no") else "finite strain"
                assumed.append(value)
            elif key == "ntens":
                assumed.append(f"{value.split(' (')[0]} stress values per point (a 3D solid has 6: three normal, three shear)")
            else:
                assumed.append(f"{_SHORT[key]} {value.split(' (')[0]}")
    missing = _unwritten(found)
    if missing:
        assumed.append(", ".join(missing) + (" is" if len(missing) == 1 else " are")
                       + " not written in your deck, so Abaqus uses 0")
    if assumed:
        lines.append("Assumed, not stated in your files (change if wrong): " + "; ".join(assumed) + ".")
    needed = found.needs_user()
    blocking = sorted([i for i in needed if i.status == "MISSING"],
                      key=lambda i: ASK_ORDER.index(i.key) if i.key in ASK_ORDER else len(ASK_ORDER))
    if blocking:
        # ONE thing at a time: the first blocking item, then a line that names what comes after it
        item = blocking[0]
        lines.append("Needs you (one thing first):")
        lines.append(f"  - {item.ask}")
        lines.append(f"    If you say nothing: {item.default}")
        later = [i.label for i in blocking[1:]]
        if later:
            lines.append("    After that I will also need: " + "; ".join(later) + ".")
    elif needed:
        lines.append("Needs you:")
        for item in needed:
            lines.append(f"  - {item.ask}")
            lines.append(f"    If you say nothing: {item.default}")
    lines.extend(amber_notes(found))
    lines.append(DETAILS_HINT)
    return "\n".join(lines) + "\n"
