"""Three states reach the page as three states, or the page is lying.

Every column the batch writes has three possible answers and only two of them
are verdicts. ``true`` and ``false`` are findings; ``null`` is a hole in the
evidence. A hole rendered as a pass is the single worst thing this interface
can do, because a reader cannot tell a measurement that was made and held from
a measurement nobody made, and everything downstream of the page -- a
screenshot, a table, a claim in a paper -- inherits the confusion.

So the rule here is narrow and absolute: ``null`` renders as "not established",
never as a pass and never as a failure, and the three strings are three
strings.

The records these run against are the shapes the batch actually writes.
Measured on the pass10 corpus round:

* 3 of the 10 entries that reached ``verified`` carry no
  ``mechanically_informative`` measurement at all -- agreement, with nothing
  established about whether the material did anything under it.
* one ``coverage`` criterion reads ``met=null`` because "no increment in this
  run applied a direct strain with no shear, so the coupling has nothing to
  show up in".
* the ``NeoHookean_umat.for`` entry verified with ``objectivity.agreed=true``
  and ``objectivity.objective=false``, its author's own response missing
  ``Q sigma Q^T`` by 9.02 relative -- two different facts about two different
  things, and one tick over both would report this pipeline's success as the
  published source's correctness.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app.corpus_view import (DID_NOT_HOLD, EVIDENCE_GATES,  # noqa: E402
                                      HELD, NOT_ESTABLISHED,
                                      OBJECTIVITY_CLAIMS, coverage_rows,
                                      entry_view, gate_tally,
                                      informativeness_row, load_run,
                                      objectivity_rows, planned_experiment,
                                      plausibility_rows, signature_rows,
                                      three_state, time_scale_row,
                                      what_may_be_claimed)
from umat_oti.app.corpus_tab import _entry_panel, render  # noqa: E402

#: The corpus round these numbers were measured on. 7 GB of Abaqus output, so
#: it lives beside the checkout rather than in it and the tests that need it
#: skip where it is not on this machine.
PASS10 = Path(os.environ.get("UMAT_OTI_CORPUS_RUN_10")
              or REPO.parent / "corpus_run" / "pass10")
PASS10_RESULTS = PASS10 / "results" / "store_verification.jsonl"


class Recorder:
    """A stand-in for Streamlit that records what would be drawn."""

    def __init__(self):
        self.written: list = []
        self.children: list = []

    def _record(self, kind, *values):
        self.written.append((kind, values))

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self._record(name, *args)
            return None
        return call

    def columns(self, count):
        made = [Recorder() for _ in range(count)]
        self.children.extend(made)
        return made

    def selectbox(self, label, options, **kwargs):
        self._record("selectbox", label, list(options))
        return list(options)[0] if options else None

    def text_input(self, label, value="", **kwargs):
        self._record("text_input", label)
        return value

    def button(self, label, **kwargs):
        self._record("button", label)
        return False

    def expander(self, label, **kwargs):
        self._record("expander", label)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def of_kind(self, kind) -> list:
        found = [values for name, values in self.written if name == kind]
        for child in self.children:
            found.extend(child.of_kind(kind))
        return found

    def texts(self) -> str:
        parts = [str(value) for _kind, values in self.written for value in values]
        for child in self.children:
            parts.append(child.texts())
        return " ".join(parts)


def calls_it_verified(claim: str) -> bool:
    """Whether a sentence calls this entry verified.

    ``derivatives_verified`` is the name of a gate and contains the word, so a
    plain substring test would read the gate's name as the verdict. The gate
    name is removed before asking.
    """
    return "verified" in (claim.replace("derivatives_verified", "")
                          .replace("derivatives verified", ""))


def drawn(row: dict) -> Recorder:
    recorder = Recorder()
    _entry_panel(entry_view(row), Path("/nowhere"), recorder)
    return recorder


# ---------------------------------------------------------------------------
# a record carrying every new column, in the shape the batch writes it
# ---------------------------------------------------------------------------
#: Shaped on pass10's ``PLANESTRESS-ORTHOTROPIC.for`` and ``NeoHookean_umat``:
#: a coverage criterion nobody could measure, an objectivity block whose two
#: claims disagree, and an informativeness gate that was never reached.
RECORD = {
    "key": "k1",
    "source": "owner__repo/oriented.for",
    "repository": "owner/repo",
    "stage": "verified",
    "reason": "agreed at all 3 states",
    "evidence": {"abaqus_job_completed": True,
                 "all_requested_outputs_present": True,
                 "complete_history_finite": True,
                 "primal_agreed": True,
                 "derivatives_verified": True,
                 "mechanically_informative": None},
    "experiment": {
        "criterion": "the response must depend on the material direction, "
                     "which is what an orientation is for",
        "family": {"name": "oriented", "driver": "strain",
                   "evidence": ["the routine reads PROPS(7:9) as direction "
                                "cosines and rotates the stiffness by them"],
                   "notes": ["this family needs *ORIENTATION on the section"]},
        "reason": "the source rotates its stiffness, so an experiment that "
                  "only pulls along an axis cannot tell it from an isotropic "
                  "one",
        "requirement": "a direct strain with no shear, so the coupling has "
                       "somewhere to show up",
        "refusal": "",
        "warnings": [],
    },
    "coverage": [
        {"name": "stress on the material scale", "met": True,
         "magnitude": 0.81, "reason": "peak stress 0.021 against a largest "
                                      "material constant of 2.564"},
        {"name": "direct strain produced shear", "met": None,
         "magnitude": 0.0,
         "reason": "no increment in this run applied a direct strain with no "
                   "shear, so the coupling has nothing to show up in"},
    ],
    "objectivity": {
        "ran": True, "agreed": True, "objective": False,
        "compared_components": 1680,
        "worst_stress_relative": 0.0, "worst_state_relative": 0.0,
        "objectivity_worst_relative": 9.020710260137786,
        "objectivity_reason": "the author's own response is NOT the unrotated "
                              "response rotated: worst |Q sigma Q^T - sigma'| "
                              "is 9.021e+00 of the stress field over 1680 "
                              "components",
        "reason": "the converted build agrees with the original on the same "
                  "path presented in a rotated frame, worst stress difference "
                  "0.000e+00 against a tolerance of 1e-10",
        "rotation": [0.91, -0.24, 0.33, 0.33, 0.91, -0.24, -0.24, 0.33, 0.91],
        "original": {"completed": True, "reasons": []},
        "transformed": {"completed": True, "reasons": []},
    },
    "mechanically_informative": None,
    "time_scale_coverage": {
        "enough": None, "fraction": 0.0, "reaches_heuristic": False,
        "total_time": 13.0,
        "reason": "the source declares no time scale of its own",
        "scale": {"declared": False, "evidence": "", "name": "", "value": 0.0},
    },
    "response_plausibility": {
        "plausible": True,
        "checks": [{"name": "stress against material constants",
                    "plausible": True, "measured": 0.0209, "against": 2.5641,
                    "detail": "peak stress 0.02098 against a largest material "
                              "constant of 2.564, a ratio of 0.008182"},
                   {"name": "stress against the smallest probe",
                    "plausible": None, "measured": 0.0209, "against": None,
                    "detail": "no smaller probe ran, so there is nothing to "
                              "compare against"}],
    },
    "searched_for_material_data": {
        "repository": "owner/repo", "decks_scanned": 17,
        "evidence": "one *MATERIAL block names this routine"},
    "material_provenance": "job.inp *MATERIAL ORTHO: 9 constants",
    "primal_signature": {
        "blocking_observations": [],
        "hypotheses": [
            {"hypothesis": "branch_divergence",
             "claim": "a conditional inside the routine sent the builds down "
                      "different paths",
             "confirmation_status": "needs_more_evidence",
             "confirmed_root_cause": None,
             "what_would_confirm": "record which branch each build took",
             "what_would_refute": "bit-identical values for every tested "
                                  "quantity",
             "supporting_evidence": [{"statement": "the source branches on "
                                                   "its own stress",
                                      "origin": "source_text",
                                      "is_measurement": False}],
             "contradicting_evidence": [],
             "reproduction": None}],
    },
}


# ---------------------------------------------------------------------------
# the vocabulary itself
# ---------------------------------------------------------------------------
def test_the_three_states_are_three_different_strings():
    """Not two strings and a blank. A blank reads as "nothing to report", and
    "nobody measured this" is very much something to report."""
    assert three_state(True) == HELD == "yes"
    assert three_state(False) == DID_NOT_HOLD == "no"
    assert three_state(None) == NOT_ESTABLISHED == "not established"
    assert len({HELD, DID_NOT_HOLD, NOT_ESTABLISHED}) == 3
    for word in (HELD, DID_NOT_HOLD, NOT_ESTABLISHED):
        assert word, "a state that renders as an empty string is invisible"


def test_a_null_never_falls_through_to_a_pass_or_to_a_failure():
    """The shortcut this function must not have. ``bool(None)`` is ``False``
    and every ordinary rendering would therefore report a measurement nobody
    made as one that failed -- inventing a failure, which is the mirror of
    inventing a pass and just as wrong."""
    assert three_state(None) != three_state(False)
    assert three_state(None) != three_state(True)
    # and nothing falsy is mistaken for absent
    assert three_state(0) == DID_NOT_HOLD
    assert three_state("") == DID_NOT_HOLD
    assert three_state([]) == DID_NOT_HOLD


# ---------------------------------------------------------------------------
# coverage: the family's own criteria
# ---------------------------------------------------------------------------
def test_a_coverage_criterion_nobody_measured_is_not_shown_as_met():
    """``met=null`` means NOT MEASURED. The pass10 criterion this is shaped on
    could not be measured because the experiment never presented the loading
    it needed, and showing it as met would claim the coupling was exercised."""
    rows = {row["finding"]: row for row in coverage_rows(RECORD)}
    assert rows["stress on the material scale"]["holds"] == HELD
    unmeasured = rows["direct strain produced shear"]
    assert unmeasured["holds"] == NOT_ESTABLISHED
    assert unmeasured["holds"] != HELD
    assert unmeasured["established"] is False
    assert "nothing to show up in" in unmeasured["why"], (
        "the record's own sentence, not a word this module composed")


def test_a_criterion_that_was_measured_and_failed_is_not_the_same_row():
    rows = coverage_rows({"coverage": [
        {"name": "growth developed", "met": False, "magnitude": 0.0,
         "reason": "no growth tensor moved over the run"},
        {"name": "stress on the material scale", "met": None,
         "reason": "nothing ran to measure it against"}]})
    assert [row["holds"] for row in rows] == [DID_NOT_HOLD, NOT_ESTABLISHED]
    assert [row["established"] for row in rows] == [True, False]


def test_a_record_with_no_coverage_block_produces_no_invented_criteria():
    assert coverage_rows({}) == []
    assert coverage_rows({"coverage": None}) == []


def test_the_page_warns_about_a_criterion_nobody_could_measure():
    page = drawn(RECORD)
    warnings = " ".join(str(v) for values in page.of_kind("warning")
                        for v in values)
    assert "direct strain produced shear" in warnings
    assert "neither met nor unmet" in warnings


# ---------------------------------------------------------------------------
# objectivity: two facts, two rows, never one tick
# ---------------------------------------------------------------------------
def test_objectivity_is_two_findings_and_they_are_about_different_things():
    """"agreed" is about THE TRANSFORM -- converting the source did not change
    what it computes in a rotated frame. "objective" is about THE MODEL -- the
    author's own response to a rotated path is the unrotated response rotated.
    They are independent and on pass10 they disagree."""
    rows = objectivity_rows(RECORD)
    assert len(rows) == len(OBJECTIVITY_CLAIMS) == 2
    transform, model = rows
    assert transform["holds"] == HELD
    assert model["holds"] == DID_NOT_HOLD
    assert transform["holds"] != model["holds"], (
        "these two are measured to differ; a page that merged them would "
        "report the transform's success as the model's correctness")
    assert "the transform" in transform["what it is about"]
    assert "the model" in model["what it is about"]
    assert transform["magnitude"] == 0.0
    assert round(model["magnitude"], 2) == 9.02
    assert "Q sigma Q^T" in model["why"]


def test_the_two_objectivity_claims_carry_their_own_reasons():
    """A single ``reason`` covering both would attach the transform's sentence
    to the model's finding, which is a sentence that says the opposite."""
    transform, model = objectivity_rows(RECORD)
    assert "converted build agrees" in transform["why"]
    assert "is NOT the unrotated response rotated" in model["why"]
    assert transform["why"] != model["why"]


def test_an_entry_with_no_objectivity_block_shows_two_not_establisheds():
    """Not a blank and not a false: no rotated-frame comparison was run."""
    rows = objectivity_rows({"key": "k", "source": "s.for"})
    assert len(rows) == 2
    assert [row["holds"] for row in rows] == [NOT_ESTABLISHED, NOT_ESTABLISHED]
    assert all(row["established"] is False for row in rows)
    assert all("no rotated-frame comparison was run" in row["why"]
               for row in rows)


def test_one_claim_measured_and_the_other_not_shows_as_one_of_each():
    """The case the bundled obj4 control is in: ``agreed`` true, ``objective``
    null, because the converted build was compared and the author's own
    response was not."""
    rows = objectivity_rows({"objectivity": {
        "ran": True, "agreed": True, "objective": None,
        "worst_stress_relative": 0.0,
        "reason": "the converted build agrees with the original on the same "
                  "path presented in a rotated frame"}})
    assert [row["holds"] for row in rows] == [HELD, NOT_ESTABLISHED]


def test_the_page_shows_the_rotation_a_reader_would_have_to_check():
    """"in a rotated frame" is not checkable until the frame is on the page."""
    page = drawn(RECORD).texts()
    assert "0.91" in page and "-0.24" in page
    assert "the rotation" in page.lower()


def test_the_page_raises_a_failed_objectivity_claim_rather_than_tabling_it():
    errors = " ".join(str(v) for values in drawn(RECORD).of_kind("error")
                      for v in values)
    assert "Q sigma Q^T" in errors


# ---------------------------------------------------------------------------
# the six gates stay six, and the stage is explained by which of them is false
# ---------------------------------------------------------------------------
def test_the_six_gates_are_split_three_ways_and_not_two():
    """"5 of 6 passed" has already merged "did not hold" with "nobody measured
    it", and those are the two a reader most needs apart: one is a result
    about the source, the other is a hole in this pipeline's evidence."""
    tally = gate_tally(RECORD)
    assert set(tally) == {"held", "did not hold", "never established"}
    assert len(tally["held"]) + len(tally["did not hold"]) \
        + len(tally["never established"]) == len(EVIDENCE_GATES) == 6
    assert tally["never established"] == ["mechanically_informative"]
    assert tally["did not hold"] == []


def test_the_stage_is_explained_by_the_gate_that_decides_it():
    row = dict(RECORD, stage="primal_disagreed",
               evidence=dict(RECORD["evidence"], primal_agreed=False,
                             derivatives_verified=None,
                             mechanically_informative=None))
    claimed = what_may_be_claimed(row)
    assert claimed["gates that did not hold"] == ["primal_agreed"]
    assert set(claimed["gates never established"]) == {
        "derivatives_verified", "mechanically_informative"}
    page = drawn(row).texts()
    assert "primal_agreed" in page
    assert "derivatives_verified" in page


def test_all_six_gates_reach_the_page_by_name():
    page = drawn(RECORD).texts()
    for name, _what, _where in EVIDENCE_GATES:
        assert name.replace("_", " ") in page or name in page, name


# ---------------------------------------------------------------------------
# "verified" is a word with six measurements under it
# ---------------------------------------------------------------------------
def test_verified_never_appears_where_informativeness_was_never_established():
    """The rule the project owner wrote down. Measured on pass10: 3 of the 10
    entries the batch settled at ``verified`` carry no informativeness
    measurement at all."""
    claimed = what_may_be_claimed(RECORD)
    assert claimed["the batch's terminal state"] == "fully_verified", (
        "the batch's own word is carried unedited -- a verdict rendered "
        "differently here than in the evidence is a second opinion")
    assert claimed["all six gates hold"] is False
    assert claimed["may be called verified"] is False
    assert not calls_it_verified(claimed["what may be claimed"])
    assert "mechanically_informative never established" in \
        claimed["what may be claimed"]
    assert "a gate nobody measured is not a gate that passed" in \
        claimed["what may be claimed"]
    assert claimed["qualified state"] == \
        "fully_verified (informativeness not established)"


def test_verified_never_appears_where_the_material_did_nothing():
    row = dict(RECORD, stage="experiment_not_informative",
               evidence=dict(RECORD["evidence"],
                             mechanically_informative=False))
    claimed = what_may_be_claimed(row)
    assert claimed["may be called verified"] is False
    assert not calls_it_verified(claimed["what may be claimed"])
    assert "the material did nothing over this run" in claimed["qualified state"]
    assert "not a verification of its behaviour" in \
        claimed["what may be claimed"]


def test_verified_is_said_only_when_all_six_were_measured_and_all_six_hold():
    row = dict(RECORD, evidence={name: True for name, _, _ in EVIDENCE_GATES})
    claimed = what_may_be_claimed(row)
    assert claimed["all six gates hold"] is True
    assert claimed["may be called verified"] is True
    assert claimed["what may be claimed"].startswith("verified")
    assert claimed["qualified state"] == "fully_verified"


def test_an_entry_that_never_ran_is_not_told_it_agreed():
    """108 of the 254 pass10 entries never reached a run at all -- no deck, no
    material, not a UMAT. Reporting those as "agreement only, informativeness
    not established" would claim an agreement that never happened, which is
    the same error as calling a null a pass wearing different words.
    """
    claimed = what_may_be_claimed({"key": "k", "source": "s.for",
                                   "stage": "needs_material_data"})
    assert claimed["nothing was measured"] is True
    assert claimed["may be called verified"] is False
    assert len(claimed["gates never established"]) == len(EVIDENCE_GATES) == 6
    said = claimed["what may be claimed"]
    assert said.startswith("nothing was measured")
    assert "none of them holds and none of them failed" in said
    assert "agreement" not in said, (
        "nothing ran, so there is no agreement to report either way")
    assert not calls_it_verified(said)
    assert claimed["qualified state"] == "missing_material_data (nothing measured)", (
        "naming ONE unestablished gate over an entry where all six are "
        "unestablished implies the other five were fine")


def test_a_page_over_an_unestablished_gate_warns_rather_than_congratulates():
    """Three channels, because the three states must be distinguishable
    without reading the sentence: success, warning, error."""
    page = drawn(RECORD)
    assert not page.of_kind("success"), (
        "nothing on this entry may be drawn as a success: its informativeness "
        "was never established")
    warnings = " ".join(str(v) for values in page.of_kind("warning")
                        for v in values)
    assert "not established" in warnings

    whole = dict(RECORD, evidence={n: True for n, _, _ in EVIDENCE_GATES},
                 objectivity=dict(RECORD["objectivity"], objective=True),
                 coverage=[{"name": "a", "met": True, "reason": "r"}])
    assert drawn(whole).of_kind("success"), (
        "an entry whose six gates were all measured and all hold is drawn as "
        "one")


def test_a_finding_the_six_gates_do_not_cover_is_carried_beside_them():
    """A source can pass every gate this pipeline measures and still be a
    source whose own response is not frame indifferent. On pass10 exactly one
    entry is: all six gates hold and objective=false at 9.02."""
    whole = dict(RECORD, evidence={n: True for n, _, _ in EVIDENCE_GATES})
    claimed = what_may_be_claimed(whole)
    assert claimed["all six gates hold"] is True
    outside = claimed["findings outside the six gates"]
    assert any("Q sigma Q^T" in said for said in outside)
    assert any("direct strain produced shear" in said and
               NOT_ESTABLISHED in said for said in outside)
    page = drawn(whole).texts()
    assert "the six gates do not cover" in page


# ---------------------------------------------------------------------------
# the planned experiment: why this source was driven the way it was
# ---------------------------------------------------------------------------
def test_the_planned_experiment_says_which_family_and_quotes_what_settled_it():
    """A reading nobody can disagree with is not evidence. The family is on
    the page with the lines of the source that decided it."""
    plan = planned_experiment(RECORD)
    assert plan["recorded"] is True
    assert plan["family"] == "oriented"
    assert plan["driven by"] == "strain"
    assert "material direction" in plan["the criterion this experiment must meet"]
    assert "somewhere to show up" in plan["what the experiment is required to do"]
    assert "rotates its stiffness" in plan["why this source was driven this way"]
    assert plan["the source lines that settled it"] == [
        "the routine reads PROPS(7:9) as direction cosines and rotates the "
        "stiffness by them"]
    assert plan["notes this family carries"] == [
        "this family needs *ORIENTATION on the section"]
    page = drawn(RECORD).texts()
    assert "oriented" in page
    assert "direction cosines" in page


def test_a_record_with_no_planned_experiment_says_not_established():
    """5 of the 38 pass10 records carrying an ``experiment`` block carry an
    empty one, and every pass9 record carries none at all. A blank would read
    as "there was nothing to say"."""
    for row in ({"key": "k", "source": "s.for"},
                {"key": "k", "source": "s.for", "experiment": {}}):
        plan = planned_experiment(row)
        assert plan["recorded"] is False
        assert plan["family"] == NOT_ESTABLISHED
        assert plan["the criterion this experiment must meet"] == NOT_ESTABLISHED
    page = drawn({"key": "k", "source": "s.for", "stage": "verified"})
    warnings = " ".join(str(v) for values in page.of_kind("warning")
                        for v in values)
    assert "records no planned experiment" in warnings


def test_an_empty_family_inside_a_recorded_experiment_is_not_a_family():
    """The shape 5 pass10 records are in: an ``experiment`` block that ran and
    refused, with every field of the family empty and the refusal saying
    why."""
    plan = planned_experiment({"experiment": {
        "criterion": "", "reason": "", "requirement": None,
        "family": {"driver": "", "evidence": [], "name": "", "notes": []},
        "refusal": "the repository publishes no deck with a *USER MATERIAL "
                   "block",
        "warnings": []}})
    assert plan["recorded"] is True
    assert plan["family"] == NOT_ESTABLISHED
    assert plan["driven by"] == NOT_ESTABLISHED
    assert "*USER MATERIAL" in plan["what stopped one being planned"]


# ---------------------------------------------------------------------------
# informativeness, the clock, and whether the response fits the problem
# ---------------------------------------------------------------------------
def test_an_absence_says_which_absence_it_is():
    """Three different reasons a thing was never established, and saying the
    wrong one invents a fact. 108 of the 254 pass10 entries never reached a
    run at all; telling those "this run predates the informativeness gate"
    would be describing a run that does not exist.
    """
    nothing_ran = informativeness_row({"key": "k", "source": "s.for"})
    assert nothing_ran["holds"] == NOT_ESTABLISHED
    assert "nothing ran for this entry" in nothing_ran["why"]

    predates = informativeness_row({"evidence": {"primal_agreed": True}})
    assert predates["holds"] == NOT_ESTABLISHED
    assert "predates the informativeness gate" in predates["why"]

    said = informativeness_row({
        "evidence": {"mechanically_informative": None},
        "mechanically_informative": {
            "informative": None,
            "reason": "the source normalises its clock by TOTALT = 10"}})
    assert said["holds"] == NOT_ESTABLISHED
    assert "TOTALT" in said["why"], (
        "where the record gives its own reason, that is the one shown")


def test_whether_the_material_did_anything_is_three_state_too():
    assert informativeness_row(RECORD)["holds"] == NOT_ESTABLISHED
    did = informativeness_row({"mechanically_informative": {
        "informative": False, "reason": "nothing indicates the material did "
                                        "anything"}})
    assert did["holds"] == DID_NOT_HOLD
    assert "did anything" in did["why"]
    ran = informativeness_row({"mechanically_informative": {
        "informative": True, "reason": "departure_from_linearity fired"}})
    assert ran["holds"] == HELD


def test_the_time_scale_says_which_of_three_things_it_is():
    """A source that declares no clock of its own is not a source whose
    experiment was too short, and the record says which."""
    row = time_scale_row(RECORD)
    assert row["holds"] == NOT_ESTABLISHED
    assert row["the source declares a time scale"] == DID_NOT_HOLD
    assert row["the experiment's total time"] == 13.0
    assert "declares no time scale" in row["why"]
    assert time_scale_row({})["holds"] == NOT_ESTABLISHED
    assert time_scale_row({"time_scale_coverage": {"enough": True,
                                                   "reason": "r"}})["holds"] \
        == HELD


def test_each_plausibility_check_keeps_its_own_answer():
    """Summed into one "plausible" they would hide which scale the response
    failed against -- and one of these was never measured at all."""
    rows = plausibility_rows(RECORD)
    assert [row["holds"] for row in rows] == [HELD, NOT_ESTABLISHED]
    assert "largest material constant" in rows[0]["why"]
    assert "nothing to compare against" in rows[1]["why"]
    page = drawn(RECORD).texts()
    assert "stress against material constants" in page


# ---------------------------------------------------------------------------
# a signature is a set of hypotheses, not a diagnosis
# ---------------------------------------------------------------------------
def test_a_hypothesis_carries_its_status_and_an_unconfirmed_cause_says_so():
    rows = signature_rows(RECORD)
    assert len(rows) == 1
    assert rows[0]["hypothesis"] == "branch_divergence"
    assert rows[0]["confirmation status"] == "needs_more_evidence"
    assert rows[0]["confirmed root cause"] == NOT_ESTABLISHED, (
        "a null root cause is not a root cause, and a blank would read as one")
    assert rows[0]["reproduced"] == NOT_ESTABLISHED
    assert rows[0]["supporting evidence"] == [
        "the source branches on its own stress"]


def test_a_page_with_no_confirmed_cause_says_so_rather_than_listing_theories():
    row = dict(RECORD, stage="primal_disagreed",
               primal=dict(agrees=False, worst_stress_relative=1e-3))
    warnings = " ".join(str(v) for values in drawn(row).of_kind("warning")
                        for v in values)
    assert "no root cause is confirmed" in warnings


def test_a_confirmed_cause_is_shown_as_confirmed():
    rows = signature_rows({"primal_signature": {"hypotheses": [{
        "hypothesis": "dropped_derivative", "claim": "a REAL cast",
        "confirmation_status": "confirmed",
        "confirmed_root_cause": "the routine casts its accumulated strain to "
                                "REAL before returning it"}]}})
    assert rows[0]["confirmation status"] == "confirmed"
    assert rows[0]["confirmed root cause"].startswith("the routine casts")


# ---------------------------------------------------------------------------
# where the constants were looked for
# ---------------------------------------------------------------------------
def test_where_constants_were_looked_for_is_a_finding_with_three_answers():
    found = entry_view(RECORD).material_search_finding
    assert found["holds"] == HELD
    assert found["repository scanned"] == "owner/repo"
    assert found["decks read"] == 17

    missing = entry_view({"key": "k", "source": "s.for",
                          "stage": "needs_material_data",
                          "searched_for_material_data": {
                              "repository": "owner/repo", "decks_scanned": 0,
                              "evidence": ""}}).material_search_finding
    assert missing["holds"] == DID_NOT_HOLD
    assert "no .inp file at all" in missing["why"]

    never = entry_view({"key": "k", "source": "s.for",
                        "stage": "not_a_umat"}).material_search_finding
    assert never["holds"] == NOT_ESTABLISHED, (
        "no scan is recorded, which is 'nobody looked here' and not "
        "'there is nothing to find'")


# ---------------------------------------------------------------------------
# and the whole page, drawn
# ---------------------------------------------------------------------------
def test_every_new_column_reaches_the_page(tmp_path):
    """The requirement this file exists to hold: nothing the batch records is
    allowed to live only in the JSONL."""
    results = tmp_path / "results"
    results.mkdir()
    (results / "store_verification.jsonl").write_text(
        json.dumps(RECORD) + "\n", encoding="utf-8")
    recorder = Recorder()
    render(results, tmp_path / "work", st=recorder)
    page = recorder.texts()
    for said in ("oriented",                       # experiment.family.name
                 "direction cosines",              # experiment.family.evidence
                 "material direction",             # experiment.criterion
                 "direct strain produced shear",   # coverage[].name
                 "Q sigma Q^T",                    # objectivity.objective
                 "converted build agrees",         # objectivity.agreed
                 "9.02",                           # objectivity worst relative
                 "mechanically informative",       # evidence[]
                 "declares no time scale",         # time_scale_coverage
                 "largest material constant",      # response_plausibility
                 "branch_divergence",              # primal_signature
                 "needs_more_evidence",            # its confirmation status
                 "owner/repo",                     # searched_for_material_data
                 NOT_ESTABLISHED):
        assert said in page, said


def test_the_page_decides_nothing_the_record_did_not(tmp_path):
    """Every word of a verdict on the page is the batch's. What this module
    adds is the qualification, and the qualification is derived from the six
    gates rather than from a judgement."""
    results = tmp_path / "results"
    results.mkdir()
    (results / "store_verification.jsonl").write_text(
        json.dumps(RECORD) + "\n", encoding="utf-8")
    recorder = Recorder()
    render(results, tmp_path / "work", st=recorder)
    page = recorder.texts()
    assert "fully_verified" in page
    assert RECORD["objectivity"]["objectivity_reason"] in page
    assert RECORD["coverage"][1]["reason"] in page


# ---------------------------------------------------------------------------
# the rule against the whole finished corpus rather than against a fixture
# ---------------------------------------------------------------------------
#: What the finished pass10 round measures, read through the page's own loader.
#: Written out because these are the numbers the assertions below are about,
#: and a test whose expected value is a variable is a test nobody can check.
#:
#: Reproduce with::
#:
#:     python -c "import sys,collections; sys.path.insert(0,'src'); \
#:       from pathlib import Path; \
#:       from umat_oti.app.corpus_view import load_run, EVIDENCE_GATES; \
#:       v=load_run(Path('../corpus_run/pass10/results')); \
#:       print(len(v.entries), v.by_terminal_state)"
PASS10_ENTRIES = 254
PASS10_WITH_EVIDENCE = 146
#: gate -> (held, did not hold, never established), over the 146 entries that
#: carry an evidence block at all.
PASS10_GATES = {
    "abaqus_job_completed": (146, 0, 0),
    "all_requested_outputs_present": (146, 0, 0),
    "complete_history_finite": (142, 4, 0),
    "primal_agreed": (65, 81, 0),
    "derivatives_verified": (63, 83, 0),
    "mechanically_informative": (113, 22, 11),
}


@pytest.fixture(scope="module")
def corpus():
    if not PASS10_RESULTS.is_file():
        pytest.skip("the finished pass10 corpus round is not on this machine")
    return load_run(PASS10_RESULTS.parent)


def test_the_finished_round_reaches_the_page_whole(corpus):
    assert len(corpus.entries) == PASS10_ENTRIES
    assert corpus.finished is True
    assert len(corpus.by_terminal_state) == 13, (
        "13 distinct terminal states, from fully_verified down to "
        "derivative_truncated; a page that showed fewer would be pooling "
        "answers the record keeps apart")


def test_the_six_gates_do_not_move_together_which_is_why_there_are_six(corpus):
    """The measurement that justifies the whole design.

    If the six always agreed, one tick would carry them. They do not. Over the
    146 entries carrying an evidence block: every one had its job complete and
    every requested output present, 4 went non-finite anyway, 81 disagreed on
    the primal, 83 failed on derivatives, and 11 were never measured for
    informativeness at all. Collapsed into one word, five of those findings
    disappear.
    """
    with_evidence = [e for e in corpus.entries
                     if any(row["established"] for row in e.evidence)]
    assert len(with_evidence) == PASS10_WITH_EVIDENCE

    measured = {}
    for name, _what, _where in EVIDENCE_GATES:
        rows = [{r["field"]: r for r in e.evidence}[name]
                for e in with_evidence]
        measured[name] = (sum(r["holds"] == HELD for r in rows),
                          sum(r["holds"] == DID_NOT_HOLD for r in rows),
                          sum(r["holds"] == NOT_ESTABLISHED for r in rows))
    assert measured == PASS10_GATES

    assert len(set(measured.values())) > 1, (
        "the six gates are not one measurement wearing six names")
    assert measured["abaqus_job_completed"][0] != \
        measured["complete_history_finite"][0], (
        "Abaqus printing THE ANALYSIS HAS COMPLETED SUCCESSFULLY is a "
        "statement about the solver: 146 jobs completed and 4 of them "
        "returned values that are not numbers")


def test_the_eleven_entries_nobody_measured_render_as_a_third_thing(corpus):
    """The single most important rendering requirement in this project.

    11 of the 146 entries carrying an evidence block have
    ``mechanically_informative`` null. Not one of them may render as either of
    the other two states, and the string they render as is neither of the
    other two strings.
    """
    unmeasured = [e for e in corpus.entries
                  if {r["field"]: r for r in e.evidence}[
                      "mechanically_informative"]["holds"] == NOT_ESTABLISHED
                  and any(row["established"] for row in e.evidence)]
    assert len(unmeasured) == 11
    for entry in unmeasured:
        row = {r["field"]: r for r in entry.evidence}["mechanically_informative"]
        assert row["holds"] == NOT_ESTABLISHED
        assert row["holds"] != HELD and row["holds"] != DID_NOT_HOLD
        assert row["established"] is False
        assert row["passed"] is None, (
            "the boolean a caller might read stays None rather than becoming "
            "a False, so a caller cannot collapse three states into two")
        assert entry.informativeness["holds"] == NOT_ESTABLISHED


def test_no_entry_the_page_cannot_vouch_for_is_called_verified(corpus):
    """44 entries reached ``verified``; 3 of them carry no informativeness
    measurement. None of the three may carry the word."""
    verified = [e for e in corpus.entries if e.stage == "verified"]
    assert len(verified) == 44
    unestablished = [e for e in verified
                     if "mechanically_informative" in
                     e.verdict["gates never established"]]
    assert len(unestablished) == 3, (
        "this test is measuring nothing if the round has no such entry")
    for entry in unestablished:
        assert entry.verdict["may be called verified"] is False, entry.source_id
        assert not calls_it_verified(entry.verdict["what may be claimed"]), \
            entry.source_id
        assert entry.verdict["qualified state"] == \
            "fully_verified (informativeness not established)", entry.source_id
        assert entry.verdict["the batch's terminal state"] == "fully_verified", (
            "the batch's own word is still carried, unedited")

    did_nothing = [e for e in corpus.entries
                   if {r["field"]: r for r in e.evidence}[
                       "mechanically_informative"]["holds"] == DID_NOT_HOLD]
    assert len(did_nothing) == 22
    for entry in did_nothing:
        assert entry.verdict["may be called verified"] is False, entry.source_id
        assert not calls_it_verified(entry.verdict["what may be claimed"]), \
            entry.source_id

    # 44 reached the stage and 38 may be called it. The six that may not split
    # two ways and the page keeps them apart: 3 whose informativeness nobody
    # measured, and 3 whose raw primal comparison disagreed and was then
    # explained -- by the author's own declared precision, or by the same
    # mathematics reassociated. Both facts are true at once and both are shown.
    may = [e for e in corpus.entries if e.verdict["may be called verified"]]
    assert len(may) == 38
    assert all(e.stage == "verified" for e in may)
    explained = [e for e in verified
                 if e.verdict["gates that did not hold"] == ["primal_agreed"]]
    assert len(explained) == 3
    for entry in explained:
        assert entry.verdict["what the batch recorded after a gate that did "
                             "not hold"]["primal_agreed"], entry.source_id


def test_every_absence_in_the_round_says_which_absence_it_is(corpus):
    """Measured over the 254: 108 where nothing ran, 4 whose run predates the
    gate, and 7 where the record gives its own reason. A single sentence
    covering all three would describe a run that does not exist for 108 of
    them."""
    reasons = {}
    for entry in corpus.entries:
        if entry.informativeness["established"]:
            continue
        key = ("nothing ran" if "nothing ran for this entry"
               in entry.informativeness["why"] else
               "predates the gate" if "predates the informativeness gate"
               in entry.informativeness["why"] else "the record's own reason")
        reasons[key] = reasons.get(key, 0) + 1
    assert reasons == {"nothing ran": 108, "predates the gate": 4,
                       "the record's own reason": 7}
    assert sum(reasons.values()) == 119


def test_the_entries_that_never_ran_are_not_told_they_agreed(corpus):
    """108 of the 254 never reached a run the gates could be measured on."""
    nothing = [e for e in corpus.entries if e.verdict["nothing was measured"]]
    assert len(nothing) == 108
    for entry in nothing:
        assert len(entry.verdict["gates never established"]) == 6
        assert "agreement" not in entry.verdict["what may be claimed"], \
            entry.source_id
        assert entry.verdict["may be called verified"] is False
        assert entry.verdict["qualified state"].endswith("(nothing measured)"), \
            entry.source_id


def test_every_qualified_state_names_the_gate_that_decides_it(corpus):
    """20 distinct qualified states over the 254, and a bare terminal state
    appears only where all six gates were measured and all six hold.

    This is what stops the page pooling answers the record keeps apart:
    ``primal_disagreed`` alone is 4 different findings once the gates are
    attached to it -- two gates down, the material having done nothing,
    informativeness unmeasured, or three gates down including finiteness.
    """
    states = {}
    for entry in corpus.entries:
        states[entry.verdict["qualified state"]] = \
            states.get(entry.verdict["qualified state"], 0) + 1
    assert len(states) == 20

    bare = [name for name in states if "(" not in name]
    assert bare == ["fully_verified"], (
        "an unqualified state is a claim that all six gates were measured "
        "and all six hold; only one state on this round earns that")
    assert states["fully_verified"] == 38

    # the same terminal state, split by which gates decided it
    disagreed = {name: n for name, n in states.items()
                 if name.startswith("primal_disagreed")}
    assert len(disagreed) == 4, disagreed
    assert sum(disagreed.values()) == 62


def test_both_objectivity_facts_survive_the_whole_corpus(corpus):
    """8 entries carry a completed objectivity pair. On 7 of them the two
    facts DISAGREE -- the converted build agreed with the original on a
    rotated path and the author's own response is not Q sigma Q^T -- which is
    exactly the pair one tick would destroy."""
    pairs = [e for e in corpus.entries
             if all(row["established"] for row in e.objectivity)]
    assert len(pairs) == 8
    outcomes = {}
    for entry in pairs:
        key = tuple(row["holds"] for row in entry.objectivity)
        outcomes[key] = outcomes.get(key, 0) + 1
    assert outcomes == {(HELD, DID_NOT_HOLD): 7, (DID_NOT_HOLD, DID_NOT_HOLD): 1}

    disagreeing = [e for e in pairs
                   if e.objectivity[0]["holds"] != e.objectivity[1]["holds"]]
    assert len(disagreeing) == 7
    for entry in disagreeing:
        transform, model = entry.objectivity
        assert "the transform" in transform["what it is about"]
        assert "the model" in model["what it is about"]
        assert transform["why"] != model["why"], entry.source_id
        assert model["magnitude"] is not None, (
            "a model that is not objective says by how much")
        assert any("Q sigma Q^T" in said for said in
                   entry.verdict["findings outside the six gates"]), \
            entry.source_id


def test_every_unmeasured_coverage_criterion_says_why_it_was_not(corpus):
    """Over the round: 260 criteria met, 21 not met, and 12 that nobody could
    measure -- and the 12 are the ones a two-state rendering would have to
    lie about."""
    tally = {HELD: 0, DID_NOT_HOLD: 0, NOT_ESTABLISHED: 0}
    for entry in corpus.entries:
        for row in entry.coverage:
            tally[row["holds"]] += 1
    assert tally == {HELD: 260, DID_NOT_HOLD: 21, NOT_ESTABLISHED: 12}
    for entry in corpus.entries:
        for row in entry.coverage:
            if row["holds"] == NOT_ESTABLISHED:
                assert row["established"] is False
                assert row["why"], (
                    "an unmeasured criterion says why it was not, or it is "
                    "indistinguishable from one nobody wrote down")


def test_the_planned_experiment_reaches_the_page_for_every_family(corpus):
    """8 families across the round, 78 entries with none settled. A family
    that never reached the page would be a reading of somebody's source that
    nobody can disagree with."""
    families = {}
    for entry in corpus.entries:
        name = entry.planned_experiment["family"]
        families[name] = families.get(name, 0) + 1
    assert families == {NOT_ESTABLISHED: 78, "growth": 129, "finite strain": 22,
                        "strain driven": 13, "plane stress": 7, "cohesive": 2,
                        "rate dependent": 2, "oriented": 1}
    settled = [e for e in corpus.entries
               if e.planned_experiment["family"] != NOT_ESTABLISHED]
    assert all(e.planned_experiment["why this source was driven this way"]
               for e in settled)


def test_every_entry_in_the_round_draws_without_raising(corpus):
    """A page that raises on one record shows nothing for the whole round.
    All 254, drawn, including the 108 that never reached an evidence block."""
    drawn_count = 0
    for entry in corpus.entries:
        recorder = Recorder()
        _entry_panel(entry, Path("/nowhere"), recorder)
        page = recorder.texts()
        assert entry.source_id or entry.key
        # whatever else it says, it never says a null held
        for row in list(entry.coverage) + list(entry.objectivity) + \
                [entry.informativeness, entry.time_scale]:
            if not row["established"]:
                assert row["holds"] == NOT_ESTABLISHED
        assert NOT_ESTABLISHED in page or all(
            row["established"] for row in entry.evidence), entry.source_id
        drawn_count += 1
    assert drawn_count == PASS10_ENTRIES
