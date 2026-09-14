"""The workflow this interface exists for, driven end to end without a browser.

Every test here drives :func:`umat_oti.app.unified_app.area_view` and the view
modules under it, which is the same code the Streamlit shell draws from. A
screen that cannot be produced headless is a screen nobody checks, and every
rule this interface is held to is a rule about what appears on one.

The records are real. ``corpus_run/pass11/results/store_verification.jsonl``
is the finished pass11 round -- 237 entries, one per store entry -- and the
scenarios the brief names are all in it rather than constructed: 36 entries
with no material constants, 9 whose original job failed, 6 whose converted
build failed, 61 whose stresses disagreed, 19 whose difference could not pin
the tangent down, 5 whose histories contain values that are not numbers, and
42 that satisfy all six gates. Where pass11 is not on the machine the suite is
running on, the bundled J2 control stands in and the pass11 tests skip; they
do not quietly pass.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app import jobs as jobs_module            # noqa: E402
from umat_oti.app import library as library_module      # noqa: E402
from umat_oti.app import residual_bridge, results       # noqa: E402
from umat_oti.app.corpus_view import (NOT_ESTABLISHED,  # noqa: E402
                                      entry_view, load_run)
from umat_oti.app.home import availability, home_view   # noqa: E402
from umat_oti.app.jobs import (StageState, TrackedJobs,  # noqa: E402
                               job_view, stage_state)
from umat_oti.app.plain_language import (EXPERT_TERMS,  # noqa: E402
                                         Failure, failure_for,
                                         may_say_verified, plain_status,
                                         verified_summary)
from umat_oti.app.unified_app import (AREAS, area_view,  # noqa: E402
                                      default_text, jargon_in)

#: The finished pass11 round. Outside the repository because the corpus is not
#: redistributable; the tests that need it skip where it is absent.
PASS11 = Path(os.environ.get(
    "UMAT_OTI_PASS11",
    "/home/ammslab3/softwarex_work/corpus_run/pass11/results"))

#: The bundled J2 control, which ships with the repository.
CONTROL = REPO / "tests" / "fixtures" / "corpus"

pass11_only = pytest.mark.skipif(
    not (PASS11 / "store_verification.jsonl").is_file(),
    reason="the pass11 corpus record is not on this machine")


def _toolchain(abaqus=True, compiler=True):
    """A toolchain probe with a known answer, so tests do not depend on the box."""
    def probe(include_abaqus: bool = True) -> dict:
        reports = {"gfortran": {"available": compiler,
                                "version": "GNU Fortran 11.4.0",
                                "probe_command": ["gfortran", "--version"],
                                "reason": "" if compiler
                                          else "gfortran is not on PATH"}}
        if include_abaqus:
            reports["abaqus"] = {
                "available": abaqus, "version": "2021",
                "probe_command": ["abaqus", "information=release"],
                "reason": "" if abaqus else "no licence could be obtained"}
        return reports
    return probe


@pytest.fixture(scope="module")
def run():
    return load_run(PASS11) if (PASS11 / "store_verification.jsonl").is_file() \
        else load_run(CONTROL / "results", CONTROL / "work")


@pytest.fixture(scope="module")
def control_run():
    return load_run(CONTROL / "results", CONTROL / "work")


def _first(run, predicate):
    return next((e for e in run.entries if predicate(e)), None)


def _at_stage(run, stage):
    entry = _first(run, lambda e: e.stage == stage)
    if entry is None:
        pytest.skip(f"no entry at stage {stage!r} in this record")
    return entry


# ---------------------------------------------------------------------------
# 1. a first-time user, who has been told nothing
# ---------------------------------------------------------------------------
@pass11_only
def test_a_first_time_user_is_told_what_is_here_and_what_they_may_press(run):
    """Home answers the three questions somebody arriving has.

    What is here, does this machine have what it needs, and what do I press.
    An action that cannot run is SHOWN, disabled, with the reason -- a button
    that vanishes teaches nobody anything, and a button that is enabled on an
    assumption fails after it is pressed.
    """
    page = home_view(PASS11, probe=_toolchain(abaqus=False), run=run)

    assert page.counts["materials here"] == 237
    assert page.capabilities["Abaqus"].usable is False
    assert "licence" in page.capabilities["Abaqus"].detail

    offered = {a.key: a for a in page.actions}
    assert set(offered) == {"add_umat", "import_corpus", "verify_umat",
                            "open_verified", "run_regression"}
    # The two that need a solver are refused, and each says why in a sentence
    # naming the thing that is missing.
    assert offered["verify_umat"].enabled is False
    assert "Abaqus" in offered["verify_umat"].reason
    # The three that do not need one are still available.
    assert offered["add_umat"].enabled
    assert offered["import_corpus"].enabled
    assert offered["open_verified"].enabled


@pass11_only
def test_the_whole_interface_speaks_english_by_default(run):
    """No Abaqus keyword and no internal rung name reaches a default screen.

    Checked over every area, for one entry at each stage the record contains,
    rather than for a happy path: the sentences that carry jargon are the ones
    written about failures, and a check that only visited a verified entry
    would pass while the screens a struggling user actually sees were full of
    it. That is how ".inp file at all" and "tangent_change" were found sitting
    in front of a first-time user on the Check-and-prepare screen.
    """
    seen, offenders, renders = {}, [], 0
    for entry in run.entries:
        if seen.get(entry.stage, 0) >= 3:
            continue
        seen[entry.stage] = seen.get(entry.stage, 0) + 1
        for area in AREAS:
            view = area_view(area["key"], results_dir=PASS11, run=run,
                             selected=entry.source_id,
                             probe=_toolchain())
            renders += 1
            offenders += [(area["key"], entry.stage, term, text)
                          for term, text in jargon_in(default_text(view))]

    assert len(seen) >= 14, "this record should cover every stage pass11 has"
    assert renders > 200
    assert offenders == [], (
        f"{len(offenders)} expert terms reached a default screen; "
        f"first: {offenders[0] if offenders else None}")


def test_every_area_the_brief_names_exists_and_renders(control_run):
    """All eight areas, each produced without a browser and without Abaqus."""
    assert [a["key"] for a in AREAS] == [
        "home", "library", "analyze", "verify", "mechanical", "derivative",
        "residual", "reports"]
    entry = control_run.entries[0]
    for area in AREAS:
        view = area_view(area["key"], results_dir=CONTROL / "results",
                         work_dir=CONTROL / "work", run=control_run,
                         selected=entry.source_id, probe=_toolchain())
        assert view["area"] == area["key"]


# ---------------------------------------------------------------------------
# 2 and 3. bringing material in
# ---------------------------------------------------------------------------
def test_importing_a_single_umat_puts_it_in_the_library_with_a_plain_status(
        control_run):
    """One source becomes one row whose status is a sentence, not a rung."""
    rows = library_module.rows(control_run.entries)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_id.endswith("j2_props.f")
    # The status column is plain language. The rung is carried beside it for
    # the Evidence panel and is not what the list shows.
    assert row.status and "_" not in row.status
    assert row.stage == "verified"
    assert row.status != row.stage


@pass11_only
def test_importing_a_corpus_gives_a_searchable_filterable_library(run):
    """237 entries, filterable by the question a user actually has."""
    rows = library_module.rows(run.entries)
    assert len(rows) == 237

    counts = library_module.counts_by_filter(rows)
    assert counts["all"] == 237
    assert counts["verified"] == 42
    # The filter that exists because of the 13. They reached the pipeline's
    # last rung and did not satisfy it, and a library without this filter
    # cannot show a user which ones those are.
    assert counts["nearly"] == 13
    assert counts["verified"] + counts["nearly"] == 55

    # Free text matches what somebody types, and narrows.
    found = library_module.search(rows, text="neohookean")
    assert found and all("neohookean" in r.haystack for r in found)
    assert len(found) < len(rows)

    # Filtering and searching compose.
    verified_only = library_module.search(rows, filter_key="verified")
    assert len(verified_only) == 42
    assert all(r.verified for r in verified_only)


@pass11_only
def test_the_library_sorts_what_a_user_can_act_on_above_what_they_cannot(run):
    """Verified first, then the user's move, then ours, then the file's."""
    rows = library_module.search(library_module.rows(run.entries))
    order = [r.whose_move for r in rows]
    assert order[0] == "nobody"
    first_you = order.index("you")
    first_ours = order.index("this program")
    assert first_you < first_ours


# ---------------------------------------------------------------------------
# 4. the material constants nobody published
# ---------------------------------------------------------------------------
@pass11_only
def test_missing_material_properties_asks_the_user_for_exactly_that(run):
    """The one screen where the answer is the user's, and it asks for it.

    Eight requirements are recorded per entry and several are unmet here. At
    most two of them are anything a person can supply, and the screen asks
    those two -- the rest appear under a heading saying they are this
    program's work. A screen that listed all eight as questions has asked the
    user to find which one is theirs.
    """
    entry = _at_stage(run, "needs_material_data")
    status = plain_status(entry)
    assert status.headline == "Material constants are missing"
    assert status.whose_move == "you"
    assert "constants" in status.what_you_must_provide

    view = area_view("analyze", results_dir=PASS11, run=run,
                     selected=entry.source_id, probe=_toolchain())
    prepare = view["prepare"]
    asked = [q["ask"] for q in prepare["questions"]]
    assert "What are this material's constants?" in asked
    assert len(asked) <= 3, f"too many questions put to the user: {asked}"
    # And the ones that are not theirs are shown as not theirs.
    assert prepare["waiting on this program"]
    for item in prepare["waiting on this program"]:
        assert item["what"] not in asked

    # The pipeline's own sentence is kept, and it is not what was asked.
    recorded = [q["as recorded"] for q in prepare["questions"]]
    assert any(recorded), "the recorded reason must be kept as evidence"
    assert all(r not in asked for r in recorded if r)


@pass11_only
def test_the_one_button_refuses_while_something_is_missing_and_says_what(run):
    """Transform and Verify will not start over an unanswered question."""
    entry = _at_stage(run, "needs_material_data")
    view = area_view("verify", results_dir=PASS11, run=run,
                     selected=entry.source_id, probe=_toolchain())
    button = view["button"]
    assert button["label"] == "Transform and verify"
    assert button["enabled"] is False
    assert "constants" in button["why not"]


def test_the_one_button_refuses_when_the_machine_cannot_run_it(control_run):
    """A missing solver disables the button with the solver named."""
    entry = control_run.entries[0]
    view = area_view("verify", results_dir=CONTROL / "results",
                     work_dir=CONTROL / "work", run=control_run,
                     selected=entry.source_id,
                     probe=_toolchain(abaqus=False))
    assert view["button"]["enabled"] is False
    assert "Abaqus" in view["button"]["why not"]


def test_the_button_is_not_enabled_on_a_capability_nobody_established(
        control_run):
    """An unprobed tool does not count as a working one.

    ``include_abaqus=False`` leaves Abaqus not-established rather than absent,
    and the button stays off. "We did not check" is not "it works", and a
    button enabled on the first would fail after it was pressed.
    """
    entry = control_run.entries[0]
    view = area_view("verify", results_dir=CONTROL / "results",
                     work_dir=CONTROL / "work", run=control_run,
                     selected=entry.source_id, probe=_toolchain(),
                     include_abaqus=False)
    assert view["button"]["enabled"] is False
    assert "could not establish" in view["button"]["why not"]
    capabilities = availability(probe=_toolchain(), include_abaqus=False)
    assert capabilities["Abaqus"].usable is None
    assert capabilities["Abaqus"].word == NOT_ESTABLISHED


# ---------------------------------------------------------------------------
# 5. a verification that succeeded
# ---------------------------------------------------------------------------
@pass11_only
def test_a_successful_verification_says_verified_and_shows_all_six_gates(run):
    """The one case where the word may appear, with the six behind it."""
    entry = _first(run, may_say_verified)
    assert entry is not None
    status = plain_status(entry)
    assert status.headline == "Verified"
    assert status.verified is True
    assert status.qualifier == ""

    summary = verified_summary(entry)
    assert summary["verified"] is True
    assert len(summary["gates"]) == 6
    assert all(g["passed"] is True for g in summary["gates"])
    assert summary["gates that did not hold"] == []
    assert summary["gates never established"] == []
    # And no failure is manufactured for it.
    assert failure_for(entry) is None


@pass11_only
def test_the_mechanical_screen_shows_what_the_material_did(run):
    """Markers, rate, plausibility -- and what the run could not measure."""
    entry = _first(run, lambda e: may_say_verified(e)
                   and e.raw.get("activation_on_the_frozen_run"))
    if entry is None:
        pytest.skip("no verified entry carries an activation record")
    view = results.mechanical_view(entry.raw)

    markers = view["markers"]
    assert markers["the material did something"] in ("yes", "no",
                                                     NOT_ESTABLISHED)
    assert markers["markers"], "the markers must reach the page"
    for marker in markers["markers"]:
        assert marker["happened"] in ("yes", "no", NOT_ESTABLISHED)
        # Plain words, and the internal name kept beside them.
        assert marker["marker"] != marker["internal name"]

    # Energy is NOT drawn. The probe does not produce it and the run says so.
    assert view["energy"]["measured"] is False
    assert view["energy"]["state"] == NOT_ESTABLISHED
    assert "energ" in view["energy"]["why"].lower()

    # Every plausibility check is returned, passing ones included, so that an
    # empty warnings panel cannot mean two different things.
    assert view["plausibility"]
    for check in view["plausibility"]:
        assert check["result"] in ("yes", "no", NOT_ESTABLISHED)


@pass11_only
def test_an_implausible_response_is_warned_about_rather_than_drawn(run):
    """A stress that no material constant accounts for is flagged."""
    entry = _first(
        run, lambda e: isinstance(e.raw.get("response_plausibility"), dict)
        and e.raw["response_plausibility"].get("plausible") is False)
    if entry is None:
        pytest.skip("no entry in this record has an implausible response")
    view = results.mechanical_view(entry.raw)
    assert view["any warning"] is True
    warned = [c for c in view["plausibility"] if c["warn"]]
    assert warned and warned[0]["why"]


# ---------------------------------------------------------------------------
# 6, 7, 8, 9. the four ways it goes wrong
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("stage,expected_headline,whose", [
    ("original_job_failed", "The original version did not finish its run",
     "this program"),
    ("transformed_job_failed",
     "The converted version did not finish its run", "this program"),
    ("primal_disagreed", "The two versions computed different stresses",
     "this program"),
    ("tangent_not_verified", "The derivative check did not settle",
     "this program"),
])
@pass11_only
def test_each_failure_says_the_five_things_a_failure_must_say(
        run, stage, expected_headline, whose):
    """Every failure message carries all five parts, and none is a traceback.

    What failed, why this program believes that, what evidence supports it,
    whether it can be retried, and what the user must provide. The full log is
    present as a field and is never the message.
    """
    entry = _at_stage(run, stage)
    status = plain_status(entry)
    assert status.headline == expected_headline
    assert status.whose_move == whose

    failure = failure_for(entry)
    assert failure is not None
    record = failure.as_dict()
    assert set(record) >= {"what failed", "why this program believes that",
                           "the evidence for it",
                           "can this be retried automatically",
                           "what you must provide", "whose move", "full log"}
    assert record["what failed"] == expected_headline
    assert record["why this program believes that"].strip()
    assert record["the evidence for it"], "a failure must cite what it read"
    assert isinstance(record["can this be retried automatically"], bool)
    # The message is not a traceback, and does not lead with one.
    assert "Traceback" not in record["what failed"]
    assert "Traceback" not in record["why this program believes that"]
    # Where the move is not the user's, nothing is demanded of them.
    if whose != "you":
        assert record["what you must provide"] == ""


@pass11_only
def test_a_failed_abaqus_job_names_the_side_that_failed(run):
    """Which build failed is the finding, and the two are not merged."""
    original = _at_stage(run, "original_job_failed")
    converted = _at_stage(run, "transformed_job_failed")
    assert plain_status(original).headline != plain_status(converted).headline
    assert "original" in plain_status(original).headline.lower()
    assert "converted" in plain_status(converted).headline.lower()


@pass11_only
def test_a_history_that_is_not_finite_is_not_reported_as_an_agreement(run):
    """A comparison against values that are not numbers agrees about nothing.

    Five entries in pass11 have ``complete_history_finite`` measured false.
    The gate reads false on the page, and the entry is not verified -- a
    comparison against NaN returns False for every component and leaves the
    worst difference reading as zero, which is exactly what a page that
    trusted the number would render as perfect agreement.
    """
    entry = _first(run, lambda e: (e.raw.get("evidence") or {}).get(
        "complete_history_finite") is False)
    assert entry is not None
    summary = verified_summary(entry)
    assert summary["verified"] is False
    assert "complete_history_finite" in summary["gates that did not hold"]
    assert may_say_verified(entry) is False
    gate = next(g for g in summary["gates"]
                if g["gate"] == "complete_history_finite")
    assert gate["holds"] == "no"
    assert gate["plain"] == "every number in the results is a number"


@pass11_only
def test_a_primal_disagreement_is_shown_as_one_and_not_softened(run):
    """The stresses differ, and the sentence says so."""
    entry = _at_stage(run, "primal_disagreed")
    assert may_say_verified(entry) is False
    status = plain_status(entry)
    assert status.headline == "The two versions computed different stresses"
    assert status.can_retry is False


@pass11_only
def test_a_derivative_disagreement_shows_the_sweep_that_could_not_settle(run):
    """A tangent that did not verify says the plateau was not found."""
    entry = _at_stage(run, "tangent_not_verified")
    assert may_say_verified(entry) is False
    view = results.derivative_view(entry)
    criteria = {c["finding"]: c for c in view["criteria"]}
    matched = criteria[
        "the derivatives matched at every point that could be checked"]
    assert matched["holds"] in ("no", NOT_ESTABLISHED)


# ---------------------------------------------------------------------------
# 10. a finite difference that did settle
# ---------------------------------------------------------------------------
@pass11_only
def test_a_stable_finite_difference_shows_the_plateau_and_all_three_sweeps(
        run):
    """The accepted range, step by step, against all three references.

    One step size cannot separate a truncation error from a cancellation one,
    so the page shows the sweep and marks the run of steps over which the
    error stops moving. All three comparisons are shown, because the third --
    the difference against itself -- is the floor under the other two.
    """
    entry = _first(run, lambda e: may_say_verified(e)
                   and (e.tangent or {}).get("states"))
    assert entry is not None
    view = results.derivative_view(entry)

    assert set(view["plateaus"]) == {"comparison",
                                     "against_the_authors_tangent",
                                     "the_references_own_error"}
    settled = view["plateaus"]["comparison"]
    assert settled["sweep"], "the sweep must be shown step by step"
    assert len(settled["accepted range"]) == 2
    assert settled["steps on the plateau"] >= 1
    assert settled["settled"] is True
    # Each row says whether it is inside the accepted range and which was best.
    assert any(row["on the plateau"] for row in settled["sweep"])
    assert any(row["best step"] for row in settled["sweep"])

    # Smooth points and transitions are told apart, and every evaluation state
    # carries which it is.
    for state in view["evaluation states"]:
        assert state["kind of point"] in (
            "smooth", "a transition, where the material changes behaviour",
            NOT_ESTABLISHED)


@pass11_only
def test_the_one_sided_differences_are_shown_beside_the_centred_one(run):
    """Forward and backward, because a centred difference hides a transition."""
    entry = _first(
        run, lambda e: any(isinstance(s, dict) and s.get("branch")
                           for s in (e.tangent or {}).get("states") or ()))
    if entry is None:
        pytest.skip("no entry in this record recorded one-sided differences")
    sides = results.one_sided(entry.raw, 0)
    if not sides["available"]:
        sides = next((results.one_sided(entry.raw, i)
                      for i in range(len(entry.tangent["states"]))
                      if results.one_sided(entry.raw, i)["available"]), sides)
    assert sides["available"] is True
    assert set(sides["one sided"]) == {"forward", "backward"}
    assert "centred" in sides
    for side in sides["one sided"].values():
        assert "best step" in side and "stable range" in side


# ---------------------------------------------------------------------------
# 11 and 12. carrying a verified material into a residual problem
# ---------------------------------------------------------------------------
@pass11_only
def test_selecting_a_verified_fixture_offers_only_what_passed_every_gate(run):
    """The picker's verified list is exactly the 42, never the 55."""
    offer = residual_bridge.offer(run.entries)
    assert offer["counts"]["verified"] == 42
    assert offer["counts"]["not verified"] == 237 - 42
    assert all(f.verified for f in offer["verified"])
    # Every unverified fixture carries its own reason, not just the banner.
    assert all(f.why_not for f in offer["experimental"])

    picked = residual_bridge.select(run.entries, offer["verified"][0].source_id)
    assert picked.fixture.verified is True
    assert picked.experimental is False
    assert picked.may_be_reported_as_verified is True
    assert picked.warning == ""


@pass11_only
def test_an_unverified_material_cannot_be_selected_by_forgetting_a_flag(run):
    """The guard is a refusal, not a returned ``None`` a caller can ignore.

    The 13 that reached the pipeline's last rung are the ones this test is
    really about: a picker that trusted the rung would offer them as verified
    fixtures. Asking for one without saying "experimental" raises.
    """
    nearly = _first(run, lambda e: e.stage == "verified"
                    and not may_say_verified(e))
    assert nearly is not None

    with pytest.raises(ValueError) as raised:
        residual_bridge.select(run.entries, nearly.source_id)
    assert "not verified" in str(raised.value)

    # An advanced user may still run it, and what they get is labelled.
    allowed = residual_bridge.select(run.entries, nearly.source_id,
                                     experimental=True)
    assert allowed.experimental is True
    assert allowed.may_be_reported_as_verified is False
    assert allowed.warning == residual_bridge.EXPERIMENTAL_WARNING
    assert "NOT VERIFIED" in allowed.warning
    # And the label travels with it into anything built from the selection.
    record = allowed.as_dict()
    assert record["may be reported as verified"] is False
    assert "warning" in record["fixture"]


@pass11_only
def test_the_residual_screen_never_lists_an_unverified_material_as_ready(run):
    """The two lists are separate keys, so no template can merge them."""
    view = area_view("residual", results_dir=PASS11, run=run,
                     probe=_toolchain())
    offer = view["offer"]
    assert set(offer) >= {"verified", "experimental",
                          "warning for experimental"}
    ready = {f.source_id for f in offer["verified"]}
    experimental = {f.source_id for f in offer["experimental"]}
    assert not (ready & experimental)
    assert all(may_say_verified(
        _first(run, lambda e, s=s: e.source_id == s)) for s in ready)


def test_a_residual_run_on_an_unverified_fixture_stays_labelled(control_run,
                                                                tmp_path):
    """A run that completes perfectly on an unverified material is still that.

    The flag comes from the SELECTION, not from whether the run succeeded.
    """
    entry = control_run.entries[0]
    assert not may_say_verified(entry)
    selection = residual_bridge.select(control_run.entries, entry.source_id,
                                       experimental=True)

    class _Fake:
        @staticmethod
        def run_from_config(path):
            return type("R", (), {"output_dir": str(tmp_path), "ok": True})()

        @staticmethod
        def read_report(path):
            return {"validation_summary": {"max_rel_error": 1e-12}}

    import sys as _sys
    _sys.modules["_fake_resasm"] = _Fake
    result = residual_bridge.evaluate(tmp_path / "resasm.yml", selection,
                                      module="_fake_resasm")
    assert result["ok"] is True
    assert result["may be reported as verified"] is False
    assert "NOT VERIFIED" in result["warning"]


def test_the_residual_assembler_reports_a_failure_in_the_five_parts(tmp_path):
    """A residual problem that will not run is explained, not tracebacked."""
    class _Broken:
        @staticmethod
        def run_from_config(path):
            raise RuntimeError("solver returned a singular tangent")

    import sys as _sys
    _sys.modules["_broken_resasm"] = _Broken
    fixture = residual_bridge.Fixture(source_id="x", key="k", verified=True)
    selection = residual_bridge.Selection(fixture=fixture, experimental=False)
    result = residual_bridge.evaluate(tmp_path / "resasm.yml", selection,
                                      module="_broken_resasm")
    assert result["ok"] is False
    failure = result["failure"]
    assert failure["what failed"] == "The residual problem did not run"
    assert failure["why this program believes that"]
    assert failure["the evidence for it"]
    # The traceback text is in the log, not in the headline.
    assert "singular" in failure["full log"]
    assert "singular" not in failure["what failed"]


def test_the_residual_assembler_availability_is_measured_not_assumed():
    """Whether it is installed is checked, and a missing one says so."""
    present = residual_bridge.__name__ and availability(
        probe=_toolchain())["Residual Assembler"]
    assert present.usable in (True, False)
    assert present.probe.startswith("import ")
    absent = __import__("umat_oti.app.home", fromlist=["x"]) \
        .residual_assembler_status(module="a_module_that_is_not_installed")
    assert absent.usable is False
    assert "not installed" in absent.detail


# ---------------------------------------------------------------------------
# 13 and 14. jobs that are cancelled, and jobs that outlive the browser
# ---------------------------------------------------------------------------
class _Manager:
    """A job manager conforming to the protocol the interface talks to."""

    def __init__(self):
        self.jobs, self._next = {}, 0

    def submit(self, kind, params):
        self._next += 1
        job_id = f"job-{self._next}"
        self.jobs[job_id] = {
            "state": "running", "kind": kind, "label": params.get("label", ""),
            "started": 1.0,
            "stages": {"analyze_umat": "succeeded",
                       "find_material_data": "succeeded",
                       "build_experiment": "running"}}
        return job_id

    def status(self, job_id):
        return dict(self.jobs.get(job_id) or {})

    def cancel(self, job_id):
        record = self.jobs.get(job_id)
        if not record:
            return {"cancelled": False, "reason": "no such job"}
        record["state"] = "cancelled"
        record["stages"]["build_experiment"] = "cancelled"
        return {"cancelled": True}

    def list_jobs(self):
        return sorted(self.jobs)


def test_cancelling_a_tracked_job_stops_it_and_says_what_had_finished(
        tmp_path):
    """Cancel is delegated, and the panel reports what was done, not a guess.

    The headline counts finished steps against the steps that were REPORTED,
    never against the nine this interface knows about: a manager that told us
    about three steps has not told us the other six did not run.
    """
    manager = _Manager()
    tracked = TrackedJobs.open(tmp_path / "jobs.json")
    job_id = manager.submit("verify", {"label": "j2_props.f"})
    tracked.track(job_id, kind="verify", label="j2_props.f")

    before = job_view(job_id, manager.status(job_id))
    assert before.state == "running"
    assert before.can_cancel is True
    assert "Working" in before.headline

    assert manager.cancel(job_id)["cancelled"] is True

    after = job_view(job_id, manager.status(job_id))
    assert after.state == "cancelled"
    assert after.can_cancel is False
    assert "Stopped" in after.headline
    # Two steps finished before it was stopped, and the panel says two.
    assert after.steps_done == 2
    assert "2 of 3" in after.headline
    # The step it was on is cancelled, not failed, and not "did not run".
    step = next(s for s in after.steps if s["key"] == "build_experiment")
    assert step["state"] == StageState.CANCELLED


def test_restarting_the_interface_finds_the_job_it_was_watching(tmp_path):
    """The registry survives the process; the manager still holds the truth."""
    manager = _Manager()
    registry = tmp_path / "jobs.json"

    tracked = TrackedJobs.open(registry)
    job_id = manager.submit("verify", {"label": "j2_props.f"})
    tracked.track(job_id, kind="verify", label="j2_props.f")
    del tracked                                     # the browser is closed

    # A new process, a new registry object, the same file.
    reopened = TrackedJobs.open(registry)
    assert reopened.ids() == [job_id]
    recovered = reopened.recover(manager)
    assert len(recovered) == 1
    assert recovered[0].job_id == job_id
    assert recovered[0].state == "running"
    assert recovered[0].label == "j2_props.f"
    assert recovered[0].lost == ""


def test_a_job_the_manager_has_forgotten_is_said_to_be_lost_not_dropped(
        tmp_path):
    """A row that vanished is a thing the user is told about."""
    manager = _Manager()
    tracked = TrackedJobs.open(tmp_path / "jobs.json")
    tracked.track("job-that-went-away", kind="verify", label="gone")
    recovered = tracked.recover(manager)
    assert len(recovered) == 1
    assert recovered[0].lost
    assert recovered[0].state == NOT_ESTABLISHED
    assert recovered[0].headline == "This run cannot be found"


def test_a_half_written_registry_does_not_take_the_interface_down(tmp_path):
    """A truncated file reads as no jobs, not as a crash on startup."""
    registry = tmp_path / "jobs.json"
    registry.write_text('{"schema": "umat-oti/tracked-jobs/1", "jobs": {"a"')
    assert TrackedJobs.open(registry).ids() == []


def test_a_step_nobody_reported_is_not_reported_as_not_having_run():
    """The three-valued boundary, which is the whole of this module's job.

    A missing key and a null key are both not-established. Neither is "did not
    run", which is a measurement. Reporting an absence as a measurement is how
    108 entries that never ran were once told "agreement only".
    """
    assert stage_state(None, present=False) == NOT_ESTABLISHED
    assert stage_state(None, present=True) == NOT_ESTABLISHED
    assert stage_state("pending") == StageState.DID_NOT_RUN
    assert stage_state(True) == StageState.PASSED
    assert stage_state(False) == StageState.FAILED
    assert stage_state("cancelled") == StageState.CANCELLED
    # A word this module does not know is not guessed at.
    assert stage_state("mysterious") == NOT_ESTABLISHED

    # A manager reporting nothing leaves every step not-established, and the
    # headline does not invent progress.
    empty = job_view("j", {"state": "running"})
    assert all(s["state"] == NOT_ESTABLISHED for s in empty.steps)
    assert "nothing has been reported" in empty.headline
    assert empty.steps_done == 0


def test_a_step_this_interface_cannot_name_is_shown_rather_than_hidden():
    """An untranslated step keeps its own name instead of being dropped."""
    view = job_view("j", {"state": "running",
                          "stages": {"analyze_umat": "succeeded",
                                     "a_rung_nobody_named": "running"}})
    untranslated = [s for s in view.steps if s["untranslated"]]
    assert len(untranslated) == 1
    assert untranslated[0]["step"] == "a_rung_nobody_named"
    assert untranslated[0]["state"] == StageState.RUNNING


def test_a_failed_job_reports_the_five_parts_with_the_log_kept_apart():
    """A job failure is a failure message, and the log is not the message."""
    view = job_view("j", {
        "state": "failed",
        "stages": {"analyze_umat": "succeeded",
                   "run_original": "failed"},
        "error": "the solver exited before writing a results file",
        "log": "Traceback (most recent call last): ...",
        "retryable": True})
    assert view.failure is not None
    failure = view.failure
    assert "Running the original routine" in failure["what failed"]
    assert "Traceback" not in failure["what failed"]
    assert "Traceback" in failure["full log"]
    assert failure["can this be retried automatically"] is True
    assert failure["the evidence for it"]


def test_the_progress_panel_reads_a_list_of_stages_as_well_as_a_mapping():
    """Whatever shape the job manager reports, the boundary normalises it."""
    as_list = job_view("j", {"state": "running", "stages": [
        {"key": "analyze_umat", "state": "succeeded"},
        {"key": "build_experiment", "state": "running"}]})
    as_map = job_view("j", {"state": "running",
                            "stages": {"analyze_umat": "succeeded",
                                       "build_experiment": "running"}})
    assert [s["state"] for s in as_list.steps] == \
           [s["state"] for s in as_map.steps]


# ---------------------------------------------------------------------------
# 15. exporting the report and the regression fixture
# ---------------------------------------------------------------------------
@pass11_only
def test_exporting_a_report_carries_the_verified_count_and_not_the_stage_count(
        run):
    """What is exported is what the gates support, never what the rung says."""
    view = area_view("reports", results_dir=PASS11, run=run,
                     probe=_toolchain())
    assert view["counts"]["materials here"] == 237
    assert view["counts"]["verified"] == 42
    assert view["counts"]["reached the last stage"] == 55
    assert len(view["verified"]) == 42
    assert all(may_say_verified(e) for e in view["verified"])


@pass11_only
def test_the_regression_fixture_covers_only_what_was_verified(run):
    """A regression compares against an earlier verified result or nothing."""
    view = area_view("reports", results_dir=PASS11, run=run,
                     probe=_toolchain())
    regression = view["regression"]
    assert regression["would re-run"] == 42
    assert regression["would not re-run"] == 237 - 42
    assert len(regression["fixtures"]) == 42
    assert regression["why some are excluded"]
    exported = {f["source"] for f in regression["fixtures"]}
    nearly = {e.source_id for e in run.entries
              if e.stage == "verified" and not may_say_verified(e)}
    assert len(nearly) == 13
    assert not (exported & nearly), (
        "the 13 that reached the last rung without satisfying it must not be "
        "exported as regression fixtures")


@pass11_only
def test_a_report_export_is_reproducible_as_json(run, tmp_path):
    """What the reports area holds serialises without losing the qualification."""
    view = area_view("reports", results_dir=PASS11, run=run,
                     probe=_toolchain())
    payload = {"counts": view["counts"], "regression": view["regression"]}
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload, indent=1))
    back = json.loads(path.read_text())
    assert back["counts"]["verified"] == 42
    assert back["counts"]["reached the last stage"] == 55
    assert back["counts"]["verified"] != back["counts"]["reached the last stage"]


# ---------------------------------------------------------------------------
# the boundary with the job manager Agent 5 published
# ---------------------------------------------------------------------------
def test_the_ladder_is_the_one_the_job_manager_publishes():
    """Nine steps, Agent 5's keys and labels, in Agent 5's order.

    One vocabulary or the progress panel and the job record disagree about
    which step a run is on. Where ``umat_oti.jobs.stages`` is installed it is
    the authority and this table is not consulted; the fallback below exists
    for an environment without it and is kept identical.
    """
    assert [s["key"] for s in jobs_module.STAGES] == [
        "analyze_umat", "find_material_data", "build_experiment",
        "search_activation", "run_original", "run_transformed",
        "compare_histories", "verify_derivatives", "create_regression"]
    for stage in jobs_module.STAGES:
        assert stage["label"] and stage["explains"]


def test_a_stage_reported_by_its_key_is_recognised():
    """The job record reports keys, not internal rung names.

    A real defect, caught by driving the boundary with the shape Agent 5's
    records actually carry: :func:`plain_stage` resolved internal names only,
    so every step of every real job came back untranslated while the nine
    known steps all read "not established" beside them. A progress panel that
    showed nothing at all about a job that was running perfectly well.
    """
    for stage in jobs_module.STAGES:
        resolved = jobs_module.plain_stage(stage["key"])
        assert resolved["key"] == stage["key"]
        assert not resolved.get("untranslated"), stage["key"]
        # And the internal rung underneath still resolves to the same step.
        for internal in stage["internal"]:
            assert jobs_module.plain_stage(internal)["key"] == stage["key"]

    view = job_view("j", {"status": "running", "stages": [
        {"key": "analyze_umat", "state": "succeeded"},
        {"key": "run_original", "state": "running"}]})
    states = {s["key"]: s["state"] for s in view.steps}
    assert states["analyze_umat"] == StageState.PASSED
    assert states["run_original"] == StageState.RUNNING
    assert not any(s["untranslated"] for s in view.steps)


def test_a_refusal_and_a_skip_are_not_reported_as_failures():
    """Agent 5's six stage states, each kept as itself.

    A manifest that refuses an underdetermined model has ANSWERED the
    question. Rendering that as "failed" invents a defect in a model that does
    not have one, and rendering a deliberate skip as "did not run" loses the
    fact that somebody decided.
    """
    view = job_view("j", {"status": "running", "stages": [
        {"key": "analyze_umat", "state": "succeeded"},
        {"key": "find_material_data", "state": "refused"},
        {"key": "build_experiment", "state": "skipped"},
        {"key": "run_original", "state": "not_run"},
        {"key": "run_transformed", "state": "failed"}]})
    states = {s["key"]: s["state"] for s in view.steps}
    assert states["find_material_data"] == StageState.REFUSED
    assert states["build_experiment"] == StageState.SKIPPED
    assert states["run_original"] == StageState.DID_NOT_RUN
    assert states["run_transformed"] == StageState.FAILED
    assert len({StageState.REFUSED, StageState.SKIPPED,
                StageState.DID_NOT_RUN, StageState.FAILED,
                StageState.NOT_ESTABLISHED}) == 5
    # Only the genuine failure counts as one.
    assert view.failure is not None
    assert "Running the transformed routine" in view.failure["what failed"]


def test_a_job_that_was_lost_is_not_called_a_failure_or_a_success():
    """Agent 5 reports ``lost`` for a job whose exit was never read.

    Nobody knows what it did. Calling it failed and calling it succeeded are
    the same fabrication in opposite directions.
    """
    assert job_view("j", {"status": "lost"}).state == "lost"
    assert job_view("j", {"status": "killed_externally"}).state == \
        "killed externally"
    for state in ("lost", "killed_externally"):
        view = job_view("j", {"status": state})
        assert view.state not in ("finished", "failed")
        assert view.running is False


def test_the_interface_asks_the_verification_service_rather_than_deciding(
        monkeypatch):
    """Where Agent 5's service is installed, it decides and this does not.

    The architecture rule: the interface calls the services and does not carry
    its own copy of a verification rule. The fallback below is the same six
    gates read the same way, and it exists only for an environment without the
    service -- but the delegation is what keeps the two from drifting when a
    gate is added there and not here.
    """
    import types

    import umat_oti.app.plain_language as pl

    asked = []

    class _Service:
        def what_may_be_claimed(self, record):
            asked.append(record.get("source"))
            return {"may_be_called_verified": False}

    module = types.ModuleType("umat_oti.services.verification")
    module.VerificationService = _Service
    monkeypatch.setitem(sys.modules, "umat_oti.services.verification", module)
    pl._verification_service.cache_clear()
    try:
        # A record whose six gates all read true, which the local reading
        # would call verified. The service says otherwise and the service wins.
        complete = {"source": "x", "evidence": {
            name: True for name, _w, _r in
            __import__("umat_oti.app.corpus_view",
                       fromlist=["EVIDENCE_GATES"]).EVIDENCE_GATES}}
        assert pl.may_say_verified(complete) is False
        assert asked == ["x"]
    finally:
        monkeypatch.delitem(sys.modules, "umat_oti.services.verification")
        pl._verification_service.cache_clear()

    # And without the service the six gates decide, identically.
    assert pl.may_say_verified(complete) is True


def test_the_interface_renders_under_streamlit_itself(tmp_path):
    """The shell draws, through Streamlit, without Abaqus and without a corpus.

    A view model that passes its tests and a page that will not render are
    different things, and only this test can tell them apart.
    """
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

    script = tmp_path / "app.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(REPO / 'src')!r})\n"
        "from pathlib import Path\n"
        "from umat_oti.app.unified_app import render\n"
        f"render(Path({str(CONTROL / 'results')!r}), "
        f"Path({str(CONTROL / 'work')!r}))\n",
        encoding="utf-8")

    app = AppTest.from_file(str(script), default_timeout=60).run()
    assert not app.exception
    # The eight areas are all reachable from the one navigation control.
    options = list(app.sidebar.radio[0].options)
    assert options == [a["label"] for a in AREAS]

    for label in options:
        app.sidebar.radio[0].set_value(label).run()
        assert not app.exception, f"{label} raised"
