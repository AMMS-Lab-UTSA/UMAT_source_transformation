"""What the offline stress-parity gate is allowed to say, and what it must not.

This gate exists to decide where Abaqus licence time goes, so its failure mode
is not a crash -- it is a row that reads as agreement when nothing was
compared. Every test here pins one of the ways that could happen: a source with
no material constants quietly acquiring some, a build failure losing the
compiler message that explains it, two all-zero stresses being scored as a
match, a resumed run treating a half-written record as done, and the report
describing itself as verification.

Nothing here compiles anything. The gate's scoring is pure functions over
records precisely so that the rules can be checked without a compiler, and the
one test that calls the whole per-entry path does so on an entry with no
material data, which is the path that must never reach a compiler at all.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from verify_store_offline import (  # noqa: E402
    AGREED, CAVEAT, DECIDED, DISAGREED, DRIVER_DID_NOT_RUN, HARNESS_ERROR,
    NEEDS_MATERIAL_DATA, NO_RESPONSE, ORIGINAL_BUILD_FAILED,
    ORIGINAL_UNAVAILABLE, OUTCOMES, TRANSFORMED_BUILD_FAILED, Material,
    Options, blocking_note, check_entry, choose_material, compiler_reason,
    HEADER_NAMES, INSTALLED_HEADER, STUB_HEADER, format_summary, header_note,
    install_headers, load_previous,
    manifest_materials, material_from_manifest,
    material_from_proposal, original_is_intact, original_source,
    partition_for_resume, portable_text, previously_recorded, probe_entry,
    proposal_materials, single_record, stress_response, summarise,
)
from umat_oti.abaqus.replay import STATE_FILE, write_state  # noqa: E402

GFORTRAN_ERROR = (
    "u.for:412:24:\n\n  412 |       CALL ROTSIG(STATEV(1),DROT,EELAS,2,NDI,NSHR)\n"
    "      |                        1\n"
    "Error: Symbol 'rotsig' at (1) has no IMPLICIT type\n")


class _Entry:
    """As much of a StoredTransform as the gate reads.

    A stub rather than a real store entry: a real one has to be produced by a
    transform, and the behaviour under test here is scoring, not transforming.
    """

    def __init__(self, key="k0", source_id="owner__name/src/u.for",
                 source_sha256="", entry_source=None, directory=None,
                 metadata=None):
        self.key = key
        self.source_id = source_id
        self.source_sha256 = source_sha256
        self.entry_source = Path(entry_source or "u.for")
        self.directory = Path(directory or ".")
        self.metadata = dict(metadata or {})
        self.fingerprint = "fp0"


def _record(**overrides):
    """A record in the state the per-entry check leaves it in, before scoring."""
    base = {
        "original_available": True,
        "original_reason": "",
        "material_provenance": "deck.inp *Material name=steel at line 12",
        "built_original": True, "original_build_reason": "",
        "built_transformed": True, "transformed_build_reason": "",
        "ran_original": True, "ran_transformed": True, "run_reason": "",
        "response": True,
        "agreed": True,
        "worst_relative": 0.0,
        "comparison_reason": "",
    }
    base.update(overrides)
    return base


def _outcome(**overrides):
    from verify_store_offline import outcome_for
    return outcome_for(_record(**overrides))


class TestTheOutcomeIsWhatActuallyHappened:
    """If any of these regress, the report claims results it does not have."""

    def test_a_source_with_no_material_data_is_classified_not_run(self):
        """Without this the gate would drive a model with constants nobody published."""
        outcome, reason = _outcome(material_provenance="")
        assert outcome == NEEDS_MATERIAL_DATA
        assert "none are invented" in reason

    def test_constants_with_no_stated_provenance_do_not_count_as_material_data(self):
        """A bare vector is indistinguishable from an invented one."""
        proposal = {"material": {"props": [210000.0, 0.3]}, "ntens": 6}
        assert material_from_proposal(proposal) is None

    def test_a_failed_original_build_is_named_as_the_original(self):
        """The two builds fail for different reasons and the report has to say which."""
        outcome, reason = _outcome(built_original=False,
                                   original_build_reason="gfortran said no")
        assert outcome == ORIGINAL_BUILD_FAILED
        assert reason == "gfortran said no"

    def test_a_failed_transformed_build_is_reported_as_the_transform_failing(self):
        """A transform that emits code the compiler rejects is the finding here."""
        outcome, reason = _outcome(built_transformed=False,
                                   transformed_build_reason="unclassifiable statement")
        assert outcome == TRANSFORMED_BUILD_FAILED
        assert "unclassifiable statement" in reason

    def test_a_driver_that_produced_no_stress_is_not_agreement(self):
        """A missing result is not a matching result; it must not score as one."""
        outcome, _ = _outcome(ran_transformed=False, agreed=True)
        assert outcome == DRIVER_DID_NOT_RUN

    def test_two_all_zero_stresses_are_not_counted_as_agreement(self):
        """compare_primal scores nothing when both sides are zero and so reports
        agreement; a probe that moved no stress has proved nothing about the
        transform, and calling that a match would fill the Abaqus queue with
        entries this gate never actually tested."""
        outcome, reason = _outcome(response=False, agreed=True, worst_relative=0.0)
        assert outcome == NO_RESPONSE
        assert "no power" in reason

    def test_a_disagreement_keeps_the_comparison_reason(self):
        """The size of the difference is the whole content of a failed row."""
        outcome, reason = _outcome(
            agreed=False, worst_relative=3.2e-4,
            comparison_reason="worst stress difference 3.200e-04")
        assert outcome == DISAGREED
        assert "3.200e-04" in reason

    def test_a_disagreement_with_no_reason_still_says_it_disagreed(self):
        """A silent row would be read as a pass by anyone scanning the reasons."""
        outcome, reason = _outcome(agreed=False, comparison_reason="")
        assert outcome == DISAGREED and reason

    def test_agreement_is_reported_only_when_a_comparison_ran_and_agreed(self):
        outcome, reason = _outcome()
        assert (outcome, reason) == (AGREED, "")

    def test_a_changed_cached_original_outranks_every_other_verdict(self):
        """If the original is not the file the transform was made from, every
        later answer is about two unrelated programs -- including a
        disagreement, which would be published as a defect in the transform."""
        outcome, reason = _outcome(original_available=False,
                                   original_reason="the cached source has changed",
                                   agreed=False, built_original=False)
        assert outcome == ORIGINAL_UNAVAILABLE
        assert "changed" in reason

    def test_every_outcome_it_can_return_is_one_it_reports(self):
        """An outcome missing from OUTCOMES vanishes from the summary table."""
        produced = {
            _outcome()[0], _outcome(agreed=False)[0],
            _outcome(response=False)[0], _outcome(built_original=False)[0],
            _outcome(built_transformed=False)[0], _outcome(ran_original=False)[0],
            _outcome(material_provenance="")[0],
            _outcome(original_available=False)[0],
        }
        assert produced <= set(OUTCOMES)


class TestABuildFailureKeepsWhatTheCompilerSaid:
    """A status line with no diagnostic in it is a row nobody can act on."""

    def test_the_compiler_message_survives_into_the_reason(self):
        reason = compiler_reason("the replay driver did not link (exit 1)",
                                 GFORTRAN_ERROR)
        assert "Error: Symbol 'rotsig' at (1) has no IMPLICIT type" in reason
        assert "did not link" in reason

    def test_a_long_log_is_truncated_rather_than_dropped(self):
        """A ten-thousand-line cascade must not become the report, and must not
        become an empty reason either."""
        log = GFORTRAN_ERROR + ("Error: cascade\n" * 5000)
        reason = compiler_reason("build failed", log, limit=400)
        assert "Symbol 'rotsig'" in reason
        assert reason.endswith("[truncated]")
        assert len(reason) < 500

    def test_the_first_diagnostic_is_the_one_kept(self):
        """gfortran reports in source order: the first message names the
        statement that broke and the rest are cascades of it."""
        log = "Error: the cause\n" + ("Error: a consequence\n" * 200)
        reason = compiler_reason("", log, limit=120)
        assert "the cause" in reason

    def test_a_machine_path_does_not_reach_the_reason(self):
        """The compiler quotes the absolute path of every file it is handed, and
        the repository audit fails the build on one of those in evidence."""
        work = "/home/someone/gate_work"  # machine-path-fixture: fabricated, fed to the filter under test
        reason = compiler_reason("build failed",
                                 f"{work}/u.for:1: Error: bad", roots=[work])
        assert "<work>/u.for:1: Error: bad" in reason
        assert "/home/someone" not in reason

    def test_the_store_and_the_cache_are_named_rather_than_spelled_out(self):
        """A compile failure quotes the path of the file it was handed, and
        that file lives in the store or the cache. A smoke run put the store's
        absolute path straight into the reason, which is exactly what the
        repository audit fails the build on -- while the part of the message a
        reader needs is which file it was, not which machine."""
        store, cache = "/home/someone/transform_store", "/home/someone/cache"  # machine-path-fixture: fabricated, fed to the filter under test
        reason = compiler_reason(
            "did not link",
            f"{store}/k0/u.for:16: Error: bad\n{cache}/o__r/u.for:2: note",
            roots=[(store, "<store>"), (cache, "<cache>")])
        assert "<store>/k0/u.for:16: Error: bad" in reason
        assert "<cache>/o__r/u.for:2: note" in reason
        assert "/home/someone" not in reason

    def test_a_nested_directory_is_named_as_itself(self):
        """A work directory inside the store must not be half-rewritten to
        <store>, which would leave the rest of its path in the report."""
        text = portable_text("/s/work/u.for", [("/s", "<store>"), ("/s/work", "<work>")])
        assert text == "<work>/u.for"

    def test_a_build_that_said_nothing_leaves_an_empty_reason(self):
        """An empty string is honest; a fabricated explanation is not."""
        assert compiler_reason("", "") == ""


class TestMaterialConstantsComeFromTheAuthorOrNowhere:
    """The rule the whole corpus rests on: an LLM may propose, not certify."""

    def test_a_proposal_that_paired_no_deck_supplies_nothing(self):
        assert material_from_proposal({"status": "no_deck", "ntens": 6}) is None

    def test_a_paired_proposal_supplies_its_props_and_says_where_from(self):
        material = material_from_proposal({
            "material": {"props": [0.5, 2.5641],
                         "provenance": "owner__repo/umat/twist.inp *Material user_mat"},
            "ntens": 6, "ndi": 3, "nshr": 3, "nstatv_inferred": 4})
        assert material.props == (0.5, 2.5641)
        assert "twist.inp" in material.provenance
        assert material.nstatv == 4
        assert "inferred" in material.nstatv_provenance

    def test_a_deck_declared_state_count_outranks_an_inferred_one(self):
        """*DEPVAR is the author's own number; the inference is only a bound.
        A driver handed the bound allocates state the author never wrote."""
        material = material_from_proposal({
            "material": {"props": [1.0], "provenance": "d.inp *Material m",
                         "nstatv_declared_by_deck": 150},
            "nstatv_inferred": 78})
        assert material.nstatv == 150
        assert "DEPVAR" in material.nstatv_provenance

    def test_a_manifest_outranks_a_pairing_for_the_same_source(self):
        """A manifest is reviewed; a pairing still says needs_review of itself."""
        reviewed = Material(props=(1.0,), provenance="reviewed deck")
        proposed = Material(props=(2.0,), provenance="scan proposal")
        chosen = choose_material("o__r/u.for", {"o__r/u.for": reviewed},
                                 {"o__r/u.for": proposed})
        assert chosen is reviewed

    def test_a_source_nobody_paired_gets_no_constants_from_anywhere(self):
        assert choose_material("o__r/u.for", {}, {"o__r/other.for": Material(
            props=(1.0,), provenance="deck")}) is None

    def test_the_index_is_keyed_by_path_within_the_cache_not_by_filename(self, tmp_path):
        """Eighteen UMATs here share a basename with something else; the last
        time a batch keyed on one, eighteen were driven with another project's
        constants and two of those reached 'verified'."""
        proposals = tmp_path / "p.json"
        proposals.write_text(json.dumps({"entries": [
            {"repository": "one/proj", "source": "src/umat.f",
             "material": {"props": [1.0], "provenance": "one deck"}},
            {"repository": "two/proj", "source": "src/umat.f",
             "material": {"props": [2.0], "provenance": "two deck"}}]}))
        index = proposal_materials(proposals)
        assert set(index) == {"one__proj/src/umat.f", "two__proj/src/umat.f"}
        assert index["one__proj/src/umat.f"].props == (1.0,)

    def test_a_manifest_is_read_by_the_same_identity(self, tmp_path):
        (tmp_path / "m.json").write_text(json.dumps({
            "source": "owner__repo/work/huang.for", "props": [266538.0, 114000.0],
            "material_provenance": "Job-1.inp *MATERIAL MATERIAL-1", "nstatv": 150}))
        index = manifest_materials(tmp_path)
        assert index["owner__repo/work/huang.for"].nstatv == 150

    def test_a_manifest_without_provenance_supplies_nothing(self):
        assert material_from_manifest({"props": [1.0, 2.0]}) is None

    def test_the_probe_carries_the_authors_constants_and_no_others(self):
        """Padding a short props vector to some expected length would be
        inventing constants one element at a time."""
        material = Material(props=(210000.0, 0.3), provenance="deck", nstatv=4)
        state = probe_entry(material)
        assert state["PROPS"] == [210000.0, 0.3]
        assert state["NPROPS"] == 2

    def test_the_probe_starts_from_a_state_it_declares(self):
        """Zero stress and zero state are a declaration, not a reading of the
        model's SDVINI -- which is one reason an agreeing row still needs Abaqus."""
        state = probe_entry(Material(props=(1.0,), provenance="deck", ntens=6))
        assert state["STRESS0"] == [0.0] * 6
        assert state["STATEV0"] == [0.0]
        assert state["DSTRAN"][0] > 0 and set(state["DSTRAN"][1:]) == {0.0}

    def test_the_deformation_gradient_moves_with_the_strain_increment(self):
        """A finite-strain source reads DFGRD1 and never looks at DSTRAN. Handed
        an unmoved gradient it reports the stress of an undeformed body, both
        builds return zero, and the gate proves nothing while looking green."""
        state = probe_entry(Material(props=(1.0,), provenance="deck"), strain=1e-3)
        assert state["DFGRD1"][0] == pytest.approx(1.001)
        assert state["DFGRD0"][0] == 1.0

    def test_the_probe_is_written_in_the_shape_the_driver_reads(self, tmp_path):
        """write_state is the driver's own reader; a state it writes wrongly is
        a replay that starts somewhere the comparison never meant to be."""
        material = Material(props=(210000.0, 0.3), provenance="deck",
                            ntens=6, ndi=3, nshr=3, nstatv=4)
        path = tmp_path / STATE_FILE
        write_state(probe_entry(material), path)
        header, timing = path.read_text().splitlines()[:2]
        assert header.split() == ["6", "4", "2", "3", "3"]
        assert float(timing.split()[0]) == 1.0

    def test_an_entry_with_no_material_never_reaches_a_compiler(self, tmp_path):
        """The rule is not only that the row is reported -- it is that nothing
        is built for it. A gate that compiled first and classified afterwards
        would spend its budget on rows it had already decided not to run."""
        original = tmp_path / "cache" / "owner__name" / "u.for"
        original.parent.mkdir(parents=True)
        original.write_text("      SUBROUTINE UMAT()\n      END\n")
        work = tmp_path / "work"
        entry = _Entry(source_id="owner__name/u.for", entry_source=original,
                       directory=tmp_path)
        record = check_entry(entry, None, Options(cache=tmp_path / "cache",
                                                  work_root=work))
        assert record["outcome"] == NEEDS_MATERIAL_DATA
        assert record["built_original"] is False
        assert not work.exists()


class TestNothingInTheReportNamesThisMachine:
    """The report is committed, and tools/audit_repository_standards.py fails
    the build on a path under a home or a scratch directory."""

    def test_the_header_a_build_used_is_recorded_without_a_path(self):
        """Which aba_param.inc was used changes what the reference means, so it
        is kept -- but build_replay answers with an absolute path, and on a
        machine with no Abaqus that path is the run's own scratch directory."""
        installed = header_note(
            "/opt/SIMULIA/EstProducts/2021/SMAUsubs/PublicInterfaces/aba_param.inc")
        stub = header_note("stub in /tmp/claude-1/gate/original")  # machine-path-fixture: fabricated, fed to the filter under test
        assert installed == INSTALLED_HEADER and "/" not in installed
        assert stub == STUB_HEADER and "/tmp" not in stub

    def test_a_build_that_named_no_header_says_nothing(self):
        assert header_note("") == ""


class TestTheHeaderResolvesUnderEveryNameASourceUsesForIt:
    def test_every_casing_of_the_include_is_present_in_a_build_directory(self, tmp_path):
        """The first real corpus source through this gate failed with "Can't
        open included file 'ABA_PARAM.INC'". The installation ships the header
        in lowercase only, so without the aliases every source that spells the
        include in capitals is reported as a build failure -- a defect in this
        harness published as a defect in somebody's UMAT."""
        used = install_headers(tmp_path)
        for name in HEADER_NAMES:
            assert (tmp_path / name).read_text().strip()
        assert used in (INSTALLED_HEADER, STUB_HEADER)

    def test_the_headers_land_in_a_directory_that_did_not_exist(self, tmp_path):
        """Each build gets its own directory, and it is made here or by the
        builder -- whichever runs first must not depend on the other."""
        target = tmp_path / "new" / "original"
        install_headers(target)
        assert (target / "aba_param.inc").is_file()


class TestIdentityIsThePathNotTheName:
    def test_the_original_is_found_under_the_cache_by_its_identity(self, tmp_path):
        entry = _Entry(source_id="owner__name/src/umat.f")
        assert original_source(entry, tmp_path) == tmp_path / "owner__name/src/umat.f"

    def test_a_path_the_store_recorded_is_preferred_to_a_reconstructed_one(self, tmp_path):
        """Where the store wrote down the file it read, that is a stronger
        statement than rebuilding the path from an identity."""
        entry = _Entry(source_id="owner__name/src/umat.f",
                       metadata={"original_source": str(tmp_path / "elsewhere.f")})
        assert original_source(entry, tmp_path) == tmp_path / "elsewhere.f"

    def test_a_cached_source_that_changed_is_not_compared_against(self, tmp_path):
        """Otherwise a re-acquired repository turns into a published claim that
        the transform changed the stress."""
        source = tmp_path / "u.for"
        source.write_text("      END\n")
        intact, reason = original_is_intact(source, "0" * 64)
        assert intact is False and "changed" in reason

    def test_a_missing_original_is_said_to_be_missing(self, tmp_path):
        intact, reason = original_is_intact(tmp_path / "gone.for", "abc")
        assert intact is False and "not in the discovery cache" in reason


class TestASourceThatWaitsForInputIsFlagged:
    def test_a_pause_is_reported_even_for_a_source_that_agreed(self, tmp_path):
        """A PAUSE hangs an Abaqus job instead of failing it: the licence is
        spent sitting on a terminal read. A batch has to know before it queues."""
        note = blocking_note(["      PAUSE 'check the input'"], [])
        assert "hang" in note and "1 in the original" in note

    def test_a_source_with_nothing_blocking_says_nothing(self):
        assert blocking_note([], []) == ""


class TestTheDenominatorIsTheWholeStore:
    def test_a_row_with_no_material_data_is_counted_not_dropped(self):
        """Dropping it would turn 'agreed on 4 of 10' into 'agreed on 4 of 4'."""
        summary = summarise([{"outcome": AGREED}, {"outcome": NEEDS_MATERIAL_DATA},
                             {"outcome": NEEDS_MATERIAL_DATA}])
        assert summary["entries"] == 3
        assert summary["by_outcome"][NEEDS_MATERIAL_DATA] == 2
        assert summary["agreed"] == 1

    def test_undecided_rows_are_reported_as_undecided(self):
        summary = summarise([{"outcome": name} for name in
                             (AGREED, DISAGREED, NO_RESPONSE,
                              TRANSFORMED_BUILD_FAILED, HARNESS_ERROR)])
        assert summary["decided"] == 2
        assert summary["undecided"] == 3
        assert set(DECIDED) == {AGREED, DISAGREED}

    def test_a_record_with_no_outcome_is_counted_as_a_harness_error(self):
        """A row that fell out of the machinery must still appear somewhere."""
        assert summarise([{}])["by_outcome"][HARNESS_ERROR] == 1

    def test_sources_carrying_a_blocking_statement_are_counted(self):
        summary = summarise([{"outcome": AGREED,
                              "blocking_statements": {"original": ["      PAUSE"]}},
                             {"outcome": AGREED, "blocking_statements": {}}])
        assert summary["with_blocking_statements"] == 1

    def test_the_worst_difference_reported_is_from_agreeing_rows(self):
        """Quoting the worst difference over every row would hide a tight
        agreement behind one build that failed."""
        summary = summarise([{"outcome": AGREED, "worst_relative": 1e-14},
                             {"outcome": DISAGREED, "worst_relative": 0.5}])
        assert summary["worst_relative_difference_among_agreeing"] == 1e-14

    def test_the_human_summary_says_this_is_not_abaqus_verification(self):
        """The count will be read as 'these UMATs are verified' unless the text
        in front of it says, every time, that no solver ran."""
        text = format_summary(summarise([{"outcome": AGREED}]))
        assert "not Abaqus verification" in CAVEAT
        assert CAVEAT in text
        assert "verified" not in text.lower()

    def test_the_summary_names_each_outcome_it_counted(self):
        text = format_summary(summarise([{"outcome": NEEDS_MATERIAL_DATA}]))
        assert NEEDS_MATERIAL_DATA in text


class TestResumingDoesNotInventProgress:
    def test_a_decided_row_is_not_rechecked(self, tmp_path):
        previous = {"entries": [{"key": "k1", "outcome": AGREED}]}
        todo, reused = partition_for_resume(
            [_Entry(key="k1"), _Entry(key="k2")], previously_recorded(previous))
        assert [entry.key for entry in todo] == ["k2"]
        assert reused[0]["key"] == "k1"

    def test_a_reused_row_stays_in_the_output_and_says_it_was_reused(self):
        """A resumed run that reported only the rows it re-ran would shrink the
        corpus it claims to have checked."""
        _, reused = partition_for_resume(
            [_Entry(key="k1")], previously_recorded({"entries": [
                {"key": "k1", "outcome": DISAGREED}]}))
        assert reused[0]["reused_from_previous_run"] is True
        assert reused[0]["outcome"] == DISAGREED

    def test_a_record_with_no_outcome_is_run_again(self):
        """A run killed halfway leaves rows like this; treating one as done
        would quietly drop it from every later denominator."""
        assert previously_recorded({"entries": [{"key": "k1"}]}) == {}
        assert previously_recorded({"entries": [{"key": "k1", "outcome": "?"}]}) == {}

    def test_a_needs_material_data_row_is_reconsidered(self):
        """Nothing was compiled for it, so re-deciding it is free -- and it can
        change without the transform changing, the moment a reviewer pairs a
        deck to the source."""
        previous = previously_recorded({"entries": [
            {"key": "k1", "outcome": NEEDS_MATERIAL_DATA}]})
        todo, reused = partition_for_resume([_Entry(key="k1")], previous)
        assert [entry.key for entry in todo] == ["k1"] and reused == []

    def test_a_row_recorded_before_the_transform_changed_is_not_served(self):
        """The store key carries a fingerprint of the transform code, so a
        record from before a change addresses a key no current entry has. That
        is what makes 'recheck everything after a change' automatic."""
        previous = previously_recorded({"entries": [
            {"key": "old-fingerprint-key", "outcome": AGREED}]})
        todo, reused = partition_for_resume([_Entry(key="new-fingerprint-key")],
                                            previous)
        assert len(todo) == 1 and reused == []

    def test_an_unreadable_previous_output_resumes_nothing(self, tmp_path):
        """A resume that swallowed a corrupt file would report every entry as
        already done."""
        broken = tmp_path / "out.json"
        broken.write_text("{not json")
        assert load_previous(broken) == {}
        assert load_previous(tmp_path / "absent.json") == {}

    def test_a_previous_output_is_read_back_from_what_this_tool_writes(self, tmp_path):
        """The resume reader and the report writer have to agree on the shape,
        or --resume silently re-runs the whole batch every time."""
        path = tmp_path / "out.json"
        path.write_text(json.dumps({"summary": {}, "entries": [
            {"key": "k1", "outcome": AGREED, "source_id": "o__r/u.for"}]}))
        assert set(load_previous(path)) == {"k1"}


class TestTheComparisonIsMadeOnWhatWasActuallyProduced:
    def test_a_replayed_call_is_offered_with_no_invented_state(self):
        """The driver writes no STATEV; filling one in would let two builds
        agree about a vector neither of them reported."""
        assert single_record([1.0, 2.0]) == {"STRESS": [1.0, 2.0], "STATEV": []}

    def test_an_all_zero_stress_is_recognised_as_no_response(self):
        assert stress_response([0.0, 0.0, 0.0]) == 0.0
        assert stress_response([0.0, -3.0]) == 3.0

    def test_a_missing_stress_is_no_response_rather_than_an_error(self):
        assert stress_response([]) == 0.0
