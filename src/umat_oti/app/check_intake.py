"""What ``umat-oti check`` can read for itself, before anything is run.

Pure functions over text: the UMAT's source and an Abaqus input deck. Nothing is
invented; every fact carries the file and line it came from, so the screen can
say "PROPS from my.inp line 76" and a test can check the line. Constants are
never defaulted: a value that is not in a deck, typed with ``--props`` or in a
material file is *missing*, and ``check`` says so.

This is the user-facing reader for ``check``. The corpus-wide scanner that
Ada maintains (``tools/intake_scan.py``) reads registry-scale evidence; this
reads one UMAT and one deck for one person.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eEdD][+-]?\d+)?$")

#: Fortran units that are not a UMAT, with the Abaqus kind they are.
OTHER_KINDS = (("VUMAT", "Abaqus/Explicit material (VUMAT)"),
               ("UEL", "user element (UEL)"),
               ("VUEL", "Abaqus/Explicit user element (VUEL)"),
               ("UMATHT", "user heat-transfer material (UMATHT)"),
               ("UHYPER", "hyperelastic user material (UHYPER)"))


@dataclass(frozen=True)
class Located:
    """A value with the place it was read from."""

    value: object
    file: str = ""
    line: int = 0
    last_line: int = 0
    text: str = ""

    def where(self) -> str:
        if not self.file:
            return ""
        if self.last_line and self.last_line != self.line:
            return f"{self.file} lines {self.line}-{self.last_line}"
        return f"{self.file} line {self.line}"


@dataclass
class SourceFacts:
    path: str = ""
    has_umat: bool = False
    umat_line: int = 0
    other_kind: str = ""              # what it is instead of a UMAT, when it is not one
    props_names: dict = field(default_factory=dict)    # slot -> Located(name)
    props_max: int = 0                # the highest literal PROPS(k) read
    props_dynamic: bool = False       # PROPS(expression): the count cannot be read off
    statev_max: int = 0
    statev_dynamic: bool = False
    uses_dfgrd1: bool = False         # finite strain is the deck's NLGEOM, not decided here
    modules_used: list = field(default_factory=list)
    modules_defined: list = field(default_factory=list)


@dataclass
class DeckFacts:
    path: str = ""
    materials: list = field(default_factory=list)   # (name, Located(constants), Located(depvar) | None)
    steps: list = field(default_factory=list)       # Located(step name) per *STEP
    element_types: list = field(default_factory=list)
    nlgeom: bool = False

    def user_materials(self) -> list:
        return [m for m in self.materials if m[1] is not None]


def _code_lines(text: str):
    """(number, text) of every non-comment line; Fortran comments dropped."""
    for number, line in enumerate(text.splitlines(), start=1):
        if line[:1] in "cC*!" or line.lstrip().startswith("!"):
            continue
        yield number, line


def scan_source(path: Path) -> SourceFacts:
    """What the UMAT's own text says about it: its entry, the PROPS and STATEV it uses."""
    path = Path(path)
    text = path.read_text(errors="replace")
    facts = SourceFacts(path=str(path))
    for number, line in _code_lines(text):
        code = line.split("!")[0]
        entry = re.match(r"^\s*(?:\d+\s+)?subroutine\s+(\w+)", code, re.IGNORECASE)
        if entry and entry.group(1).upper() == "UMAT" and not facts.has_umat:
            facts.has_umat, facts.umat_line = True, number
        for name, label in OTHER_KINDS:
            if entry and entry.group(1).upper() == name and not facts.other_kind:
                facts.other_kind = label
        used = re.match(r"^\s*use\s+(\w+)", code, re.IGNORECASE)
        if used and used.group(1).lower() not in ("iso_fortran_env", "iso_c_binding", "omp_lib"):
            facts.modules_used.append(used.group(1))
        defined = re.match(r"^\s*module\s+(?!procedure\b)(\w+)\s*$", code, re.IGNORECASE)
        if defined:
            facts.modules_defined.append(defined.group(1))
        if re.match(r"^\s*(?:\d+\s+)?(?:\w+\s+)?(?:real|integer|double|dimension|character)\b",
                    code, re.IGNORECASE) and "PROPS" in code.upper() and "=" not in code:
            continue                                     # a declaration, not a use
        assigned = re.match(r"^\s*(\w+)\s*=\s*PROPS\(\s*(\d+)\s*\)\s*$", code, re.IGNORECASE)
        if assigned:
            slot = int(assigned.group(2))
            facts.props_names.setdefault(slot, Located(assigned.group(1).upper(), path.name, number,
                                                       text=code.strip()))
        for ref in re.finditer(r"\bPROPS\s*\(([^()]*)\)", code, re.IGNORECASE):
            index = ref.group(1).strip()
            if index.isdigit():
                facts.props_max = max(facts.props_max, int(index))
            elif index:
                facts.props_dynamic = True
        for ref in re.finditer(r"\bSTATEV\s*\(([^()]*)\)", code, re.IGNORECASE):
            index = ref.group(1).strip()
            if index.isdigit():
                facts.statev_max = max(facts.statev_max, int(index))
            elif index:
                facts.statev_dynamic = True
        if re.search(r"\bDFGRD1\b", code, re.IGNORECASE):
            facts.uses_dfgrd1 = True
    facts.modules_used = sorted({m for m in facts.modules_used},
                                key=lambda m: m.lower())
    return facts


def _numbers(line: str) -> list:
    values = []
    for token in line.split(","):
        token = token.strip()
        if not token:
            continue
        if not _NUMBER.match(token):
            return []
        values.append(float(token.replace("d", "e").replace("D", "e")))
    return values


def scan_deck(path: Path) -> DeckFacts:
    """The facts an Abaqus input file gives: constants, DEPVAR, steps, elements, NLGEOM."""
    path = Path(path)
    facts = DeckFacts(path=str(path))
    lines = path.read_text(errors="replace").splitlines()
    material = {"name": "", "constants": None, "depvar": None}
    pending = None

    def close():
        nonlocal material
        if material["name"] or material["constants"] or material["depvar"]:
            facts.materials.append((material["name"], material["constants"], material["depvar"]))
        material = {"name": "", "constants": None, "depvar": None}

    index = 0
    while index < len(lines):
        raw = lines[index]
        number = index + 1
        index += 1
        stripped = raw.strip()
        if not stripped.startswith("*") or stripped.startswith("**"):
            continue
        keyword = stripped.split(",")[0].strip().upper()
        options = stripped.upper()
        if keyword == "*MATERIAL":
            close()
            found = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
            material["name"] = found.group(1) if found else ""
        elif keyword == "*USER MATERIAL":
            values, first, last = [], index + 1, index
            while index < len(lines) and not lines[index].strip().startswith("*"):
                got = _numbers(lines[index])
                if lines[index].strip() and got:
                    values += got
                    last = index + 1
                index += 1
            material["constants"] = Located(values, path.name, number, last,
                                            text=stripped)
        elif keyword == "*DEPVAR":
            count = 0
            if index < len(lines):
                head = lines[index].split(",")[0].strip()
                count = int(head) if head.isdigit() else 0
            material["depvar"] = Located(count, path.name, number + 1)
        elif keyword == "*STEP":
            step = re.search(r"NAME\s*=\s*([^,\s]+)", stripped, re.IGNORECASE)
            facts.steps.append(Located(step.group(1) if step else "", path.name, number))
            if re.search(r"NLGEOM\s*=\s*YES", options):
                facts.nlgeom = True
        elif keyword == "*ELEMENT":
            kind = re.search(r"TYPE\s*=\s*([A-Z0-9]+)", options)
            if kind and kind.group(1) not in facts.element_types:
                facts.element_types.append(kind.group(1))
    close()
    return facts


def contains_user_material(path: Path) -> bool:
    try:
        return bool(re.search(r"(?im)^\*USER MATERIAL", Path(path).read_text(errors="replace")))
    except OSError:
        return False


def decks_in(folder: Path, limit: int = 300) -> list:
    """Input decks in ``folder`` (not below it) that carry a *USER MATERIAL block."""
    found = sorted(p for p in Path(folder).glob("*.inp") if contains_user_material(p))
    return found[:limit]


def parse_props(text: str, names: dict, count: int) -> tuple:
    """``"E=210000 nu=0.3"`` or ``"210000 0.3"`` -> (values, notes, problems).

    ``names`` maps a PROPS slot to the name the source gives it
    (:attr:`SourceFacts.props_names`). A name is matched ignoring case, with
    the slot's own name or ``PROPS_<k>``; a bare number takes the next slot in
    order. Nothing is guessed: an unknown name or a missing slot is a problem.
    """
    by_name = {}
    for slot, located in names.items():
        by_name[str(located.value).upper()] = slot
    by_name.update({f"PROPS_{slot}": slot for slot in range(1, max(count, 1) + 1)})
    values: dict = {}
    problems: list = []
    notes: list = []
    next_slot = 1
    for token in re.split(r"[\s,;]+", text.strip()):
        if not token:
            continue
        if "=" in token:
            name, _, number = token.partition("=")
            slot = by_name.get(name.strip().upper())
            if slot is None:
                known = ", ".join(sorted({str(v.value) for v in names.values()})) or "none named in the source"
                problems.append(f"I do not know a constant called '{name}'. The source names: {known}.")
                continue
        else:
            slot, number = next_slot, token
        try:
            parsed = float(number.replace("d", "e").replace("D", "e"))
        except ValueError:
            problems.append(f"'{token}' is not a number.")
            continue
        if not math.isfinite(parsed):
            problems.append(f"'{token}' is not a finite number.")
            continue
        if slot in values:
            problems.append(f"PROPS({slot}) is given twice.")
            continue
        values[slot] = parsed
        next_slot = slot + 1
    missing = [s for s in range(1, count + 1) if s not in values]
    if missing and not problems:
        problems.append("These constants are still missing: " + ", ".join(
            f"PROPS({s})" + (f" ({names[s].value})" if s in names else "") for s in missing) + ".")
    ordered = [values[s] for s in sorted(values)]
    return (ordered if not missing else []), notes, problems


def out_back_path(peak: float, *, rise: int = 10, reverse: int = 20, ntens: int = 6) -> dict:
    """The strain path ``--peak`` stands for: uniaxial in the first component, out to
    +peak, back through zero to -peak, and unloaded to zero, in equal increments
    (a reversal exercises history in a way a monotonic test does not)."""
    if not (peak > 0 and math.isfinite(peak)):
        raise ValueError("--peak must be a positive strain, for example 0.02")
    rows = ([[peak / rise] + [0.0] * (ntens - 1)] * rise
            + [[-2.0 * peak / reverse] + [0.0] * (ntens - 1)] * reverse
            + [[peak / rise] + [0.0] * (ntens - 1)] * rise)
    return {"description": f"uniaxial strain out to +{peak:g}, back to -{peak:g}, unloaded to 0 "
                           f"({len(rows)} increments), written by umat-oti check --peak",
            "increments": rows}


def material_config(*, props: Sequence[float], nstatev: int, check_path: dict) -> dict:
    """The existing material-settings JSON the pipeline reads (small strain, NTENS 6)."""
    return {"kinematics": "small_strain", "ntens": 6, "nstatev": int(nstatev),
            "props_values": [float(v) for v in props], "check_path": check_path}


def template_material(source: SourceFacts, *, nstatev: Optional[int], peak: float = 0.02) -> dict:
    """A commented material file with the blanks the user has to fill in.

    JSON has no comments, so the comments are keys beginning with an
    underscore; ``check`` removes them (and refuses a ``null`` left in
    ``props_values``) before the pipeline sees the file.
    """
    count = source.props_max or 1
    meaning = {str(k): f"{v.value} ({v.where()})" for k, v in sorted(source.props_names.items())}
    for slot in range(1, count + 1):
        meaning.setdefault(str(slot), "(the source gives no name; see how it is used)")
    return {
        "_help": ["Fill in props_values (one number per PROPS slot, in this order), check nstatev "
                  "and the strain path, then run:",
                  "  umat-oti check YOUR_UMAT.for --material-config THIS_FILE.json",
                  "Lines starting with _ are comments and are ignored."],
        "_props_values_are": meaning,
        "_nstatev_is": ("the number of state variables (*DEPVAR in a deck). "
                        + (f"The source uses STATEV up to index {source.statev_max}."
                           if source.statev_max else "The source uses no STATEV by a literal index.")),
        "_check_path_is": ("strain increments in Voigt order 11 22 33 12 13 23 (engineering shear). "
                           "It must push the material past its elastic range if you want the "
                           "check to say anything about plasticity or damage."),
        "kinematics": "small_strain",
        "ntens": 6,
        "nstatev": nstatev if nstatev is not None else 0,
        "props_values": [None] * count,
        "check_path": out_back_path(peak),
    }


def strip_comments(settings: dict) -> dict:
    """The settings without the ``_comment`` keys the template carries."""
    return {k: v for k, v in settings.items() if not str(k).startswith("_")}
