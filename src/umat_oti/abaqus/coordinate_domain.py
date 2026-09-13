"""Where the element goes, for a UMAT whose answer depends on where it is.

Most UMATs never look at COORDS, and for those a unit cube at the origin is as
good a material point as any. A family of them does look, and for those the
unit cube is not a neutral choice -- it is a different material.

``Jeff97__.../PureGrowth.for`` caches ``COORDS(2)`` into ``STATEV(2)`` and
builds its growth tensor from it::

    Lambda1z0 = Pi/2.
    Lambda1z1 = -Pi
    DtltaG11  = (Lambda1z0 + Y*Lambda1z1 - 1.0)*(TIME(1)+DTIME)/TotalT
    G11       = 1.0 + DtltaG11

The author's plate is a millimetre thick: its nodes span ``y in [0, 0.01]``,
where ``G11`` runs from ``1 + 0.571 t`` to ``1 + 0.539 t`` -- a growth stretch
of about 1.55 at the end of the step, and ``det G = G11`` never near zero. On
a unit cube the integration points sit at ``y = 0.211`` and ``y = 0.789``, and
at the upper one ``G11 = 1 - 1.908 t``, which passes through ZERO at
``t = 0.524``. ``CalAe`` divides by ``det G``. The routine then returns values
that are not numbers, at every amplitude, and the harness reported "this
harness generated no experiment this source will run".

``Jeff97__growth-of-circular-plate/Wrinkle/*.for`` is sharper still::

    G12 = (G11-G22)*STATEV(3)*STATEV(4)/(STATEV(3)*STATEV(3)-STATEV(4)*STATEV(4))

with ``STATEV(3) = COORDS(1)`` and ``STATEV(4) = COORDS(2)``. The denominator
is ``x^2 - y^2``, which vanishes on the diagonals -- and four of the eight
integration points of a unit cube sit exactly on ``x = y``. Six sources, six
verdicts of "the model produced no numbers at any amplitude from 8e-07 to 1".
The amplitude was never the variable.

So two rules, each measured on one of those repositories:

**Stand where the author stood.** The verification element is one element of
the author's own mesh, with the author's own node coordinates, reduced to its
corner nodes. Nothing about its position is chosen by this harness.

**Among the author's elements, choose one the routine's own arithmetic is
defined at.** Every denominator the source builds out of its cached
coordinates is evaluated at the candidate element's integration points, and
the element that keeps them furthest from zero is the one used.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

_KEYWORD = re.compile(r"^\s*\*(?!\*)\s*([^,\n]+)(.*)$")
_PARAMETER = re.compile(r"([A-Za-z][\w \-]*)\s*=\s*([^,]+)")
_COMMENT = re.compile(r"^[cC*!]")

#: How many leading nodes of a connectivity are the corners of the element.
#: A higher-order element's midside nodes add no material point a comparison
#: needs, and the first-order sibling this harness runs takes the corners.
_CORNERS: dict[str, int] = {
    "C3D8": 8, "C3D8H": 8, "C3D8R": 8, "C3D8I": 8,
    "C3D20": 8, "C3D20H": 8, "C3D20R": 8, "C3D20RH": 8,
    "C3D4": 4, "C3D4H": 4, "C3D10": 4, "C3D10H": 4, "C3D10M": 4,
    "C3D6": 6, "C3D6H": 6, "C3D15": 6,
    "CPE4": 4, "CPE4H": 4, "CPE4R": 4, "CPE8": 4, "CPE8R": 4, "CPE8H": 4,
    "CPS4": 4, "CPS4R": 4, "CPS8": 4, "CPS8R": 4,
    "CAX4": 4, "CAX4H": 4, "CAX4R": 4, "CAX8": 4, "CAX8R": 4,
    "CPE3": 3, "CPS3": 3, "CAX3": 3,
    "COH3D8": 8, "COH3D8T": 8, "COH2D4": 4, "COH2D4T": 4, "COH3D6": 6,
    "S4": 4, "S4R": 4, "S8R": 4, "S3": 3, "S3R": 3,
    # Coupled temperature-displacement, piezoelectric, pore-pressure and
    # incompatible-mode variants. Each is the same geometry as the sibling
    # above it and differs only in the degrees of freedom its nodes carry, so
    # the corner count is the sibling's. They are listed because the corpus
    # publishes them: C3D8IH is what both refused Jeff97 growth-of-shell decks
    # declare, and leaving it out refused two entries that verify, for a
    # missing table row rather than anything about the material.
    "C3D8I": 8, "C3D8IH": 8, "C3D8RH": 8,
    "C3D8T": 8, "C3D8RT": 8, "C3D8E": 8, "EC3D8RT": 8,
    "C3D20T": 8, "C3D20E": 8, "C3D20P": 8,
    "C3D4T": 4, "C3D10HS": 4,
    "CPE4I": 4, "CPE4T": 4, "CPE4RT": 4, "CPE8T": 4, "CPE3T": 3,
    "CPS3T": 3, "CPS6": 3,
    "CAX4T": 4, "CAX4RT": 4, "CAX3T": 3,
    # Generalised plane strain: four corners in the plane, and the two
    # reference nodes that carry the thickness change are not corners.
    "CPEG3": 3, "CPEG4": 4, "CPEG4H": 4, "CPEG4R": 4, "CPEG8": 4,
    "CPEG8H": 4, "CPEG8R": 4,
}


# ---------------------------------------------------------------------------
# what the source does with the coordinates it is handed
# ---------------------------------------------------------------------------
#: A statement that names variables rather than using them.
_DECLARATION = re.compile(
    r"^(DOUBLE\s*PRECISION|REAL|INTEGER|DIMENSION|COMMON|PARAMETER|CHARACTER"
    r"|LOGICAL|IMPLICIT|SUBROUTINE|FUNCTION|INCLUDE|DATA|SAVE|EXTERNAL)\b",
    re.IGNORECASE)

_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_]\w*(?:\s*\([^)]*\))?)\s*=\s*(.+?)\s*$")
_COORDS = re.compile(r"^COORDS\s*\(\s*([123])\s*\)$", re.IGNORECASE)


def _lvalue(text: str) -> str:
    """A name a value can be stored under, normalised so it can be matched.

    ``STATEV(3)`` keeps its literal subscript because that is what makes it a
    distinct slot. ``ReadX(NOEL,NPT)`` loses its subscripts, because the whole
    array holds the same axis whatever element and point it is indexed by.
    """
    text = "".join(str(text or "").split()).upper()
    match = re.match(r"^([A-Za-z_]\w*)\((\d+)\)$", text)
    if match:
        return f"{match.group(1)}({match.group(2)})"
    match = re.match(r"^([A-Za-z_]\w*)(\(.*\))?$", text)
    return match.group(1) if match else text


def _code_lines(text: str) -> Iterable[str]:
    for line in (text or "").splitlines():
        if not line.strip() or _COMMENT.match(line) or line.lstrip().startswith("!"):
            continue
        yield line.split("!")[0]


def statements(text: str) -> list[str]:
    """Logical Fortran statements, with continuation lines joined onto them.

    Reading a source line by line loses the half of a statement that matters.
    ``PureGrowth.for`` writes::

        DtltaG11 = (Lambda1z0 + Y*Lambda1z1-1.0)
     &              *(TIME(1)+DTIME)/TotalT

    and a line-by-line scan for "computed from TIME" finds nothing on the
    first line and no assignment on the second. Worse, the circular-plate
    sources put the whole of the singular divisor on a continuation::

        G12=(G11-G22)*STATEV(3)*STATEV(4)/
     &      (STATEV(3)*STATEV(3)-STATEV(4)*STATEV(4))

    so a scan that stops at the newline sees a division by nothing.

    Both forms of continuation: fixed-form, where column six carries any
    character but a blank or a zero, and free-form, where the line before ends
    with an ampersand or this one begins with one.
    """
    out: list[str] = []
    for raw in _code_lines(text):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        fixed = (len(line) > 5 and line[:5].strip() == ""
                 and line[5] not in (" ", "0", "\t"))
        free = stripped.startswith("&")
        if out and (fixed or free):
            body = line[6:] if fixed else stripped[1:]
            out[-1] = out[-1].rstrip() + " " + body.strip()
            continue
        if out and out[-1].rstrip().endswith("&"):
            out[-1] = out[-1].rstrip()[:-1] + " " + stripped
            continue
        out.append(line)
    return out


def coordinate_aliases(source_text: str) -> dict[str, int]:
    """Every name this routine stores a COORDS component in, and which axis.

    Traced to a fixed point through simple copies, because these routines cache
    the point's original position on the first call and read it back from state
    for the rest of the analysis::

        IF (STATEV(2) .EQ. 0) STATEV(2)=COORDS(2)
        ...
        Y = STATEV(2)

    Only whole-value copies are followed. ``Y = 2*COORDS(2)`` is not an alias
    for the coordinate and is not treated as one.
    """
    aliases: dict[str, int] = {}
    lines = statements(source_text)
    for _round in range(4):
        before = len(aliases)
        for line in lines:
            found = _ASSIGNMENT.match(line)
            if not found:
                continue
            target = _lvalue(found.group(1))
            source = "".join(found.group(2).split()).upper()
            direct = _COORDS.match(source)
            if direct:
                aliases.setdefault(target, int(direct.group(1)) - 1)
                continue
            copied = aliases.get(_lvalue(source))
            if copied is not None:
                aliases.setdefault(target, copied)
        if len(aliases) == before:
            break
    return aliases


_INTRINSICS = {"SQRT": "math.sqrt", "ABS": "abs", "DABS": "abs",
               "COS": "math.cos", "SIN": "math.sin", "TAN": "math.tan",
               "EXP": "math.exp", "LOG": "math.log", "DLOG": "math.log",
               "DSQRT": "math.sqrt", "DCOS": "math.cos", "DSIN": "math.sin",
               "MAX": "max", "MIN": "min"}


def _balanced(text: str, start: int) -> int:
    """Index just past the parenthesis group that opens at ``start``."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return -1


def denominator_texts(source_text: str, aliases: dict) -> tuple[str, ...]:
    """Every divisor this routine builds out of a coordinate it cached.

    Only parenthesised divisors and bare names are taken, and only those that
    mention at least one alias. A divisor that has nothing to do with position
    says nothing about where the element should go.
    """
    wanted = {name for name in aliases}
    found: list[str] = []
    for line in statements(source_text):
        # A declaration is not arithmetic. ``COMMON /DLoadUSER/ ReadX(...)``
        # puts a slash on either side of the block name, and reading the
        # second one as a division made ``ReadX`` -- a cached coordinate --
        # look like a divisor the element had to stay away from.
        if _DECLARATION.match(line.strip()):
            continue
        text = "".join(line.split()).upper()
        index = 0
        while True:
            index = text.find("/", index)
            if index < 0:
                break
            index += 1
            if index < len(text) and text[index] == "(":
                end = _balanced(text, index)
                if end < 0:
                    break
                expression = text[index:end]
                index = end
            else:
                match = re.match(r"[A-Za-z_]\w*(\(\d+\))?", text[index:])
                if not match:
                    continue
                expression = match.group(0)
                index += len(expression)
            names = set(re.findall(r"[A-Za-z_]\w*(?:\(\d+\))?", expression))
            if names & wanted and expression not in found:
                found.append(expression)
    return tuple(found)


def compile_denominator(expression: str, aliases: dict) -> Optional[Callable]:
    """A Python callable for a Fortran divisor, or None when it cannot be one.

    Refuses rather than guesses. An expression mentioning a quantity this
    module cannot resolve to a coordinate or a number is not evaluated at all,
    because a wrong value here would place the element somewhere the routine
    is undefined while claiming it had been checked.
    """
    text = expression.upper()
    text = re.sub(r"(\d)[DE]([-+]?\d+)", r"\1e\2", text)
    text = text.replace("**", "^")
    tokens = re.findall(r"[A-Za-z_]\w*(?:\(\d+\))?", text)
    pieces: list[str] = []
    last = 0
    for match in re.finditer(r"[A-Za-z_]\w*(?:\(\d+\))?", text):
        pieces.append(text[last:match.start()])
        name = match.group(0)
        axis = aliases.get(_lvalue(name))
        if axis is not None:
            pieces.append(f"p[{axis}]")
        elif name in _INTRINSICS:
            pieces.append(_INTRINSICS[name])
        else:
            return None
        last = match.end()
    pieces.append(text[last:])
    python = "".join(pieces).replace("^", "**")
    try:
        code = compile(python, "<denominator>", "eval")
    except SyntaxError:
        return None

    def evaluate(p, _code=code):
        try:
            return float(eval(_code, {"math": math, "abs": abs,
                                      "max": max, "min": min}, {"p": p}))
        except Exception:                          # noqa: BLE001
            return float("nan")

    return evaluate


# ---------------------------------------------------------------------------
# the author's own mesh
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AuthorElement:
    """One element of the author's deck, reduced to its corner coordinates."""

    number: int
    element_type: str
    nodes: tuple[tuple[int, float, float, float], ...]

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def centroid(self) -> tuple[float, float, float]:
        count = float(len(self.nodes)) or 1.0
        return tuple(sum(node[axis + 1] for node in self.nodes) / count
                     for axis in range(3))

    def sample_points(self) -> tuple[tuple[float, float, float], ...]:
        """Where the material points of this element sit.

        The corners and the centroid, plus -- for an eight-node hexahedron --
        the eight 2x2x2 Gauss points, because those are the positions the UMAT
        is actually called at and the positions a denominator has to be
        defined at. A corner is included too: a routine evaluated near a
        singularity is badly conditioned even when the Gauss point misses it.
        """
        points = [(node[1], node[2], node[3]) for node in self.nodes]
        points.append(self.centroid)
        if len(self.nodes) == 8:
            g = 1.0 / math.sqrt(3.0)
            corners = [(node[1], node[2], node[3]) for node in self.nodes]
            for xi in (-g, g):
                for eta in (-g, g):
                    for zeta in (-g, g):
                        weights = (
                            (1 - xi) * (1 - eta) * (1 - zeta),
                            (1 + xi) * (1 - eta) * (1 - zeta),
                            (1 + xi) * (1 + eta) * (1 - zeta),
                            (1 - xi) * (1 + eta) * (1 - zeta),
                            (1 - xi) * (1 - eta) * (1 + zeta),
                            (1 + xi) * (1 - eta) * (1 + zeta),
                            (1 + xi) * (1 + eta) * (1 + zeta),
                            (1 - xi) * (1 + eta) * (1 + zeta),
                        )
                        points.append(tuple(
                            sum(w * corner[axis] for w, corner
                                in zip(weights, corners)) / 8.0
                            for axis in range(3)))
        return tuple(points)

    def as_dict(self) -> dict:
        return {"number": self.number, "element_type": self.element_type,
                "nodes": [list(node) for node in self.nodes]}


def _parameters(remainder: str) -> dict:
    return {name.strip().upper().replace(" ", ""): value.strip()
            for name, value in _PARAMETER.findall(remainder or "")}


def read_mesh(deck_text: str, wanted_types: Sequence[str] = (),
              limit: int = 400000) -> tuple[dict, list]:
    """The nodes and elements a deck declares, as written.

    Coordinates are the author's. Nothing is scaled, recentred or normalised:
    a routine that reads COORDS reads whatever number the deck put there, and
    a harness that moved it would be running a different material.
    """
    nodes: dict[int, tuple[float, float, float]] = {}
    elements: list[tuple[int, str, tuple[int, ...]]] = []
    wanted = {kind.upper() for kind in wanted_types}
    mode = ""
    current_type = ""
    pending: list[int] = []
    pending_number = 0

    def close_element() -> None:
        nonlocal pending, pending_number
        if pending_number and pending:
            elements.append((pending_number, current_type, tuple(pending)))
        pending, pending_number = [], 0

    for raw in deck_text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("**"):
            continue
        found = _KEYWORD.match(line)
        if found:
            close_element()
            keyword = "".join(found.group(1).split()).upper()
            parameters = _parameters(found.group(2))
            if keyword == "NODE":
                mode = "node"
            elif keyword == "ELEMENT":
                current_type = parameters.get("TYPE", "").upper()
                mode = "element" if (not wanted or current_type in wanted) else ""
            else:
                mode = ""
            continue
        if mode == "node":
            pieces = [piece.strip() for piece in line.split(",")]
            if len(pieces) >= 3 and pieces[0].lstrip("-").isdigit():
                try:
                    nodes[int(pieces[0])] = (
                        float(pieces[1]), float(pieces[2]),
                        float(pieces[3]) if len(pieces) > 3 and pieces[3] else 0.0)
                except ValueError:
                    continue
            if len(nodes) > limit:                 # pragma: no cover - guard
                mode = ""
        elif mode == "element":
            pieces = [piece.strip() for piece in line.split(",") if piece.strip()]
            numbers = [int(piece) for piece in pieces if piece.lstrip("-").isdigit()]
            if not numbers:
                continue
            if not pending_number:
                pending_number, pending = numbers[0], list(numbers[1:])
            else:
                pending.extend(numbers)
            if not line.rstrip().endswith(","):
                close_element()
            if len(elements) > limit:              # pragma: no cover - guard
                mode = ""
    close_element()
    return nodes, elements


def author_elements(deck_text: str, wanted_types: Sequence[str] = (),
                    most: int = 4000) -> tuple[AuthorElement, ...]:
    """The author's elements, reduced to corner nodes with real coordinates."""
    nodes, elements = read_mesh(deck_text, wanted_types)
    out: list[AuthorElement] = []
    for number, kind, connectivity in elements:
        corners = _CORNERS.get(kind.upper())
        if corners is None or len(connectivity) < corners:
            continue
        placed = []
        for node_id in connectivity[:corners]:
            position = nodes.get(node_id)
            if position is None:
                placed = []
                break
            placed.append((node_id, *position))
        if placed:
            out.append(AuthorElement(number, kind.upper(), tuple(placed)))
        if len(out) >= most:
            break
    return tuple(out)


# ---------------------------------------------------------------------------
# choosing where to stand
# ---------------------------------------------------------------------------
#: How far from zero a coordinate-built divisor has to stay, as a fraction of
#: the largest value that divisor takes anywhere in the author's own mesh.
#:
#: A tenth. Not a tolerance on an answer: a floor on conditioning. On
#: ``l1-is-1--l2-is-101.for`` the divisor is ``x^2 - y^2`` over a disc of
#: radius one, so its scale is 1 and this asks for ``|x^2 - y^2| >= 0.1`` --
#: satisfied on most of the disc and violated on the two diagonals, which is
#: exactly the distinction that matters. The unit cube this harness used to
#: emit scores 0.
SAFE_FRACTION = 0.1


@dataclass(frozen=True)
class Placement:
    """Where the verification element sits, and what decided it."""

    element: Optional[AuthorElement] = None
    aliases: dict = field(default_factory=dict)
    denominators: tuple[str, ...] = ()
    margin: float = 0.0
    reason: str = ""
    refusal: str = ""

    @property
    def found(self) -> bool:
        return self.element is not None

    @property
    def coordinate_dependent(self) -> bool:
        """Does this source's answer depend on where the element is at all?"""
        return bool(self.aliases)

    def as_dict(self) -> dict:
        return {"element": self.element.as_dict() if self.element else None,
                "aliases": dict(self.aliases),
                "denominators": list(self.denominators),
                "margin": self.margin, "reason": self.reason,
                "refusal": self.refusal}


def reads_coordinates(source_text: str) -> bool:
    """Does this routine look at where its material point is?"""
    return bool(re.search(r"\bCOORDS\s*\(", source_text or "", re.IGNORECASE))


def place(source_text: str, deck_text: str,
          wanted_types: Sequence[str] = (),
          floor: float = SAFE_FRACTION) -> Placement:
    """One element of the author's mesh, chosen so the routine is defined on it.

    Returns a refusal rather than a compromise when every element of the
    author's own mesh sits too close to a singularity of the routine's own
    arithmetic: that would be the model saying something about itself, and it
    is worth reporting rather than papering over.
    """
    aliases = coordinate_aliases(source_text)
    candidates = author_elements(deck_text, wanted_types)
    if not candidates:
        return Placement(
            aliases=aliases,
            refusal=("the author's deck declares no element of a type whose "
                     "corners this harness knows how to read, so there is no "
                     "position of the author's to stand at"))
    if not aliases:
        best = candidates[len(candidates) // 2]
        return Placement(
            element=best, aliases={},
            reason=("this routine never reads COORDS, so where the element "
                    "sits cannot change what it computes; one element of the "
                    "author's own mesh is used so the geometry is still the "
                    "author's"))

    texts = denominator_texts(source_text, aliases)
    checks: list[tuple[str, Callable]] = []
    unreadable: list[str] = []
    for text in texts:
        compiled = compile_denominator(text, aliases)
        if compiled is None:
            unreadable.append(text)
        else:
            checks.append((text, compiled))
    if not checks:
        best = candidates[len(candidates) // 2]
        axes = ", ".join(f"{name}=COORDS({axis + 1})"
                         for name, axis in sorted(aliases.items()))
        return Placement(
            element=best, aliases=aliases, denominators=texts,
            reason=(f"this routine caches its point's position ({axes}) and "
                    f"builds no divisor out of it that this module can "
                    f"evaluate, so one element of the author's own mesh is "
                    f"used and its coordinates are the author's"
                    + (f"; not evaluated: {', '.join(unreadable[:3])}"
                       if unreadable else "")))

    # The scale of each divisor is the largest value it takes anywhere in the
    # author's mesh. Relative, because "x^2 - y^2 >= 0.1" means one thing on a
    # disc of radius one and another on a plate a millimetre thick.
    scales: list[float] = []
    for _text, check in checks:
        biggest = 0.0
        for element in candidates:
            for point in element.sample_points():
                value = abs(check(point))
                if math.isfinite(value) and value > biggest:
                    biggest = value
        scales.append(biggest or 1.0)

    best_element: Optional[AuthorElement] = None
    best_margin = -1.0
    for element in candidates:
        margin = float("inf")
        for (_text, check), scale in zip(checks, scales):
            for point in element.sample_points():
                value = abs(check(point))
                if not math.isfinite(value):
                    margin = -1.0
                    break
                margin = min(margin, value / scale)
            if margin < 0:
                break
        if margin > best_margin:
            best_margin, best_element = margin, element

    named = ", ".join(text for text, _ in checks[:3])
    if best_element is None or best_margin < floor:
        return Placement(
            aliases=aliases, denominators=texts, margin=max(best_margin, 0.0),
            refusal=(f"this routine divides by {named}, built from the "
                     f"coordinates it caches, and no element of the author's "
                     f"own mesh keeps that divisor above {floor:.0%} of its "
                     f"own range -- the best is {max(best_margin, 0.0):.1%}. "
                     f"A verification run there would be measuring the "
                     f"conditioning of a division, not the material"))
    return Placement(
        element=best_element, aliases=aliases, denominators=texts,
        margin=best_margin,
        reason=(f"this routine divides by {named}, built from the coordinates "
                f"it caches; element {best_element.number} of the author's own "
                f"mesh keeps every such divisor at or above "
                f"{best_margin:.0%} of its range over the whole mesh, which is "
                f"the largest margin any of the author's elements offers"))


# ---------------------------------------------------------------------------
# does this deck's mesh have the shape the source hard-codes?
# ---------------------------------------------------------------------------
#: ``name = number``, and ``name = number op number``. The second form is not
#: decoration: ``Experiment-DRAGONSKIN20-Flat/Th01/PureGrowth.for`` writes
#: ``h = 0.1/20.0`` and ``L = 1.0/10.0``, so reading only bare literals said
#: that source declared no geometry at all -- and it declares a plate a tenth
#: as long as every other one in its repository.
_SCALAR = re.compile(
    r"^\s*(?:\d+\s+)?([A-Za-z_]\w*)\s*=\s*"
    r"([-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?"
    r"(?:\s*[*/]\s*[-+]?\d+(?:\.\d*)?(?:[EeDd][-+]?\d+)?)?)"
    r"\s*(?:!.*)?$")


def _literal(text: str) -> Optional[float]:
    """A number, or a product or quotient of two, as an author writes one."""
    body = str(text or "").replace("D", "E").replace("d", "e")
    try:
        return float(body)
    except ValueError:
        pass
    for operator, apply in (("/", lambda a, b: a / b if b else None),
                            ("*", lambda a, b: a * b)):
        if operator in body:
            left, _, right = body.partition(operator)
            try:
                return apply(float(left), float(right))
            except (ValueError, ZeroDivisionError):
                return None
    return None


def declared_lengths(source_text: str,
                     only_positional: bool = False) -> dict[str, float]:
    """Scalar constants a routine assigns to itself, which may be lengths.

    Every scalar is taken, not only the ones that look like lengths, because
    the ones that look like lengths are the ones an author happened to call
    ``h`` or ``L``. A constant that coincidentally equals a mesh extent -- and
    ``DetF = 1.0`` beside a beam of length one does -- matches EVERY candidate
    equally and so discriminates between none of them; the constant that
    matches one deck and not its siblings is the one that decides. Passing
    ``only_positional`` narrows the set to constants the routine uses in the
    same statement as a cached coordinate, which is stricter and, on
    ``PureGrowth.for`` -- whose ``h`` is assigned and never used -- too strict.

    ``Jeff97__.../Th001/PureGrowth.for`` says::

        h = 0.005 ! m (total thickness = 2h)
        L = 1.0 ! length of the beam

    and its deck's nodes span ``x in [0, 1]`` and ``y in [0, 0.01]``. Its
    sibling in ``Th01`` says ``h = 0.05`` for the same ``L``. Those numbers are
    the author stating which mesh the routine belongs on, in the routine, and
    they separate five decks this harness could otherwise not tell apart.
    """
    found: dict[str, float] = {}
    lines = statements(source_text)
    for line in lines:
        match = _SCALAR.match(line)
        if not match:
            continue
        value = _literal(match.group(2))
        if value is not None and value > 0.0:
            found[match.group(1).upper()] = value
    if not only_positional:
        return found
    # A constant is a LENGTH of the author's geometry only if the routine uses
    # it alongside a position. ``DetF = 1.0`` is assigned in every one of these
    # sources and would otherwise match any mesh whose span happens to be one;
    # ``h`` and ``L`` appear in the same statements as the cached X and Y.
    aliases = set(coordinate_aliases(source_text))
    if not aliases:
        return found
    positional: dict[str, float] = {}
    declaring = False
    for line in lines:
        stripped = line.strip().upper()
        continued = line[:1] in " \t" and (
            line[5:6] not in (" ", "") or stripped.startswith("&"))
        if _DECLARATION.match(stripped):
            declaring = True
            continue
        if declaring and continued:
            # A continuation of a declaration lists names beside one another
            # without using them together, and reading it as use would make
            # every name in the routine positional.
            continue
        declaring = False
        names = {_lvalue(name) for name
                 in re.findall(r"[A-Za-z_]\w*(?:\(\d+\))?", line.upper())}
        if not (names & aliases):
            continue
        for name in names:
            if name in found and name not in aliases:
                positional[name] = found[name]
    return positional or found


def node_box(deck_text: str) -> tuple[tuple[float, float], ...]:
    """The box the author's nodes occupy, per axis."""
    nodes, _elements = read_mesh(deck_text)
    if not nodes:
        return ()
    axes = list(zip(*nodes.values()))
    return tuple((min(axis), max(axis)) for axis in axes)


def geometry_agreement(source_text: str, deck_text: str,
                       tolerance: float = 2e-3) -> tuple[int, str]:
    """How many of this mesh's extents the source's own constants account for.

    A score and a sentence, not a verdict. A routine that hard-codes ``h`` and
    ``L`` and is run on a mesh whose spans are neither is being run on
    somebody else's geometry, and for a routine that reads COORDS that is a
    different material. Both ``c`` and ``2c`` count, because a half-thickness
    is as common a way to write it as a thickness.
    """
    box = node_box(deck_text)
    constants = declared_lengths(source_text)
    if not box or not constants:
        return 0, ""
    matched: list[str] = []
    for axis, (low, high) in enumerate(box):
        span = high - low
        if span <= 0.0:
            continue
        for name, value in sorted(constants.items()):
            for factor, how in ((1.0, ""), (2.0, "2*")):
                if abs(span - factor * value) <= tolerance * max(
                        span, factor * value):
                    matched.append(f"axis {axis + 1} spans {span:g} = "
                                   f"{how}{name}")
                    break
            else:
                continue
            break
    if not matched:
        return 0, (f"none of this mesh's extents ("
                   + ", ".join(f"{high - low:g}" for low, high in box)
                   + ") is a constant this routine assigns ("
                   + ", ".join(f"{name}={value:g}"
                               for name, value in sorted(constants.items())[:6])
                   + ")")
    return len(matched), "; ".join(matched)
