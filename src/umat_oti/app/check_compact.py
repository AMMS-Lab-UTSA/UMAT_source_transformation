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

__all__ = ["compact_intake", "DETAILS_HINT"]

DETAILS_HINT = ("The full list, with the lines quoted: add --details, or read "
                "intake.md in the input folder.")

#: Items whose value is a plain fact the reader wants to see at a glance when
#: it was not found in the files (so it is an assumption they may change).
_ASSUMED_KEYS = ("ntens", "element", "kinematics", "nstatv", "temperature")
_SHORT = {"ntens": "stress components", "element": "element",
          "kinematics": "small strain", "nstatv": "state variables",
          "temperature": "temperature", "quantity": "differentiate"}


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
    names = _item(found, "props_names")
    labels = []
    if names is not None and isinstance(names.value, dict):
        labels = [str(v) for _, v in sorted(names.value.items(),
                                            key=lambda kv: int(kv[0][6:-1]) if kv[0][6:-1].isdigit() else 0)]
    return [labels[i] if i < len(labels) else f"PROPS({i + 1})" for i in range(count)]


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
            else:
                assumed.append(f"{_SHORT[key]} {value.split(' (')[0]}")
    missing = _unwritten(found)
    if missing:
        assumed.append(", ".join(missing) + (" is" if len(missing) == 1 else " are")
                       + " not written in your deck, so Abaqus uses 0")
    if assumed:
        lines.append("Assumed, not stated in your files (change if wrong): " + "; ".join(assumed) + ".")
    needed = found.needs_user()
    if needed:
        lines.append("Needs you:")
        for item in needed:
            lines.append(f"  - {item.ask}")
            lines.append(f"    If you say nothing: {item.default}")
    else:
        lines.append("Needs you: nothing.")
    lines.append(DETAILS_HINT)
    return "\n".join(lines) + "\n"
