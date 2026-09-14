"""What names one row of a history, and the two counts that are not each other.

This module is SHARED VERBATIM between UMAT_source_transformation and
Residual_Assembler, like :mod:`umat_oti.contract.tristate`. It imports nothing
but the standard library so that the consuming repository can carry a
byte-identical copy rather than a reimplementation, and the digest in
``contract_lock.json`` fails in both repositories if the two drift. Two
implementations of one identity rule are two identity rules, and the last time
these two ends disagreed about which count was which, a complete 280-record
history was refused as "35 of the 280 asked for".

This module exists because both halves of it were bought with a wrong number
that no tolerance would have caught.

Five fields name a row, not one
-------------------------------
``element``, ``point``, ``step``, ``increment``, ``time``.

``step`` is half the identity of an increment and was missing. Abaqus numbers
increments from 1 again in every step, so a four-step J2 cycle has four
increment 1s. Measured on the committed ``j2_props`` fixture: 35 records over
4 steps, in which increment 1 occurs four times carrying stresses of 269.2,
1571.5, -264.0 and -182.6 -- four different states of the material. A consumer
reconstructing boundary conditions from ``increment`` alone picked the wrong
one and was wrong by 3.0 relative. That is a different deformation, not a
tolerance.

``element`` and ``point`` are the other half. A C3D8 hands back one record per
integration point per increment, so without them a consumer cannot group rows
into increments at all.

``time`` is kept in the key rather than derived from it, because two runs of
the same deck must produce the same key and a step's clock is the only thing
that says where in the step a row sits.

Records and increments are two counts
-------------------------------------
A record is one material point of one increment. A 35-increment C3D8 history
is 280 records. Reporting the first as the second is the defect this module
prevents: an exporter reported records as increments, a loader then compared
one against the other, and a complete history was refused as "35 of the 280
asked for" -- a correct fixture rejected by arithmetic between two different
quantities.

So five counts travel together and none may stand for another:

``records_carried``
    rows in the carried history.
``increments_carried``
    distinct ``(step, increment, time)`` among them.
``material_points_per_increment``
    rows per increment, or 0 when uneven -- uneven is not a number to average,
    because an increment short of a point did not produce the state a
    comparison would compare.
``material_point_carried``
    which integration point these rows are.
``material_points_available``
    how many the RUN wrote, which is not how many are kept.

:func:`check_counts` is the arithmetic, stated once so that neither side
invents its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = ["FrameKey", "PointKey", "IncrementKey", "frame_key", "point_key",
           "increment_key", "FrameError", "HistoryCounts", "count_history",
           "check_counts", "IDENTITY_FIELDS", "COUNT_FIELDS",
           "group_by_increment"]

#: The five fields that name one row. Order is part of the contract: a
#: consumer sorting rows must not have to guess it.
IDENTITY_FIELDS: tuple = ("element", "point", "step", "increment", "time")

#: The five counts that must travel together.
COUNT_FIELDS: tuple = ("records_carried", "increments_carried",
                       "material_points_per_increment",
                       "material_point_carried", "material_points_available")


class FrameError(ValueError):
    """A history row, or a count, that cannot be read without guessing."""


@dataclass(frozen=True)
class PointKey:
    """Which material point: element and integration point together."""

    element: Any
    point: Any

    def as_tuple(self) -> tuple:
        return (self.element, self.point)


@dataclass(frozen=True)
class IncrementKey:
    """Which increment: step, increment number and time together.

    ``step`` is in here and not optional. Without it a four-step cycle has
    four increment 1s and they are four different states of the material.
    """

    step: Any
    increment: Any
    time: Any

    def as_tuple(self) -> tuple:
        return (self.step, self.increment, self.time)


@dataclass(frozen=True)
class FrameKey:
    """The whole five-field identity of one row."""

    point: PointKey
    increment: IncrementKey

    def as_tuple(self) -> tuple:
        return self.point.as_tuple() + self.increment.as_tuple()

    def as_dict(self) -> dict:
        return {"element": self.point.element, "point": self.point.point,
                "step": self.increment.step,
                "increment": self.increment.increment,
                "time": self.increment.time}

    def __str__(self) -> str:  # pragma: no cover - display only
        return (f"element {self.point.element} point {self.point.point} "
                f"step {self.increment.step} increment "
                f"{self.increment.increment} at t={self.increment.time}")


def _required(record: Mapping[str, Any], field: str) -> Any:
    if not isinstance(record, Mapping):
        raise FrameError(f"a history row must be an object; got "
                         f"{type(record).__name__}")
    if field not in record or record[field] is None:
        missing = [f for f in IDENTITY_FIELDS
                   if f not in record or record[f] is None]
        raise FrameError(
            f"this history row carries no {field!r}, so it cannot be told "
            f"apart from another row. All five of {', '.join(IDENTITY_FIELDS)} "
            f"are required and {', '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} absent. Abaqus numbers "
            f"increments from 1 again in every step and a C3D8 writes one row "
            f"per integration point, so no subset of these five names a row.")
    return record[field]


def point_key(record: Mapping[str, Any]) -> PointKey:
    return PointKey(_required(record, "element"), _required(record, "point"))


def increment_key(record: Mapping[str, Any]) -> IncrementKey:
    return IncrementKey(_required(record, "step"),
                        _required(record, "increment"),
                        _required(record, "time"))


def frame_key(record: Mapping[str, Any]) -> FrameKey:
    """The five-field identity of one row, refusing any row missing one."""
    return FrameKey(point_key(record), increment_key(record))


def group_by_increment(records: Iterable[Mapping[str, Any]]) -> dict:
    """Rows grouped by ``(step, increment, time)``, in first-seen order.

    This is what "how long is this history" means: the number of groups, never
    the number of rows.
    """
    grouped: dict = {}
    for record in records:
        grouped.setdefault(increment_key(record).as_tuple(), []).append(record)
    return grouped


# ---------------------------------------------------------------------------
# the counts
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HistoryCounts:
    """The five counts, with the arithmetic between them stated."""

    records_carried: int
    increments_carried: int
    material_points_per_increment: int
    material_point_carried: Any = None
    material_points_available: Optional[int] = None

    def as_dict(self) -> dict:
        return {"records_carried": self.records_carried,
                "increments_carried": self.increments_carried,
                "material_points_per_increment":
                    self.material_points_per_increment,
                "material_point_carried": self.material_point_carried,
                "material_points_available": self.material_points_available}

    def describe(self) -> str:
        points = (f"{self.material_points_per_increment} point(s) per increment"
                  if self.material_points_per_increment
                  else "an uneven number of points per increment")
        return (f"{self.records_carried} record(s) = "
                f"{self.increments_carried} increment(s) x {points}")


def count_history(records: Sequence[Mapping[str, Any]], *,
                  material_points_available: Optional[int] = None
                  ) -> HistoryCounts:
    """Derive the five counts from the rows themselves, refusing a bad row."""
    rows = list(records)
    groups = group_by_increment(rows)
    sizes = {len(v) for v in groups.values()}
    per_increment = sizes.pop() if len(sizes) == 1 else 0
    points = {point_key(r).as_tuple() for r in rows}
    carried = next(iter(points))[1] if len(points) == 1 else None
    return HistoryCounts(
        records_carried=len(rows),
        increments_carried=len(groups),
        material_points_per_increment=per_increment,
        material_point_carried=carried,
        material_points_available=material_points_available)


def check_counts(declared: Mapping[str, Any],
                 records: Optional[Sequence[Mapping[str, Any]]] = None
                 ) -> list:
    """Every way the five counts can contradict each other or the rows.

    Returns a list of readable problems; empty means they agree. A list rather
    than a raise, so a caller can report all of them at once instead of
    fixing one and discovering the next.
    """
    problems: list = []
    if not isinstance(declared, Mapping):
        return [f"the counts block must be an object; got "
                f"{type(declared).__name__}"]

    missing = [f for f in ("records_carried", "increments_carried",
                           "material_points_per_increment")
               if declared.get(f) is None]
    if missing:
        problems.append(
            f"{', '.join(missing)} absent. Records and increments are two "
            f"different counts and a document carrying only one of them "
            f"forces its reader to guess which quantity it is looking at -- "
            f"which is how a complete 280-record history was refused as "
            f"'35 of the 280 asked for'.")
        return problems

    records_carried = int(declared["records_carried"])
    increments_carried = int(declared["increments_carried"])
    per_increment = int(declared["material_points_per_increment"])

    if records_carried < 1:
        problems.append(f"records_carried is {records_carried}")
    if increments_carried < 1:
        problems.append(f"increments_carried is {increments_carried}")
    if increments_carried > records_carried:
        problems.append(
            f"increments_carried ({increments_carried}) exceeds "
            f"records_carried ({records_carried}): an increment cannot be "
            f"made of fewer than one record")
    if per_increment:
        expected = increments_carried * per_increment
        if expected != records_carried:
            problems.append(
                f"records_carried is {records_carried} but "
                f"{increments_carried} increment(s) x {per_increment} "
                f"point(s) per increment is {expected}. One of these three "
                f"numbers is another one wearing the wrong name.")

    available = declared.get("material_points_available")
    if available is not None:
        if int(available) < 1:
            problems.append(f"material_points_available is {available}")
        elif per_increment and per_increment > int(available):
            problems.append(
                f"material_points_per_increment ({per_increment}) exceeds "
                f"material_points_available ({available})")

    if records is not None:
        actual = count_history(list(records))
        if actual.records_carried != records_carried:
            problems.append(
                f"records_carried says {records_carried} and the history has "
                f"{actual.records_carried} row(s)")
        if actual.increments_carried != increments_carried:
            problems.append(
                f"increments_carried says {increments_carried} and the "
                f"history covers {actual.increments_carried} distinct "
                f"(step, increment, time) key(s). Counting rows instead of "
                f"increments is the error this check exists for.")
        if per_increment and \
                actual.material_points_per_increment != per_increment:
            problems.append(
                f"material_points_per_increment says {per_increment} and the "
                f"history has "
                f"{actual.material_points_per_increment or 'an uneven number'}")
        declared_point = declared.get("material_point_carried")
        if declared_point is not None and actual.material_point_carried is not None \
                and declared_point != actual.material_point_carried:
            problems.append(
                f"material_point_carried says {declared_point!r} and the rows "
                f"are point {actual.material_point_carried!r}")
    return problems
