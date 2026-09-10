"""What precision the author's own arithmetic carried, and what that costs.

A UMAT that declares ``REAL S(6)`` and copies the incoming stress into it is
not writing a different model from one that declares ``REAL*8 S(6)``. It is
writing the same model in seven digits. Fortran's default real is single
precision, and an explicit ``REAL`` declaration overrides the
``IMPLICIT REAL*8(A-H,O-Z)`` that ``aba_param.inc`` supplies -- so a variable
named in one of those declarations holds float32 no matter what the include
file says.

The OTI type is built over doubles. There is no single-precision OTI number to
promote such a variable to, so the transform promotes it to a double-based one,
and from that increment on the converted build no longer rounds where the
author's build rounded. The two stress histories then differ by the author's
own truncation -- about 1e-7 relative, which is float32 epsilon, and more
wherever the model amplifies it.

Reported as a primal disagreement, that reads as "the conversion computes
something else". It is not: it is the conversion computing the same expression
without the author's rounding. The two are distinguishable, and this module is
how they are distinguished -- by running a control.

**The control.** Take the ORIGINAL source and widen exactly the declarations
the transform promoted, and nothing else. Nothing is reordered, no expression
is rewritten, no constant is changed: the only difference is the declared kind
of variables that the converted build already carries at double. Run that in
Abaqus on the same deck. Then:

* control agrees with the converted build to the tight tolerance
  -> the difference between the author's build and the converted one is the
  author's declared precision, and that is now measured rather than asserted;
* control still disagrees
  -> precision was not the explanation and the disagreement stands.

Measured on ``irfancn__Abaqus-UMAT-viscoelastic/umat_viscoelastic.for``, whose
line 22 reads ``real E, nu, lambda, mu, S(6), D1(6,6), D2(6,6), D3(6,6)`` and
whose stress update is ``stress = stress + D1.dstran + D2.stran - S``: the
original and the converted build disagree by 1.106e-07 over thirty increments,
and the control -- with ``S`` alone widened, because ``S`` alone is what the
transform promoted -- agrees with the converted build to 0.000e+00, every
component of every increment.

Widening every ``REAL`` in the file instead of the promoted ones is not the
same experiment and does not answer the question: ``D1`` stays single in the
converted build, because the transform never promoted it, so a control that
widens ``D1`` disagrees with the converted build for a new reason. Measured
too: ``-r8`` over the whole unit moved the control to 9.786e-08 from the
converted build rather than to zero.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

#: The suffix the transform gives every hypercomplex shadow. ``S`` becomes
#: ``S_OTI``; reading the shadows back out of the converted source is how the
#: promoted set is recovered without the transform having to hand it over.
OTI_SUFFIX = "_OTI"

#: A declaration of the OTI derived type in the converted source.
_OTI_DECLARATION = re.compile(
    r"^\s*TYPE\s*\(\s*[A-Za-z_]\w*\s*\)\s*(?:::)?\s*(.+)$", re.IGNORECASE)

#: An entity in a declaration's entity list: a name, optionally with an array
#: spec or an initialiser, which are skipped over by the splitter below.
_NAME = re.compile(r"^\s*([A-Za-z_]\w*)")

#: A type specification that means "single precision" -- Fortran's default
#: real, or one of the spellings of kind 4. ``REAL*8``, ``REAL(8)``,
#: ``REAL(KIND=8)``, ``DOUBLE PRECISION`` and ``REAL(REAL64)`` are all wider
#: than the default and are deliberately not matched.
_SINGLE_REAL = re.compile(
    r"^\s*REAL\s*(?:\*\s*4|\(\s*(?:KIND\s*=\s*)?4\s*\))?\s*(?:,[^:]*)?(::)?\s*(?=[A-Za-z_])",
    re.IGNORECASE)

#: Anything that makes a line not a declaration this may touch: a continuation
#: of something else, a comment, or a statement.
_COMMENT_FIXED = re.compile(r"^[cC*!]")


@dataclass(frozen=True)
class NarrowDeclaration:
    """One declaration that holds a promoted name at single precision."""

    line: int
    text: str
    #: The promoted names this declaration declares.
    names: tuple[str, ...]
    #: Every name the declaration declares, promoted or not.
    all_names: tuple[str, ...]


@dataclass(frozen=True)
class PrecisionFinding:
    """What the author declared narrow, and what a control would change."""

    #: Names the transform promoted to an OTI shadow.
    promoted: tuple[str, ...] = ()
    #: Declarations in the ORIGINAL that hold one of them at single precision.
    narrow: tuple[NarrowDeclaration, ...] = ()
    #: Names a control would widen: promoted and declared single.
    widened: tuple[str, ...] = ()
    reason: str = ""

    @property
    def explains_a_difference(self) -> bool:
        """Whether a precision control is worth an Abaqus job for this source."""
        return bool(self.widened)

    def as_dict(self) -> dict:
        return {
            "promoted": list(self.promoted),
            "widened": list(self.widened),
            "narrow_declarations": [
                {"line": found.line, "text": found.text.strip(),
                 "names": list(found.names)} for found in self.narrow],
            "reason": self.reason,
        }


def promoted_names(transformed_text: str) -> tuple[str, ...]:
    """The names the transform gave a hypercomplex shadow, from the shadows.

    Read out of the converted source rather than taken from the transform's
    own report, so that what is widened in the control is what the build that
    ran actually carries -- a report can drift from the file, a declaration in
    the file cannot drift from itself.
    """
    found: set[str] = set()
    for line in transformed_text.splitlines():
        if _COMMENT_FIXED.match(line):
            continue
        match = _OTI_DECLARATION.match(line)
        if not match:
            continue
        for name in _entity_names(match.group(1)):
            if name.upper().endswith(OTI_SUFFIX):
                base = name[:-len(OTI_SUFFIX)]
                if base:
                    found.add(base.upper())
    return tuple(sorted(found))


def _entity_names(entities: str) -> list[str]:
    """The names in a declaration's entity list, array specs skipped.

    ``S(6), D1(6,6)`` is two names. Splitting on commas is wrong -- the commas
    inside ``D1(6,6)`` are not separators -- so this walks the text and tracks
    bracket depth.
    """
    names: list[str] = []
    depth = 0
    start = 0
    pieces: list[str] = []
    for index, character in enumerate(entities):
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == "," and depth == 0:
            pieces.append(entities[start:index])
            start = index + 1
    pieces.append(entities[start:])
    for piece in pieces:
        match = _NAME.match(piece)
        if match:
            names.append(match.group(1))
    return names


def _declaration_split(line: str) -> Optional[tuple[str, str]]:
    """A single-precision REAL declaration split into its head and entities."""
    body = line
    match = _SINGLE_REAL.match(body)
    if not match:
        return None
    return body[:match.end()], body[match.end():]


def narrow_declarations(original_text: str,
                        names: Iterable[str]) -> tuple[NarrowDeclaration, ...]:
    """Declarations in the original that hold one of ``names`` at single precision.

    Only explicit declarations. A name typed by ``IMPLICIT REAL*8(A-H,O-Z)``
    -- which is what ``aba_param.inc`` installs -- is already double and needs
    no control; a name typed by Fortran's own default implicit rule in a source
    with no include and no IMPLICIT statement is single, and that case is
    reported by :func:`survey` as unexplained rather than silently widened,
    because widening it would mean writing a declaration the author never wrote.
    """
    wanted = {str(name).upper() for name in names}
    found: list[NarrowDeclaration] = []
    for number, line in enumerate(original_text.splitlines(), start=1):
        if _COMMENT_FIXED.match(line):
            continue
        split = _declaration_split(line)
        if split is None:
            continue
        _head, entities = split
        declared = _entity_names(entities)
        hits = tuple(name for name in declared if name.upper() in wanted)
        if hits:
            found.append(NarrowDeclaration(number, line, hits,
                                           tuple(declared)))
    return tuple(found)


def survey(original_text: str, transformed_text: str) -> PrecisionFinding:
    """Whether the author's declared precision could explain a disagreement."""
    promoted = promoted_names(transformed_text)
    if not promoted:
        return PrecisionFinding(
            reason="the converted source declares no OTI shadow, so there is "
                   "no promoted variable whose declared precision could differ")
    narrow = narrow_declarations(original_text, promoted)
    widened = tuple(sorted({name.upper() for found in narrow
                            for name in found.names}))
    if not widened:
        return PrecisionFinding(
            promoted=promoted,
            reason=f"none of the {len(promoted)} promoted variables is "
                   f"declared at single precision in the original, so the "
                   f"author's arithmetic was already double and the "
                   f"disagreement is not a precision one")
    return PrecisionFinding(
        promoted=promoted, narrow=narrow, widened=widened,
        reason=(f"{len(widened)} promoted variable(s) are declared REAL "
                f"(single precision) in the original at line(s) "
                f"{', '.join(str(found.line) for found in narrow)}: "
                f"{', '.join(widened)}. The OTI type is built over doubles, "
                f"so the converted build does not round where the author's "
                f"build rounds"))


def widen(original_text: str, finding: PrecisionFinding) -> tuple[str, tuple[str, ...]]:
    """The original with exactly the promoted narrow declarations widened.

    A declaration that mixes promoted and unpromoted names is split in two so
    that only the promoted ones change kind. The source form is preserved: the
    replacement lines start in the same column as the line they replace, so a
    fixed-form file stays fixed-form and a free-form one stays free.

    Returns the new text and a line-by-line account of what changed, which
    goes into the record beside the control's result. A control nobody can see
    the diff of is not a control.
    """
    if not finding.widened:
        return original_text, ()
    wanted = {name.upper() for name in finding.widened}
    by_line = {found.line: found for found in finding.narrow}
    changes: list[str] = []
    out: list[str] = []
    for number, line in enumerate(original_text.splitlines(), start=1):
        found = by_line.get(number)
        if found is None:
            out.append(line)
            continue
        split = _declaration_split(line)
        if split is None:                       # pragma: no cover - defensive
            out.append(line)
            continue
        head, entities = split
        indent = line[:len(line) - len(line.lstrip())]
        keep, move = _partition(entities, wanted)
        widened_head = _widen_head(head)
        if keep.strip():
            out.append(head + keep)
            out.append(indent + _widen_head(head).lstrip() + move)
            changes.append(f"line {number}: {line.strip()} -> "
                           f"{(head + keep).strip()} / "
                           f"{(indent + widened_head.lstrip() + move).strip()}")
        else:
            replacement = indent + widened_head.lstrip() + entities
            out.append(replacement)
            changes.append(f"line {number}: {line.strip()} -> "
                           f"{replacement.strip()}")
    return "\n".join(out) + ("\n" if original_text.endswith("\n") else ""), tuple(changes)


def _widen_head(head: str) -> str:
    """``REAL`` becomes ``REAL*8``; ``REAL*4`` and ``REAL(4)`` become it too."""
    widened = re.sub(r"REAL\s*\*\s*4", "REAL*8", head, flags=re.IGNORECASE)
    widened = re.sub(r"REAL\s*\(\s*(?:KIND\s*=\s*)?4\s*\)", "REAL*8", widened,
                     flags=re.IGNORECASE)
    if widened == head:
        widened = re.sub(r"\bREAL\b", "REAL*8", head, count=1, flags=re.IGNORECASE)
    return widened


def _partition(entities: str, wanted: set[str]) -> tuple[str, str]:
    """Entities split into the ones to leave alone and the ones to widen."""
    depth = 0
    start = 0
    pieces: list[str] = []
    for index, character in enumerate(entities):
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == "," and depth == 0:
            pieces.append(entities[start:index])
            start = index + 1
    pieces.append(entities[start:])
    keep, move = [], []
    for piece in pieces:
        match = _NAME.match(piece)
        target = move if (match and match.group(1).upper() in wanted) else keep
        target.append(piece.strip())
    return (", ".join(part for part in keep if part),
            ", ".join(part for part in move if part))
