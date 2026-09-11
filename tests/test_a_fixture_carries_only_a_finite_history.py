"""A regression fixture is what later runs are compared against, so it is the
one artefact nothing downstream can catch an error in.

Everything else in this pipeline is checked by something after it. A fixture is
not: it IS the check. A NaN frozen into one does not fail -- it propagates, and
the comparison that should have caught it is being made against the NaN. An
increment that is one material point short does not fail either; it quietly
narrows what every later run is held to.

So the rule is absolute and it is enforced at freeze time rather than argued
about at use time: a fixture carries a completely finite successful history and
nothing else. Every increment present, every material point present, every
number a number. A case that fails that is refused with the reason, not written
with a warning.

Checked twice on purpose, because either reading alone can be fooled. What the
batch RECORDED about the run -- the gates it measured, and the grouping that
says where the first incomplete increment and the first value that is not a
number are. And the numbers actually about to be written, scanned one at a
time, because "this history was finite" and "these numbers are finite" are two
different claims and a fixture is the second.
"""
import json
import os
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from export_residual_fixture import (FixtureRefused, REQUIRED_GATES,  # noqa: E402
                                     freeze, fixture_from, window_start,
                                     why_this_may_not_be_frozen)

CORPUS = REPO / "tests" / "fixtures" / "corpus"
FROZEN = REPO / "tests" / "fixtures" / "verified"
#: The corpus run this evidence was measured on. It is 7 GB of Abaqus output,
#: so it lives beside the checkout rather than in it, and the tests that need
#: it skip when it is not on this machine. Derived from the checkout's location
#: rather than written out, because an absolute path under a home directory is
#: a property of one computer and means nothing to a reader of this file.
PASS9 = Path(os.environ.get("UMAT_OTI_CORPUS_RUN")
             or REPO.parent / "corpus_run" / "pass9")


@pytest.fixture(scope="module")
def control():
    return json.loads(
        (CORPUS / "results" / "store_verification.jsonl").read_text().strip())


def test_the_bundled_control_freezes(control):
    """The J2 control is this project's own source, it verified cleanly, and
    it is the permanent fixture everything else is read against.

    Measured: 6 increments carried from a run of 35 complete increments at 8
    material points each, every one finite, with all five recorded gates true.
    """
    frozen = freeze(control, CORPUS / "work")
    assert frozen["schema"] == "umat-oti/residual-fixture/1"
    assert len(frozen["original"]) == 6 == len(frozen["converted"])
    evidence = frozen["finite_history"]
    assert evidence["complete_finite_verification_run"] is True
    for gate in REQUIRED_GATES:
        assert evidence["evidence"][gate] is True, gate
    for side in ("original", "transformed"):
        grouping = evidence["history_grouping"][side]
        assert grouping["complete"] is True
        assert grouping["first_incomplete_increment"] is None
        assert grouping["first_non_finite_material_point"] is None
        assert grouping["complete_increments"] == 35
        assert grouping["material_points_per_increment"] == 8


def test_the_frozen_control_in_the_tree_is_finite_in_every_number():
    """The assertion restated against the file that is actually committed,
    because the one that matters is the one on disk."""
    paths = sorted(FROZEN.glob("*.json"))
    assert paths, f"no fixture is frozen in {FROZEN}"
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["finite_history"]["complete_finite_verification_run"] \
            is True, path.name
        counted = 0
        for side in ("original", "converted"):
            for record in payload[side]:
                for name in ("strain", "dstrain", "stress", "state", "ddsdde"):
                    for value in record.get(name) or ():
                        assert math.isfinite(float(value)), \
                            f"{path.name} {side} {record['increment']} {name}"
                        counted += 1
        assert counted > 100, path.name


def test_a_run_that_was_not_finite_end_to_end_is_refused(control):
    """Abaqus printing THE ANALYSIS HAS COMPLETED SUCCESSFULLY is a statement
    about the solver, not about the routine it called.

    Measured on BodyForce-Growth-2Stages.for: both builds "completed" 35
    increments and both were non-finite from the third.
    """
    row = dict(control, complete_finite_verification_run=False)
    row["discovery"] = dict(row["discovery"],
                            complete_finite_verification_run=False)
    with pytest.raises(FixtureRefused) as raised:
        freeze(row, CORPUS / "work")
    assert "complete_finite_verification_run=False" in str(raised.value)


def test_a_history_with_a_non_finite_material_point_is_refused(control):
    """Not "something went wrong": which element, which point, which
    increment. Shaped on the 38 pass9 records that carry one."""
    grouping = json.loads(json.dumps(control["history_grouping"]))
    grouping["original"]["first_non_finite_material_point"] = {
        "element": 1, "point": 3, "increment": 6, "step": 1, "time": 0.5}
    grouping["original"]["complete"] = False
    row = dict(control, history_grouping=grouping)
    with pytest.raises(FixtureRefused) as raised:
        freeze(row, CORPUS / "work")
    said = str(raised.value)
    assert "element 1 point 3 of increment 6" in said
    assert "not marked complete" in said


def test_a_history_with_an_incomplete_increment_is_refused(control):
    """An increment short of a material point did not produce the state a
    later comparison would compare."""
    grouping = json.loads(json.dumps(control["history_grouping"]))
    grouping["transformed"]["first_incomplete_increment"] = {
        "increment": 6, "points": 7, "expected_points": 8, "present": True,
        "finite": True, "time": 0.5}
    row = dict(control, history_grouping=grouping)
    with pytest.raises(FixtureRefused) as raised:
        freeze(row, CORPUS / "work")
    assert "first incomplete increment is 6" in str(raised.value)
    assert "7 of 8 material points" in str(raised.value)


def test_a_gate_that_was_never_measured_is_not_taken_as_passed(control):
    """A step whose result was never established is not a step that passed,
    and a fixture is exactly where that convention has to be pessimistic."""
    for gate in REQUIRED_GATES:
        row = dict(control, evidence={k: v for k, v in control["evidence"].items()
                                      if k != gate})
        with pytest.raises(FixtureRefused) as raised:
            freeze(row, CORPUS / "work")
        assert f"evidence.{gate}='not measured'" in str(raised.value)


def test_a_case_that_did_not_verify_is_refused(control):
    for stage in ("primal_disagreed", "tangent_not_verified",
                  "experiment_not_generated", "harness_error"):
        with pytest.raises(FixtureRefused) as raised:
            freeze(dict(control, stage=stage), CORPUS / "work")
        assert f"settled at {stage!r}" in str(raised.value)


def test_a_nan_in_the_numbers_is_refused_even_when_the_record_says_otherwise(
        control, tmp_path: Path):
    """The reading that cannot be talked out of. Every gate in the record says
    the run was finite; one number in the history is not; the fixture is
    refused on the number.
    """
    key = control["key"]
    for job in ("original", "transformed"):
        source = CORPUS / "work" / key / job / f"{job}_history.json"
        history = json.loads(source.read_text())
        folder = tmp_path / key / job
        folder.mkdir(parents=True)
        if job == "transformed":
            history[4]["DDSDDE"][7] = float("nan")
        (folder / f"{job}_history.json").write_text(json.dumps(history))
    with pytest.raises(FixtureRefused) as raised:
        freeze(control, tmp_path)
    said = str(raised.value)
    assert "ddsdde[7]" in said
    assert "nan" in said.lower()


def test_an_infinity_is_refused_the_same_way(control, tmp_path: Path):
    key = control["key"]
    for job in ("original", "transformed"):
        history = json.loads(
            (CORPUS / "work" / key / job / f"{job}_history.json").read_text())
        folder = tmp_path / key / job
        folder.mkdir(parents=True)
        if job == "original":
            history[3]["STRESS"][2] = float("inf")
        (folder / f"{job}_history.json").write_text(json.dumps(history))
    with pytest.raises(FixtureRefused) as raised:
        freeze(control, tmp_path)
    assert "stress[2]" in str(raised.value)
    assert "inf" in str(raised.value)


def test_an_increment_short_of_its_components_is_refused(control, tmp_path: Path):
    """A stress of four components where the case states NTENS=6 is an
    increment that did not produce the material point it should have."""
    key = control["key"]
    for job in ("original", "transformed"):
        history = json.loads(
            (CORPUS / "work" / key / job / f"{job}_history.json").read_text())
        folder = tmp_path / key / job
        folder.mkdir(parents=True)
        if job == "original":
            history[5]["STRESS"] = history[5]["STRESS"][:4]
        (folder / f"{job}_history.json").write_text(json.dumps(history))
    with pytest.raises(FixtureRefused) as raised:
        freeze(control, tmp_path)
    assert "the stress has 4 components" in str(raised.value)
    assert "NTENS=6" in str(raised.value)


def test_a_case_with_no_history_on_disk_is_refused_rather_than_skipped(
        control, tmp_path: Path):
    """A caller that forgets to check a return value writes the fixture
    anyway, and this is the check nobody may forget -- so it is an exception,
    not a None."""
    with pytest.raises(FixtureRefused) as raised:
        freeze(control, tmp_path)
    assert "no probe history on disk" in str(raised.value)


def test_the_window_starts_where_a_tangent_was_verified(control):
    """The first records of a history are where a material is still elastic
    and, one increment later, yields. A chord taken ACROSS that corner is not
    the derivative of anything.

    Measured on the control: the first verified state is at record 3, and a
    window starting at record 0 spans increments 1 to 6, whose 1-to-2 chord
    misses the reported tangent by 2.75e-01. Starting at record 3 gives
    increments 4 to 9, which are linear hardening and where the same check is
    exact -- which is what the fixture committed to this tree carries, having
    been exported from the full 280-record history.
    """
    assert window_start(control, available=280, increments=6) == 3
    committed = json.loads(
        (FROZEN / "j2_props--2feae9f158.json").read_text(encoding="utf-8"))
    assert committed["finite_history"]["window_starts_at_record"] == 3
    assert [record["increment"] for record in committed["original"]] == \
        [4, 5, 6, 7, 8, 9]
    # The corpus fixture beside these tests carries only the first eight
    # records, so the same rule clamps the window back to 2 to keep it full.
    assert [record["increment"] for record
            in fixture_from(control, CORPUS / "work")["original"]] == \
        [3, 4, 5, 6, 7, 8]
    assert [record["increment"] for record
            in fixture_from(control, CORPUS / "work", start=0)["original"]] == \
        [1, 2, 3, 4, 5, 6]


def test_the_window_is_clamped_so_a_full_one_still_fits(control):
    """A verified state near the end of a history would otherwise give a
    window shorter than the one that was asked for."""
    assert window_start(control, available=6, increments=6) == 0
    assert window_start(control, available=8, increments=6) == 2
    assert window_start({"tangent": {}}, available=280, increments=6) == 0


def test_the_refusal_says_every_reason_rather_than_the_first(control):
    """A fixture rejected for one reason gets fixed for that reason and
    resubmitted; one that lists all of them gets understood."""
    row = dict(control, stage="primal_disagreed",
               complete_finite_verification_run=False, evidence={})
    row["discovery"] = dict(row["discovery"],
                            complete_finite_verification_run=False)
    problems = why_this_may_not_be_frozen(
        row, fixture_from(row, CORPUS / "work"))
    assert len(problems) >= 5
    assert any("primal_disagreed" in p for p in problems)
    assert any("complete_finite_verification_run" in p for p in problems)
    assert sum("evidence." in p for p in problems) == len(REQUIRED_GATES)


@pytest.mark.skipif(not (PASS9 / "results" / "store_verification.jsonl").is_file(),
                    reason="the pass9 corpus run is not on this machine")
def test_across_the_whole_corpus_only_the_verified_survive_the_refusal():
    """The rule against the real thing rather than against a fixture of it.

    Measured on pass9: 250 records, 67 verified. All 67 freeze -- every one
    carries a complete finite run on both sides and every number in the
    carried window is a number. All 183 that are not verified are refused,
    including the 13 that reached ``transformed_job_failed`` and the 42 whose
    two builds disagreed, which are exactly the cases whose numbers would
    otherwise look plausible in a fixture.
    """
    from export_residual_fixture import _rows

    rows = _rows(PASS9 / "results" / "store_verification.jsonl")
    work = PASS9 / "work"
    assert len(rows) == 250
    frozen, refused = [], []
    for row in rows:
        try:
            freeze(row, work)
            frozen.append(row)
        except FixtureRefused:
            refused.append(row)
    assert len(frozen) == 67
    assert all(row.get("stage") == "verified" for row in frozen)
    assert len(refused) == 183
    assert not any(row.get("stage") == "verified" for row in refused)
