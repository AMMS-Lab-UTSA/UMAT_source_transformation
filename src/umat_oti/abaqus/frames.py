"""A history record is not an increment, and counting them as if it were lies.

Abaqus calls a UMAT once per material point per iteration, so the probe's
history has a record for every integration point of every element in every
increment. A single-element C3D8 job of thirty-five increments writes two
hundred and eighty records; the same job on a CPE4 writes one hundred and
forty. Neither number is thirty-five, and neither is a count of anything a
constitutive law did once.

Treating the flattened record count as an increment count is not a cosmetic
error. It made a verification say "agreed over 280 increments" about a
thirty-five increment analysis. It made a prefix of twenty-two records --
two complete increments and six integration points of a third -- clear a
minimum of five "increments" five times over. And it made the safe-loading
reconstruction read the edge of a material's domain off a partially
evaluated increment, which is not a state the solver ever reached.

So the history is grouped by what identifies a state: the step, the
increment within it, the element and the integration point. An increment is
complete only when every material point that increment is expected to
produce is present and finite -- every one, because a solver's answer for an
increment whose seventh point returned a value that is not a number is
already contaminated, and its first six say nothing to the contrary.

The counts are kept apart and named for what they are, so no later reader
has to guess which one a number is:

``raw_output_records``
    what the probe wrote, one per material point per increment;
``complete_increments``
    increments with every expected point present and finite;
``material_points_per_increment``
    how many points an increment of this model is expected to produce;
``first_incomplete_increment``
    the first increment missing a point it should have had;
``first_non_finite_material_point``
    which step, increment, element and point first returned a value that is
    not a number.
"""
from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

#: Outputs a verification depends on. DDSDDE is included because the finite
#: difference is checked against it: a run whose stress is finite while its
#: tangent is not has not produced what the verification asks for.
CHECKED = ("STRESS", "STATEV", "DDSDDE")


def _finite(record: dict) -> bool:
    for name in CHECKED:
        for value in (record.get(name) or ()):
            try:
                if not math.isfinite(float(value)):
                    return False
            except (TypeError, ValueError):
                return False
    return True


def identity(record: dict) -> tuple:
    """What names a material point's state: step, increment, element, point."""
    return (int(record.get("step") or 0), int(record.get("increment") or 0),
            int(record.get("element") or 0), int(record.get("point") or 0))


@dataclass
class Increment:
    """One increment of one step, and every material point it produced."""

    step: int
    increment: int
    time: float = 0.0
    records: list = field(default_factory=list)
    expected_points: int = 0

    @property
    def points(self) -> int:
        return len({identity(record)[2:] for record in self.records})

    @property
    def present(self) -> bool:
        return self.expected_points <= 0 or self.points >= self.expected_points

    @property
    def finite(self) -> bool:
        return all(_finite(record) for record in self.records)

    @property
    def complete(self) -> bool:
        """Every expected material point present, and every one of them finite."""
        return self.present and self.finite and bool(self.records)

    def as_dict(self) -> dict:
        return {"step": self.step, "increment": self.increment,
                "time": self.time, "points": self.points,
                "expected_points": self.expected_points,
                "present": self.present, "finite": self.finite,
                "complete": self.complete}


@dataclass
class History:
    """A probe history, grouped into the increments it actually describes."""

    raw_output_records: int = 0
    increments: list = field(default_factory=list)
    material_points_per_increment: int = 0

    @property
    def complete_increments(self) -> int:
        """How many increments are complete, counted from the start.

        Counted as a PREFIX, not a total: an analysis that produced good
        increments, then a broken one, then more good ones has not given a
        history a verification can walk, and counting the later ones would
        say it had.
        """
        seen = 0
        for increment in self.increments:
            if not increment.complete:
                break
            seen += 1
        return seen

    @property
    def total_increments(self) -> int:
        return len(self.increments)

    @property
    def complete(self) -> bool:
        """Is every increment of this history complete?"""
        return bool(self.increments) and self.complete_increments == len(self.increments)

    @property
    def first_incomplete_increment(self) -> Optional[dict]:
        for increment in self.increments:
            if not increment.complete:
                return increment.as_dict()
        return None

    @property
    def first_non_finite_material_point(self) -> Optional[dict]:
        for increment in self.increments:
            for record in increment.records:
                if not _finite(record):
                    step, number, element, point = identity(record)
                    return {"step": step, "increment": number,
                            "element": element, "point": point,
                            "time": float(record.get("time") or 0.0)}
        return None

    @property
    def last_complete(self) -> tuple[int, int]:
        """The (step, increment) of the last complete increment of the prefix."""
        seen = (0, 0)
        for increment in self.increments:
            if not increment.complete:
                break
            seen = (increment.step, increment.increment)
        return seen

    def prefix(self) -> list:
        """The records of the complete increments, in order."""
        out: list = []
        for increment in self.increments[:self.complete_increments]:
            out.extend(increment.records)
        return out

    def as_dict(self) -> dict:
        return {
            "raw_output_records": self.raw_output_records,
            "total_increments": self.total_increments,
            "complete_increments": self.complete_increments,
            "material_points_per_increment": self.material_points_per_increment,
            "first_incomplete_increment": self.first_incomplete_increment,
            "first_non_finite_material_point": self.first_non_finite_material_point,
            "complete": self.complete,
        }

    def reason(self) -> str:
        if not self.increments:
            return "the run recorded no history at all"
        if self.complete:
            return (f"{self.complete_increments} increment(s), every one with "
                    f"all {self.material_points_per_increment} of its material "
                    f"points present and finite, from "
                    f"{self.raw_output_records} output records")
        broken = self.first_non_finite_material_point
        where = self.first_incomplete_increment or {}
        detail = (f"step {broken['step']} increment {broken['increment']} "
                  f"element {broken['element']} point {broken['point']}"
                  if broken else
                  f"step {where.get('step')} increment {where.get('increment')}, "
                  f"which produced {where.get('points')} of "
                  f"{where.get('expected_points')} material points")
        return (f"{self.complete_increments} complete increment(s) of "
                f"{self.total_increments} before {detail}; "
                f"{self.raw_output_records} output records in all, at "
                f"{self.material_points_per_increment} material points per "
                f"increment -- which is why a count of records is not a count "
                f"of increments")


def group(records: Sequence[dict], expected_points: int = 0) -> History:
    """Group a flat probe history into the increments it describes.

    ``expected_points`` is how many material points an increment of this
    model should produce, when the caller knows it -- the element's
    integration points, from the deck that was generated. Without it the
    count is inferred from the history, which is right whenever the history
    holds more than one increment and cannot be right when it holds only a
    partial one: six records of an eight-point element look like a complete
    six-point increment to anything with nothing else to compare them to.
    """
    found = History(raw_output_records=len(records or ()))
    if not records:
        return found
    order: list = []
    buckets: dict = {}
    for record in records:
        step, number, _element, _point = identity(record)
        key = (step, number)
        if key not in buckets:
            buckets[key] = Increment(step=step, increment=number,
                                     time=float(record.get("time") or 0.0))
            order.append(key)
        buckets[key].records.append(record)
    increments = [buckets[key] for key in order]
    # How many material points an increment of THIS model produces, taken
    # from the increments themselves rather than from the element type: a
    # deck can carry section points, and the probe records what it records.
    if expected_points > 0:
        expected = int(expected_points)
    else:
        counts = collections.Counter(increment.points for increment in increments)
        expected = (max(counts, key=lambda value: (counts[value], value))
                    if counts else 0)
    for increment in increments:
        increment.expected_points = expected
    found.increments = increments
    found.material_points_per_increment = expected
    return found


def complete_increments(records: Sequence[dict], expected_points: int = 0) -> int:
    """How many whole increments from the start of this history are usable."""
    return group(records, expected_points).complete_increments


#: Integration points per element, by Abaqus element type. Only the elements
#: this harness generates decks for; anything else falls back to inferring
#: the count from the history, which is right whenever the history holds
#: more than one increment.
POINTS_PER_ELEMENT = {
    "C3D8": 8, "C3D8H": 8, "C3D8R": 1,
    "C3D20": 27, "C3D20H": 27, "C3D20R": 8,
    "C3D4": 1, "C3D4H": 1, "C3D10": 4, "C3D10H": 4,
    "CPE4": 4, "CPE4H": 4, "CPE4R": 1, "CPE3": 1, "CPE8": 9, "CPE8R": 4,
    "CPS4": 4, "CPS4R": 1, "CPS3": 1, "CPS8": 9, "CPS8R": 4,
    "CAX4": 4, "CAX4H": 4, "CAX4R": 1, "CAX3": 1, "CAX8": 9, "CAX8R": 4,
}


def points_for(element_type: str) -> int:
    """How many material points one element of this type reports, or 0."""
    return POINTS_PER_ELEMENT.get(str(element_type or "").strip().upper(), 0)
