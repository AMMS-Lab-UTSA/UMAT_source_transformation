"""A frozen snapshot is what a figure cites, so it is the one artefact nothing
downstream can catch an error in.

The rule ``export_residual_fixture.py`` already applies to a regression
fixture applies here for the same reason, and it was not being applied.
``freeze_publication_evidence.py`` copied every listed file, hashed it, and
wrote SHA256SUMS over the result -- so a NaN in ``table6_parameter_sensitivity
.csv`` would have been frozen, blessed with a digest, and cited by a figure.
A NaN does not fail: it propagates. Matplotlib draws a gap. A mean over it
comes back NaN. A table cell renders as "nan" and reads as a measurement.

Two things are refused, and they are different:

**A value that is not a number.** Every .json and .csv is read before it is
copied. ``json.loads`` decodes the bare literals ``NaN`` and ``Infinity``
happily, so the check is made against the decoded floats AND against the text,
because a value that reached a CSV as the string "nan" is still a NaN the
moment a figure plots it.

**A number taken from an analysis that stopped.** Abaqus printing THE ANALYSIS
HAS COMPLETED SUCCESSFULLY is a statement about the solver, not about the
routine it called: a job completes while its UMAT returns values that are not
numbers, and the finite PREFIX of such a run looks exactly like a short
successful one. Every number in it is finite. So the markers the pipeline
writes about its own runs are refused the same way a NaN is.

And the same gap in the fixture exporter, which this file also closes: the
carried window clamped itself to whatever was on disk, so a run truncated to
three increments produced a three-increment fixture with no complaint, and
nothing downstream could tell it from a run that was meant to be that length.
"""
import json
import math
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

import freeze_publication_evidence as freezer  # noqa: E402
from export_residual_fixture import (FixtureRefused, INCREMENTS,  # noqa: E402
                                     freeze, fixture_from, scan_whole_history,
                                     why_this_may_not_be_frozen)

CORPUS = REPO / "tests" / "fixtures" / "corpus"
WORK = CORPUS / "work"
PASS9 = Path(os.environ.get("UMAT_OTI_CORPUS_RUN")
             or REPO.parent / "corpus_run" / "pass9")


@pytest.fixture(scope="module")
def control():
    return json.loads(
        (CORPUS / "results" / "store_verification.jsonl").read_text().strip())


def _history(job: str) -> list:
    key = json.loads((CORPUS / "results" / "store_verification.jsonl")
                     .read_text().strip())["key"]
    return json.loads((WORK / key / job / f"{job}_history.json").read_text())


def _work_with(tmp_path: Path, control: dict, histories: dict) -> Path:
    key = control["key"]
    for job, records in histories.items():
        folder = tmp_path / key / job
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{job}_history.json").write_text(json.dumps(records))
    return tmp_path


# ===========================================================================
# the publication snapshot
# ===========================================================================
def test_the_evidence_in_the_tree_today_is_finite(tmp_path):
    """The rule against the real thing rather than against a fixture of it.

    Measured: all 37 listed evidence files are present in this checkout and
    not one of them carries a NaN, an infinity, or a marker that a published
    number came off a truncated analysis. If that stops being true, this test
    says so before a snapshot is frozen rather than after a figure cites it.
    """
    present = [(name, freezer.RESULTS / name) for name in freezer.EVIDENCE
               if (freezer.RESULTS / name).is_file()]
    assert present, "no publication evidence is in this checkout at all"
    assert freezer.why_this_snapshot_may_not_be_frozen(present) == []


def test_a_nan_decoded_from_json_is_refused(tmp_path):
    """``json.loads('{"x": NaN}')`` succeeds and returns a float nobody can
    plot. Written as the bare literal because that is what a Python writer
    emits by default."""
    path = tmp_path / "table.json"
    path.write_text('{"rows": [{"source": "j2.f", "relative": NaN}]}')
    problems = freezer.not_a_number_in(path, "tables/table.json")
    assert problems == ["tables/table.json.rows[0].relative is nan"]


def test_an_infinity_is_refused_the_same_way(tmp_path):
    path = tmp_path / "summary.json"
    path.write_text('{"worst": Infinity, "best": -Infinity}')
    problems = freezer.not_a_number_in(path, "summary.json")
    assert len(problems) == 2
    assert any("worst is inf" in p for p in problems)
    assert any("best is -inf" in p for p in problems)


def test_a_nan_that_arrived_as_a_string_is_refused_too(tmp_path):
    """A value that reached a file as the text "nan" is still a NaN the moment
    a figure plots it, and a check made only against decoded floats would walk
    straight past it."""
    path = tmp_path / "rows.json"
    path.write_text(json.dumps({"rows": [{"relative": "NaN"},
                                         {"relative": "inf"},
                                         {"relative": "0.0"}]}))
    problems = freezer.not_a_number_in(path, "rows.json")
    assert len(problems) == 2
    assert "rows[0].relative is the string 'NaN'" in problems[0]


def test_a_nan_in_a_csv_cell_is_named_by_line_and_column(tmp_path):
    """A table is what a reader sees. "Something in the CSV" is not a finding;
    "line 3 column 4" is."""
    path = tmp_path / "table6.csv"
    path.write_text("source,parameter,relative\n"
                    "j2.f,E,1.0e-12\n"
                    "visco.f,tau,nan\n")
    problems = freezer.not_a_number_in(path, "parameter_sensitivity/table6.csv")
    assert problems == [
        "parameter_sensitivity/table6.csv line 3 column 3 is 'nan'"]


def test_a_finite_file_is_not_refused(tmp_path):
    """The check must not fire on ordinary evidence, including booleans and
    the strings that merely contain those letters."""
    path = tmp_path / "clean.json"
    path.write_text(json.dumps({
        "verified": True, "count": 67, "worst": 8.25e-11,
        "note": "infinitely many steps would be nice",
        "name": "nanocomposite.for"}))
    assert freezer.not_a_number_in(path, "clean.json") == []


def test_a_figure_is_not_scanned_but_what_it_is_drawn_from_is(tmp_path):
    """A PNG is bytes. The file a number comes out of is in the evidence list
    beside it, and that is the one that is read."""
    path = tmp_path / "figure.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nnan inf")
    assert freezer.not_a_number_in(path, "figures/figure.png") == []
    assert any(name.endswith(".png") for name in freezer.EVIDENCE)
    assert any(name.endswith(".csv") for name in freezer.EVIDENCE)


def test_a_published_number_from_a_run_that_was_not_finite_is_refused(tmp_path):
    """Every number in the finite prefix of a failed analysis is finite, so a
    NaN scan cannot catch it. What catches it is the pipeline's own marker.

    Measured on BodyForce-Growth-2Stages.for: both builds "completed" 35
    increments and both were non-finite from the third.
    """
    path = tmp_path / "round.json"
    path.write_text(json.dumps({"cases": [
        {"source": "BodyForce-Growth-2Stages.for",
         "complete_finite_verification_run": False,
         "worst_stress_relative": 1.2e-9}]}))
    problems = freezer.rests_on_a_truncated_analysis(path, "corpus/round.json")
    assert len(problems) == 1
    assert "not finite from end to end" in problems[0]
    assert "complete_finite_verification_run" in problems[0]


def test_a_truncation_marker_that_is_a_dict_is_not_walked_past(tmp_path):
    """``first_non_finite_material_point`` is ``{"element": 1, "point": 3,
    "increment": 6}``. A leaves-only walk descends straight past the key into
    three integers, none of which is named anything a check would notice --
    which is why the scan walks nodes and not only leaves."""
    path = tmp_path / "round.json"
    path.write_text(json.dumps({"cases": [{"history_grouping": {"original": {
        "first_non_finite_material_point": {"element": 1, "point": 3,
                                            "increment": 6},
        "first_incomplete_increment": None}}}]}))
    problems = freezer.rests_on_a_truncated_analysis(path, "round.json")
    assert len(problems) == 1
    assert "'element': 1" in problems[0]
    assert "stopped before it finished" in problems[0]


def test_a_run_that_was_finite_and_says_so_is_not_refused(tmp_path):
    path = tmp_path / "round.json"
    path.write_text(json.dumps({"grouping": {
        "complete_finite_verification_run": True,
        "first_non_finite_material_point": None,
        "first_incomplete_increment": None}}))
    assert freezer.rests_on_a_truncated_analysis(path, "round.json") == []


def test_the_refusal_says_every_reason_rather_than_the_first(tmp_path):
    """A snapshot rejected for one reason gets fixed for that reason and
    resubmitted; one that lists all of them gets understood."""
    (tmp_path / "a.json").write_text('{"x": NaN, "y": Infinity}')
    (tmp_path / "b.csv").write_text("a,b\n1,inf\n")
    (tmp_path / "c.json").write_text(
        '{"complete_finite_verification_run": false}')
    problems = freezer.why_this_snapshot_may_not_be_frozen(
        [(name, tmp_path / name) for name in ("a.json", "b.csv", "c.json")])
    assert len(problems) == 4
    assert sum("a.json" in p for p in problems) == 2
    assert sum("b.csv" in p for p in problems) == 1
    assert sum("c.json" in p for p in problems) == 1


def test_a_refused_snapshot_writes_nothing_at_all(tmp_path, monkeypatch):
    """A half-written snapshot directory is worse than none: a later reader
    cannot tell it from one whose freeze was interrupted, and it sits in
    ``paper_results/frozen`` looking citable."""
    evidence = tmp_path / "evidence"
    (evidence / "tables").mkdir(parents=True)
    (evidence / "tables" / "t.csv").write_text("a,b\n1,nan\n")
    monkeypatch.setattr(freezer, "RESULTS", evidence)
    monkeypatch.setattr(freezer, "EVIDENCE", ("tables/t.csv",))
    out = tmp_path / "frozen"
    assert freezer.main(["--out-root", str(out), "--label", "trial"]) == 4
    assert not out.exists(), (
        "a refused freeze leaves no directory behind to be mistaken for a "
        "snapshot")


def test_a_clean_snapshot_still_freezes_and_records_that_it_was_checked(
        tmp_path, monkeypatch):
    """The check has to be visible in the artefact. A reader of a snapshot
    cannot tell "checked and clean" from "never checked" unless it says so."""
    evidence = tmp_path / "evidence"
    (evidence / "tables").mkdir(parents=True)
    (evidence / "tables" / "t.csv").write_text("a,b\n1,2.5\n")
    (evidence / "tables" / "t.json").write_text('{"worst": 8.25e-11}')
    monkeypatch.setattr(freezer, "RESULTS", evidence)
    monkeypatch.setattr(freezer, "EVIDENCE",
                        ("tables/t.csv", "tables/t.json", "tables/absent.csv"))
    out = tmp_path / "frozen"
    assert freezer.main(["--out-root", str(out), "--label", "trial"]) == 0
    manifest = json.loads((out / "trial" / "MANIFEST.json").read_text())
    check = manifest["finiteness_check"]
    assert check["files_read"] == 2
    assert check["problems_found"] == []
    assert check["frozen_anyway"] is False
    assert "no NaN" in check["rule"]
    assert manifest["evidence_files_absent"] == ["tables/absent.csv"], (
        "a file listed and absent is recorded as absent, not refused -- a "
        "snapshot that says what is missing is honest")


def test_the_escape_hatch_marks_the_snapshot_as_uncitable(tmp_path,
                                                          monkeypatch):
    """There is a reason to freeze a broken round: to look at it. There is no
    reason to cite one, and the snapshot says which it is."""
    evidence = tmp_path / "evidence"
    (evidence / "tables").mkdir(parents=True)
    (evidence / "tables" / "t.csv").write_text("a,b\n1,nan\n")
    monkeypatch.setattr(freezer, "RESULTS", evidence)
    monkeypatch.setattr(freezer, "EVIDENCE", ("tables/t.csv",))
    out = tmp_path / "frozen"
    assert freezer.main(["--out-root", str(out), "--label", "broken",
                         "--allow-non-finite"]) == 0
    check = json.loads(
        (out / "broken" / "MANIFEST.json").read_text())["finiteness_check"]
    assert check["frozen_anyway"] is True
    assert check["problems_found"]


# ===========================================================================
# the regression fixture
# ===========================================================================
def test_a_fixture_carved_out_of_a_truncated_run_is_refused(control, tmp_path):
    """The gap this closes. The window clamped itself to whatever was on disk,
    so a run that stopped at three increments produced a three-increment
    fixture, written without complaint, and nothing downstream could tell it
    from a run that was meant to be that length."""
    work = _work_with(tmp_path, control,
                      {"original": _history("original")[:3],
                       "transformed": _history("transformed")[:3]})
    with pytest.raises(FixtureRefused) as raised:
        freeze(control, work)
    said = str(raised.value)
    assert f"3 increment(s) of the {INCREMENTS} asked for" in said
    assert "however far an analysis got before it stopped" in said


def test_the_shortfall_is_recorded_in_the_artefact_not_only_in_the_refusal(
        control, tmp_path):
    """``increments_carried`` alone cannot be read: 3 carried is either a run
    that stopped or a request for 3. Both numbers are written."""
    work = _work_with(tmp_path, control,
                      {"original": _history("original")[:3],
                       "transformed": _history("transformed")[:3]})
    evidence = fixture_from(control, work)["finite_history"]
    assert evidence["increments_carried"] == 3
    assert evidence["increments_requested"] == INCREMENTS == 6
    assert evidence["records_available"] == 3
    assert evidence["records_requested_from"] == {"original": 3,
                                                  "transformed": 3}


def test_a_window_of_exactly_what_was_asked_for_is_not_refused(control,
                                                               tmp_path):
    """The check must not fire on a shorter window that was ASKED for -- the
    complaint is about a silent shortfall, not about a small fixture."""
    work = _work_with(tmp_path, control,
                      {"original": _history("original")[:3],
                       "transformed": _history("transformed")[:3]})
    frozen = freeze(control, work, increments=3)
    assert len(frozen["original"]) == 3
    assert frozen["finite_history"]["increments_requested"] == 3


def test_a_nan_outside_the_carried_window_is_refused(control, tmp_path):
    """A window of six increments out of hundreds is finite in a run that went
    to NaN at increment 200. Scanning only what is carried cannot tell a
    verification apart from the salvageable prefix of a failed analysis.

    The NaN here is at record 31 and the window ends at record 7, so the
    per-increment scan sees nothing and only the whole-history reading fires.
    """
    def lengthened(job: str) -> list:
        records = _history(job)
        long = records + [dict(r, increment=r["increment"] + 8 * (k + 1))
                          for k in range(3) for r in records]
        if job == "original":
            long[-1] = dict(long[-1],
                            STRESS=[float("nan")] + list(long[-1]["STRESS"][1:]))
        return long

    work = _work_with(tmp_path, control,
                      {"original": lengthened("original"),
                       "transformed": lengthened("transformed")})
    with pytest.raises(FixtureRefused) as raised:
        freeze(control, work)
    said = str(raised.value)
    assert "OUTSIDE the carried window" in said
    assert "STRESS[0] is nan at record 31" in said
    assert "prefix of a failed analysis" in said
    assert said.count("- ") == 1, (
        "only the whole-history reading fires: the carried window is finite, "
        "which is the whole point")


def test_an_infinity_outside_the_window_is_refused_in_the_tangent_too(
        control, tmp_path):
    """A history whose stress is finite and whose tangent is not would freeze
    a value that only shows up once somebody assembles a stiffness."""
    def lengthened(job: str) -> list:
        records = _history(job)
        long = records + [dict(r, increment=r["increment"] + 8 * (k + 1))
                          for k in range(3) for r in records]
        if job == "transformed":
            long[-1] = dict(long[-1],
                            DDSDDE=[float("inf")] + list(long[-1]["DDSDDE"][1:]))
        return long

    work = _work_with(tmp_path, control,
                      {"original": lengthened("original"),
                       "transformed": lengthened("transformed")})
    with pytest.raises(FixtureRefused) as raised:
        freeze(control, work)
    assert "DDSDDE[0] is inf" in str(raised.value)
    assert "transformed history" in str(raised.value)


def test_the_whole_history_scan_names_the_number_rather_than_the_file():
    """Not "something went wrong": which record, which array, which index,
    and the increment and material point it was written at."""
    scan = scan_whole_history([
        {"increment": 1, "element": 1, "point": 1, "time": 0.1,
         "STRESS": [1.0, 2.0], "STATEV": [0.0], "DDSDDE": [1.0]},
        {"increment": 2, "element": 1, "point": 3, "time": 0.2,
         "STRESS": [1.0, float("nan")], "STATEV": [0.0], "DDSDDE": [1.0]},
    ], "original")
    where = scan["first_non_finite"]
    assert where["record"] == 1
    assert where["array"] == "STRESS"
    assert where["index"] == 1
    assert where["value"] == "nan"
    assert where["increment"] == 2 and where["point"] == 3
    assert scan["records_scanned"] == 2


def test_a_history_that_is_finite_throughout_scans_clean():
    scan = scan_whole_history(
        [{"increment": 1, "STRESS": [1.0], "STATEV": [], "DDSDDE": [2.0]}],
        "original")
    assert scan["first_non_finite"] is None
    assert scan["values_scanned"] == 2


def test_the_scan_travels_with_the_fixture_so_a_loader_can_repeat_it(control):
    """A fixture that says it is finite and is not would otherwise be caught
    nowhere. The scan's own numbers are written into the artefact."""
    evidence = fixture_from(control, WORK)["finite_history"]
    assert set(evidence["whole_history"]) == {"original", "transformed"}
    for side, scan in evidence["whole_history"].items():
        assert scan["first_non_finite"] is None, side
        assert scan["records_scanned"] == 8
        assert scan["values_scanned"] > 100


def test_the_committed_fixtures_carry_a_full_window_of_finite_numbers():
    """Restated against the files actually in the tree, because the ones that
    matter are the ones on disk."""
    frozen = sorted((REPO / "tests" / "fixtures" / "verified").glob("*.json"))
    assert frozen, "no fixture is frozen in this tree"
    for path in frozen:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert len(payload["original"]) == len(payload["converted"])
        for side in ("original", "converted"):
            for record in payload[side]:
                for name in ("strain", "dstrain", "stress", "state", "ddsdde"):
                    for value in record.get(name) or ():
                        assert math.isfinite(float(value)), (path.name, name)


def test_the_two_new_refusals_are_reported_beside_the_old_ones(control,
                                                               tmp_path):
    """Every reason at once. A fixture rejected for one gets resubmitted; one
    that lists all of them gets understood."""
    work = _work_with(tmp_path, control,
                      {"original": _history("original")[:2],
                       "transformed": _history("transformed")[:2]})
    row = dict(control, stage="primal_disagreed", evidence={})
    problems = why_this_may_not_be_frozen(row, fixture_from(row, work))
    assert any("settled at 'primal_disagreed'" in p for p in problems)
    assert any("increment(s) of the 6 asked for" in p for p in problems)
    assert sum("evidence." in p for p in problems) == 3


@pytest.mark.skipif(
    not (PASS9 / "results" / "store_verification.jsonl").is_file(),
    reason="the pass9 corpus run is not on this machine")
def test_the_new_refusals_reject_nothing_that_used_to_freeze():
    """A check that tightens a rule has to be measured against the corpus, not
    argued about. Measured on pass9: all 67 entries that froze before still
    freeze -- every one carries a full six-increment window and is finite in
    every number of both histories end to end, not only inside the window.
    """
    from export_residual_fixture import _rows

    rows = _rows(PASS9 / "results" / "store_verification.jsonl")
    frozen = []
    for row in rows:
        try:
            frozen.append(freeze(row, PASS9 / "work"))
        except FixtureRefused:
            continue
    assert len(frozen) == 67
    for fixture in frozen:
        evidence = fixture["finite_history"]
        assert evidence["increments_carried"] == evidence["increments_requested"]
        for scan in evidence["whole_history"].values():
            assert scan["first_non_finite"] is None
