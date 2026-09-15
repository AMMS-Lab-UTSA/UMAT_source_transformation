"""The rules this interface may not break, each checked against the real round.

Every one of these was bought with a defect this project actually shipped, and
each test names the one it guards. They are separated from the workflow tests
because they are not about whether a screen works: they are about what a
working screen is allowed to say.

The record is ``corpus_run/pass11/results/store_verification.jsonl`` --  237
entries, the finished round, nothing written to make a test pass. Where it is
not on the machine, the pass11 tests skip; the rules that can be checked
against constructed records are checked either way, because a rule that only
holds on one corpus is not a rule.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.abaqus.terminal_states import FULLY_VERIFIED  # noqa: E402
from umat_oti.app import library as library_module          # noqa: E402
from umat_oti.app import residual_bridge                    # noqa: E402
from umat_oti.app.corpus_view import (EVIDENCE_GATES,       # noqa: E402
                                      NOT_ESTABLISHED,
                                      objectivity_detail,
                                      objectivity_frame_reading,
                                      objectivity_rows, load_run, three_state)
from umat_oti.app.jobs import StageState, job_view, stage_state  # noqa: E402
from umat_oti.app.plain_language import (PLAIN,             # noqa: E402
                                         STAGE_OVERRIDES, Failure,
                                         failure_for, may_say_verified,
                                         plain_status, unmapped_stages,
                                         verified_summary)
from umat_oti.app.unified_app import area_view, default_text  # noqa: E402

PASS11 = Path(os.environ.get("UMAT_OTI_PASS11") or (
    Path.home() / "softwarex_work" / "corpus_run" / "pass11" / "results"))
RECORD = PASS11 / "store_verification.jsonl"

pass11_only = pytest.mark.skipif(
    not RECORD.is_file(),
    reason="the pass11 corpus record is not on this machine")

GATE_NAMES = tuple(name for name, _w, _r in EVIDENCE_GATES)


@pytest.fixture(scope="module")
def records():
    return [json.loads(line) for line in
            RECORD.read_text().splitlines() if line.strip()]


@pytest.fixture(scope="module")
def run():
    return load_run(PASS11)


def _toolchain(include_abaqus: bool = True) -> dict:
    return {"gfortran": {"available": True, "version": "GNU Fortran 11"},
            "abaqus": {"available": True, "version": "2021"}}


# ---------------------------------------------------------------------------
# the word "verified"
# ---------------------------------------------------------------------------
@pass11_only
def test_the_word_verified_appears_only_where_all_six_gates_read_true(records):
    """55 entries stand at the last rung. 42 of them may be called verified.

    The other 13 carry ``primal_agreed`` measured FALSE with a control beside
    it that explains why. An explanation is a reason and a reason is not a
    gate reading true, so the word does not appear over them anywhere.
    """
    at_rung = [r for r in records if r.get("stage") == "verified"]
    passing = [r for r in records if may_say_verified(r)]
    assert len(at_rung) == 55
    assert len(passing) == 42

    disagreed = [r for r in at_rung if not may_say_verified(r)]
    assert len(disagreed) == 13
    for record in disagreed:
        assert (record["evidence"]["primal_agreed"] is False), \
            "the 13 are the ones whose raw stress comparison disagreed"
        status = plain_status(record)
        assert status.verified is False
        assert status.headline != "Verified"
        # And the rung is still carried, unedited, beside the plain sentence.
        assert status.stage == "verified"
        assert status.terminal_state == FULLY_VERIFIED


@pass11_only
def test_both_facts_about_the_thirteen_are_visible_at_once(records):
    """The gate reads false AND the measured control that explains it.

    Showing only the verdict hides that the builds differ. Showing only the
    gate reads as a contradiction beside a run that reached the end. Both, and
    in separate fields, so no template can substitute one for the other.
    """
    disagreed = [r for r in records
                 if r.get("stage") == "verified" and not may_say_verified(r)]
    assert len(disagreed) == 13
    for record in disagreed:
        summary = verified_summary(record)
        assert summary["verified"] is False
        assert "primal_agreed" in summary["gates that did not hold"]
        gate = next(g for g in summary["gates"]
                    if g["gate"] == "primal_agreed")
        assert gate["holds"] == "no"
        assert gate["passed"] is False
        # The explanation is present, in its own key, and it does not claim
        # the gate passed.
        assert summary["explained"], record["source"]
        assert "not the check passing" in summary["explained"]
        assert summary["explained"] != gate["holds"]


@pass11_only
def test_no_screen_anywhere_calls_one_of_the_thirteen_verified(run):
    """Swept across every area, for every one of the 13."""
    nearly = [e for e in run.entries
              if e.stage == "verified" and not may_say_verified(e)]
    assert len(nearly) == 13
    for entry in nearly:
        for area in ("library", "analyze", "mechanical", "derivative",
                     "residual", "reports"):
            view = area_view(area, results_dir=PASS11, run=run,
                             selected=entry.source_id,
                             probe=lambda include_abaqus=True: _toolchain())
            for text in default_text(view):
                assert "Verified" not in str(text) or area in ("library",
                                                               "residual"), \
                    f"{area} says Verified over {entry.source_id}"
        row = next(r for r in library_module.rows(run.entries)
                   if r.source_id == entry.source_id)
        assert row.verified is False
        assert row.status != "Verified"
        assert row.usable_as_fixture is False


def test_a_missing_gate_and_a_null_gate_are_both_not_a_pass():
    """Three states, and the two absences are the same absence.

    A key that is not there and a key holding ``null`` are both
    not-established, and not-established is not a pass. The bug this guards is
    the one already found and fixed: 108 entries that never ran being told
    "agreement only", which reported an agreement that never happened.
    """
    complete = {name: True for name in GATE_NAMES}
    assert may_say_verified({"evidence": complete}) is True

    for name in GATE_NAMES:
        missing = {k: v for k, v in complete.items() if k != name}
        nulled = dict(complete, **{name: None})
        assert may_say_verified({"evidence": missing}) is False, name
        assert may_say_verified({"evidence": nulled}) is False, name
        # And both describe themselves the same way.
        assert (verified_summary({"evidence": missing})["gates never established"]
                == verified_summary({"evidence": nulled})["gates never established"])

    # No evidence block at all is the same answer again.
    assert may_say_verified({}) is False
    assert may_say_verified({"evidence": None}) is False
    assert may_say_verified({"evidence": {}}) is False


def test_an_entry_that_never_ran_is_not_told_it_agreed_about_anything():
    """Nothing measured is its own answer and is not an agreement."""
    summary = verified_summary({"evidence": {}})
    assert summary["verified"] is False
    assert set(summary["gates never established"]) == set(GATE_NAMES)
    assert summary["gates that did not hold"] == []
    assert "Nothing was measured" in summary["why not"]
    assert "agree" not in summary["why not"].lower()
    assert summary["explained"] == ""


def test_a_gate_measured_true_is_not_reported_as_unestablished():
    """three_state is the only translation, and it has exactly three answers."""
    assert three_state(True) == "yes"
    assert three_state(False) == "no"
    assert three_state(None) == NOT_ESTABLISHED
    assert len({three_state(True), three_state(False), three_state(None)}) == 3


@pass11_only
def test_every_gate_reaches_the_page_for_every_entry(records):
    """All six, always, whether measured or not.

    A gate that is simply left off the page when nobody measured it is a blank
    where a finding should be, and a blank reads as a pass.
    """
    for record in records[:60]:
        summary = verified_summary(record)
        assert [g["gate"] for g in summary["gates"]] == list(GATE_NAMES)
        for gate in summary["gates"]:
            assert gate["holds"] in ("yes", "no", NOT_ESTABLISHED)
            assert gate["plain"] and gate["plain"] != gate["gate"]
            assert gate["what it measures"]
            assert gate["read from"]


# ---------------------------------------------------------------------------
# objectivity: the display is the last place this gets caught
# ---------------------------------------------------------------------------
@pass11_only
def test_both_objectivity_magnitudes_reach_the_page(records):
    """The global verdict AND the unrotated cross-check, never one alone.

    This project once published 8 of 9 models as non-objective off the global
    number by itself. The two are not symmetric:
    ``objectivity_worst_relative`` is the global-frame figure the verdict
    rests on and ``objectivity_worst_corotational`` is the same departure
    measured without rotating. The SMALLER of the two says which basis the
    history is recorded in, and that is what separates a model that is not
    frame indifferent from a history written co-rotationally.
    """
    with_block = [r for r in records if r.get("objectivity")]
    assert with_block, "pass11 records objectivity for some entries"

    checked = 0
    for record in with_block:
        block = record["objectivity"]
        if block.get("objectivity_worst_corotational") is None:
            continue
        checked += 1
        rows = objectivity_rows(record)
        objective = next(r for r in rows if "Q sigma Q^T" in r["finding"])
        assert objective["magnitude"] == block["objectivity_worst_relative"]
        assert objective["cross-check"] == \
            block["objectivity_worst_corotational"]
        assert objective["cross-check established"] is True
        # Each number is labelled with which it is.
        assert "verdict" in objective["what the magnitude is"]
        assert "cross-check" in objective["what the cross-check is"]

        detail = objectivity_detail(record)
        assert block["objectivity_worst_corotational"] in detail.values()
        assert block["objectivity_worst_relative"] in detail.values()
        assert detail["lead-in steps dropped before the comparison"] == \
            block.get("lead_in_steps_dropped")
    assert checked, "no entry carried both magnitudes"


@pass11_only
def test_the_frame_the_history_is_in_is_read_off_and_said(records):
    """Which of the two is smaller is stated, not left to the reader."""
    record = next(r for r in records
                  if (r.get("objectivity") or {}).get(
                      "objectivity_worst_corotational") is not None)
    reading = objectivity_frame_reading(record)
    block = record["objectivity"]

    assert reading["the verdict, global frame"] == \
        block["objectivity_worst_relative"]
    assert reading["the cross-check, unrotated"] == \
        block["objectivity_worst_corotational"]
    assert reading["lead-in steps dropped"] == block["lead_in_steps_dropped"]
    assert reading["frame the history is in"] in ("global", "corotational")
    assert reading["what this means"]

    # And the reading is the comparison, not a guess about it.
    smaller = ("global" if abs(block["objectivity_worst_relative"])
               <= abs(block["objectivity_worst_corotational"])
               else "corotational")
    assert reading["frame the history is in"] == smaller


def test_a_corotational_history_is_not_reported_as_a_non_objective_model():
    """When the unrotated figure is the small one, the page says so.

    The day that happens the frame assumption has stopped holding, and the
    large global number is measuring the frame rather than the model. A page
    that reported it as a verdict would be publishing the 8-of-9 error again.
    """
    corotational = {"objectivity": {
        "objectivity_worst_relative": 7.0e-01,
        "objectivity_worst_corotational": 4.4e-13,
        "lead_in_steps_dropped": 1, "compared_components": 1680}}
    reading = objectivity_frame_reading(corotational)
    assert reading["frame the history is in"] == "corotational"
    assert reading["the frame assumption holds"] is False
    assert "must not be read as a finding about this material" in \
        reading["what this means"]


def test_one_objectivity_magnitude_alone_is_not_a_frame_reading():
    """A verdict with no cross-check cannot say which basis anything is in."""
    for block in ({"objectivity_worst_relative": 1.0},
                  {"objectivity_worst_corotational": 1.0},
                  {}):
        reading = objectivity_frame_reading({"objectivity": block})
        assert reading["frame the history is in"] == NOT_ESTABLISHED
        assert reading["the frame assumption holds"] is None
        assert reading["what this means"]


@pass11_only
def test_objectivity_is_two_findings_and_never_one(records):
    """The transform's behaviour and the model's property are different claims."""
    for record in records[:40]:
        rows = objectivity_rows(record)
        assert len(rows) == 2
        assert rows[0]["finding"] != rows[1]["finding"]
        for row in rows:
            assert row["holds"] in ("yes", "no", NOT_ESTABLISHED)


# ---------------------------------------------------------------------------
# never fabricate progress
# ---------------------------------------------------------------------------
def test_a_stage_that_did_not_run_says_so_and_is_not_an_absence():
    """"Did not run" is a value; an absence is not-established."""
    assert stage_state("not_run") == StageState.DID_NOT_RUN
    assert stage_state(None, present=False) == NOT_ESTABLISHED
    assert StageState.DID_NOT_RUN != NOT_ESTABLISHED

    view = job_view("j", {"state": "running",
                          "stages": {"analyze_umat": "succeeded",
                                     "find_material_data": "not_run"}})
    states = {s["key"]: s["state"] for s in view.steps}
    assert states["analyze_umat"] == StageState.PASSED
    assert states["find_material_data"] == StageState.DID_NOT_RUN
    # Everything the manager said nothing about stays not-established.
    assert states["build_experiment"] == NOT_ESTABLISHED
    assert states["verify_derivatives"] == NOT_ESTABLISHED


def test_the_progress_headline_counts_only_what_was_reported():
    """No percentage is invented out of steps nobody mentioned."""
    view = job_view("j", {"state": "running",
                          "stages": {"analyze_umat": "succeeded",
                                     "find_material_data": "succeeded"}})
    assert view.steps_done == 2
    assert "2 of 2" in view.headline
    # Nine steps exist; only two were reported, and the denominator is two.
    assert len(view.steps) == 9
    assert "of 9" not in view.headline


def test_an_unknown_job_state_is_not_guessed_at():
    """A word the interface does not know leaves the state unestablished."""
    view = job_view("j", {"state": "quantum"})
    assert view.state == NOT_ESTABLISHED
    assert view.running is False


# ---------------------------------------------------------------------------
# every failure says the five things
# ---------------------------------------------------------------------------
@pass11_only
def test_every_unverified_entry_in_the_corpus_gets_a_complete_failure(records):
    """All 195 of them, each with the five parts and none with a traceback."""
    unverified = [r for r in records if not may_say_verified(r)]
    assert len(unverified) == 237 - 42

    for record in unverified:
        failure = failure_for(record)
        assert failure is not None, record["source"]
        payload = failure.as_dict()
        assert payload["what failed"].strip()
        assert payload["why this program believes that"].strip()
        assert payload["the evidence for it"], record["source"]
        assert isinstance(payload["can this be retried automatically"], bool)
        assert payload["whose move"] in ("you", "this program",
                                         "the author of this UMAT", "nobody")
        # A failure that demands something of the user says the move is theirs.
        if payload["what you must provide"]:
            assert payload["whose move"] == "you"
        # The headline is never a traceback and never a rung name.
        assert "Traceback" not in payload["what failed"]
        assert "_" not in payload["what failed"]


def test_a_failure_cannot_be_constructed_without_saying_what_and_why():
    """The five fields are required by the type, not by convention."""
    with pytest.raises(ValueError):
        Failure(what_failed="", why="something")
    with pytest.raises(ValueError):
        Failure(what_failed="something", why="   ")
    # And a failure may not ask the user for something while saying the move
    # is not theirs.
    with pytest.raises(ValueError):
        Failure(what_failed="x", why="y",
                what_you_must_provide="the constants",
                whose_move="this program")


@pass11_only
def test_a_verified_entry_is_given_no_failure_at_all(records):
    """``failure_for`` returns None for exactly the 42 and nothing else."""
    none_given = [r for r in records if failure_for(r) is None]
    assert len(none_given) == 42
    assert all(may_say_verified(r) for r in none_given)


# ---------------------------------------------------------------------------
# the taxonomy: no stage translated by a default
# ---------------------------------------------------------------------------
@pass11_only
def test_every_stage_in_the_real_record_has_a_word_of_its_own(records):
    """No rung this round produced falls through to a default.

    A second, independent check on what ``terminal_states`` guarantees. The
    lead's own test walks the same file; two checks on this are not one too
    many, because the defect they guard -- three entries that ran and diverged
    being rendered "this run did not reach it", and booked as this project's
    failure rather than the file's -- was invisible precisely because one
    layer trusted the other.
    """
    stages = {str(r.get("stage") or "") for r in records}
    assert len(stages) >= 14
    assert unmapped_stages(stages) == []

    for record in records:
        status = plain_status(record)
        assert status.headline, record.get("stage")
        assert status.means
        assert status.kind in ("verified", "external", "internal")
        # A real stage never translates to "not started".
        if record.get("stage"):
            assert status.terminal_state != "not_attempted", record["stage"]
            assert status.headline != "Not started"


@pass11_only
def test_the_three_new_states_carry_the_right_owner(records):
    """``arguments_diverged_before_the_routine`` is ours, not the file's."""
    diverged = [r for r in records
                if r.get("stage") == "arguments_diverged_before_the_routine"]
    assert len(diverged) == 3
    for record in diverged:
        status = plain_status(record)
        assert status.kind == "internal"
        assert status.whose_move == "this program"
        assert "not given the same starting point" in status.headline

    # The other two are not in pass11 yet and must still be named.
    for stage, kind, whose in (
            ("disagreement_not_in_any_recorded_call", "internal",
             "this program"),
            ("published_stub_no_constitutive_content", "external",
             "the author of this UMAT")):
        status = plain_status({"stage": stage, "reason": ""})
        assert status.kind == kind, stage
        assert status.whose_move == whose, stage
        assert status.headline and status.headline != "Not started"


def test_a_stage_nobody_has_named_is_not_rendered_as_not_started():
    """An invented rung gets an honest non-answer, never a silent default."""
    status = plain_status({"stage": "a_rung_from_the_future", "reason": "x"})
    assert status.terminal_state != "not_attempted"
    assert status.headline != "Not started"
    assert "no translation" in status.reason
    assert unmapped_stages(["a_rung_from_the_future"]) == \
        ["a_rung_from_the_future"]


def test_an_entry_with_no_stage_at_all_really_has_not_been_attempted():
    """The one case a default was right about, kept."""
    status = plain_status({"stage": "", "reason": ""})
    assert status.terminal_state == "not_attempted"
    assert status.headline == "Not started"
    assert status.whose_move == "you"


def test_every_state_the_interface_can_reach_has_plain_words():
    """No state in the plain table is missing a headline or an owner."""
    for state, entry in PLAIN.items():
        assert entry["headline"], state
        assert entry["means"], state
        assert entry["whose move"] in ("you", "this program",
                                       "the author of this UMAT", "nobody")
        # A state that asks the user for something says what.
        if entry["whose move"] == "you" and state != FULLY_VERIFIED:
            assert entry["provide"], state
        else:
            assert entry["provide"] == "", state


# ---------------------------------------------------------------------------
# the Residual Assembler guard, stated as a property of the whole corpus
# ---------------------------------------------------------------------------
@pass11_only
def test_no_entry_the_gates_refuse_can_reach_the_residual_assembler(run):
    """Every one of the 195, refused, each by a raise rather than a None."""
    offer = residual_bridge.offer(run.entries)
    ready = {f.source_id for f in offer["verified"]}
    assert len(ready) == 42

    refused = 0
    for entry in run.entries:
        if may_say_verified(entry):
            continue
        refused += 1
        with pytest.raises(ValueError):
            residual_bridge.select(run.entries, entry.source_id)
    assert refused == 237 - 42
