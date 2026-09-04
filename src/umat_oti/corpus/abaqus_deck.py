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

Two keywords publish a constant vector, and this reads both. ``*Material`` /
``*User Material`` is what a UMAT is handed. ``*UEL PROPERTY`` is what a UEL
is handed, with its count and its state-variable length declared up on the
``*USER ELEMENT`` line instead of on the data keyword. Fifteen decks in the
pinned corpus -- jgomezc1/ABAQUS-US and HIT-FSW-314/abaqus -- publish their
constants *only* under ``*UEL PROPERTY``, and while this parser had no path
for that keyword every one of them read as a deck that declared no material,
so eight sources whose constants were published were filed as
``needs_material_data``. They are kept as a distinct ``kind`` rather than
folded into the material list: both are constants the author wrote down, but
provenance that called an element property vector a ``*Material`` block would
be a false citation.
"""

from __future__ import annotations

import ast
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
    """One published constant vector, as the deck declares it.

    ``kind`` says which keyword published it: ``"material"`` for a
    ``*Material`` block, ``"uel property"`` for a ``*UEL PROPERTY`` vector.
    The two are not interchangeable in a citation, so the distinction is
    carried rather than flattened.
    """

    name: str
    deck: str
    kind: str = "material"
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
            "kind": self.kind,
            "props": list(self.props),
            "nprops": len(self.props),
            "declared_constants": self.declared_constants,
            "nstatv": self.nstatv,
            "unsymmetric": self.unsymmetric,
            "orientation": self.orientation,
            "line_numbers": dict(self.line_numbers),
            "problems": list(self.problems),
            "provenance": f"read from {self.deck}, {self.citation}",
        }

    @property
    def citation(self) -> str:
        """The keyword and line this vector was read from.

        A ``*UEL PROPERTY`` vector cited as a ``*Material`` block would send a
        reviewer looking for a material definition the deck does not contain.
        """
        if self.kind == "uel property":
            head = f"*UEL PROPERTY elset={self.name or '(unnamed)'}"
            key = "uel_property"
        else:
            head = f"*Material name={self.name or '(unnamed)'}"
            key = "user_material"
        line = self.line_numbers.get(key)
        return head + (f" at line {line}" if line is not None else "")


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


#: ``<name>`` in a data line, substituted from the deck's own ``*PARAMETER``
#: block at input-processing time. A deck writing its material constants this
#: way reads as publishing none, so its source is classified as needing
#: material data that its author did in fact publish -- in the same file.
_SUBSTITUTION = re.compile(r"<\s*([A-Za-z_][A-Za-z0-9_]*)\s*>")

#: One ``name = value`` line inside a ``*PARAMETER`` block.
_PARAMETER_ASSIGNMENT = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")


def _parameter_table(lines: list[str]) -> dict[str, float]:
    """The numeric parameters a deck defines for its own substitutions.

    Abaqus accepts arithmetic here, and one parameter may be written in terms
    of another (``bulk = mu*1e2``). Those are resolved, because the value is
    the one the author wrote in the author's own file -- refusing them would
    leave a vector one constant short. They are resolved by walking a parsed
    expression tree against a fixed whitelist, never by evaluating the text:
    arithmetic on numbers and on names already in the table, and nothing else.
    A call, an attribute, a subscript or an unknown name is refused, and the
    constant it feeds stays unresolved rather than becoming a wrong number.

    Assignments are resolved by repeated passes, so order in the file does not
    matter, and a cycle simply stops making progress and is left out.

    A name assigned more than once keeps the LAST assignment, as Abaqus does.
    That matters: these decks carry a superseded value commented out above the
    live one (``**k = 0.663`` then ``k = 0.24``), and `**` is a comment, so
    only the live assignment is ever seen.
    """
    written: dict[str, str] = {}
    inside = False
    for line in lines:
        if line.lstrip().startswith("**"):
            continue
        keyword = _KEYWORD.match(line)
        if keyword is not None:
            inside = _canonical(keyword.group(1)) == "PARAMETER"
            continue
        if not inside:
            continue
        found = _PARAMETER_ASSIGNMENT.match(line)
        if found:
            written[found.group(1).upper()] = found.group(2)

    table: dict[str, float] = {}
    pending = dict(written)
    while pending:
        resolved_this_pass = False
        for name, text in list(pending.items()):
            value = _arithmetic_value(text, table)
            if value is None:
                continue
            table[name] = value
            del pending[name]
            resolved_this_pass = True
        if not resolved_this_pass:
            break
    return table


#: Every node kind the parameter evaluator will walk. Anything else -- a call,
#: an attribute, a subscript, a comparison, a comprehension -- is refused, so
#: text out of a downloaded deck can describe arithmetic and nothing more.
_ALLOWED_OPERATORS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
                      ast.FloorDiv, ast.Mod)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)


def _arithmetic_value(text: str, table: dict[str, float]) -> Optional[float]:
    """The number an assignment's right-hand side denotes, or None.

    None means "not resolvable here", never a default: the caller leaves the
    name out of the table, `_substituted` leaves ``<name>`` standing, and the
    declared-CONSTANTS check reports the short vector. A material constant
    guessed at is worse than one reported missing.
    """
    candidate = re.sub(r"(?<=[0-9.])[dD](?=[-+0-9])", "e", text.strip())
    if not candidate:
        return None
    try:
        tree = ast.parse(candidate, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None

    def walk(node: ast.AST) -> Optional[float]:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            return (float(node.value)
                    if isinstance(node.value, (int, float))
                    and not isinstance(node.value, bool) else None)
        if isinstance(node, ast.Name):
            return table.get(node.id.upper())
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
            operand = walk(node.operand)
            if operand is None:
                return None
            return +operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_OPERATORS):
            left, right = walk(node.left), walk(node.right)
            if left is None or right is None:
                return None
            try:
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    return left / right
                if isinstance(node.op, ast.FloorDiv):
                    return float(left // right)
                if isinstance(node.op, ast.Mod):
                    return float(left % right)
                # A large exponent is a denial of service on a parser that
                # reads a thousand decks, so the range is bounded rather
                # than trusted.
                if isinstance(node.op, ast.Pow):
                    if abs(right) > 64:
                        return None
                    return float(left ** right)
            except (ZeroDivisionError, OverflowError, ValueError):
                return None
        return None

    value = walk(tree)
    if value is None or value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _substituted(text: str, table: dict[str, float]) -> str:
    """``<name>`` replaced by its parameter value, where one is known.

    An unknown name is left as it stands so `_numbers` skips it, which keeps
    the count short and lets the declared-CONSTANTS check report the
    mismatch. Silently dropping it would shift every later constant one
    position left -- a whole material vector wrong, in order, with nothing to
    show for it.
    """
    if not table or "<" not in text:
        return text
    return _SUBSTITUTION.sub(
        lambda m: repr(table[m.group(1).upper()])
        if m.group(1).upper() in table else m.group(0),
        text)


def parse_deck(path: Path) -> list[DeckMaterial]:
    """Every constant vector a deck publishes, with what it declares.

    That is every ``*Material`` block and every ``*UEL PROPERTY`` vector, in
    the order the deck writes them, each tagged with the keyword it came from.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    # NOT `parameters`: the keyword loop below binds that name to each
    # card's own attributes (NAME=, CONSTANTS=), which silently emptied
    # this table through the closure on the very first keyword line.
    substitutions = _parameter_table(lines)

    materials: list[DeckMaterial] = []
    current: Optional[DeckMaterial] = None
    collecting: Optional[str] = None
    buffer: list[str] = []
    pending_orientation = ""
    # A *UEL PROPERTY line carries an ELSET and nothing else; the count of
    # values and the SVARS length are declared on the *USER ELEMENT line
    # above it. Carrying them forward is the only way to check a UEL vector
    # against a declared count the way CONSTANTS= is checked.
    #
    # Only when the deck defines exactly one user element, though. Which
    # *USER ELEMENT a *UEL PROPERTY belongs to is decided by the element type
    # of its ELSET, which this parser does not resolve, so a deck defining
    # several -- plate_with_notch.inp defines four, of two different property
    # counts -- would have had the last one's count checked against every
    # vector and reported contradictions that are not in the file. Where the
    # association is ambiguous nothing is declared, which is the honest
    # answer: the values are still read, they simply carry no declared count.
    pending_element: dict[str, str] = {}
    element_blocks = sum(
        1 for line in lines
        if not line.lstrip().startswith("**")
        and (found := _KEYWORD.match(line)) is not None
        and _canonical(found.group(1)) == "USERELEMENT")

    def flush() -> None:
        nonlocal collecting, buffer
        if current is None or collecting is None:
            collecting, buffer = None, []
            return
        text = _substituted("\n".join(buffer), substitutions)
        if collecting in ("user_material", "uel_property"):
            current.props = _numbers(text)
            declared = current.declared_constants
            if declared is not None and declared != len(current.props):
                keyword = ("CONSTANTS" if collecting == "user_material"
                           else "PROPERTIES")
                current.problems.append(
                    f"the deck declares {keyword}={declared} but "
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
        elif keyword == "USERELEMENT":
            # Remembered, not emitted: a *USER ELEMENT block on its own
            # publishes no constants, only how many are coming.
            pending_element = parameters if element_blocks == 1 else {}
        elif keyword == "UELPROPERTY":
            current = DeckMaterial(name=parameters.get("ELSET", ""),
                                   deck=str(path), kind="uel property")
            current.line_numbers["uel_property"] = number
            declared = pending_element.get("PROPERTIES", "")
            if declared.isdigit():
                current.declared_constants = int(declared)
            variables = pending_element.get("VARIABLES", "")
            if variables.isdigit():
                # A UEL's state array is sized on *USER ELEMENT, not *Depvar.
                current.nstatv = int(variables)
            materials.append(current)
            collecting = "uel_property"
        elif keyword == "USERMATERIAL" and current is not None \
                and current.kind == "material":
            current.line_numbers["user_material"] = number
            declared = parameters.get("CONSTANTS", "")
            if declared.isdigit():
                current.declared_constants = int(declared)
            current.unsymmetric = "UNSYMM" in parameters
            collecting = "user_material"
        elif keyword == "DEPVAR" and current is not None \
                and current.kind == "material":
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
