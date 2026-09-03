"""The store-wide Abaqus batch must not claim more than it measured.

Every test here runs without Abaqus, without gfortran and without a licence
token, because the parts worth pinning are the parts that decide what a batch
is allowed to say: which rung of the ladder an entry reached, where its
material constants and kinematics came from, whether the two builds were asked
the same question, what a resumed batch is allowed to skip, and what the
denominator is.

The failures these guard against are all ones that produce a *better-looking*
report: a stage that was never reached being reported as reached, a source with
no deck disappearing from the denominator, a tangent believed on one lucky step,
a resumed batch serving a verdict about code that has since changed, and two
builds compared against each other while running different decks.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from umat_oti.abaqus.manifest import VerificationManifest, uniaxial  # noqa: E402
from verify_store_in_abaqus import (  # noqa: E402
    DEFAULT_JOBS, HARNESS_ERROR, MINIMUM_PLATEAU, STAGES, VERIFIED,
    DifferentDecks, StageEvidence, append_record, build_manifest, build_plan,
    choose_probe_record, classify_stage, deck_kinematics, is_terminal,
    job_evidence, main, merge_records, oti_tangent, paired_block_name,
    perturbation_scale, point_shape, previous_outcomes, replay_flags, scrub,
    select_entries, should_skip, stage_rank, summarise, support_plan,
    tangent_verdict, require_one_manifest, require_same_deck,
)


# --------------------------------------------------------------------------
# fixtures that stand in for the store and the corpus
# --------------------------------------------------------------------------

DECK = """*HEADING
a deck the author shipped
*MATERIAL, NAME=STEEL
*DEPVAR
13,
*USER MATERIAL, CONSTANTS=3, UNSYMM
210000.0, 0.3, 250.0
*STEP, NLGEOM=NO, INC=100
*STATIC
0.1, 1.0
*END STEP
"""

#: The same deck as a finite-strain job. Only the *STEP line differs.
FINITE_DECK = DECK.replace("*STEP, NLGEOM=NO, INC=100", "*Step, name=Step-1, nlgeom=YES")


def _row(**overrides) -> dict:
    row = {"source": "owner__name/sub/umat.for", "repository": "owner/name",
           "ntens": "6", "form": "fixed", "kinematics": "small strain",
           "stage": "transformed"}
    row.update(overrides)
    return row


def _proposal(deck: str = "owner__name/decks/job.inp", **overrides) -> dict:
    entry = {
        "repository": "owner/name", "source": "sub/umat.for", "ntens": 6,
        "pairing": {"proposed": deck} if deck else {},
        "material": {"provenance": f"{deck}, *Material name=STEEL at line 3"},
    }
    entry.update(overrides)
    return entry


def _cache_with_deck(tmp_path: Path, text: str = DECK,
                     deck: str = "owner__name/decks/job.inp") -> Path:
    cache = tmp_path / "cache"
    target = cache / deck
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    source = cache / "owner__name/sub/umat.for"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("      SUBROUTINE UMAT\n      RETURN\n      END\n")
    return cache


@dataclass
class FakeStored:
    """A stand-in for StoredTransform: only the fields the batch reads."""

    key: str = "aaaa0000"
    source_id: str = "owner__name/sub/umat.for"
    source_sha256: str = "deadbeef"
    fingerprint: str = "ffff1111"
    directory: Path = Path(".")
    entry_source: Path = Path("umat.for")


# --------------------------------------------------------------------------
# the ladder
# --------------------------------------------------------------------------

def test_the_stages_are_ordered_and_only_the_last_one_is_verified():
    """The ladder is the report's whole vocabulary.

    If another stage is ever added after "verified", or "verified" stops being
    last, then stage_rank stops meaning "how far it got" and a partial result
    can outrank a complete one.
    """
    assert STAGES[-1] == VERIFIED == "verified"
    assert stage_rank("needs_material_data") == 0
    assert stage_rank(VERIFIED) == len(STAGES) - 1
    assert [stage_rank(stage) for stage in STAGES] == list(range(len(STAGES)))
    assert stage_rank(HARNESS_ERROR) == -1, (
        "a harness crash must not sit on the ladder; it is not a statement "
        "about the model")


def test_each_step_that_fails_names_its_own_stage():
    """Each rung is a distinct recorded outcome, not a shared 'failed'."""
    complete = dict(material_found=True, support_ok=True,
                    original_completed=True, transformed_completed=True,
                    primal_agrees=True, tangent_verified=True)
    assert classify_stage(StageEvidence(**complete)) == VERIFIED

    cases = {
        "needs_material_data": dict(complete, material_found=False),
        "manifest_refused": dict(complete, manifest_refusals=("no loading",)),
        "support_build_failed": dict(complete, support_ok=False),
        "original_job_failed": dict(complete, original_completed=False),
        "transformed_job_failed": dict(complete, transformed_completed=False),
        "primal_disagreed": dict(complete, primal_agrees=False),
        "tangent_not_verified": dict(complete, tangent_verified=False),
    }
    for expected, evidence in cases.items():
        assert classify_stage(StageEvidence(**evidence)) == expected


def test_a_step_that_never_ran_is_not_a_step_that_passed():
    """Silence must read as "not established", never as agreement.

    A primal comparison that produced no records, or a tangent sweep that never
    ran, leaves its field at None. If None were treated as passing, an entry
    that produced nothing at all would be published as verified.
    """
    unmeasured = StageEvidence(material_found=True, support_ok=True,
                               original_completed=True,
                               transformed_completed=True,
                               primal_agrees=None, tangent_verified=None)
    assert classify_stage(unmeasured) == "primal_disagreed"
    assert classify_stage(StageEvidence(
        material_found=True, support_ok=True, original_completed=True,
        transformed_completed=True, primal_agrees=True,
        tangent_verified=None)) == "tangent_not_verified"


def test_nothing_is_verified_by_default():
    """The empty evidence is the bottom rung, not the top one."""
    assert classify_stage(StageEvidence()) == "needs_material_data"


def test_a_transform_with_no_support_units_is_not_a_support_failure():
    """support_ok is None when there was nothing to build.

    Conflating "no modules to compile" with "the modules did not compile"
    would report a whole class of transforms as broken builds.
    """
    assert classify_stage(StageEvidence(
        material_found=True, support_ok=None, original_completed=True,
        transformed_completed=True, primal_agrees=True,
        tangent_verified=True)) == VERIFIED


# --------------------------------------------------------------------------
# the manifest comes from the deck
# --------------------------------------------------------------------------

def test_the_manifest_takes_its_constants_from_the_paired_deck(tmp_path: Path):
    """Constants, nstatv and unsymmetry are read, never inferred."""
    cache = _cache_with_deck(tmp_path)
    plan = build_manifest("owner__name/sub/umat.for", _row(), _proposal(), cache)
    assert plan.stage == ""
    assert plan.manifest.props == (210000.0, 0.3, 250.0)
    assert plan.manifest.nprops == 3
    assert plan.manifest.nstatv == 13, "the *DEPVAR count is the author's number"
    assert plan.manifest.unsymmetric is True


def test_the_manifest_names_the_deck_and_the_block_it_read(tmp_path: Path):
    """Provenance is what makes a number checkable by a reader.

    Without the deck's name and the block's name in the record, a reviewer
    cannot tell whether a result rests on the author's constants or on
    somebody's guess, and the two are indistinguishable in the output.
    """
    cache = _cache_with_deck(tmp_path)
    plan = build_manifest("owner__name/sub/umat.for", _row(), _proposal(), cache)
    assert "job.inp" in plan.manifest.material_provenance
    assert "STEEL" in plan.manifest.material_provenance
    assert "owner__name/decks/job.inp" in plan.manifest.material_provenance
    assert plan.material_block == "STEEL"
    assert plan.manifest.missing_requirements() == ()


def test_a_source_with_no_paired_deck_needs_material_data(tmp_path: Path):
    """No deck means no constants, and no constants means no run.

    The alternative -- inventing a plausible elastic vector -- produces a job
    that runs, a comparison that passes and a result about a material the
    author never described.
    """
    cache = _cache_with_deck(tmp_path)
    plan = build_manifest("owner__name/sub/umat.for", _row(),
                          _proposal(deck=""), cache)
    assert plan.stage == "needs_material_data"
    assert plan.manifest is None
    assert "no deck is paired" in plan.reason


def test_a_deck_with_no_material_block_needs_material_data(tmp_path: Path):
    """A paired deck that declares nothing usable is still no data."""
    cache = _cache_with_deck(tmp_path, "*HEADING\nnothing here\n")
    plan = build_manifest("owner__name/sub/umat.for", _row(), _proposal(), cache)
    assert plan.stage == "needs_material_data"
    assert plan.manifest is None


def test_a_paired_deck_missing_from_the_cache_needs_material_data(tmp_path: Path):
    """A named file that is not there is not a licence to make one up."""
    cache = _cache_with_deck(tmp_path)
    plan = build_manifest("owner__name/sub/umat.for", _row(),
                          _proposal(deck="owner__name/decks/absent.inp"), cache)
    assert plan.stage == "needs_material_data"
    assert "not in the cache" in plan.reason


def test_the_material_block_named_by_the_pairing_is_the_one_read(tmp_path: Path):
    """The pairing was judged on one block; the manifest must use that block.

    A deck with two materials and a larger irrelevant one would otherwise hand
    the run a vector belonging to a different model in the same file.
    """
    two = DECK + """*MATERIAL, NAME=OTHER
*USER MATERIAL, CONSTANTS=5
1.0, 2.0, 3.0, 4.0, 5.0
"""
    cache = _cache_with_deck(tmp_path, two)
    plan = build_manifest("owner__name/sub/umat.for", _row(), _proposal(), cache)
    assert plan.material_block == "STEEL"
    assert plan.manifest.props == (210000.0, 0.3, 250.0)


def test_a_provenance_for_another_deck_does_not_select_in_this_one():
    """A block name is only usable where it was actually observed.

    Reading "name=STEEL" out of a provenance that names some other file and
    applying it here is how a material vector ends up attached to a source that
    never declared it.
    """
    assert paired_block_name("elsewhere.inp, *Material name=STEEL",
                             "owner__name/decks/job.inp") is None
    assert paired_block_name("owner__name/decks/job.inp, *Material name=STEEL",
                             "owner__name/decks/job.inp") == "STEEL"


def test_ntens_comes_from_the_triage_row(tmp_path: Path):
    """The tensor size is the scanner's reading of the source, not the deck's."""
    cache = _cache_with_deck(tmp_path)
    plan = build_manifest("owner__name/sub/umat.for", _row(ntens="4"),
                          _proposal(), cache)
    assert plan.manifest.ntens == 4
    assert (plan.manifest.ndi, plan.manifest.nshr) == (3, 1)
    assert plan.manifest.element_type == "CPE4"


def test_an_ntens_with_no_element_refuses_the_manifest(tmp_path: Path):
    """Refused, not driven on whatever element is nearest.

    An element whose component ordering the source does not use compares every
    stress against the wrong component, and the comparison still produces a
    number.
    """
    assert point_shape(5) is None
    cache = _cache_with_deck(tmp_path)
    plan = build_manifest("owner__name/sub/umat.for", _row(ntens="5"),
                          _proposal(), cache)
    assert plan.stage == "manifest_refused"
    assert "ntens=5" in plan.reason


def test_a_source_with_no_triage_row_is_not_silently_given_defaults(tmp_path: Path):
    """Nothing established its tensor size, so nothing may assume one."""
    cache = _cache_with_deck(tmp_path)
    plan = build_manifest("owner__name/sub/umat.for", None, _proposal(), cache)
    assert plan.stage == "needs_material_data"


def test_the_manifest_records_that_its_loading_is_a_probe(tmp_path: Path):
    """A verified row must not read as a statement about the author's loading."""
    cache = _cache_with_deck(tmp_path)
    plan = build_manifest("owner__name/sub/umat.for", _row(), _proposal(), cache)
    assert "declared probe" in plan.manifest.notes
    assert "not this source's own loading history" in plan.manifest.notes


def test_the_manifest_never_records_a_machine_path(tmp_path: Path):
    """A manifest naming one computer is unusable on any other, and the
    repository audit fails the build on it."""
    cache = _cache_with_deck(tmp_path)
    plan = build_manifest("owner__name/sub/umat.for", _row(), _proposal(), cache)
    assert str(tmp_path) not in str(plan.manifest.source)


# --------------------------------------------------------------------------
# kinematics come from the deck
# --------------------------------------------------------------------------

def test_nlgeom_yes_in_the_deck_makes_the_manifest_finite(tmp_path: Path):
    """A finite-strain model driven as small strain differentiates something
    it never reads, and the difference check then measures nothing."""
    cache = _cache_with_deck(tmp_path, FINITE_DECK)
    plan = build_manifest("owner__name/sub/umat.for", _row(), _proposal(), cache)
    assert plan.manifest.kinematics == "finite"
    assert "nlgeom=YES" in plan.kinematics_provenance


def test_the_deck_outranks_the_triage_row_on_kinematics_and_says_so(tmp_path: Path):
    """The deck is the author's own statement; the triage row is a scan.

    When they disagree the disagreement is recorded rather than resolved out of
    sight, so a reader can see which of the two the run followed.
    """
    cache = _cache_with_deck(tmp_path, FINITE_DECK)
    plan = build_manifest("owner__name/sub/umat.for",
                          _row(kinematics="small strain"), _proposal(), cache)
    assert plan.manifest.kinematics == "finite"
    assert "the deck is what the manifest follows" in plan.kinematics_note


def test_nlgeom_is_read_in_any_case_and_spacing():
    """Abaqus ignores case and internal spacing in keywords, so this must too."""
    for line in ("*Step, name=Step-1, nlgeom=YES",
                 "*STEP, NLGEOM=yes",
                 "* Step , NLGEOM"):
        assert deck_kinematics(line + "\n").kinematics == "finite", line


def test_a_deck_that_does_not_set_nlgeom_is_small_strain_by_abaqus_default():
    """Reading a documented default off the author's file is not guessing, but
    the record has to say that is what happened."""
    found = deck_kinematics("*STEP, INC=100\n*STATIC\n", "job.inp")
    assert found.kinematics == "small strain"
    assert "default" in found.provenance and "job.inp" in found.provenance


def test_nlgeom_no_is_not_read_as_yes():
    assert deck_kinematics("*STEP, NLGEOM=NO\n").kinematics == "small strain"


def test_a_comment_line_cannot_declare_nlgeom():
    """** is a comment in an Abaqus deck; reading one as a keyword would let a
    disabled step decide the kinematics of the run."""
    assert deck_kinematics("** *STEP, NLGEOM=YES\n").kinematics == "small strain"


# --------------------------------------------------------------------------
# one manifest, two builds
# --------------------------------------------------------------------------

def _manifest(**overrides) -> VerificationManifest:
    fields = dict(name="m", source=Path("u.for"), props=(1.0, 2.0),
                  material_provenance="job.inp *MATERIAL M",
                  loading=(uniaxial(0.005, 5),))
    fields.update(overrides)
    return VerificationManifest(**fields)


def test_both_builds_are_handed_the_same_manifest_object(tmp_path: Path):
    """The whole comparison rests on one deck driving both builds.

    If the original ran on one material vector and the transformed on another,
    a disagreement is the harness's fault reported as the transform's -- and,
    far worse, an agreement is a coincidence between two different questions
    published as evidence about the transform.
    """
    manifest = _manifest()
    original, transformed = build_plan(manifest, Path("orig.for"),
                                       Path("tx.for"), tmp_path, 60)
    assert original["manifest"] is manifest
    assert transformed["manifest"] is manifest
    assert original["job"] != transformed["job"]
    assert original["work_dir"] != transformed["work_dir"]
    assert require_one_manifest(original, transformed)


def test_two_different_manifests_are_refused_before_anything_runs(tmp_path: Path):
    """The guard has to fire on the inputs, not on the results.

    A batch that discovers the mismatch afterwards has already spent two
    Abaqus jobs and has two histories it must not compare.
    """
    first, _ = build_plan(_manifest(), Path("a.for"), Path("b.for"), tmp_path, 60)
    _, second = build_plan(_manifest(props=(9.0, 9.0)), Path("a.for"),
                           Path("b.for"), tmp_path, 60)
    with pytest.raises(DifferentDecks) as raised:
        require_one_manifest(first, second)
    assert "different decks" in str(raised.value)


def test_manifests_that_differ_only_off_the_deck_are_accepted(tmp_path: Path):
    """The guard compares the deck, which is what Abaqus reads.

    Refusing on any difference at all would reject a pair differing only in a
    note, and the check would then be turned off rather than fixed.
    """
    first, _ = build_plan(_manifest(notes="one"), Path("a.for"), Path("b.for"),
                          tmp_path, 60)
    _, second = build_plan(_manifest(notes="another"), Path("a.for"),
                           Path("b.for"), tmp_path, 60)
    assert require_one_manifest(first, second)


def test_the_decks_the_jobs_actually_read_are_compared_after_the_fact():
    """The second guard catches a deck rewritten between the two jobs."""
    assert require_same_deck("*HEADING\nx\n", "*HEADING\nx\n")
    with pytest.raises(DifferentDecks):
        require_same_deck("*HEADING\nx\n", "*HEADING\ny\n")


def test_a_finite_manifest_and_a_small_strain_one_are_different_decks(tmp_path: Path):
    """Kinematics reach the deck through NLGEOM, so the guard must see them."""
    first, _ = build_plan(_manifest(kinematics="finite"), Path("a.for"),
                          Path("b.for"), tmp_path, 60)
    _, second = build_plan(_manifest(kinematics="small strain"), Path("a.for"),
                           Path("b.for"), tmp_path, 60)
    with pytest.raises(DifferentDecks):
        require_one_manifest(first, second)


# --------------------------------------------------------------------------
# support units
# --------------------------------------------------------------------------

def test_the_entry_source_is_excluded_from_the_support_build(tmp_path: Path):
    """abaqus user= compiles the entry source itself.

    Building it here as well defines every routine in the file twice and the
    link fails on all of them at once.
    """
    directory = tmp_path / "tx"
    directory.mkdir()
    for name in ("otim6n1.f90", "helper.f90", "umat_oti.for"):
        (directory / name).write_text("! unit\n")
    (directory / "compile_order.txt").write_text(
        "otim6n1.f90\nhelper.f90\numat_oti.for\n")
    plan = support_plan(directory, directory / "umat_oti.for")
    assert [p.name for p in plan.units] == ["otim6n1.f90", "helper.f90"]
    assert plan.build_required is True
    assert plan.refusal == ""


def test_a_transform_without_a_compile_order_is_refused_not_guessed(tmp_path: Path):
    """Module dependencies make the order load-bearing, and only the transform
    knows it. Guessing an order produces a link failure blamed on the source."""
    directory = tmp_path / "tx"
    directory.mkdir()
    plan = support_plan(directory, directory / "umat_oti.for")
    assert plan.refusal and "compile_order.txt" in plan.refusal
    assert plan.build_required is False


def test_a_transform_whose_only_unit_is_the_entry_needs_no_support(tmp_path: Path):
    """Nothing to build is not the same as a build that failed."""
    directory = tmp_path / "tx"
    directory.mkdir()
    (directory / "umat_oti.for").write_text("! unit\n")
    (directory / "compile_order.txt").write_text("umat_oti.for\n")
    plan = support_plan(directory, directory / "umat_oti.for")
    assert plan.units == () and plan.build_required is False and not plan.refusal


# --------------------------------------------------------------------------
# reading a job
# --------------------------------------------------------------------------

def test_a_wrapup_abort_is_a_warning_and_never_a_failure():
    """Abaqus 2021 here aborts in post-analysis wrap-up after writing that the
    analysis completed -- with no user subroutine at all.

    If the exit code were the verdict, every job in the store would be reported
    as failed and the batch would say nothing about any transform.
    """
    # The two strings classify_job actually emits for this, not invented ones.
    report = {"completed": True, "increments": 20, "converged_records": 20,
              "warnings": ["post_analysis_wrapup_failure",
                           "process_exit_code_134"],
              "reasons": []}
    evidence = job_evidence(report)
    assert evidence.completed is True
    assert "post_analysis_wrapup_failure" in evidence.warnings
    assert "process_exit_code_134" in evidence.warnings, (
        "the exit code is preserved beside the result, never rewritten to zero")
    assert classify_stage(StageEvidence(
        material_found=True, support_ok=True,
        original_completed=evidence.completed,
        transformed_completed=True, primal_agrees=True,
        tangent_verified=True)) == VERIFIED


def test_a_build_whose_probe_found_no_call_site_says_so():
    """That build completes and records nothing, which looks like success.

    run_one reports it under a different key from the status warnings, and
    reading only the status tuple left the batch with a completed job, an empty
    history and no stated reason for either.
    """
    evidence = job_evidence({"completed": True, "instrumented": False,
                             "converged_records": 0,
                             "warning": "the probe found no call site"})
    assert evidence.instrumented is False
    assert any("no call site" in w for w in evidence.warnings)
    assert evidence.converged_records == 0


def test_a_job_that_left_no_record_is_not_completed():
    """Absence of reasons is not evidence of success."""
    assert job_evidence({}).completed is False
    assert job_evidence({"completed": False,
                         "reasons": ["x.sta was not written"]}).completed is False


# --------------------------------------------------------------------------
# the tangent
# --------------------------------------------------------------------------

def test_the_probe_record_used_carries_the_state_it_started_from():
    """The reference is the original replayed from that exact state.

    A record with no ENTRY block cannot be replayed, and replaying from a state
    made up to fill the gap gives the derivative of a different function.
    """
    records = [{"increment": 1, "DDSDDE": [1.0], "entry": {"DSTRAN": [1e-4]}},
               {"increment": 2, "DDSDDE": [1.0]},
               {"increment": 3, "entry": {"DSTRAN": [1e-4]}}]
    position, chosen = choose_probe_record(records)
    assert position == 0 and chosen["increment"] == 1
    assert choose_probe_record([]) is None
    assert choose_probe_record([{"increment": 1}]) is None


def test_the_last_usable_record_is_the_one_taken():
    """The furthest point along the path is where a path-dependent model is
    least likely to be showing the elastic tangent every build gets right."""
    entry = {"DSTRAN": [1e-4], "STRESS0": [0.0], "PROPS": [1.0]}
    records = [{"increment": n, "DDSDDE": [1.0], "entry": dict(entry)}
               for n in (1, 2, 3)]
    assert choose_probe_record(records)[1]["increment"] == 3


def test_an_empty_entry_block_is_not_a_recorded_state():
    """A record whose ENTRY carries nothing cannot be replayed.

    Accepting it would send the replay driver a state file of zeros and an
    identity deformation gradient -- an invented starting point, and the
    difference of two runs from it is the derivative of a different function.
    """
    assert choose_probe_record([{"increment": 1, "DDSDDE": [1.0], "entry": {}}]) is None


def test_the_oti_tangent_is_read_in_the_order_the_probe_wrote_it():
    """The probe writes ((DDSDDE(I,J),J=1,NTENS),I=1,NTENS): row by row.

    Reading it the other way transposes the tangent, which is invisible for a
    symmetric material and wrong for every UNSYMM one -- and UNSYMM is exactly
    where a hand-coded tangent is most likely to be wrong.
    """
    record = {"DDSDDE": [1.0, 2.0, 3.0, 4.0]}
    assert oti_tangent(record, 2) == [[1.0, 2.0], [3.0, 4.0]]
    assert oti_tangent({"DDSDDE": [1.0, 2.0]}, 2) == [], (
        "a truncated record must produce nothing, not a padded matrix")


def test_the_difference_steps_are_relative_to_the_increment_being_perturbed():
    """The same ladder has to mean the same thing at any strain magnitude."""
    assert perturbation_scale({"DSTRAN": [1e-4, 0.0, 0.0]}) == pytest.approx(1e-4)
    assert perturbation_scale({"DSTRAN": [0.0, 0.0]}) == 1.0
    assert perturbation_scale({}) == 1.0


def test_a_tangent_believed_on_one_step_is_not_verified():
    """One step cannot separate truncation error from cancellation.

    A single step that lands on the right answer while its neighbours do not is
    a coincidence, and reporting it as verification lets a finite-difference
    check say whatever is wanted of it.
    """
    comparison = {
        "best_relative": 1e-12, "best_frobenius": 1e-12,
        "sweep": [{"step": 1e-3, "frobenius": 1.0},
                  {"step": 1e-4, "frobenius": 1e-12},
                  {"step": 1e-5, "frobenius": 5.0}],
    }
    verified, reason = tangent_verdict(comparison)
    assert verified is False
    assert "cancellation" in reason
    assert MINIMUM_PLATEAU >= 2


def test_a_tangent_that_holds_over_a_plateau_is_verified():
    comparison = {
        "best_relative": 2e-9, "best_frobenius": 1e-9,
        "sweep": [{"step": 1e-3, "frobenius": 5e-9},
                  {"step": 1e-4, "frobenius": 1e-9},
                  {"step": 1e-5, "frobenius": 3e-9}],
    }
    verified, reason = tangent_verdict(comparison)
    assert verified is True
    # The message names which shape corroborated it: a plateau, or a sweep in
    # which every step agreed. They are different evidence and read differently.
    assert "plateau of 3 step sizes" in reason


def test_a_tangent_that_agrees_loosely_is_not_verified():
    comparison = {
        "best_relative": 1e-2, "best_frobenius": 1.0,
        "sweep": [{"step": 1e-3, "frobenius": 1.0},
                  {"step": 1e-4, "frobenius": 2.0}],
    }
    verified, reason = tangent_verdict(comparison)
    assert verified is False and "tolerance" in reason


def test_an_empty_sweep_is_not_verified():
    """A sweep that produced nothing is the loudest kind of unverified."""
    assert tangent_verdict({"sweep": []})[0] is False
    assert tangent_verdict({"sweep": [{"step": 1e-4, "frobenius": 0.0}],
                            "best_relative": None,
                            "best_frobenius": None})[0] is False


def test_an_exact_tangent_is_still_judged_on_its_plateau():
    """A zero residual at every step is convergence, not a division by zero."""
    comparison = {"best_relative": 0.0, "best_frobenius": 0.0,
                  "sweep": [{"step": 1e-3, "frobenius": 0.0},
                            {"step": 1e-4, "frobenius": 0.0}]}
    assert tangent_verdict(comparison)[0] is True


def test_neither_source_form_is_forced_on_the_whole_command_line():
    """Two files are compiled together and they are not in the same form.

    The replay driver is free-form .f90 and the UMAT beside it is usually
    fixed-form .for. Forcing -ffixed-form globally compiled the DRIVER as
    fixed, and gfortran rejected every line of it with "Non-numeric character
    in statement label" -- so four entries that had already agreed on their
    primal histories in Abaqus were recorded as tangent failures for a flag.

    Both length limits are passed because each applies only to its own form,
    and gfortran infers the form from the suffix. That is what the offline
    gate has always done, which is why it never hit this.
    """
    for form in ("fixed", "free", ""):
        flags = replay_flags(form, Path("/w"))
        assert "-ffixed-form" not in flags, form
        assert "-ffree-form" not in flags, form
        assert "-ffixed-line-length-132" in flags
        assert "-ffree-line-length-none" in flags
        assert "-std=legacy" in flags


# --------------------------------------------------------------------------
# resuming
# --------------------------------------------------------------------------

def test_every_rung_is_a_settled_outcome_and_a_crash_is_not():
    """A batch of this size runs for hours; a crash must be retried, and a
    recorded stage must not be."""
    for stage in STAGES:
        assert is_terminal(stage), stage
    assert not is_terminal(HARNESS_ERROR)
    assert not is_terminal("")


def test_resume_skips_only_entries_with_a_recorded_terminal_outcome(tmp_path: Path):
    path = tmp_path / "results.jsonl"
    append_record(path, {"key": "aaa", "stage": VERIFIED})
    append_record(path, {"key": "bbb", "stage": HARNESS_ERROR})
    append_record(path, {"key": "ccc", "stage": "needs_material_data"})
    previous = previous_outcomes(path)
    assert should_skip("aaa", previous, resume=True) is True
    assert should_skip("ccc", previous, resume=True) is True, (
        "needs_material_data is a finding, not a failed attempt")
    assert should_skip("bbb", previous, resume=True) is False
    assert should_skip("ddd", previous, resume=True) is False


def test_without_resume_nothing_is_skipped(tmp_path: Path):
    path = tmp_path / "results.jsonl"
    append_record(path, {"key": "aaa", "stage": VERIFIED})
    assert should_skip("aaa", previous_outcomes(path), resume=False) is False


def test_a_resumed_batch_reruns_everything_after_the_transform_changes(tmp_path: Path):
    """Outcomes are keyed by the STORE key, which digests the source identity,
    the source bytes and a fingerprint of the transform code together.

    Keying on the source alone would let --resume serve yesterday's verdict
    about code that no longer exists, which is the one thing the store's
    staleness rule exists to prevent.
    """
    path = tmp_path / "results.jsonl"
    append_record(path, {"key": "key-from-old-transform",
                         "source": "owner__name/sub/umat.for", "stage": VERIFIED})
    previous = previous_outcomes(path)
    assert should_skip("key-from-new-transform", previous, resume=True) is False


def test_a_half_written_line_does_not_lose_the_rest_of_the_file(tmp_path: Path):
    """A batch killed mid-write leaves a truncated last line. Losing every
    earlier hour of Abaqus over it is exactly what --resume is for."""
    path = tmp_path / "results.jsonl"
    append_record(path, {"key": "aaa", "stage": VERIFIED})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"key": "bbb", "sta')
    assert previous_outcomes(path) == {"aaa": VERIFIED}


def test_each_result_is_on_disk_before_the_next_entry_starts(tmp_path: Path):
    """Writing at the end loses every hour that came before a crash."""
    path = tmp_path / "results.jsonl"
    append_record(path, {"key": "aaa", "stage": VERIFIED})
    assert [json.loads(line)["key"] for line in path.read_text().splitlines()] == ["aaa"]
    append_record(path, {"key": "bbb", "stage": "primal_disagreed"})
    keys = [json.loads(line)["key"] for line in path.read_text().splitlines()]
    assert keys == ["aaa", "bbb"]


def test_a_rerun_entry_is_counted_once(tmp_path: Path):
    """A resumed batch appends to the file it read, so a key can appear twice.

    Counting both inflates the denominator, which is a silent change of
    denominator in the direction that flatters the result.
    """
    merged = merge_records([{"key": "aaa", "stage": HARNESS_ERROR}],
                           [{"key": "aaa", "stage": VERIFIED}])
    assert len(merged) == 1 and merged[0]["stage"] == VERIFIED


# --------------------------------------------------------------------------
# selection and accounting
# --------------------------------------------------------------------------

def test_selection_matches_the_path_within_the_cache_not_the_basename():
    """Eighteen UMATs here share a basename with something else.

    A filter on basenames selects files from other projects, and the run then
    reports a result under one project's name that was measured on another's
    source.
    """
    entries = [FakeStored(key="1", source_id="alice__proj/src/umat.for"),
               FakeStored(key="2", source_id="bob__other/src/umat.for")]
    assert [e.key for e in select_entries(entries, only="alice__proj")] == ["1"]
    assert [e.key for e in select_entries(entries, only="umat.for")] == ["1", "2"]
    assert [e.key for e in select_entries(entries, limit=1)] == ["1"]
    assert len(select_entries(entries)) == 2


def test_the_denominator_is_every_entry_attempted():
    """A source with no material data stays in the count.

    Dropping it turns "3 of 8 verified" into "3 of 3", which is the single
    easiest way to make this project's headline number look better than it is.
    """
    records = [{"key": "a", "source": "x/u1.for", "stage": VERIFIED},
               {"key": "b", "source": "x/u2.for", "stage": "needs_material_data"},
               {"key": "c", "source": "x/u3.for", "stage": "primal_disagreed"},
               {"key": "d", "source": "x/u4.for", "stage": HARNESS_ERROR}]
    summary = summarise(records)
    assert summary["attempted"] == 4
    assert summary["counted"] == 4, "every record must land in exactly one stage"
    assert summary["verified_count"] == 1
    assert summary["by_stage"]["needs_material_data"] == 1
    assert summary["by_stage"][HARNESS_ERROR] == 1


def test_the_summary_counts_are_reported_in_ladder_order():
    """A reader scanning the report has to see how far the batch got."""
    records = [{"key": "a", "stage": VERIFIED},
               {"key": "b", "stage": "needs_material_data"},
               {"key": "c", "stage": "support_build_failed"}]
    order = list(summarise(records)["by_stage"])
    assert order == ["needs_material_data", "support_build_failed", VERIFIED]


def test_the_summary_names_verified_entries_by_their_identity():
    """The verified list is what gets quoted, so it must name the file that was
    actually run -- its path within the cache, never its basename."""
    records = [{"key": "a", "source": "alice__proj/src/umat.for", "stage": VERIFIED},
               {"key": "b", "source": "bob__other/src/umat.for", "stage": VERIFIED}]
    assert summarise(records)["verified"] == ["alice__proj/src/umat.for",
                                              "bob__other/src/umat.for"]


def test_a_record_with_no_stage_still_counts():
    """A record that lost its stage is a harness problem, not a free row."""
    summary = summarise([{"key": "a"}, {"key": "b", "stage": VERIFIED}])
    assert summary["attempted"] == 2 and summary["counted"] == 2
    assert summary["verified_count"] == 1


# --------------------------------------------------------------------------
# what reaches the committed file
# --------------------------------------------------------------------------

def test_no_machine_path_survives_into_a_result_record():
    """A compiler quotes the absolute path of every file it was handed.

    Those paths are a property of the machine, not of the failure, and the
    repository audit fails the build when one reaches committed output.
    """
    home = "/home/somebody/work"  # machine-path-fixture: the scrubber has to be given a real-shaped path to strip
    record = {"reason": f"{home}/u.for:12: error", "warnings": [f"{home}/x"],
              "nested": {"log": f"cannot open {home}/otis_state.txt"}}
    cleaned = scrub(record, Path(home))
    assert home not in json.dumps(cleaned)
    assert "u.for:12: error" in cleaned["reason"]


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------

def test_the_batch_runs_one_job_at_a_time_by_default():
    """The licence server here is shared and contended.

    Two concurrent jobs demand two sets of tokens at once and wait for them;
    multi-minute waits have been measured. A default of anything but 1 makes a
    long batch slower and much less predictable.
    """
    assert DEFAULT_JOBS == 1
    parser_default = _parsed_defaults()
    assert parser_default["jobs"] == 1
    assert parser_default["resume"] is False
    assert parser_default["limit"] == 0
    assert parser_default["only"] == ""
    assert parser_default["timeout"] > 0


def _parsed_defaults() -> dict:
    """The argument defaults, read from the parser itself rather than restated."""
    import argparse
    import verify_store_in_abaqus as batch

    captured: dict = {}

    class _Stop(Exception):
        pass

    def fake_store(*args, **kwargs):
        raise _Stop

    original_parse = argparse.ArgumentParser.parse_args

    def spy(self, argv=None, namespace=None):
        parsed = original_parse(self, argv, namespace)
        captured.update(vars(parsed))
        raise _Stop

    argparse.ArgumentParser.parse_args = spy
    try:
        batch.main(["--work-dir", "unused"])
    except _Stop:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original_parse
    return captured


def test_an_empty_store_reports_nothing_rather_than_failing(tmp_path: Path):
    """A store with no entries is a fact about the store, not an error.

    It also proves the batch reaches its own summary without Abaqus: nothing
    up to this point needs a licence token.
    """
    assert main(["--store", str(tmp_path / "store"),
                 "--work-dir", str(tmp_path / "work"),
                 "--results-dir", str(tmp_path / "out")]) == 0


def test_a_real_store_entry_reaches_a_recorded_outcome_without_a_licence_token(
        tmp_path: Path):
    """The whole batch, end to end, over a store entry that stops early.

    The entry's stored transform carries no compile_order.txt, so the run
    settles at support_build_failed before either Abaqus job is reached -- which
    is the point: the ladder's early rungs must be reachable, recorded and
    counted without spending a licence token, and this test would call Abaqus
    if that ordering were ever inverted.
    """
    from umat_oti.store import TransformStore

    cache = _cache_with_deck(tmp_path)
    triage = tmp_path / "triage.csv"
    triage.write_text("source,repository,ntens,form,kinematics,stage\n"
                      "owner__name/sub/umat.for,owner/name,6,fixed,"
                      "small strain,transformed\n", encoding="utf-8")
    proposals = tmp_path / "proposals.json"
    proposals.write_text(json.dumps({"entries": [_proposal()]}), encoding="utf-8")

    out = tmp_path / "transform_out"
    out.mkdir()
    (out / "umat.for").write_text("      SUBROUTINE UMAT\n      RETURN\n      END\n")
    store = TransformStore(root=tmp_path / "store")
    store.put("owner__name/sub/umat.for", "abc123", out, out / "umat.for", {})

    results = tmp_path / "results"
    assert main(["--store", str(tmp_path / "store"),
                 "--cache-dir", str(cache), "--triage", str(triage),
                 "--proposals", str(proposals),
                 "--work-dir", str(tmp_path / "work"),
                 "--results-dir", str(results)]) == 0

    written = [json.loads(line) for line in
               (results / "store_verification.jsonl").read_text().splitlines()]
    assert [r["stage"] for r in written] == ["support_build_failed"]
    assert written[0]["source"] == "owner__name/sub/umat.for"
    assert written[0]["material_provenance"], (
        "an entry that stopped early still has to say where its constants "
        "came from")

    payload = json.loads((results / "store_verification.json").read_text())
    assert payload["summary"]["attempted"] == 1
    assert payload["summary"]["verified_count"] == 0
    assert payload["summary"]["by_stage"] == {"support_build_failed": 1}
    assert str(tmp_path) not in json.dumps(payload), (
        "the results file is written under paper_results/, where the "
        "repository audit fails the build on a machine path")


def test_a_resumed_batch_does_not_run_a_settled_entry_again(tmp_path: Path):
    """Batches of this take hours; a crash must not lose what was finished.

    The second run is given no cache, no triage and no proposals at all. If it
    re-ran the entry it would crash on them, so passing proves the entry was
    skipped -- and the denominator still counts it.
    """
    from umat_oti.store import TransformStore

    cache = _cache_with_deck(tmp_path)
    triage = tmp_path / "triage.csv"
    triage.write_text("source,repository,ntens,form,kinematics,stage\n"
                      "owner__name/sub/umat.for,owner/name,6,fixed,"
                      "small strain,transformed\n", encoding="utf-8")
    proposals = tmp_path / "proposals.json"
    proposals.write_text(json.dumps({"entries": [_proposal()]}), encoding="utf-8")
    out = tmp_path / "transform_out"
    out.mkdir()
    (out / "umat.for").write_text("      SUBROUTINE UMAT\n      RETURN\n      END\n")
    TransformStore(root=tmp_path / "store").put(
        "owner__name/sub/umat.for", "abc123", out, out / "umat.for", {})
    results = tmp_path / "results"
    common = ["--store", str(tmp_path / "store"),
              "--work-dir", str(tmp_path / "work"),
              "--results-dir", str(results)]
    assert main(common + ["--cache-dir", str(cache), "--triage", str(triage),
                          "--proposals", str(proposals)]) == 0

    # The deck goes away before the resumed run. A re-run would find no
    # material data and record a different stage; a skipped one cannot.
    (cache / "owner__name/decks/job.inp").unlink()
    assert main(common + ["--resume", "--cache-dir", str(cache),
                          "--triage", str(triage),
                          "--proposals", str(proposals)]) == 0
    lines = (results / "store_verification.jsonl").read_text().splitlines()
    assert len(lines) == 1, "a skipped entry must not be written again"
    payload = json.loads((results / "store_verification.json").read_text())
    assert payload["summary"]["attempted"] == 1, (
        "a skipped entry stays in the denominator")
    assert payload["summary"]["by_stage"] == {"support_build_failed": 1}


def test_the_deck_material_name_is_carried_into_the_generated_deck(tmp_path: Path):
    """The material's name becomes CMNAME, which some UMATs branch on.

    A source that switches on CMNAME takes a different path -- or refuses --
    under a name its author never used, and the run then measures a branch the
    deck was not describing.
    """
    cache = _cache_with_deck(tmp_path)
    plan = build_manifest("owner__name/sub/umat.for", _row(), _proposal(), cache)
    assert plan.manifest.name == "STEEL"


def test_an_unnamed_material_block_falls_back_without_losing_identity(tmp_path: Path):
    """The manifest's name is a label inside a generated deck.

    The entry's identity stays its path within the cache -- eighteen UMATs here
    share a basename with something else, so a name is never a key.
    """
    cache = _cache_with_deck(tmp_path, DECK.replace(", NAME=STEEL", ""))
    plan = build_manifest("owner__name/sub/umat.for", _row(),
                          _proposal(**{"material": {"provenance": ""}}), cache)
    assert plan.manifest.name == "umat"
    assert plan.material_block == "(unnamed)"


def test_a_missing_original_source_stops_the_entry_before_any_job(tmp_path: Path):
    """The original is the whole reference; without it there is nothing to
    compare the transform against.

    Discovering that inside a job spends a licence token and reports the
    absence as a crashed harness rather than as the recorded outcome it is.
    """
    from verify_store_in_abaqus import verify_one

    cache = _cache_with_deck(tmp_path)
    (cache / "owner__name/sub/umat.for").unlink()
    out = tmp_path / "tx"
    out.mkdir()
    (out / "umat.for").write_text("      RETURN\n      END\n")
    stored = FakeStored(directory=out, entry_source=out / "umat.for")
    record = verify_one(stored, _row(), _proposal(), cache, tmp_path / "work",
                        timeout=1)
    assert record["stage"] == "manifest_refused"
    assert "nothing to compare against" in record["reason"]


def test_more_than_one_job_still_writes_every_record_once(tmp_path: Path):
    """--jobs N exists for a machine whose licence pool is not shared.

    It shares one results file across threads, so the append has to be locked:
    two entries writing at once would interleave into a line that no resumed
    batch could parse, and the batch would then repeat work it had finished.
    """
    from verify_store_in_abaqus import run_batch

    entries = []
    for name in ("alice__proj/src/umat.for", "bob__other/src/umat.for"):
        directory = tmp_path / name.replace("/", "_")
        directory.mkdir(parents=True)
        (directory / "umat.for").write_text("      RETURN\n      END\n")
        entries.append(FakeStored(key=name.split("__")[0], source_id=name,
                                  directory=directory,
                                  entry_source=directory / "umat.for"))
    results = tmp_path / "results.jsonl"
    written = run_batch(entries, {}, {}, tmp_path / "cache", tmp_path / "work",
                        results, timeout=1, jobs=2)
    assert len(written) == 2
    lines = [json.loads(line) for line in results.read_text().splitlines()]
    assert sorted(r["source"] for r in lines) == ["alice__proj/src/umat.for",
                                                  "bob__other/src/umat.for"]
    assert {r["stage"] for r in lines} == {"needs_material_data"}
    assert summarise(lines)["attempted"] == 2
