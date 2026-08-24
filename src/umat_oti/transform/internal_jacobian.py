"""Discover the local nonlinear solve inside a UMAT, generically.

An internal constitutive Jacobian (``FJAC``, ``DETDG``, ``GDIA``, ``ANP1P``,
``BNP1P``, ``CEVPI``) is the derivative of a *local* residual with respect to the
*local* iteration variable, evaluated inside the return-mapping loop. To
differentiate it the pipeline first has to find that loop, and it has to do so
without knowing which model it is looking at.

The discovery is purely syntactic. A scalar Newton update has one shape:

    X = X - A / B

where ``X`` is the iteration variable, ``A`` the residual and ``B`` the
hand-coded Jacobian. Matching that shape alone -- no symbol whitelist, no model
names -- identifies the triple in 9 of the 12 ICP UMATs, every one of them as
``(GAM_PAR, FGAM, FJAC)``. The three that do not match genuinely have no scalar
Newton update, and are reported as such rather than forced.

What this module does *not* do is decide that the discovered ``B`` is correct.
It is the model's own hand-coded Jacobian, and checking it against an
independent derivative is the entire point of the exercise -- so it is treated
as a claim to be verified, never as a reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: ``X = X - A / B`` with a scalar X on both sides. The backreference is what
#: makes this specific: it must be the *same* variable being updated.
_NEWTON_UPDATE = re.compile(
    r"^\s*(?:\d+\s+)?([A-Za-z_]\w*)\s*=\s*\1\s*([+-])\s*([A-Za-z_]\w*)\s*/\s*([A-Za-z_]\w*)\s*$"
)
#: A convergence test tells us the loop is a solve rather than a fixed sweep.
_CONVERGENCE = re.compile(
    r"\b(?:D?ABS|ABS)\s*\(\s*([A-Za-z_]\w*)[^)]*\)\s*(?:\.LT\.|<)\s*"
    r"([A-Za-z_][A-Za-z_0-9]*|[0-9][0-9.EeDd+-]*)", re.I)
#: Both loop forms these sources use: a counted ``DO K=1,N`` and the bare ``DO``
#: infinite loop that a return map exits on convergence. Matching only the
#: counted form silently missed every iteration loop in the ICP family.
_LOOP_START = re.compile(
    r"^\s*(?:\d+\s+)?DO\s*(?:\d+\s+)?(?:[A-Za-z_]\w*\s*=|WHILE\b|$)", re.I)
_LOOP_END = re.compile(r"^\s*(?:\d+\s+)?(?:END\s*DO|CONTINUE)\b", re.I)


@dataclass(frozen=True)
class LocalSolve:
    """A local nonlinear solve found in a UMAT source."""

    iterate: str
    residual: str
    jacobian: str
    sign: str
    update_line: int
    loop_start_line: int | None
    loop_end_line: int | None
    convergence_variable: str | None
    convergence_tolerance: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "iteration_variable": self.iterate,
            "residual_variable": self.residual,
            # Named for what it is: the model's own claim about the derivative,
            # which this pipeline exists to check rather than to trust.
            "hand_coded_jacobian_variable": self.jacobian,
            "update_sign": self.sign,
            "update_line": self.update_line,
            "loop_start_line": self.loop_start_line,
            "loop_end_line": self.loop_end_line,
            "convergence_variable": self.convergence_variable,
            "convergence_tolerance": self.convergence_tolerance,
            "discovery": ("syntactic scan for a scalar Newton update X = X +/- A/B; "
                          "no symbol whitelist and no model name was used"),
        }


def discover_local_solves(source_text: str) -> list[LocalSolve]:
    """Every scalar Newton solve in the source, in line order."""
    lines = source_text.splitlines()
    solves: list[LocalSolve] = []
    for index, raw in enumerate(lines):
        # Skip fixed-form comment lines: column 1 in {C,c,*,!}.
        if raw[:1] in ("C", "c", "*", "!"):
            continue
        match = _NEWTON_UPDATE.match(raw.rstrip())
        if not match:
            continue
        iterate, sign, residual, jacobian = match.groups()
        start = _enclosing_loop_start(lines, index)
        end = _enclosing_loop_end(lines, index)
        variable, tolerance = _convergence_near(lines, index, start, end)
        solves.append(LocalSolve(
            iterate=iterate.upper(), residual=residual.upper(),
            jacobian=jacobian.upper(), sign=sign, update_line=index + 1,
            loop_start_line=None if start is None else start + 1,
            loop_end_line=None if end is None else end + 1,
            convergence_variable=variable, convergence_tolerance=tolerance,
        ))
    return solves


def _enclosing_loop_start(lines: list[str], index: int) -> int | None:
    depth = 0
    for cursor in range(index, -1, -1):
        line = lines[cursor]
        if line[:1] in ("C", "c", "*", "!"):
            continue
        if _LOOP_END.match(line) and cursor != index:
            depth += 1
        elif _LOOP_START.match(line):
            if depth == 0:
                return cursor
            depth -= 1
    return None


def _enclosing_loop_end(lines: list[str], index: int) -> int | None:
    depth = 0
    for cursor in range(index + 1, len(lines)):
        line = lines[cursor]
        if line[:1] in ("C", "c", "*", "!"):
            continue
        if _LOOP_START.match(line):
            depth += 1
        elif _LOOP_END.match(line):
            if depth == 0:
                return cursor
            depth -= 1
    return None


def _convergence_near(lines: list[str], index: int, start: int | None,
                      end: int | None) -> tuple[str | None, str | None]:
    lower = start if start is not None else max(0, index - 20)
    upper = end if end is not None else min(len(lines), index + 20)
    for cursor in range(lower, upper):
        line = lines[cursor]
        if line[:1] in ("C", "c", "*", "!"):
            continue
        match = _CONVERGENCE.search(line)
        if match:
            return match.group(1).upper(), match.group(2)
    return None, None


def describe_source(source_text: str, *, name: str = "source") -> dict[str, Any]:
    """Discovery result for one source, including an honest negative."""
    solves = discover_local_solves(source_text)
    if not solves:
        return {
            "source": name,
            "local_solves": [],
            "supported": False,
            # A model with no scalar Newton update is not a failure of the model
            # and not a defect here; it simply has no internal Jacobian of this
            # shape to extract, and saying so is the correct outcome.
            "reason": ("no scalar Newton update of the form X = X +/- A/B was found. "
                       "This source either solves its local problem in another shape "
                       "(vector/matrix solve, direct closed form, fixed-point sweep) "
                       "or has no local solve at all. No internal Jacobian of this "
                       "kind can be extracted, and none is claimed."),
        }
    return {
        "source": name,
        "local_solves": [solve.as_dict() for solve in solves],
        "supported": True,
        "reason": None,
    }
