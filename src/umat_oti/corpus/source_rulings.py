"""What a source's own text says about whether it can be run, as rules.

Two readings of a published file that decide its corpus verdict before any
run does, both ruled by Vera (B10 pre-pass22, rulings b and c):

``unpublished_absolute_inputs``
    The routine OPENs a file by the AUTHOR's absolute path -- ``/work/...``,
    ``T:\\...``, ``\\\\server\\...``, ``~/...`` -- READs from it, and no file of
    that name is published in the repository. Nobody but the author can
    supply it, so the source is ``missing_material_data``: external, and out
    of the adequately-specified denominator. ``vishalsubbiah``'s SDVINI is the
    case that made the rule: it reads the three Euler angles of every
    integration point into STATEV(1-3) from ``/work/btech/mm12b035/...``.

    A file that IS published beside the source is not missing -- only its
    path is, and :mod:`umat_oti.abaqus.data_files` stages it under the literal
    name the source asks for (``Growth-Alex.for``'s ``T:\\...\\Lambda10.csv``).
    And an absolute path the routine only WRITES to (no READ on the unit and
    no ``STATUS='OLD'``) is output, not a dependency.

``visualisation_umat``
    The file defines a UEL and a UMAT that share a COMMON block; the UMAT's
    STATEV are assigned from that COMMON array, which only the UEL writes, at
    an element number offset from NOEL (``kelem = noel - nelem``). That UMAT is
    the overlay ("decoy") mesh that lets Abaqus display a UEL's state: the
    constitutive model is the UEL. Run on its own, its state outputs are
    copies of storage nothing filled, at an index that is out of range for
    any NOEL below the offset. It is ``not_a_umat``. ``irfancn`` UEL-elastic
    (deck material ``decoy``, E = 1e-11) made the rule.

Only executable statements count: comments are dropped by the logical-line
reader, so a commented-out OPEN decides nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

#: An absolute path on any machine an author might have written it on: POSIX
#: root or home, a Windows drive letter with either separator, a UNC share.
_ABSOLUTE = re.compile(r"^(?:/|~[/\\]|~$|[A-Za-z]:[\\/]|\\\\)")

_UNIT_HEADER = re.compile(
    r"^\s*(?:(?:RECURSIVE|PURE|ELEMENTAL|IMPURE|MODULE)\s+)*"
    r"(?:(?:DOUBLE\s+PRECISION|REAL|INTEGER|LOGICAL|COMPLEX|CHARACTER)"
    r"(?:\s*\*\s*\d+|\s*\([^)]*\))?\s+)?"
    r"(SUBROUTINE|FUNCTION)\s+([A-Za-z_]\w*)", re.IGNORECASE)
_END_UNIT = re.compile(r"^\s*END\s*(?:(?:SUBROUTINE|FUNCTION)\b\s*\w*)?\s*$",
                       re.IGNORECASE)
_OPEN = re.compile(r"\bOPEN\s*\((?P<body>.*)\)", re.IGNORECASE)
_FILE = re.compile(r"FILE\s*=\s*(?P<name>(?:'[^']*'|\"[^\"]*\")"
                   r"(?:\s*//\s*(?:'[^']*'|\"[^\"]*\"))*)", re.IGNORECASE)
_STATUS = re.compile(r"STATUS\s*=\s*['\"]([A-Za-z]+)['\"]", re.IGNORECASE)
_UNIT_KW = re.compile(r"\bUNIT\s*=\s*([^,)]+)", re.IGNORECASE)
_PIECE = re.compile(r"'([^']*)'|\"([^\"]*)\"")
_READ = re.compile(r"\bREAD\s*\(\s*(?:UNIT\s*=\s*)?(?P<unit>[^,)]+)[^)]*\)"
                   r"\s*(?P<targets>.*)$", re.IGNORECASE)
_COMMON = re.compile(r"\bCOMMON\s*/\s*(\w+)\s*/\s*(.*)$", re.IGNORECASE)


def is_absolute_path(name: str) -> bool:
    """Is this file name an absolute path on the author's machine?"""
    return bool(_ABSOLUTE.match((name or "").strip()))


def _basename(name: str) -> str:
    return re.split(r"[\\/]", name)[-1]


@dataclass(frozen=True)
class AbsoluteOpen:
    """One OPEN of a file by an absolute path, and what the routine reads."""

    name: str
    unit: str
    status: str
    routine: str
    line: int
    read_targets: tuple = ()
    read_line: int = 0

    @property
    def basename(self) -> str:
        return _basename(self.name)

    @property
    def is_input(self) -> bool:
        """A file the routine needs: it reads from it or demands it exist."""
        return bool(self.read_targets) or self.status == "old"

    @property
    def fills_state(self) -> bool:
        """Does it supply the initial state (SDVINI, or READ into STATEV)?"""
        return (self.routine.upper() == "SDVINI"
                or any(t.upper().startswith("STATEV") for t in self.read_targets))

    def as_dict(self) -> dict:
        return {"name": self.name, "basename": self.basename,
                "unit": self.unit, "status": self.status,
                "routine": self.routine, "line": self.line,
                "read_targets": list(self.read_targets),
                "read_line": self.read_line, "is_input": self.is_input}


@dataclass
class _Unit:
    name: str
    line: int
    lines: list = field(default_factory=list)     # (line_number, text)


def _units(text: str, form: str = "", path: Optional[Path] = None) -> list:
    """Program units as (name, [(line, logical text)]), comments removed."""
    from umat_oti.corpus.entry_routines import (detect_form_from_text,
                                                detect_source_form,
                                                logical_lines_from_text)
    if not form:
        form = (detect_source_form(path, text) if path is not None
                else detect_form_from_text(text))
    units: list = []
    current: Optional[_Unit] = None
    for logical in logical_lines_from_text(text, form):
        body = getattr(logical, "text", str(logical))
        numbers = getattr(logical, "line_numbers", ()) or ()
        number = numbers[0] if numbers else 0
        header = _UNIT_HEADER.match(body)
        if header and not body.strip().upper().startswith("END"):
            current = _Unit(name=header.group(2).upper(), line=number)
            units.append(current)
            continue
        if _END_UNIT.match(body):
            current = None
            continue
        if current is None:
            current = _Unit(name="", line=number)    # main program / loose text
            units.append(current)
        current.lines.append((number, body))
    return units


def _split_top(args: str) -> list:
    out, depth, piece = [], 0, ""
    for ch in args:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(piece.strip())
            piece = ""
        else:
            piece += ch
    if piece.strip():
        out.append(piece.strip())
    return out


def absolute_opens(text: str, form: str = "",
                   path: Optional[Path] = None) -> tuple:
    """Every OPEN of a file named by an absolute path, with what is READ."""
    found: list = []
    for unit in _units(text, form, path):
        opens: list = []
        for number, body in unit.lines:
            match = _OPEN.search(body)
            if not match:
                continue
            args = match.group("body")
            named = _FILE.search(args)
            if not named:
                continue
            name = "".join(a or b for a, b in _PIECE.findall(named.group("name")))
            if not is_absolute_path(name):
                continue
            keyword = _UNIT_KW.search(args)
            first = _split_top(args)[0] if _split_top(args) else ""
            unit_id = (keyword.group(1) if keyword
                       else ("" if "=" in first else first)).strip().upper()
            status = _STATUS.search(args)
            opens.append((number, name, unit_id,
                          status.group(1).lower() if status else ""))
        for number, name, unit_id, status in opens:
            targets: tuple = ()
            read_line = 0
            for later, body in unit.lines:
                if later < number:
                    continue
                read = _READ.search(body)
                if read and read.group("unit").strip().upper() == unit_id:
                    targets = tuple(_split_top(read.group("targets")))
                    read_line = later
                    break
            found.append(AbsoluteOpen(name=name, unit=unit_id, status=status,
                                      routine=unit.name, line=number,
                                      read_targets=targets,
                                      read_line=read_line))
    return tuple(found)


def unpublished_absolute_inputs(text: str, published: Iterable[str], *,
                                form: str = "",
                                path: Optional[Path] = None) -> tuple:
    """The absolute-path inputs whose file is not published in the repository.

    ``published`` is every file name in the source's repository (paths or base
    names); a match on the base name, ignoring case, counts as published --
    the generous direction, because staging can supply that file.
    """
    names = {_basename(str(p)).lower() for p in published}
    return tuple(o for o in absolute_opens(text, form, path)
                 if o.is_input and o.basename.lower() not in names)


def _statev_span(targets: Iterable[str]) -> str:
    idx = [m.group(1) for t in targets
           if (m := re.match(r"STATEV\s*\(\s*(\d+)\s*\)$", t, re.IGNORECASE))]
    if idx and len(idx) == len(list(targets)):
        ints = sorted(int(i) for i in idx)
        if ints == list(range(ints[0], ints[-1] + 1)) and len(ints) > 1:
            return f"STATEV({ints[0]}-{ints[-1]})"
    return ", ".join(targets)


def missing_input_reason(opens: Iterable[AbsoluteOpen]) -> str:
    """The named reason for ``missing_material_data`` from absolute inputs."""
    parts = []
    for o in opens:
        what = (f"{o.routine or 'the main program'} reads "
                f"{_statev_span(o.read_targets) or 'it'} (line {o.read_line or o.line})"
                if o.read_targets else f"STATUS='OLD' at line {o.line}")
        parts.append(f"'{o.name}' (OPEN at line {o.line}; {what})")
    opens = list(opens)
    lead = ("needs_initial_state" if any(o.fills_state for o in opens)
            else "needs_data_file")
    return (f"{lead}: the file the source reads is at the author's absolute "
            f"path and not published in the repository: " + "; ".join(parts))


# --------------------------------------------------------------------------
# visualisation UMATs
# --------------------------------------------------------------------------

def _commons(unit: _Unit) -> dict:
    """{block: [variable names in order]} declared in one unit."""
    out: dict = {}
    for _number, body in unit.lines:
        match = _COMMON.search(body)
        if match:
            names = [re.match(r"\s*(\w+)", v).group(1).upper()
                     for v in _split_top(match.group(2)) if re.match(r"\s*\w", v)]
            out.setdefault(match.group(1).upper(), []).extend(names)
    return out


def _assigned(unit: _Unit, name: str) -> list:
    rx = re.compile(rf"^\s*(?:\d+\s+)?{re.escape(name)}\s*\([^=]*\)\s*=(?!=)",
                    re.IGNORECASE)
    return [(n, b) for n, b in unit.lines if rx.match(b)]


@dataclass(frozen=True)
class VisualisationEvidence:
    """Why a file's UMAT is a display layer for its UEL."""

    block: str
    umat_array: str
    uel_array: str
    statev_line: int
    statev_text: str
    uel_write_line: int
    uel_write_text: str
    offset_line: int
    offset_text: str

    def reason(self) -> str:
        return (f"the UMAT is the visualisation layer of this file's UEL: its "
                f"STATEV are copies of COMMON /{self.block}/ "
                f"(line {self.statev_line}: {self.statev_text}), which only "
                f"the UEL fills (line {self.uel_write_line}: "
                f"{self.uel_write_text}), at an element number offset from "
                f"NOEL (line {self.offset_line}: {self.offset_text}); the "
                f"constitutive model is the UEL")[:600]


def visualisation_umat(text: str, form: str = "",
                       path: Optional[Path] = None) -> Optional[VisualisationEvidence]:
    """Evidence that the file's UMAT only displays its UEL's state, or None.

    All four must hold: (1) the file defines both UEL and UMAT; (2) they
    declare the same COMMON block; (3) the UMAT assigns STATEV from that
    block's array and never writes the array, which the UEL does write;
    (4) the array's element index in that assignment is NOEL, or a variable
    assigned from NOEL, minus an offset.
    """
    units = {u.name: u for u in _units(text, form, path) if u.name}
    umat, uel = units.get("UMAT"), units.get("UEL")
    if umat is None or uel is None:
        return None
    umat_blocks, uel_blocks = _commons(umat), _commons(uel)
    offsets = {}
    for number, body in umat.lines:
        match = re.match(r"^\s*(\w+)\s*=\s*(.*\bNOEL\b.*-.*|.*-.*\bNOEL\b.*)$",
                         body, re.IGNORECASE)
        if match:
            offsets[match.group(1).upper()] = (number, body.strip())
    for block, names in umat_blocks.items():
        partner = uel_blocks.get(block)
        if not partner:
            continue
        for position, array in enumerate(names):
            if _assigned(umat, array):
                continue                      # the UMAT writes it itself
            uel_array = partner[position] if position < len(partner) else array
            writes = _assigned(uel, uel_array)
            if not writes:
                continue
            rx = re.compile(rf"^\s*(?:\d+\s+)?STATEV\s*\([^=]*\)\s*=\s*"
                            rf"{re.escape(array)}\s*\((?P<idx>[^,)]*)",
                            re.IGNORECASE)
            for number, body in umat.lines:
                hit = rx.match(body)
                if not hit:
                    continue
                first = hit.group("idx").strip().upper()
                offset = offsets.get(first)
                if offset is None and re.search(r"\bNOEL\b", first) and "-" in first:
                    offset = (number, body.strip())
                if offset is None:
                    continue
                return VisualisationEvidence(
                    block=block, umat_array=array, uel_array=uel_array,
                    statev_line=number, statev_text=body.strip(),
                    uel_write_line=writes[0][0], uel_write_text=writes[0][1].strip(),
                    offset_line=offset[0], offset_text=offset[1])
    return None
