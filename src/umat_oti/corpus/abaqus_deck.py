"""Read the material a source's own Abaqus deck declares.

The corpus round cannot verify a source without a material vector and a
loading history, and for most externally authored UMATs the only place either
is written down is the example deck the author shipped beside it. Until now
that meant a person read the deck and typed the numbers into a snapshot entry,
which does not scale past a handful of sources and puts a transcription step
between the upstream file and the evidence.

This reads the deck instead. It is a parser, not an inference: every value it
returns appears verbatim in the file it names, and it records where. Nothing
here fills a gap -- a deck that declares no material yields no material, and a
deck whose ``CONSTANTS=`` disagrees with the number of values that follow is
reported as the contradiction it is rather than being trimmed or padded to fit.

The Abaqus input syntax it has to survive, all of which appears in the pinned
corpus: keywords in any case and with or without an internal space
(``*USER MATERIAL`` and ``*User Material``), parameters in any order
(``CONSTANTS=160,UNSYMM``), ``**`` comment lines interleaved with data, values
continued across as many lines as the author liked, and blank lines anywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

__all__ = ["DeckMaterial", "parse_deck", "materials_in_tree"]

#: A keyword line. Abaqus ignores case and internal spacing in keywords, so
#: "*USER MATERIAL" and "*UserMaterial" are the same keyword.
_KEYWORD = re.compile(r"^\s*\*(?!\*)\s*([^,]+)(.*)$")

#: A parameter on a keyword line: NAME or NAME=VALUE.
_PARAMETER = re.compile(r"([A-Za-z_][A-Za-z0-9_ ]*)\s*(?:=\s*([^,]+))?")


def _canonical(keyword: str) -> str:
    return "".join(keyword.split()).upper()


def _parameters(remainder: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in remainder.split(","):
        part = part.strip()
        if not part:
            continue
        match = _PARAMETER.match(part)
        if match:
            found[_canonical(match.group(1))] = (match.group(2) or "").strip()
    return found


@dataclass
class DeckMaterial:
    """One ``*Material`` block, as the deck declares it."""

    name: str
    deck: str
    props: list[float] = field(default_factory=list)
    declared_constants: Optional[int] = None
    nstatv: Optional[int] = None
    unsymmetric: bool = False
    orientation: str = ""
    line_numbers: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        """Did the deck declare a count that matches the values it then gave?"""
        return not self.problems

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "deck": self.deck,
            "props": list(self.props),
            "nprops": len(self.props),
            "declared_constants": self.declared_constants,
            "nstatv": self.nstatv,
            "unsymmetric": self.unsymmetric,
            "orientation": self.orientation,
            "line_numbers": dict(self.line_numbers),
            "problems": list(self.problems),
            "provenance": (
                f"read from {self.deck}, *Material name={self.name or '(unnamed)'}"
                + (f" at line {self.line_numbers['user_material']}"
                   if "user_material" in self.line_numbers else "")),
        }


def _numbers(text: str) -> list[float]:
    values: list[float] = []
    for token in text.replace("\n", ",").split(","):
        token = token.strip()
        if not token:
            continue
        # Fortran-style exponents appear in hand-written decks.
        candidate = re.sub(r"(?<=[0-9.])[dD](?=[-+0-9])", "e", token)
        try:
            values.append(float(candidate))
        except ValueError:
            # A non-numeric token in a data line is a real problem, but it is
            # the caller's to report with context; skip it here so one stray
            # token does not discard the whole vector silently.
            continue
    return values


def parse_deck(path: Path) -> list[DeckMaterial]:
    """Every ``*Material`` block a deck defines, with what it declares."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    materials: list[DeckMaterial] = []
    current: Optional[DeckMaterial] = None
    collecting: Optional[str] = None
    buffer: list[str] = []
    pending_orientation = ""

    def flush() -> None:
        nonlocal collecting, buffer
        if current is None or collecting is None:
            collecting, buffer = None, []
            return
        text = "\n".join(buffer)
        if collecting == "user_material":
            current.props = _numbers(text)
            declared = current.declared_constants
            if declared is not None and declared != len(current.props):
                current.problems.append(
                    f"the deck declares CONSTANTS={declared} but "
                    f"{len(current.props)} values follow")
        elif collecting == "depvar":
            found = _numbers(text)
            if found:
                current.nstatv = int(found[0])
            else:
                current.problems.append("*Depvar carries no count")
        collecting, buffer = None, []

    for number, raw in enumerate(lines, start=1):
        if raw.lstrip().startswith("**"):
            continue
        match = _KEYWORD.match(raw)
        if not match:
            if collecting and raw.strip():
                buffer.append(raw)
            continue
        flush()
        keyword = _canonical(match.group(1))
        parameters = _parameters(match.group(2))

        if keyword == "MATERIAL":
            current = DeckMaterial(name=parameters.get("NAME", ""),
                                   deck=str(path),
                                   orientation=pending_orientation)
            current.line_numbers["material"] = number
            materials.append(current)
        elif keyword == "ORIENTATION":
            pending_orientation = parameters.get("NAME", "")
        elif keyword == "SOLIDSECTION" and parameters.get("ORIENTATION"):
            # A section names the orientation the material is used with; it is
            # the only place the pairing is written down.
            for material in materials:
                if material.name == parameters.get("MATERIAL", ""):
                    material.orientation = parameters["ORIENTATION"]
        elif keyword == "USERMATERIAL" and current is not None:
            current.line_numbers["user_material"] = number
            declared = parameters.get("CONSTANTS", "")
            if declared.isdigit():
                current.declared_constants = int(declared)
            current.unsymmetric = "UNSYMM" in parameters
            collecting = "user_material"
        elif keyword == "DEPVAR" and current is not None:
            current.line_numbers["depvar"] = number
            collecting = "depvar"
    flush()
    return [m for m in materials if m.props or m.nstatv is not None]


def materials_in_tree(root: Path, *, limit: int = 200) -> list[DeckMaterial]:
    """Every material declared by every deck under ``root``.

    Sorted by deck path so the result does not depend on filesystem order --
    a material vector that changes between runs because a directory was
    walked differently would be worse than none.
    """
    found: list[DeckMaterial] = []
    for deck in sorted(Path(root).rglob("*.inp"))[:limit]:
        try:
            found.extend(parse_deck(deck))
        except OSError:
            continue
    return found
