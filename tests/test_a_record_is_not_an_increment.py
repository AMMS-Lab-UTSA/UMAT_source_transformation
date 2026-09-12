"""Eight records per increment, and six of them is not one increment.

Abaqus calls a UMAT once per material point per increment. A single-element
C3D8 job of thirty-five increments writes two hundred and eighty probe
records; the same job on a CPE4 writes one hundred and forty. Neither number
is thirty-five, and neither counts anything a constitutive law did once.

Counting the flattened records as increments was not cosmetic:

* a verification reported "agreed over 280 increments" about a thirty-five
  increment analysis -- measured on CompresibleNeoHookean.for and four other
  controls, every one of which reported its record count as its increment
  count;
* a prefix of twenty-two records -- two complete increments and six
  integration points of a third -- cleared a minimum of five "increments"
  more than four times over;
* the safe-loading reconstruction read the edge of a material's domain off a
  partially evaluated increment, which is not a state the solver reached.

An increment is complete only when every material point it is expected to
produce is present and finite. Every one: a solver's answer for an increment
whose seventh point returned a value that is not a number is contaminated,
and its first six say nothing to the contrary.
"""
import math

from umat_oti.abaqus.amplitude_search import (ENOUGH_COMPLETE_INCREMENTS,
                                              enough_to_drive)
from umat_oti.abaqus.frames import complete_increments, group
from umat_oti.abaqus.safe_loading import examine

POINTS = 8


def _increment(number: int, bad_point: int = 0, points: int = POINTS,
               step: int = 1):
    return [{"step": step, "increment": number, "element": 1, "point": point,
             "time": number * 0.1,
             "STRESS": [float("nan") if point == bad_point else 1.0],
             "STATEV": [0.0], "DDSDDE": [1.0]}
            for point in range(1, points + 1)]


def _history(increments: int, bad_at: tuple = ()):
    records = []
    for number in range(1, increments + 1):
        bad = bad_at[1] if bad_at and bad_at[0] == number else 0
        records.extend(_increment(number, bad_point=bad))
    return records


# ---- the headline: six raw records are not one increment -----------------
def test_six_good_records_are_not_even_one_complete_increment():
    six = _increment(1)[:6]
    assert len(six) == 6
    grouped = group(six, expected_points=POINTS)
    assert grouped.raw_output_records == 6
    assert grouped.total_increments == 1
    # Six of eight points. The increment is not complete, so the count of
    # complete increments is zero -- not six, and not one.
    assert grouped.complete_increments == 0
    assert complete_increments(six, expected_points=POINTS) == 0


def test_without_the_element_a_partial_increment_cannot_be_told_from_a_whole_one():
    """Honest about the limit of inference. Six records of an eight-point
    element look like a complete six-point increment to anything with
    nothing else to compare them against, which is why the deck's element is
    passed in wherever the caller knows it."""
    six = _increment(1)[:6]
    assert group(six).material_points_per_increment == 6
    assert group(six, expected_points=POINTS).material_points_per_increment == 8


def test_twenty_two_records_are_two_complete_increments():
    """The measured case: 22 usable records is 2 increments and 6 points."""
    history = _history(2) + _increment(3, bad_point=7)
    assert len(history) == 24
    grouped = group(history)
    assert grouped.raw_output_records == 24
    assert grouped.material_points_per_increment == 8
    assert grouped.complete_increments == 2, (
        "two complete increments, not twenty-two of anything")
    assert grouped.last_complete == (1, 2)


def test_a_seventh_point_that_is_not_a_number_spoils_its_increment():
    grouped = group(_increment(1, bad_point=7))
    assert grouped.complete_increments == 0
    where = grouped.first_non_finite_material_point
    assert (where["step"], where["increment"], where["point"]) == (1, 1, 7)


def test_a_missing_point_spoils_its_increment_too():
    """Not only non-finite: an increment that never produced its eighth
    point did not produce the state the verification would compare."""
    history = _history(3)[:-1]          # drop the last point of increment 3
    grouped = group(history)
    assert grouped.material_points_per_increment == 8
    assert grouped.complete_increments == 2
    incomplete = grouped.first_incomplete_increment
    assert incomplete["increment"] == 3
    assert incomplete["points"] == 7 and incomplete["expected_points"] == 8


# ---- and every gate downstream counts increments --------------------------
def test_the_search_gate_counts_increments_not_records():
    """Four complete increments is 32 records. Records would clear a minimum
    of five; increments correctly do not."""
    four = _history(4)
    assert len(four) == 32
    assert ENOUGH_COMPLETE_INCREMENTS == 5
    assert enough_to_drive(four) is False, (
        "32 records must not clear a minimum of 5 increments")
    assert enough_to_drive(_history(5)) is True


def test_the_safe_prefix_counts_increments_not_records():
    prefix = examine(_history(2) + _increment(3, bad_point=7))
    assert prefix.usable == 2, "complete increments"
    assert prefix.records == 24, "raw output records, kept separately"
    assert prefix.complete is False
    assert prefix.last_safe == (1, 2)
    assert prefix.first_bad == (1, 3)


def test_the_counts_are_reported_under_names_that_say_what_they_are():
    grouped = group(_history(2) + _increment(3, bad_point=7)).as_dict()
    for name in ("raw_output_records", "complete_increments",
                 "material_points_per_increment", "first_incomplete_increment",
                 "first_non_finite_material_point", "total_increments"):
        assert name in grouped, name
    assert grouped["raw_output_records"] != grouped["complete_increments"]


def test_the_reason_says_why_records_are_not_increments():
    said = group(_history(2) + _increment(3, bad_point=7)).reason()
    assert "complete increment(s)" in said
    assert "material points per increment" in said
    assert "a count of records is not a count of increments" in said


# ---- element type changes the ratio, and nothing else --------------------
def test_a_four_point_element_groups_the_same_way():
    """CPE4 writes four records per increment, C3D8 writes eight. The
    grouping reads it off the history rather than assuming either."""
    records = []
    for number in range(1, 6):
        records.extend(_increment(number, points=4))
    grouped = group(records)
    assert grouped.raw_output_records == 20
    assert grouped.material_points_per_increment == 4
    assert grouped.complete_increments == 5


def test_increments_of_different_steps_are_different_increments():
    records = _increment(1, step=1) + _increment(1, step=2)
    grouped = group(records)
    assert grouped.total_increments == 2
    assert grouped.complete_increments == 2


def test_a_later_good_increment_does_not_repair_an_earlier_broken_one():
    """The prefix is what a verification can walk. An analysis that broke and
    then recovered has not given it one."""
    history = _history(2) + _increment(3, bad_point=2) + _increment(4)
    grouped = group(history)
    assert grouped.total_increments == 4
    assert grouped.complete_increments == 2


def test_an_empty_history_is_no_increments_rather_than_an_error():
    grouped = group([])
    assert grouped.raw_output_records == 0
    assert grouped.complete_increments == 0
    assert grouped.complete is False
    assert "recorded no history at all" in grouped.reason()


def test_an_infinity_spoils_an_increment_as_surely_as_a_nan():
    records = _increment(1)
    records[3]["STATEV"] = [math.inf]
    assert group(records).complete_increments == 0


def test_a_cohesive_element_reports_the_points_on_its_interface():
    """Cohesive elements integrate across the face, not through the volume.

    Until these were listed, ``points_for`` returned 0 for every cohesive deck
    and the count fell back to being inferred from the history. That inference
    is right for a run that completed and wrong for a truncated one, where the
    count it infers is whatever the last partial increment happened to write --
    and five of the filed cohesive decks exist precisely because their runs are
    expected to be difficult.
    """
    from umat_oti.abaqus import frames

    assert frames.points_for("COH2D4") == 2
    assert frames.points_for("COH2D4T") == 2
    assert frames.points_for("COH3D6") == 3
    assert frames.points_for("COH3D8") == 4
    assert frames.points_for("COH3D8T") == 4
    # and the coupled variant is the same element as far as counting goes
    for plain in ("COH2D4", "COH3D6", "COH3D8"):
        assert frames.points_for(plain) == frames.points_for(plain + "T")


def test_a_truncated_cohesive_increment_is_not_counted_as_complete():
    """The point of knowing the count: 4 of 8 records is half an increment.

    A COH3D8 writes four material points per increment. A run that died partway
    through increment 2 leaves two of them, and inferring the count from the
    history would read those two as the whole of a complete increment.
    """
    from umat_oti.abaqus import frames

    records = []
    for increment, points in ((1, 4), (2, 2)):
        for point in range(1, points + 1):
            records.append({"step": 1, "increment": increment,
                            "element": 1, "point": point,
                            "STRESS": [1.0, 0.0, 0.0],
                            "STATEV": [0.5], "DDSDDE": [1.0]})

    inferred = frames.group(records)
    told = frames.group(records, expected_points=frames.points_for("COH3D8"))

    assert told.complete_increments == 1
    assert told.material_points_per_increment == 4
    assert told.first_incomplete_increment["increment"] == 2
    assert told.first_incomplete_increment["points"] == 2
    # and this is what the fallback would have said instead
    assert inferred.complete_increments >= told.complete_increments
