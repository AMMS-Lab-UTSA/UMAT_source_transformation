"""What a routine's own literal constants make of the expressions it writes.

A source can be growth-SHAPED and compute no growth. ``PureGravity.for`` in
Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces
builds a growth tensor out of the clock in the ordinary way::

    Lambda1z0 = 1.0
    Lambda1z1 = 0.0
    DtltaG11  = (Lambda1z0 + Y*Lambda1z1 - 1.0)*(TIME(1)+DTIME)/TotalT
    G11       = 1.0 + DtltaG11
    STATEV(8) = G11

and every one of those statements reads as growth to a scan that matches on
shape. It is not growth. With ``Lambda1z0 = 1`` and ``Lambda1z1 = 0`` the
increment is ``(1 + Y*0 - 1)*clock = 0`` for every Y and every time, so G is
the identity for the whole analysis and STATEV(8) is 1.0 by construction. The
author switched the growth off on purpose: the file is named PureGravity and
its deformation comes from the body force its own ``SUBROUTINE DLOAD``
computes.

The general statement, which is what this module implements: **a quantity
whose value does not depend on the clock is not computed from the clock,
however clock-shaped the statement that assigns it.** Deciding that needs
constant propagation over the routine's literal assignments, and two
properties of the abstract arithmetic:

*Annihilation.* ``Y*Lambda1z1`` is zero for an unknown Y once Lambda1z1 folds
to zero. Without that rule nothing here is decidable, because Y is a
coordinate read out of STATEV and is unknown by construction. Every real
constant propagator has this rule; it is why a compiler deletes the
multiplication rather than emitting it.

*Unknown is the safe answer.* The analysis concludes "constant" or
"undecided", never "varies". A name it cannot resolve poisons every expression
it reaches, so a genuine growth law whose coefficients this cannot evaluate
stays a genuine growth law. That direction matters: in the same repository the
sibling ``HelixUp/.../PureGravity.for`` -- the same filename, the same
variables, the same statements -- writes ``Lambda1z0 = (3*Sqrt(1 +
16*Pi**2*X**4))/5.`` against the point's coordinate X, which this cannot
evaluate and does not try to. Two of those reached ``verified`` in the pass10
corpus run. A rule keyed on the filename, or on the names Lambda1z0 and
DtltaG11, would have taken a verified growth entry out of the growth family.

What makes the analysis sound enough to act on:

* Each routine is folded on its own. A name is a local unless the header
  declares it a dummy argument, and a dummy argument is never constant: its
  value comes from the caller. Folding the file as one namespace let a literal
  in one routine decide an expression in another.
* Assignments are read in order, and an expression sees only the bindings
  fixed by statements ABOVE it. That is the dataflow of straight-line code,
  and it is why ``TotalT = 1.0`` two lines above its use is usable while an
  assignment below it is not.
* An assignment inside an IF or a DO poisons its target from that point on.
  A conditional assignment may not execute, and a loop may execute it many
  times; neither yields a value this can name.
* ``GOTO`` is recorded, not assumed away. A backward jump can re-enter a
  region this read as straight-line, so :attr:`Folding.jumps` carries the
  count and a caller that wants certainty can refuse to act on a routine that
  has any. Measured over the 1933 corpus proposals, no entry whose family this
  analysis changes contains one.

The one arithmetic assumption is that a value this cannot resolve is finite:
``0 * x`` is 0 in IEEE arithmetic unless x is a NaN or an infinity, in which
case it is a NaN. A constitutive routine that has already produced a NaN in
its growth coefficient has a larger problem than its classification.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from umat_oti.abaqus.coordinate_domain import statements
from umat_oti.corpus.entry_routines import INTERFACES, program_units

#: The routines that compute a MATERIAL's response. Growth is a property of a
#: material, so this is where a growth quantity has to be computed to make the
#: source a growth law. UEXPAN is here and not among the utilities because it
#: exists to return an expansion strain increment, which is a growth tensor by
#: another name.
MATERIAL_ROUTINES = frozenset({
    "UMAT", "VUMAT", "UMATHT", "UHYPER", "UANISOHYPER_INV", "UEL", "VUEL",
    "UEXPAN", "CREEP", "USDFLD", "UVARM", "HETVAL", "SDVINI"})

#: The routines that describe how a LOAD or a boundary condition is applied.
#: A quantity one of these computes from the clock is a load ramp -- the shape
#: of the loading in time -- and not a material growing. ``PureGravity.for``'s
#: DLOAD ends with ``F = TargetF*TIME(1)/TotalT``, which is gravity switched on
#: over the step and is exactly what the body-force family is for.
LOAD_ROUTINES = frozenset({
    "DLOAD", "VDLOAD", "UTRACLOAD", "DISP", "UAMP", "UFIELD", "UTEMP",
    "UPRESS", "UMASFL", "UFLUID", "UMOTION", "URDFIL", "UEXTERNALDB"})


def role_of(name: str, arguments: int = -1) -> str:
    """``"material"``, ``"load"`` or ``"utility"`` for a routine of this name.

    The argument count is checked for a MATERIAL name and not for a LOAD name,
    and the asymmetry is deliberate, because the two mistakes cost different
    things. Calling somebody's private nine-argument helper ``UMAT`` a
    material routine would let its quantities decide a family; that is the
    misreading :mod:`umat_oti.corpus.entry_routines` records, and the count is
    what catches it. Refusing to call a routine named DLOAD a load definition
    only makes the reading more permissive -- the quantity stays in the
    growth-candidate set -- but it does so for a routine that plainly is one:
    ``PureGravity.for``'s DLOAD takes the eleven arguments Abaqus documents,
    and the interface table in that module records twelve, so the count check
    demoted a real load definition and put its ``F = TargetF*TIME(1)/TotalT``
    ramp back among the growth candidates. A name in :data:`LOAD_ROUTINES` is
    a load definition; a disagreement about its arity is a question for the
    registry and not a reason to read gravity as growth.
    """
    key = (name or "").upper()
    if key in LOAD_ROUTINES:
        return "load"
    counts = INTERFACES.get(key)
    if counts and arguments >= 0 and arguments not in counts:
        return "utility"
    if key in MATERIAL_ROUTINES:
        return "material"
    return "utility"


# ---------------------------------------------------------------------------
# splitting the file into routines
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Routine:
    """One program unit, with the lines that belong to it."""

    name: str
    kind: str
    role: str
    first_line: int
    arguments: frozenset
    text: str


def routines(source_text: str, path: Optional[Path] = None) -> tuple[Routine, ...]:
    """Every SUBROUTINE and FUNCTION in the file, with its own body.

    The headers come from :func:`entry_routines.program_units`, which already
    handles both source forms and headers split over continuations; the bodies
    are the lines between one header and the next. A file with no header at all
    -- an include fragment, a bare block of statements -- is returned as one
    unnamed routine holding the whole text, so a caller never has to special-
    case it.
    """
    text = source_text or ""
    lines = text.splitlines()
    try:
        units = program_units(text, path=path)
    except Exception:                                    # pragma: no cover
        units = []
    if not units:
        return (Routine("", "", "utility", 1, frozenset(), text),)
    bounds = [max(unit.line, 1) for unit in units] + [len(lines) + 1]
    out: list[Routine] = []
    for index, unit in enumerate(units):
        body = "\n".join(lines[bounds[index] - 1:bounds[index + 1] - 1])
        out.append(Routine(
            name=unit.name, kind=unit.kind,
            role=role_of(unit.name, unit.argument_count),
            first_line=unit.line,
            arguments=frozenset(argument.upper()
                                for argument in unit.arguments),
            text=body))
    return tuple(out)


# ---------------------------------------------------------------------------
# the expression language
# ---------------------------------------------------------------------------
_NUMBER = re.compile(
    r"(?:\d+\.\d*|\.\d+|\d+)(?:[dDeEqQ][+-]?\d+)?")
_NAME = re.compile(r"[A-Za-z_]\w*")
#: Fortran's intrinsics that are pure functions of their arguments. Anything
#: not here -- an author's own FUNCTION, an array reference, a query like
#: SIZE -- folds to unknown, which is the safe answer.
_INTRINSICS = {
    "ABS": abs, "DABS": abs,
    "SQRT": math.sqrt, "DSQRT": math.sqrt,
    "EXP": math.exp, "DEXP": math.exp,
    "LOG": math.log, "DLOG": math.log, "ALOG": math.log,
    "LOG10": math.log10, "DLOG10": math.log10,
    "SIN": math.sin, "DSIN": math.sin,
    "COS": math.cos, "DCOS": math.cos,
    "TAN": math.tan, "DTAN": math.tan,
    "ASIN": math.asin, "ACOS": math.acos,
    "ATAN": math.atan, "DATAN": math.atan,
    "SINH": math.sinh, "COSH": math.cosh, "TANH": math.tanh,
    "ATAN2": math.atan2, "DATAN2": math.atan2,
    "MAX": max, "MIN": min, "DMAX1": max, "DMIN1": min,
    "AMAX1": max, "AMIN1": min, "MAX1": max, "MIN1": min,
    "REAL": float, "DBLE": float, "FLOAT": float, "DFLOAT": float,
    "SIGN": lambda a, b: math.copysign(a, b),
    "DSIGN": lambda a, b: math.copysign(a, b),
    "MOD": math.fmod, "DMOD": math.fmod, "AMOD": math.fmod,
    "INT": lambda a: float(int(a)), "IDINT": lambda a: float(int(a)),
    "NINT": lambda a: float(round(a)),
}


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char == "*" and text[index:index + 2] == "**":
            out.append("**")
            index += 2
            continue
        if char.isdigit() or (char == "." and _NUMBER.match(text, index)):
            match = _NUMBER.match(text, index)
            if match:
                out.append(match.group(0))
                index = match.end()
                continue
        if char.isalpha() or char == "_":
            match = _NAME.match(text, index)
            out.append(match.group(0))
            index = match.end()
            continue
        out.append(char)
        index += 1
    return out


def _number(token: str) -> Optional[float]:
    try:
        return float(token.replace("d", "e").replace("D", "e")
                     .replace("q", "e").replace("Q", "e"))
    except ValueError:
        return None


class _Undecidable(Exception):
    """The expression is not in the subset this folds, so nothing is claimed."""


class _Parser:
    """Recursive descent over one Fortran expression, folding as it goes.

    The value of every sub-expression is a float when it is known and None
    when it is not. The precedence is Fortran's: ``**`` binds tighter than a
    unary sign, so ``-X**2`` is ``-(X**2)`` and not ``(-X)**2``.
    """

    def __init__(self, text: str, env: dict):
        self.tokens = _tokens(text)
        self.at = 0
        self.env = env

    # -- plumbing ---------------------------------------------------------
    def peek(self) -> str:
        return self.tokens[self.at] if self.at < len(self.tokens) else ""

    def take(self) -> str:
        token = self.peek()
        self.at += 1
        return token

    def expect(self, token: str) -> None:
        if self.take() != token:
            raise _Undecidable(token)

    # -- the abstract arithmetic ------------------------------------------
    @staticmethod
    def _mul(left: Optional[float], right: Optional[float]) -> Optional[float]:
        """Known times unknown is unknown -- unless the known one is zero.

        This is the rule the whole module turns on. ``Y*Lambda1z1`` with
        Lambda1z1 folded to 0.0 is 0.0 whatever Y is, and Y -- a coordinate
        read back out of STATEV -- is never going to be known.
        """
        if left == 0.0 or right == 0.0:
            return 0.0
        if left is None or right is None:
            return None
        return left * right

    # -- the grammar ------------------------------------------------------
    def expression(self) -> Optional[float]:
        value = self.term()
        while self.peek() in ("+", "-"):
            operator = self.take()
            right = self.term()
            if value is None or right is None:
                value = None
            else:
                value = value + right if operator == "+" else value - right
        return value

    def term(self) -> Optional[float]:
        value = self.factor()
        while self.peek() in ("*", "/"):
            operator = self.take()
            right = self.factor()
            if operator == "*":
                value = self._mul(value, right)
                continue
            if value is None or right is None or right == 0.0:
                value = None
            else:
                value = value / right
        return value

    def factor(self) -> Optional[float]:
        if self.peek() in ("+", "-"):
            operator = self.take()
            value = self.factor()
            if value is None:
                return None
            return value if operator == "+" else -value
        return self.power()

    def power(self) -> Optional[float]:
        base = self.primary()
        if self.peek() != "**":
            return base
        self.take()
        exponent = self.factor()
        if base is None or exponent is None:
            return None
        try:
            value = float(base) ** float(exponent)
        except (ValueError, OverflowError, ZeroDivisionError):
            raise _Undecidable("**")
        if not math.isfinite(value):
            raise _Undecidable("**")
        return value

    def primary(self) -> Optional[float]:
        token = self.take()
        if not token:
            raise _Undecidable("end of expression")
        if token == "(":
            value = self.expression()
            self.expect(")")
            return value
        number = _number(token) if (token[0].isdigit() or token[0] == ".") else None
        if number is not None:
            return number
        if not (token[0].isalpha() or token[0] == "_"):
            raise _Undecidable(token)
        name = token.upper()
        if self.peek() != "(":
            # A bare name. Fortran's logical literals are the only names that
            # are not variables, and a routine that puts one in an arithmetic
            # expression is outside this subset.
            if name in ("TRUE", "FALSE"):
                raise _Undecidable(token)
            return self.env.get(name)
        self.take()                                             # "("
        arguments: list[Optional[float]] = []
        if self.peek() != ")":
            while True:
                arguments.append(self.expression())
                if self.peek() != ",":
                    break
                self.take()
        self.expect(")")
        function = _INTRINSICS.get(name)
        if function is not None:
            if any(value is None for value in arguments) or not arguments:
                return None
            try:
                value = float(function(*arguments))
            except (ValueError, TypeError, OverflowError, ZeroDivisionError):
                raise _Undecidable(name)
            return value if math.isfinite(value) else None
        # An array element, or a FUNCTION this cannot see inside. Subscripts
        # that are all literal integers give a name a binding can be looked up
        # under -- STATEV(8) is a place, and one the routine may have written
        # a constant into further up.
        if arguments and all(value is not None and value == int(value)
                             for value in arguments):
            key = f"{name}({','.join(str(int(value)) for value in arguments)})"
            return self.env.get(key)
        return None


def fold_expression(text: str, env: Optional[dict] = None) -> Optional[float]:
    """The value of one Fortran expression, or None if it is not decidable.

    None covers both "this depends on something unknown" and "this is outside
    the subset folded here". Both mean the same thing to a caller: nothing is
    claimed about it.
    """
    try:
        parser = _Parser(text, dict(env or {}))
        value = parser.expression()
    except (_Undecidable, IndexError, RecursionError):
        return None
    if parser.at != len(parser.tokens):
        return None                     # trailing tokens: not an expression
    if value is not None and not math.isfinite(value):
        return None
    return value


# ---------------------------------------------------------------------------
# folding a routine
# ---------------------------------------------------------------------------
_ASSIGN = re.compile(
    r"^\s*(?:\d+\s+)?([A-Za-z_]\w*(?:\s*\(\s*[\d\s,]+\s*\))?)\s*=\s*(.+)$")
_LABEL = re.compile(r"^\s*(\d+)\s")
_OPEN = re.compile(
    r"^\s*(?:\d+\s+)?(?:[A-Za-z_]\w*\s*:\s*)?"
    r"(?:IF\b.*\bTHEN\s*$|DO\b|SELECT\s*CASE\b|WHERE\s*\(.*\)\s*$"
    r"|FORALL\s*\(.*\)\s*$|BLOCK\s*$|ASSOCIATE\b|TYPE\s*::|INTERFACE\b)",
    re.IGNORECASE)
_CLOSE = re.compile(
    r"^\s*(?:\d+\s+)?END\s*(IF|DO|SELECT|WHERE|FORALL|BLOCK|ASSOCIATE"
    r"|TYPE|INTERFACE)\b", re.IGNORECASE)
_ONE_LINE_IF = re.compile(
    r"^\s*(?:\d+\s+)?IF\s*\(", re.IGNORECASE)
_LABELLED_DO = re.compile(r"^\s*(?:\d+\s+)?DO\s+(\d+)\b", re.IGNORECASE)
_JUMP = re.compile(r"\bGO\s*TO\b", re.IGNORECASE)
_PARAMETER = re.compile(
    r"^\s*(?:\d+\s+)?PARAMETER\s*\((.*)\)\s*$", re.IGNORECASE)
_DECLARED_PARAMETER = re.compile(
    r"^\s*(?:\d+\s+)?(?:DOUBLE\s*PRECISION|REAL|INTEGER)\b[^:]*::\s*(.+)$",
    re.IGNORECASE)
_COMMENT_OR_DECL = re.compile(
    r"^\s*(?:\d+\s+)?(DOUBLE\s*PRECISION|REAL|INTEGER|DIMENSION|COMMON"
    r"|CHARACTER|LOGICAL|IMPLICIT|SUBROUTINE|FUNCTION|INCLUDE|DATA|SAVE"
    r"|EXTERNAL|INTENT|ALLOCATABLE|PARAMETER|USE|MODULE|CONTAINS|TYPE)\b",
    re.IGNORECASE)


def _key(target: str) -> str:
    """``STATEV ( 8 )`` and ``statev(8)`` are one place, spelled two ways."""
    squeezed = "".join(target.split()).upper()
    match = re.match(r"^([A-Z_]\w*)\((.*)\)$", squeezed)
    if not match:
        return squeezed
    parts = [piece.strip() for piece in match.group(2).split(",")]
    return f"{match.group(1)}({','.join(parts)})"


@dataclass(frozen=True)
class Constant:
    """A name this routine pins to a value, and the statement that pins it."""

    name: str
    value: float
    routine: str
    statement: str

    def as_dict(self) -> dict:
        return {"name": self.name, "value": self.value,
                "routine": self.routine, "statement": self.statement}


@dataclass(frozen=True)
class Folding:
    """What one file's literal assignments decide, per routine and overall."""

    constants: dict = field(default_factory=dict)
    #: Every routine that assigns each name, so a caller can tell a quantity
    #: the material computes from one a load definition computes.
    assigned_in: dict = field(default_factory=dict)
    #: The role of each routine, keyed by routine name.
    roles: dict = field(default_factory=dict)
    #: Routines holding a GOTO, where the straight-line reading is a reading
    #: and not a proof.
    jumps: tuple = ()
    #: What each routine pins down on its own, keyed by routine name then by
    #: name. A caller asking about one routine's quantity must ask here and
    #: not of :attr:`constants`: ``PureGravity.for`` calls the body force F in
    #: its DLOAD and the deformation gradient F in its UMAT, and the two share
    #: nothing but four bits of spelling.
    per_routine: dict = field(default_factory=dict)
    #: The routines, in the order the file declares them.
    units: tuple = ()

    def value(self, name: str):
        found = self.constants.get(_key(name))
        return found.value if found is not None else None

    def is_constant(self, name: str) -> bool:
        return _key(name) in self.constants

    def constant_in(self, routine: str, name: str):
        """What ``routine`` pins ``name`` to, or None if it pins nothing."""
        return (self.per_routine.get((routine or "").upper())
                or {}).get(_key(name))

    def assigned_by_role(self, name: str) -> frozenset:
        return frozenset(self.roles.get(routine, "utility")
                         for routine in self.assigned_in.get(_key(name), ()))


def _parameters(lines) -> dict:
    """The PARAMETER constants a routine declares, both spellings.

    ``PARAMETER (ONE=1.0, TWO=2.0)`` and ``REAL, PARAMETER :: ONE = 1.0``.
    These are constants by the language's own rules -- they cannot be assigned
    -- so they are the one place a value can be read without a dataflow
    argument.
    """
    found: dict = {}
    for line in lines:
        body = ""
        match = _PARAMETER.match(line)
        if match:
            body = match.group(1)
        elif re.search(r"\bPARAMETER\b", line, re.IGNORECASE):
            declared = _DECLARED_PARAMETER.match(line)
            if declared:
                body = declared.group(1)
        if not body:
            continue
        for piece in re.split(r",(?![^()]*\))", body):
            name, _, expression = piece.partition("=")
            if not expression.strip():
                continue
            value = fold_expression(expression, found)
            if value is not None:
                found[_key(name)] = value
    return found


def fold_routine(routine: Routine) -> tuple[dict, dict, bool]:
    """Walk one routine top to bottom and record what it pins down.

    Returns the constants it fixes, the statement each was fixed by, and
    whether the routine contains a GOTO.

    The walk is a single forward pass and not a fixed point, and that is the
    point: an expression may use only what the statements ABOVE it have
    already fixed. A fixed point would happily fold ``TotalT`` into a
    statement written before ``TotalT = 1.0``, which is not what the program
    does.
    """
    lines = statements(routine.text)
    env: dict = _parameters(lines)
    statement_of: dict = {name: "declared PARAMETER" for name in env}
    poisoned: set = set(routine.arguments)
    poisoned.add(routine.name.upper())
    for name in tuple(env):
        if name in poisoned:
            env.pop(name, None)
    depth = 0
    pending_labels: list = []
    jumps = False

    for line in lines:
        if _JUMP.search(line):
            jumps = True
        label = _LABEL.match(line)
        while pending_labels and label and label.group(1) == pending_labels[-1]:
            pending_labels.pop()
            depth = max(0, depth - 1)
        if _CLOSE.match(line):
            depth = max(0, depth - 1)
            continue
        if _COMMENT_OR_DECL.match(line):
            continue
        opening = bool(_OPEN.match(line))
        labelled = _LABELLED_DO.match(line)
        match = _ASSIGN.match(line)
        conditional = depth > 0
        if match is None and _ONE_LINE_IF.match(line):
            # ``IF (cond) X = 1.0``: an assignment that may not happen. Find it
            # past the condition's closing parenthesis.
            tail = _after_condition(line)
            match = _ASSIGN.match(tail) if tail else None
            conditional = True
        if opening or labelled:
            if labelled:
                pending_labels.append(labelled.group(1))
            depth += 1
            if match is None:
                continue
        if match is None:
            continue
        target = _key(match.group(1))
        if target in poisoned:
            continue
        if conditional:
            # It may not execute, or it may execute many times. Either way the
            # name has no single value from here on.
            poisoned.add(target)
            env.pop(target, None)
            continue
        value = fold_expression(match.group(2), env)
        if value is None:
            poisoned.add(target)
            env.pop(target, None)
            continue
        if target in env and env[target] != value:
            poisoned.add(target)
            env.pop(target, None)
            continue
        env[target] = value
        statement_of.setdefault(target, line.strip()[:120])
    for name in poisoned:
        env.pop(name, None)
    return env, statement_of, jumps


def _after_condition(line: str) -> str:
    """The statement a one-line IF guards, past its balanced condition."""
    start = line.find("(")
    if start < 0:
        return ""
    level = 0
    for index in range(start, len(line)):
        if line[index] == "(":
            level += 1
        elif line[index] == ")":
            level -= 1
            if level == 0:
                return line[index + 1:]
    return ""


def fold(source_text: str, path: Optional[Path] = None) -> Folding:
    """Every name this file's own literal assignments pin to a value.

    A name is reported constant only if EVERY routine that assigns it folds it
    to a value and they all agree. A file where one routine pins ``F`` to a
    literal and another computes it is a file where ``F`` is not constant, and
    the union of two routines' constants is not a fact about either.
    """
    per_name: dict = {}
    assigned_in: dict = {}
    roles: dict = {}
    jumping: list = []
    per_routine: dict = {}
    units = routines(source_text, path=path)
    for routine in units:
        key = routine.name.upper()
        roles[key] = routine.role
        env, statement_of, jumps = fold_routine(routine)
        if jumps:
            jumping.append(key)
        assigned = _assigned_names(routine)
        for name in assigned:
            assigned_in.setdefault(name, []).append(key)
        here: dict = {}
        for name, value in env.items():
            found = Constant(name, value, key, statement_of.get(name, ""))
            here[name] = found
            per_name.setdefault(name, []).append(found)
        per_routine.setdefault(key, {}).update(here)
        for name in assigned - set(env):
            per_name.setdefault(name, []).append(None)
    constants: dict = {}
    for name, found in per_name.items():
        if any(entry is None for entry in found):
            continue
        values = {entry.value for entry in found}
        if len(values) == 1:
            constants[name] = found[0]
    return Folding(constants=constants,
                   assigned_in={name: tuple(where)
                                for name, where in assigned_in.items()},
                   roles=roles, jumps=tuple(jumping),
                   per_routine=per_routine, units=units)


def _assigned_names(routine: Routine) -> set:
    """Every name this routine assigns anywhere, conditionally or not."""
    found: set = set()
    for line in statements(routine.text):
        if _COMMENT_OR_DECL.match(line) or _CLOSE.match(line):
            continue
        match = _ASSIGN.match(line)
        if match is None and _ONE_LINE_IF.match(line):
            tail = _after_condition(line)
            match = _ASSIGN.match(tail) if tail else None
        if match is None:
            continue
        found.add(_key(match.group(1)))
    return found
