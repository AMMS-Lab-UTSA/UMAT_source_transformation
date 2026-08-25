"""Locate the DDSDDE tangent block when region classification finds none.

Ported from ``tools/corpus/corpus_batch.py::_fallback_ranges`` in the local
``framework_repos (2)/framework_repos/umat-oti`` copy. That bundle's
architecture was not reused -- it has ``sys.path`` manipulation, no licence
categorisation and no immutable snapshot pinning -- but this one algorithm is
worth keeping: its own report records ``no_ddsdde_region`` falling from 66 to 17
and transform successes rising from 35 to 65 over a 207-UMAT corpus.

The idea is small. A region classifier that looks for a contiguous "tangent"
block misses the common loop-based form::

    DO I = 1, NTENS
      DO J = 1, NTENS
        DDSDDE(I,J) = ...
      END DO
    END DO

because the assignment is buried inside nested loops. Finding the assignment
directly and expanding outward to the enclosing loops recovers it.

The port is deliberately conservative: it reports candidate ranges and never
decides on its own that a source is transformable. A range here is a hypothesis
for the contract to carry, not a verified tangent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DDSDDE_ASSIGN = re.compile(r"^\s*DDSDDE\s*(\([^)]*\))?\s*=", re.I)
_DO = re.compile(r"^\s*(?:\d+\s+)?DO\b", re.I)
_END_DO = re.compile(r"^\s*(?:\d+\s+)?(END\s*DO|ENDDO|CONTINUE)\b", re.I)


def is_code_line(line: str) -> bool:
    """Fixed-form comments start in column 1; free-form ones start with ``!``."""
    return bool(line.strip()) and line[:1] not in "Cc*!" \
        and not line.lstrip().startswith("!")


@dataclass(frozen=True)
class TangentRange:
    """A 1-based inclusive line span believed to compute DDSDDE."""

    start: int
    end: int
    assignments: int

    def as_spec(self) -> str:
        return f"{self.start}-{self.end}"


def find_tangent_ranges(text: str) -> list[TangentRange]:
    """Candidate DDSDDE regions, expanded to their enclosing DO blocks.

    Returns an empty list when the source contains no DDSDDE assignment at all,
    which is a real answer: some UMATs never form a tangent.
    """
    lines = text.splitlines()
    hits = [index for index, line in enumerate(lines) if _DDSDDE_ASSIGN.match(line)]
    if not hits:
        return []

    code = [index for index, line in enumerate(lines) if is_code_line(line)]
    spans: list[tuple[int, int]] = []
    for hit in hits:
        low = high = hit
        # Walk outward while the nearest preceding statement is a loop header.
        before = [index for index in code if index < low]
        while before and _DO.match(lines[before[-1]]):
            low = before.pop()
            before = [index for index in before if index < low]
        after = [index for index in code if index > high]
        while after and _END_DO.match(lines[after[0]]):
            high = after.pop(0)
        spans.append((low + 1, high + 1))

    spans.sort()
    merged: list[list[int]] = [list(spans[0]) + [1]]
    for start, end in spans[1:]:
        # Adjacent spans belong to one region: a tangent split across two blocks
        # is still one tangent.
        if start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2] += 1
        else:
            merged.append([start, end, 1])
    return [TangentRange(start=s, end=e, assignments=n) for s, e, n in merged]


def describe(text: str, *, name: str = "source") -> dict:
    """Candidate ranges plus an honest negative when there are none."""
    ranges = find_tangent_ranges(text)
    if not ranges:
        return {
            "source": name,
            "tangent_ranges": [],
            "found": False,
            "reason": ("no DDSDDE assignment appears in this source. It may compute "
                       "its tangent through a helper, or not form one at all. This "
                       "is a candidate-location result, not a transformability "
                       "verdict."),
        }
    return {
        "source": name,
        "tangent_ranges": [r.as_spec() for r in ranges],
        "assignments": sum(r.assignments for r in ranges),
        "found": True,
        "reason": None,
        "provenance": ("algorithm ported from tools/corpus/corpus_batch.py::"
                       "_fallback_ranges in the local framework_repos (2) copy"),
    }
