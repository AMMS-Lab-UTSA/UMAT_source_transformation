"""Every measurement the batch records reaches the page, or it is not evidence.

A verification that exists only inside a JSONL file is a verification nobody
read. The corpus page is where a reader meets it, so the rule this file holds
is narrow and absolute: for every field the batch writes about an entry, there
is somewhere on the page it appears, and there is a path to the file it came
out of.

The record these run against is the real one. ``tests/fixtures/corpus`` is the
bundled J2 control -- this project's own ``UMATs/generic_ps/j2_props.f``, which
is the one source in the corpus it may redistribute -- exactly as
``verify_store_in_abaqus.py`` wrote it, with the two probe histories trimmed to
the first eight records so the fixture stays small. Nothing in it was written
to make a test pass.

What each test is for: a field that moved is a field the page silently stops
showing. Five of them had already moved. ``failure_mechanism``,
``segment_repair``, ``coverage_given_up``, ``safe_loading_reconstructed`` and
``discovery_usable_prefix`` are written inside ``discovery`` by the run that
settles them there, and the view read them from the top of the record. On the
pass9 corpus not one of the 250 records carries any of the five at the top, so
the page showed a blank for all of them -- hiding 139 usable prefixes, 30 named
failure mechanisms, 23 repaired segments, 13 experiments that gave up coverage
and 7 rebuilt loadings. A blank reads as "not measured".
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.abaqus.terminal_states import ALL, FULLY_VERIFIED  # noqa: E402
from umat_oti.app.corpus_view import (EVIDENCE_GATES,  # noqa: E402
                                      EVIDENCE_LOCATIONS, componentwise_errors,
                                      entry_view, evidence_paths, evidence_rows,
                                      fd_plateau, field_anywhere, histories,
                                      history_rows, job_log, load_run,
                                      loading_rows)
from umat_oti.app.corpus_tab import GLOSS, render  # noqa: E402

CORPUS = REPO / "tests" / "fixtures" / "corpus"
RESULTS = CORPUS / "results"
WORK = CORPUS / "work"


@pytest.fixture(scope="module")
def control():
    """The bundled J2 control, as the interface sees it."""
    return load_run(RESULTS, WORK).entries[0]


@pytest.fixture(scope="module")
def record():
    """The same entry, as the batch wrote it."""
    return json.loads((RESULTS / "store_verification.jsonl").read_text().strip())


class Recorder:
    """A stand-in for Streamlit that records what would be drawn."""

    def __init__(self, choices=None):
        self.written: list = []
        self.choices = choices or {}
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
        return self.choices.get(label, list(options)[0] if options else None)

    def text_input(self, label, value="", **kwargs):
        self._record("text_input", label)
        return self.choices.get(label, value)

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

    def texts(self) -> str:
        parts = [str(value) for _kind, values in self.written for value in values]
        for child in self.children:
            parts.append(child.texts())
        return " ".join(parts)


@pytest.fixture(scope="module")
def page():
    """Everything the page would draw for the control, as one string."""
    recorder = Recorder()
    render(RESULTS, WORK, st=recorder)
    return recorder.texts()


# ---------------------------------------------------------------------------
# the manifest
# ---------------------------------------------------------------------------
def test_the_manifest_that_was_run_is_on_the_page(control, record, page):
    """Not a summary of it: the constants, the tensor split, the step ladder
    and the tolerances the batch actually drove.

    Measured on the control: 4 constants (200000, 0.3, 250, 2000), NTENS 6 as
    NDI 3 and NSHR 3, NSTATV 1, eight finite-difference steps from 1e-1 to
    1e-8, a primal tolerance of 1e-10. A regression replays this manifest, so
    a reader who cannot see it cannot see what a regression is replaying.
    """
    assert control.run_manifest == record["manifest"], (
        "the page shows the manifest the batch ran, unedited")
    for value in ("200000.0", "1e-10", "'C3D8'", "'small strain'"):
        assert value in page, value
    assert control.run_manifest["nprops"] == 4
    assert control.run_manifest["ndi"] + control.run_manifest["nshr"] == \
        control.run_manifest["ntens"]
    assert len(control.run_manifest["fd_steps"]) == 8


def test_the_inferred_manifest_carries_the_provenance_of_every_inference(control):
    """Element type, kinematics and tensor shape each with what decided them.

    A constant with no stated origin is worse than a missing one: it reads as
    established when nothing established it. The control's kinematics is
    small strain because "no *STEP in j2.inp sets NLGEOM, which is Abaqus's
    default of NLGEOM=NO" -- a sentence a reader can go and check.
    """
    manifest = control.manifest
    assert manifest["kinematics"] == "small strain"
    assert "NLGEOM" in manifest["kinematics_provenance"]
    assert manifest["element_type"] and manifest["ntens"] == 6
    assert manifest["deck_digest"] and manifest["source_form"]


# ---------------------------------------------------------------------------
# material provenance
# ---------------------------------------------------------------------------
def test_the_material_provenance_names_the_deck_the_constants_came_from(
        control, page):
    """"Four constants" is not provenance; "j2.inp *MATERIAL J2: 4 constants,
    *DEPVAR 1" is, because it names a file and a block a reader can open."""
    provenance = control.manifest["material_provenance"]
    assert "*MATERIAL J2" in provenance
    assert "4 constants" in provenance
    assert control.manifest["deck"].endswith(".inp")
    assert provenance in page
    satisfied = {r.name: r for r in control.requirements}
    assert satisfied["published material constants"].satisfied
    assert satisfied["published material constants"].detail == provenance


def test_a_source_with_no_constants_says_what_was_read_looking_for_them(tmp_path):
    """"No deck publishes constants for this source" is a claim until it names
    the files it read. The pairing scan's own account is what goes on the page.

    All 250 pass9 records carry ``searched_for_material_data``; 40 of them
    settled at ``needs_material_data`` and each one names the repository it
    scanned and how many .inp files were in it.
    """
    results = tmp_path / "results"
    results.mkdir()
    (results / "store_verification.jsonl").write_text(json.dumps({
        "key": "k1", "source": "owner__repo/umat.for", "stage": "needs_material_data",
        "reason": "no deck is paired with this source",
        "searched_for_material_data": {
            "repository": "owner/repo", "decks_scanned": 17,
            "evidence": "no *MATERIAL block names this routine"},
    }) + "\n", encoding="utf-8")
    entry = load_run(results).entries[0]
    detail = {r.name: r.detail for r in entry.requirements}[
        "published material constants"]
    assert "17 .inp file(s)" in detail
    assert "owner/repo" in detail
    assert entry.material_search["decks_scanned"] == 17


# ---------------------------------------------------------------------------
# the loading history
# ---------------------------------------------------------------------------
def test_the_loading_history_is_on_the_page_segment_by_segment(control, page):
    """What the experiment walked, not what the search chose.

    The control's path is four segments: a uniaxial pull of 1e-2 over 10
    increments, a simple shear, a reversal at half amplitude, and a hold of
    the uniaxial strain over ten times the step time. The hold is there
    because a rate probe found the material time dependent -- stress moved by
    6.07e-01 relative while the strain was held -- and no amplitude would have
    found that, because raising the strain does not make time pass.
    """
    names = [row["segment"] for row in control.loading]
    assert names == ["uniaxial", "simple_shear", "uniaxial_reversed",
                     "uniaxial_hold"]
    held = control.loading[-1]
    assert held["step time"] == 10.0, "the hold runs on a stretched clock"
    assert held["increments"] == 5
    for name in names:
        assert name in page, name
    assert "reversal" in page, "what each segment is for, not only its name"


def test_the_rate_probe_that_added_the_hold_is_on_the_page(control, page):
    """A segment nobody can see the reason for is a segment nobody can check."""
    probe = control.discovery.get("time") or {}
    assert probe["rate_dependent"] is True
    assert probe["relaxed"] is True
    assert round(probe["rate_difference"], 3) == 0.607
    assert "time dependent" in page


def test_a_record_with_no_manifest_has_no_loading_rows_rather_than_a_guess():
    assert loading_rows({}) == []
    assert loading_rows({"manifest": {"loading": ["not a segment"]}}) == []


# ---------------------------------------------------------------------------
# what Abaqus did
# ---------------------------------------------------------------------------
def test_the_abaqus_job_status_is_on_the_page_for_both_builds(control, page):
    """Both jobs, separately: completed, how many increments, what they warned.

    Measured on the control: both builds completed 35 increments and produced
    280 converged records each, and the original carries 2 warnings that are
    on the page rather than folded into a verdict.
    """
    assert set(control.jobs) >= {"original", "transformed"}
    for name in ("original", "transformed"):
        job = control.jobs[name]
        assert job["completed"] is True
        assert job["increments"] == 35
        assert job["converged_records"] == 280
    assert control.jobs["original"]["warnings"], "warnings are shown, not eaten"
    assert "35" in page


def test_the_solvers_own_files_are_readable_from_the_page(control):
    """Which file a diagnostic came from is part of reading it, so the status,
    message and data files are named apart rather than concatenated."""
    found = job_log(WORK, control.key, "original")
    assert ".sta" in found["files"]
    assert "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in found["files"][".sta"]
    assert ".msg" in found["files"]


def test_a_completed_job_is_not_by_itself_a_finite_one(control, record):
    """Abaqus printing THE ANALYSIS HAS COMPLETED SUCCESSFULLY is a statement
    about the solver, not about the constitutive routine it called.

    Measured on BodyForce-Growth-2Stages.for: both builds "completed" 35
    increments and both were non-finite from the third. So the page carries
    ``abaqus_job_completed`` and ``complete_history_finite`` as two separate
    gates, and this asserts the second is not derived from the first.
    """
    gates = {row["field"]: row for row in control.evidence}
    assert gates["abaqus_job_completed"]["passed"] is True
    assert gates["complete_history_finite"]["passed"] is True
    broken = dict(record, evidence=dict(record["evidence"],
                                        complete_history_finite=False))
    gates = {row["field"]: row for row in evidence_rows(broken)}
    assert gates["abaqus_job_completed"]["passed"] is True
    assert gates["complete_history_finite"]["passed"] is False


def test_the_history_grouping_says_where_the_numbers_stopped_being_numbers():
    """Not that something went wrong -- which increment, which element, which
    material point.

    Shaped on the 38 pass9 records that carry a first non-finite material
    point; the one below is the shape they are all written in.
    """
    rows = history_rows({"history_grouping": {"original": {
        "complete": False, "raw_output_records": 40, "complete_increments": 5,
        "material_points_per_increment": 8, "total_increments": 35,
        "first_incomplete_increment": {"increment": 6, "points": 8,
                                       "expected_points": 8, "finite": False,
                                       "present": True, "time": 0.5},
        "first_non_finite_material_point": {"element": 1, "increment": 6,
                                            "point": 1, "step": 1,
                                            "time": 0.5}}}})
    assert len(rows) == 1
    said = rows[0]["first non finite material point"]
    assert "element=1" in said and "point=1" in said and "increment=6" in said
    assert rows[0]["complete increments"] == "5"
    assert rows[0]["complete"] == "no"


def test_both_histories_are_shown_side_by_side(control):
    """A transformed history two increments shorter than the original is the
    finding, and it is only a finding if the two are next to each other."""
    kinds = [row["history"] for row in control.history]
    assert "original" in kinds and "transformed" in kinds
    original, transformed = control.history[0], control.history[1]
    assert original["raw output records"] == transformed["raw output records"]
    assert original["complete increments"] == "35"


def test_the_stress_histories_come_back_as_series_a_plot_can_use(control):
    series = histories(WORK, control.key)
    assert set(series) >= {"original", "transformed"}
    assert len(series["original"]["stress"]) == 8
    assert len(series["original"]["stress"][0]) == 6
    assert series["original"]["increment"][:3] == [1, 2, 3]


# ---------------------------------------------------------------------------
# mechanical activation
# ---------------------------------------------------------------------------
def test_the_page_says_what_made_the_material_count_as_active(control, page):
    """Four indicators, each with whether it fired and by how much.

    Measured on the control at the chosen amplitude: departure from linearity
    fired at 2.0 and residual after reversal at 0.333, while state change did
    not move at all and tangent change measured nothing -- so "activated" on
    the page is four numbers a reader can disagree with, not a word.
    """
    attempt = (control.discovery.get("attempts") or [])[0]
    indicators = {i["name"]: i for i in attempt["activation"]["indicators"]}
    assert set(indicators) == {"state_change", "departure_from_linearity",
                               "tangent_change", "residual_after_reversal"}
    assert indicators["departure_from_linearity"]["fired"] is True
    assert indicators["state_change"]["fired"] is False
    assert indicators["state_change"]["detail"] == "no state variable moved"
    assert "activated" in page and "departure_from_linearity" in page


def test_what_the_activation_probe_could_not_measure_is_said_too(control):
    """A probe that lists only what it found reads as exhaustive. This one
    names the three things it cannot see -- dissipated energy, a PNEWDT
    cutback request, and which constitutive branch executed."""
    not_measured = (control.discovery.get("attempts") or [])[0][
        "activation"]["not_measured"]
    assert len(not_measured) == 3
    assert any("PNEWDT" in line for line in not_measured)
    assert any("dissipated energy" in line for line in not_measured)


def test_a_gate_nobody_measured_is_not_reported_as_a_failure(control):
    """A step whose result was never established is not a step that failed,
    and reporting it as one invents a failure the batch did not record.

    The control predates the informativeness gate, so
    ``mechanically_informative`` is absent from its evidence. The page says
    "not measured" for it and leaves ``passed`` as None.
    """
    gates = {row["field"]: row for row in control.evidence}
    assert gates["mechanically_informative"]["measured"] == "not measured"
    assert gates["mechanically_informative"]["passed"] is None
    requirement = {r.name: r for r in control.requirements}[
        "an experiment the material did something in"]
    assert requirement.satisfied is True
    assert "never measured" in requirement.detail


def test_a_run_that_agreed_about_nothing_is_shown_as_such():
    """Agreement about a material sitting near its initial state is agreement
    about the part every build gets right."""
    entry = entry_view({
        "key": "k", "source": "s.for", "stage": "experiment_not_informative",
        "evidence": {"abaqus_job_completed": True,
                     "all_requested_outputs_present": True,
                     "complete_history_finite": True, "primal_agreed": True,
                     "derivatives_verified": True,
                     "mechanically_informative": False},
        "mechanically_informative": {
            "informative": False,
            "reason": "nothing in the run that was verified indicates the "
                      "material did anything"},
        "time_scale_coverage": {"enough": False,
                                "reason": "the source divides by TotalT = 1.0 "
                                          "and the experiment ran for 0.01"}})
    gates = {row["field"]: row for row in entry.evidence}
    assert gates["mechanically_informative"]["passed"] is False
    requirement = {r.name: r for r in entry.requirements}[
        "an experiment the material did something in"]
    assert requirement.satisfied is False
    assert "did anything" in requirement.detail
    assert entry.experiment["time_scale_coverage"]["enough"] is False


# ---------------------------------------------------------------------------
# the finite-difference plateau
# ---------------------------------------------------------------------------
def test_the_plateau_is_shown_step_by_step_and_not_as_one_number(control, page):
    """One step cannot separate a truncation error from a cancellation one, so
    what a tangent verdict rests on is the run of step sizes the error stops
    moving over -- and that is what the page shows.

    Measured on the control's first verified state: eight steps from 1e-1 to
    1e-8, best 8.25e-11 at 1e-5, and a stable range of 1e-6 to 1e-4. Three of
    the eight rows are inside it.
    """
    rows = fd_plateau(control)
    assert len(rows) == 8
    assert [row["step"] for row in rows][0] == 0.1
    inside = [row for row in rows if row["on the plateau"]]
    assert len(inside) == 3, [r["step"] for r in inside]
    best = [row for row in rows if row["best step"]]
    assert len(best) == 1 and best[0]["step"] == 1e-05
    assert best[0]["relative"] < 1e-10
    assert "8.250183296249711e-11" in page or "8.25" in page


def test_the_three_things_a_step_sweep_can_be_compared_against_are_all_shown(
        control):
    """The converted build's tangent against a difference of the original is
    what a verdict rests on. The author's own DDSDDE against the same
    difference, and the difference's own error, are what say whether a
    disagreement is the transform's or the author's.

    Measured on the control: 8.25e-11 for the verdict, 6.07e-01 for the
    author's own tangent, 4.41e-01 for the reference's own error. A page
    showing only the first would report a verified transform of a source whose
    published tangent is 60% wrong without saying so.
    """
    verdict = fd_plateau(control, against="comparison")
    authors = fd_plateau(control, against="against_the_authors_tangent")
    reference = fd_plateau(control, against="the_references_own_error")
    assert verdict and authors and reference
    assert min(r["relative"] for r in verdict) < 1e-10
    assert min(r["relative"] for r in authors) > 0.5
    assert min(r["relative"] for r in reference) > 0.4


def test_the_regime_that_made_a_state_differentiable_is_shown(control):
    """A kink's gap is the difference between two limiting derivatives and is
    of order one; round-off is not. The control's first state was accepted at
    a step of 1e-7 where the one-sided differences agree to 2.12e-08."""
    state = control.tangent["states"][0]
    regime = state["regime"]
    assert regime["regime"] == "smooth_inelastic"
    assert regime["verifiable"] is True
    assert regime["selected_step"] == 1e-07
    assert len(regime["rejected_steps"]) == 5
    assert len(state["smoothness"]) == 8


# ---------------------------------------------------------------------------
# componentwise errors
# ---------------------------------------------------------------------------
def test_the_componentwise_table_names_the_entry_that_disagrees(control):
    """"The tangent disagreed by 3e-4" is a number; "DDSDDE(4,4) disagreed by
    3e-4 and every other entry agreed to 1e-12" is a finding.

    Measured on the control at its first verified state: DDSDDE(1,1) is
    2.69e+05 in the author's routine and 1.68e+05 in the converted build, a
    relative difference of 3.78e-01 -- which is the same disagreement the
    record summarises as against_the_authors_tangent = 6.07e-01, laid out per
    entry instead of summed into a norm.
    """
    rows = componentwise_errors(control, 0, work_dir=WORK)
    assert len(rows) == 36, "six by six, every entry, none hidden"
    assert rows[0]["entry"] == "DDSDDE(1,1)"
    assert round(rows[0]["relative"], 3) == 0.378
    assert rows[0]["the author's own"] > rows[0]["the converted build's"]
    assert [r["relative"] for r in rows if r["relative"] is not None] == \
        sorted((r["relative"] for r in rows if r["relative"] is not None),
               reverse=True), "worst first, so a reader sees it without sorting"


def test_a_component_too_small_to_resolve_is_left_unscored_rather_than_scored(
        control):
    """A component eight orders below the largest holds each build's rounding
    and nothing else, and dividing by it manufactures a disagreement out of
    round-off.

    Measured on the control: of 36 entries, 24 are unscored and the largest of
    them is 1.25e-13 against a tangent whose largest entry is 2.69e+05 -- 18
    orders down. The 12 that are scored disagree by 2.95e-02 to 3.78e-01, and
    those are the entries that carry the stiffness.
    """
    rows = componentwise_errors(control, 0, work_dir=WORK)
    unscored = [r for r in rows if r["relative"] is None]
    assert len(unscored) == 24
    largest = max(abs(r["the author's own"]) for r in rows)
    assert all(max(abs(r["the author's own"]),
                   abs(r["the converted build's"])) <= largest * 1e-8
               for r in unscored)
    scored = [r["relative"] for r in rows if r["relative"] is not None]
    assert len(scored) == 12
    assert min(scored) > 1e-2, (
        "every entry that was scored carries some of the response")


def test_the_table_is_empty_rather_than_invented_when_the_probe_is_gone(control):
    """An interface that fills this in from nothing would be showing a
    difference nobody computed."""
    assert componentwise_errors(control, 0, work_dir=None) == []
    assert componentwise_errors(control, 99, work_dir=WORK) == []


# ---------------------------------------------------------------------------
# terminal classification
# ---------------------------------------------------------------------------
def test_the_terminal_state_is_the_batchs_and_carries_whose_move_it_is(control):
    assert control.terminal_state == FULLY_VERIFIED
    assert control.kind == "verified"
    assert control.stage == "verified"


def test_every_terminal_state_has_a_gloss_and_names_an_owner():
    """A table of terminal states is unreadable without the vocabulary, and a
    state that does not say whose move it is cannot route anything."""
    assert set(ALL) <= set(GLOSS), sorted(set(ALL) - set(GLOSS))
    ours = [state for state in ALL if GLOSS[state].endswith("-- ours")
            or "-- our work" in GLOSS[state]]
    assert ours, "the states that are this project's work say so"
    for state in ALL:
        assert GLOSS[state], state


def test_a_superseded_verdict_does_not_sit_beside_the_one_that_replaced_it(
        tmp_path, record):
    """The results file is append-only: a resumed run appends rather than
    edits, and counting both reports two outcomes for one entry."""
    results = tmp_path / "results"
    results.mkdir()
    superseded = dict(record, stage="tangent_not_verified")
    (results / "store_verification.jsonl").write_text(
        json.dumps(superseded) + "\n" + json.dumps(record) + "\n",
        encoding="utf-8")
    view = load_run(results)
    assert view.attempted == 1
    assert view.by_terminal_state == {FULLY_VERIFIED: 1}


# ---------------------------------------------------------------------------
# the path to every piece of evidence
# ---------------------------------------------------------------------------
def test_there_is_a_path_to_every_piece_of_evidence_on_the_page(control):
    """A panel that shows a number without saying which file it came out of is
    asking to be believed. Every claim names the field in the record and, where
    the claim rests on something on disk, the file under this entry's work
    directory.

    Measured on the control: 16 claims, of which 10 point at a file. Six of
    those ten are present in this trimmed fixture and four are not -- the
    replay directory, the discovery directory, the precision control and the
    association control were left out or never ran -- and the page says so for
    each rather than showing a path that is not there as though it were.
    """
    rows = evidence_paths(control)
    assert len(rows) == len(EVIDENCE_LOCATIONS) == 16
    assert all(row["field in the record"] for row in rows)
    on_disk = [row for row in rows if row["on disk"]]
    assert len(on_disk) == 10
    assert len([row for row in on_disk if row["present"]]) == 6
    assert len([row for row in on_disk if row["present"] is False]) == 4
    for row in on_disk:
        assert str(WORK) in row["on disk"], row
    for row in rows:
        if not row["on disk"]:
            assert row["present"] is None, (
                "a claim that rests on the record alone says so rather than "
                "reporting a missing file")


def test_every_gate_reaches_the_page_with_what_it_measures(control, page):
    """Six gates, six sentences. A gate whose meaning is not on the page is a
    boolean a reader has to take on trust."""
    rows = control.evidence
    assert [row["field"] for row in rows] == [name for name, _, _ in EVIDENCE_GATES]
    for row in rows:
        assert row["what it measures"] and row["read from"]
        assert row["field"].replace("_", " ") in page, row["field"]


def test_a_field_written_under_discovery_still_reaches_the_page():
    """The bug this file exists to stop coming back.

    ``failure_mechanism``, ``segment_repair``, ``coverage_given_up``,
    ``safe_loading_reconstructed`` and ``discovery_usable_prefix`` are written
    inside ``discovery`` by the run that settles them there. Read from the top
    of the record they come back as None, and None renders as a blank, and a
    blank reads as "not measured". On pass9 that was 139 records.
    """
    row = {"key": "k", "source": "s.for", "stage": "experiment_not_generated",
           "discovery": {
               "complete_finite_verification_run": False,
               "failure_mechanism": {"kind": "path_segment_limited"},
               "segment_repair": "'uniaxial_reversed' was dropped",
               "coverage_given_up": "'uniaxial_hold' was dropped",
               "safe_loading_reconstructed": {"amplitude": 0.008,
                                              "fraction": 0.8},
               "discovery_usable_prefix": {
                   "complete": False, "complete_increments": 20,
                   "total_increments": 26, "raw_output_records": 160,
                   "material_points_per_increment": 8,
                   "first_non_finite_material_point": {
                       "element": 1, "point": 3, "increment": 21}}}}
    for name in ("failure_mechanism", "segment_repair", "coverage_given_up",
                 "safe_loading_reconstructed", "discovery_usable_prefix",
                 "complete_finite_verification_run"):
        assert field_anywhere(row, name) is not None, name
    entry = entry_view(row)
    assert entry.experiment["failure_mechanism"]["kind"] == "path_segment_limited"
    assert entry.manifest["coverage_given_up"] == "'uniaxial_hold' was dropped"
    assert entry.history and entry.history[0]["complete increments"] == "20"
    detail = {r.name: r.detail for r in entry.requirements}[
        "an analysis finite from end to end"]
    assert "20 complete increment(s) of 26" in detail
    assert "path segment limited" in detail
    assert "element 1 point 3" in detail
    assert "rebuilt at 0.008" in detail
    assert "dropped" in detail


def test_a_verified_entry_still_says_what_its_experiment_stopped_exercising():
    """An experiment that stopped testing reversal must not be shown as though
    it still did. 139 pass9 records carry a coverage_given_up sentence."""
    entry = entry_view({
        "key": "k", "source": "s.for", "stage": "verified",
        "complete_finite_verification_run": True,
        "history_grouping": {"original": {"complete_increments": 26,
                                          "material_points_per_increment": 8}},
        "discovery": {"coverage_given_up": "'uniaxial_reversed' was dropped: "
                                           "the model left its domain"}})
    detail = {r.name: r.detail for r in entry.requirements}[
        "an analysis finite from end to end"]
    assert "26 complete increment(s)" in detail
    assert "dropped" in detail


# ---------------------------------------------------------------------------
# and the page as a whole
# ---------------------------------------------------------------------------
def test_the_page_draws_the_control_without_deciding_anything(page):
    """Every verdict on the page is a word the batch wrote."""
    assert "fully_verified" in page
    assert "bundled__generic_ps/src/j2_props.f" in page
    assert "j2.inp *MATERIAL J2" in page


def test_the_page_never_starts_a_run_the_user_did_not_press(tmp_path):
    recorder = Recorder()
    render(RESULTS, tmp_path / "work", st=recorder)
    assert [kind for kind, _ in recorder.written if kind == "button"]
    assert not (RESULTS / "discovery.log").exists()


def test_the_page_reads_no_corpus_source():
    """The corpus is not redistributable. The interface shows paths, digests
    and provenance; the text stays outside the tree."""
    for name in ("corpus_view.py", "corpus_tab.py"):
        module = (REPO / "src" / "umat_oti" / "app" / name).read_text()
        assert "cache_root" not in module, name
        assert "discovery_cache" not in module, name


# ---------------------------------------------------------------------------
# a gate that did not pass, next to a verdict that did
# ---------------------------------------------------------------------------
def test_a_disagreement_that_was_explained_says_what_explained_it():
    """17 pass9 entries reached ``verified`` with ``evidence.primal_agreed``
    false, and both of those are true at once.

    The raw comparison of the two builds is one claim; what the batch did next
    is another. It re-runs the ORIGINAL with the author's own declared
    precision widened, and where that does not settle it, with the same
    mathematics reassociated. A page showing only the gate reads as a
    contradiction; a page showing only the verdict hides that the raw builds
    differ. Both are shown, and the sentence between them is the batch's own.
    """
    entry = entry_view({
        "key": "k", "source": "s.for", "stage": "verified",
        "reason": "the original declares LAMBDA1 at single precision and the "
                  "OTI type is built over doubles",
        "evidence": {"abaqus_job_completed": True,
                     "all_requested_outputs_present": True,
                     "complete_history_finite": True, "primal_agreed": False,
                     "derivatives_verified": True},
        "primal": {"agrees": False, "worst_stress_relative": 1.2e-06,
                   "explained_by_declared_precision": True},
        "precision_control": {
            "agrees": True,
            "reason": "the original with those declarations alone widened to "
                      "REAL*8 agrees with the converted build to 0.000e+00"}})
    gate = {row["field"]: row for row in entry.evidence}["primal_agreed"]
    assert gate["passed"] is False
    assert "declared precision" in gate["and then"]
    assert "REAL*8" in gate["and then"]
    assert entry.terminal_state == FULLY_VERIFIED


def test_the_association_control_reaches_the_page_too():
    """"The two builds differ by 1.189e-06, and this model differs from ITSELF
    by 1.422e-06 when the same source is compiled so that the same mathematics
    is computed differently" is the whole of the argument, and it is unreadable
    without the number it is made of."""
    entry = entry_view({
        "key": "k", "source": "s.for", "stage": "verified",
        "reason": "the two builds differ by 1.189e-06, and this model differs "
                  "from ITSELF by 1.422e-06 when the same source is compiled "
                  "so that the same mathematics is computed differently",
        "evidence": {"primal_agreed": False},
        "primal": {"agrees": False, "worst_stress_relative": 1.189e-06},
        "association_control": {"ran": True, "measured": True,
                                "worst_stress_relative": 1.422e-06}})
    assert entry.association_control["worst_stress_relative"] == 1.422e-06
    gate = {row["field"]: row for row in entry.evidence}["primal_agreed"]
    assert "reassociated" in gate["and then"]
    assert "1.422e-06" in gate["and then"]
    claims = {row["field in the record"] for row in evidence_paths(entry)}
    assert "association_control" in claims


def test_a_gate_that_passed_carries_no_excuse(control):
    """The "and then" column is for a gate that did not pass. Filling it in for
    one that did would read as a caveat on a clean measurement."""
    for row in control.evidence:
        if row["passed"] is not False:
            assert row["and then"] == "", row["field"]


# ---------------------------------------------------------------------------
# and against the whole corpus, not only the one entry it was written on
# ---------------------------------------------------------------------------
#: The corpus run this evidence was measured on. It is 7 GB of Abaqus output,
#: so it lives beside the checkout rather than in it, and the tests that need
#: it skip when it is not on this machine. Derived from the checkout's location
#: rather than written out, because an absolute path under a home directory is
#: a property of one computer and means nothing to a reader of this file.
PASS9 = Path(os.environ.get("UMAT_OTI_CORPUS_RUN")
             or REPO.parent / "corpus_run" / "pass9")


@pytest.mark.skipif(not (PASS9 / "results" / "store_verification.jsonl").is_file(),
                    reason="the pass9 corpus run is not on this machine")
def test_every_record_in_the_corpus_reaches_the_page():
    """A panel written against one clean entry is a panel that has met one
    clean entry. The shapes that break it are the failures.

    Measured on pass9: 250 records across 12 terminal stages -- 67 verified,
    42 whose builds disagreed, 40 with no published constants, 27 that are not
    UMATs, 26 with no experiment, 23 job failures and the rest. Every one goes
    through the view, and one entry of every stage renders, without an
    exception and without a field coming back as an unhandled shape.
    """
    from umat_oti.app.corpus_view import RESULTS_FILE

    rows = [json.loads(line) for line
            in (PASS9 / "results" / RESULTS_FILE).read_text().splitlines()
            if line.strip()]
    work = PASS9 / "work"
    assert len(rows) == 250
    stages = set()
    for row in rows:
        entry = entry_view(row, work)
        stages.add(entry.stage)
        assert len(entry.evidence) == 6
        assert len(evidence_paths(entry)) == len(EVIDENCE_LOCATIONS)
        entry.as_dict()
        fd_plateau(entry)
        componentwise_errors(entry, 0, work_dir=work)
    assert len(stages) == 12, sorted(stages)


@pytest.mark.skipif(not (PASS9 / "results" / "store_verification.jsonl").is_file(),
                    reason="the pass9 corpus run is not on this machine")
def test_the_fields_written_under_discovery_are_recovered_across_the_corpus():
    """The count that made this a bug rather than a detail.

    Measured on pass9: 139 of the 250 records reached the loading search, and
    every one of those carries ``discovery_usable_prefix``,
    ``failure_mechanism``, ``segment_repair``, ``coverage_given_up`` and
    ``safe_loading_reconstructed`` inside ``discovery``. NONE of the 250 carry
    any of the five at the top of the record, which is where the view read
    them -- so every one came back as None and rendered as a blank, and a
    blank reads as "not measured".

    What is actually there once they are read from the right place: 139
    usable prefixes, 30 named failure mechanisms, 23 repaired segments, 13
    experiments that gave up coverage, and 7 loadings rebuilt inside the part
    a run had proved safe.
    """
    from umat_oti.app.corpus_view import RESULTS_FILE

    rows = [json.loads(line) for line
            in (PASS9 / "results" / RESULTS_FILE).read_text().splitlines()
            if line.strip()]
    for name in ("failure_mechanism", "segment_repair", "coverage_given_up",
                 "discovery_usable_prefix", "safe_loading_reconstructed"):
        assert not any(row.get(name) for row in rows), (
            f"{name} is never at the top of a pass9 record")
    recovered = {name: sum(1 for row in rows if field_anywhere(row, name))
                 for name in ("discovery_usable_prefix", "failure_mechanism",
                              "segment_repair", "coverage_given_up",
                              "safe_loading_reconstructed")}
    assert recovered == {"discovery_usable_prefix": 139,
                         "failure_mechanism": 30, "segment_repair": 23,
                         "coverage_given_up": 13,
                         "safe_loading_reconstructed": 7}
    with_a_prefix = [entry_view(row) for row in rows
                     if field_anywhere(row, "discovery_usable_prefix")]
    assert all(entry.history for entry in with_a_prefix), (
        "an entry that never reached a verification still has one history in "
        "it, and a panel that shows nothing for it hides the only thing "
        "measured about it")


def test_only_the_fields_known_to_move_are_looked_for_in_two_places():
    """A fallback that reaches into ``discovery`` for any key at all would let
    an unrelated entry of the same name in the search's own bookkeeping stand
    in for a field the verification never recorded -- and a borrowed value is
    worse than a missing one, because it reads as measured.

    ``discovery`` really does carry keys that collide: ``reason``, ``ran``,
    ``jobs``, ``summary`` and ``amplitude`` are all in it on every one of the
    139 pass9 records that reached the search.
    """
    from umat_oti.app.corpus_view import EITHER_LEVEL

    row = {"discovery": {"reason": "the search's own reason",
                         "summary": "activated at 2.5e-05",
                         "coverage_given_up": "'uniaxial_reversed' was dropped"}}
    assert field_anywhere(row, "reason") is None
    assert field_anywhere(row, "summary") is None
    assert field_anywhere(row, "coverage_given_up") is not None
    assert "reason" not in EITHER_LEVEL and "summary" not in EITHER_LEVEL
    source = (REPO / "src" / "umat_oti" / "app" / "corpus_view.py").read_text()
    import re
    asked = set(re.findall(r'field_anywhere\(row, "([a-z_]+)"\)', source))
    assert asked, "the view reads fields through the resolver"
    assert asked <= set(EITHER_LEVEL), sorted(asked - set(EITHER_LEVEL))
