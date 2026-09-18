"""Five fields name a row, and records are not increments.

Both halves were bought with a wrong number that no tolerance would have
caught: a boundary condition rebuilt from the wrong one of four increment 1s,
and a complete history refused by arithmetic between two different quantities.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from umat_oti.contract import (COUNT_FIELDS, FrameError, IDENTITY_FIELDS,
                               check_counts, count_history, frame_key,
                               group_by_increment, increment_key, point_key)
from repository_paths import verified_fixtures

#: Found relative to this checkout; an absolute path is true on one computer.
def _fixtures() -> list:
    return verified_fixtures()


def _five_field_fixture(*, spanning_steps: bool = False):
    """A committed fixture carrying all five identity fields.

    ``spanning_steps`` asks for one whose rows cross a step boundary. That is
    the only place an increment number can collide, because Abaqus restarts the
    numbering in each step -- so once every fixture carries five fields, taking
    the first one gets a single-step history with nothing to collide, and a
    test written against that is asserting which fixture sorts first.
    """
    for path in _fixtures():
        payload = json.loads(path.read_text())
        rows = payload.get("original") or []
        if not (rows and all(f in rows[0] for f in IDENTITY_FIELDS)):
            continue
        if spanning_steps and len({r.get("step") for r in rows}) < 2:
            continue
        return path, payload
    return None, None


# ---------------------------------------------------------------------------
# the five fields
# ---------------------------------------------------------------------------
def test_five_fields_name_a_row_and_no_subset_does():
    assert IDENTITY_FIELDS == ("element", "point", "step", "increment", "time")
    assert len(IDENTITY_FIELDS) == 5


def test_a_row_missing_any_one_of_them_is_refused_by_name():
    complete = {"element": 1, "point": 1, "step": 1, "increment": 1, "time": 0.0}
    frame_key(complete)
    for dropped in IDENTITY_FIELDS:
        partial = {k: v for k, v in complete.items() if k != dropped}
        with pytest.raises(FrameError) as exc:
            frame_key(partial)
        assert dropped in str(exc.value)
        # And the message explains why, not merely that.
        assert "increments from 1 again in every step" in str(exc.value)


def test_a_null_field_is_as_absent_as_a_missing_one():
    with pytest.raises(FrameError):
        frame_key({"element": 1, "point": 1, "step": None,
                   "increment": 1, "time": 0.0})


def test_step_is_in_the_increment_key_and_element_point_are_not():
    """An increment is a moment in the analysis; a point is a place in the
    mesh. Mixing them would make two integration points of one increment look
    like two increments."""
    row = {"element": 3, "point": 7, "step": 2, "increment": 4, "time": 1.5}
    assert increment_key(row).as_tuple() == (2, 4, 1.5)
    assert point_key(row).as_tuple() == (3, 7)
    assert frame_key(row).as_tuple() == (3, 7, 2, 4, 1.5)


def test_four_increment_ones_are_four_different_rows():
    """The defect, as a unit test: a four-step cycle restarts the numbering."""
    rows = [{"element": 1, "point": 1, "step": s, "increment": 1,
             "time": float(s - 1)} for s in (1, 2, 3, 4)]
    assert len({increment_key(r).as_tuple() for r in rows}) == 4
    assert len({r["increment"] for r in rows}) == 1
    assert len(group_by_increment(rows)) == 4


def test_the_real_fixture_shows_the_collision():
    """Measured on a committed fixture that crosses a step boundary.

    Which is where the collision lives: Abaqus restarts increment numbering in
    every step, so a single-step history has nothing to collide and says
    nothing either way.
    """
    path, payload = _five_field_fixture(spanning_steps=True)
    if payload is None:
        pytest.skip("no committed fixture spans more than one step")
    rows = payload["original"]
    by_increment_alone = {r["increment"] for r in rows}
    by_full_key = {increment_key(r).as_tuple() for r in rows}
    assert len(by_full_key) == len(rows)
    assert len(by_increment_alone) < len(by_full_key), (
        f"{path.name}: increment alone gives {len(by_increment_alone)} keys "
        f"for {len(rows)} rows")
    # And the rows that share an increment number are genuinely different.
    ones = [r for r in rows if r["increment"] == 1]
    assert len(ones) > 1
    assert len({r["step"] for r in ones}) == len(ones)
    assert len({round(r["stress"][0], 6) for r in ones}) == len(ones)


# ---------------------------------------------------------------------------
# the two counts
# ---------------------------------------------------------------------------
def test_five_counts_travel_together():
    assert COUNT_FIELDS == ("records_carried", "increments_carried",
                            "material_points_per_increment",
                            "material_point_carried",
                            "material_points_available")


def test_a_c3d8_history_has_more_records_than_increments():
    """35 increments at 8 integration points is 280 records. Reporting the
    first as the second is the whole defect."""
    rows = [{"element": 1, "point": p, "step": 1, "increment": i,
             "time": i * 0.1} for i in range(1, 36) for p in range(1, 9)]
    counts = count_history(rows, material_points_available=8)
    assert counts.records_carried == 280
    assert counts.increments_carried == 35
    assert counts.material_points_per_increment == 8
    assert counts.records_carried != counts.increments_carried
    assert "280 record(s) = 35 increment(s) x 8 point(s)" in counts.describe()


def test_counts_that_do_not_multiply_are_refused():
    declared = {"records_carried": 280, "increments_carried": 280,
                "material_points_per_increment": 8}
    problems = check_counts(declared)
    assert problems
    assert "another one wearing the wrong name" in problems[0]


def test_a_document_carrying_only_one_count_is_refused():
    problems = check_counts({"increments_carried": 35})
    assert problems
    assert "35 of the 280 asked for" in problems[0]


def test_more_increments_than_records_is_impossible():
    problems = check_counts({"records_carried": 6, "increments_carried": 35,
                             "material_points_per_increment": 0})
    assert any("cannot be made of fewer than one record" in p for p in problems)


def test_uneven_points_per_increment_is_zero_and_never_an_average():
    """An increment short of a point did not produce the state a comparison
    would compare, and saying 'about seven' would hide exactly that."""
    rows = [{"element": 1, "point": p, "step": 1, "increment": 1, "time": 0.1}
            for p in (1, 2, 3)]
    rows += [{"element": 1, "point": p, "step": 1, "increment": 2, "time": 0.2}
             for p in (1, 2)]
    counts = count_history(rows)
    assert counts.material_points_per_increment == 0
    assert counts.records_carried == 5
    assert counts.increments_carried == 2
    assert "uneven" in counts.describe()


def test_the_counts_are_checked_against_the_rows_not_only_each_other():
    rows = [{"element": 1, "point": 1, "step": 1, "increment": i, "time": i * 0.1}
            for i in range(1, 7)]
    assert check_counts({"records_carried": 6, "increments_carried": 6,
                         "material_points_per_increment": 1}, rows) == []
    problems = check_counts({"records_carried": 6, "increments_carried": 3,
                             "material_points_per_increment": 2}, rows)
    assert any("distinct (step, increment, time)" in p for p in problems)


def test_points_per_increment_cannot_exceed_points_available():
    problems = check_counts({"records_carried": 16, "increments_carried": 2,
                             "material_points_per_increment": 8,
                             "material_points_available": 4})
    assert any("exceeds material_points_available" in p for p in problems)


def test_the_real_fixtures_counts_agree_with_their_own_rows():
    path, payload = _five_field_fixture()
    if payload is None:
        pytest.skip("no five-field fixture in the checkout beside this one")
    assert check_counts(payload["finite_history"], payload["original"]) == []
    assert check_counts(payload["finite_history"], payload["converted"]) == []
    counts = count_history(payload["original"])
    declared = payload["finite_history"]
    assert counts.records_carried == declared["records_carried"]
    assert counts.increments_carried == declared["increments_carried"]
