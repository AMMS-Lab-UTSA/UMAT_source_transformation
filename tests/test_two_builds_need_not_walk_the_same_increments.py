"""A comparison has to pair records by where they are, not by their position.

A displacement-controlled step caps the increment at its initial size, so
both builds take the same increments and the histories line up one for one.
A load-controlled step does not. Abaqus cuts back when Newton needs it to,
and the converted routine does not return the author's analytic DDSDDE -- it
returns the OTI tangent, and a different tangent converges at a different
rate. Measured on BodyForce-Growth-2Stages.for: the original took the ten
increments asked for and the converted build took sixteen, both completing.

Two things were wrong with that. The job was called failed for running MORE
increments than requested, which is a solver recovering rather than a run
that stopped short. And had it been compared, increment 3 of one would have
been held against increment 3 of the other at a different time.

Forcing both onto a fixed increment is not the answer either: measured on
the same model, the ORIGINAL then reports FIXED TIME INCREMENT IS TOO LARGE
at t=0.15, because its stiffness changes along the path and it needs the
cutbacks it was denied.
"""
from umat_oti.abaqus.compare import SAME_TIME, align_by_time


def _record(time: float, stress: float, step: int = 1, point: int = 1) -> dict:
    return {"step": step, "element": 1, "point": point, "time": time,
            "STRESS": [stress], "STATEV": []}


def test_identical_histories_are_left_exactly_as_they_are():
    history = [_record(t / 10, t) for t in range(1, 11)]
    left, right, note = align_by_time(history, history)
    assert left == history and right == history
    assert note == "", "an untroubled comparison should say nothing"


def test_a_build_that_cut_back_is_paired_on_the_times_it_shares():
    original = [_record(t / 10, t) for t in range(1, 11)]
    converted = [_record(t, t * 10) for t in (0.1, 0.15, 0.175, 0.2, 0.3)]
    left, right, note = align_by_time(original, converted)
    assert [r["time"] for r in left] == [0.1, 0.2, 0.3]
    assert len(right) == len(left)
    assert "10" in note and "5" in note and "3" in note


def test_the_note_says_how_much_of_each_history_was_used():
    """A comparison resting on three of forty increments is a different
    claim from one resting on forty, and has to read as one."""
    original = [_record(t / 10, t) for t in range(1, 11)]
    converted = [_record(0.1, 1.0)]
    _left, _right, note = align_by_time(original, converted)
    assert "walked different increments" in note
    assert "share by step, integration point and time" in note


def test_records_from_different_integration_points_do_not_cross():
    original = [_record(0.1, 1.0, point=1), _record(0.1, 2.0, point=2)]
    converted = [_record(0.1, 9.0, point=2)]
    left, right, _note = align_by_time(original, converted)
    assert [r["point"] for r in left] == [2]
    assert right[0]["STRESS"] == [9.0]


def test_records_from_different_steps_do_not_cross():
    original = [_record(0.5, 1.0, step=1), _record(0.5, 2.0, step=2)]
    converted = [_record(0.5, 9.0, step=2)]
    left, _right, _note = align_by_time(original, converted)
    assert [r["step"] for r in left] == [2]


def test_two_times_closer_than_the_printed_precision_are_one_increment():
    original = [_record(0.1, 1.0)]
    converted = [_record(0.1 + SAME_TIME / 10, 1.0)]
    left, _right, _note = align_by_time(original, converted)
    assert len(left) == 1


def test_nothing_in_common_pairs_nothing():
    left, right, note = align_by_time([_record(0.1, 1.0)], [_record(0.7, 1.0)])
    assert left == [] and right == []
    assert "0" in note


def test_a_solver_that_recovered_is_not_a_job_that_failed():
    import pathlib
    source = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "src", "umat_oti", "abaqus", "job_status.py").read_text()
    assert "short = (status.increments is not None" in source
    assert "the solver cut back and recovered" in source
    # fewer is still short, and short is still a failure
    assert "status.increments < expected_increments" in source


def test_the_verifier_aligns_before_it_compares():
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "verify_store_in_abaqus.py").read_text()
    block = text[:text.index("primal = compare_primal(compared_original")]
    assert "align_by_time(" in block.rsplit("def ", 1)[-1], (
        "the histories must be paired before they are compared")
