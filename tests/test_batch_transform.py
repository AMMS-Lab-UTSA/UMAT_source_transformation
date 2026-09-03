"""What the batch transform is allowed to claim, and what it must never lose.

The number this tool prints will be read as "the transformer handles this many
real UMATs", so the three things that bound that claim are pinned here. Work
served from the store is not work this run did, and the two counts stay apart.
A source that fails keeps its reason and stays in the denominator, because the
histogram of reasons is the finding and a batch that shrank to what it could
handle would be reporting on itself. And a second run with nothing changed does
nothing and says so, which is only true while the store's address includes a
fingerprint of the transform code.

Nothing here runs the real transform or Abaqus. The selection, the accounting
and the idempotency are ordinary functions over ordinary data, and that is
deliberate: they are the parts that decide what gets counted.
"""
from __future__ import annotations

import csv
import multiprocessing
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from transform_all import (  # noqa: E402
    OUTCOME_CACHED, OUTCOME_FAILED, OUTCOME_NOT_IN_CACHE, OUTCOME_TRANSFORMED,
    OUTCOMES, TransformResult, compiled_cleanly, plan_work, read_work_list,
    reason_for_report, record_outcome, report_lines, run_plan, scrub,
    select_work, summarise, work_dir_for,
)

TRIAGE_FIELDS = ("source", "repository", "stage", "ntens", "kinematics",
                 "blocker_kind", "blocker", "compiled")

#: Enough of a UMAT to be a file with bytes. Nothing here reads it as Fortran.
SOURCE_TEXT = "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)\n      RETURN\n      END\n"


def write_triage(path: Path, rows: list[dict]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TRIAGE_FIELDS),
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in TRIAGE_FIELDS})
    return path


def cache_a_source(cache: Path, identity: str, text: str = SOURCE_TEXT) -> Path:
    """Put a file at ``identity`` under the cache, as discovery would have."""
    path = cache / identity
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class FakeStore:
    """The real store's three-part address, in memory.

    An entry is found only when identity, bytes and fingerprint all match, so
    raising the fingerprint hides every entry exactly as an edit to the
    transform code does. ``put`` takes the (item, result) pair that ``run_plan``
    hands its put callable; against the real store that callable is
    ``put_into``, which unpacks the pair into TransformStore.put.
    """

    def __init__(self, fingerprint: str = "fingerprint-1") -> None:
        self.fingerprint = fingerprint
        self.entries: dict[str, SimpleNamespace] = {}
        self.puts: list[str] = []

    def key_for(self, source_id: str, sha: str) -> str:
        return f"{source_id}|{sha}|{self.fingerprint}"

    def get(self, source_id: str, sha: str):
        return self.entries.get(self.key_for(source_id, sha))

    def put(self, item, result):
        key = self.key_for(item.source_id, item.sha256)
        stored = SimpleNamespace(key=key, source_id=item.source_id,
                                 metadata=dict(result.metadata))
        self.entries[key] = stored
        self.puts.append(item.source_id)
        return stored


def transforms_cleanly(item, work) -> TransformResult:
    """A transform that succeeds, without running one."""
    return TransformResult(
        source_id=item.source_id, ok=True, seconds=1.5,
        out_dir=Path(work) / "out", entry_source=Path(work) / "out" / "u_oti.f90",
        metadata={"ntens": item.ntens, "kinematics": "finite", "compiled": True,
                  "blockers": [], "warnings": [], "completion_issues": [],
                  "seconds": 1.5})


def fails_with(reason: str):
    def transform(item, work) -> TransformResult:
        return TransformResult(source_id=item.source_id, ok=False, seconds=0.4,
                               reason=reason, metadata={"kinematics": "finite"})
    return transform


def never_called(item, work):  # pragma: no cover - called only if a test fails
    raise AssertionError(f"{item.source_id} should not have been transformed")


class TestTheWorkListComesFromTheTriage:
    def test_only_rows_that_reached_transformed_are_attempted_by_default(self, tmp_path):
        """A blocked source has no output to store; attempting it every run
        would pay for the same failure forever and pad the batch with it."""
        triage = write_triage(tmp_path / "t.csv", [
            {"source": "o__a/u.for", "stage": "transformed"},
            {"source": "o__b/v.for", "stage": "blocked"},
            {"source": "o__c/w.for", "stage": "semantic_checks_failed"},
        ])
        chosen = select_work(read_work_list(triage))
        assert [row["source"] for row in chosen] == ["o__a/u.for"]

    def test_all_attempts_every_row_including_the_ones_that_did_not_transform(self, tmp_path):
        """--all is how a change to the transformer is checked against the
        sources it could not read before, so it must not filter by stage."""
        triage = write_triage(tmp_path / "t.csv", [
            {"source": "o__a/u.for", "stage": "transformed"},
            {"source": "o__b/v.for", "stage": "blocked"},
            {"source": "o__c/w.for", "stage": "not_a_umat"},
        ])
        chosen = select_work(read_work_list(triage), every=True)
        assert len(chosen) == 3

    def test_only_filters_on_the_identity_and_not_on_the_basename(self, tmp_path):
        """Eighteen sources here share a basename with something else. A filter
        that matched basenames would select another project's file."""
        triage = write_triage(tmp_path / "t.csv", [
            {"source": "alice__growth/umat.f", "stage": "transformed"},
            {"source": "bob__plastic/umat.f", "stage": "transformed"},
        ])
        rows = read_work_list(triage)
        assert [r["source"] for r in select_work(rows, only="alice__growth")] \
            == ["alice__growth/umat.f"]
        assert len(select_work(rows, only="umat.f")) == 2

    def test_limit_counts_rows_that_survived_the_filter(self, tmp_path):
        """--only X --limit 2 means two of X. Applying the limit first would
        return two rows of which none need be X."""
        triage = write_triage(tmp_path / "t.csv", [
            {"source": f"o__{name}/u.for", "stage": "transformed"}
            for name in ("a", "b", "target1", "target2", "target3")])
        rows = read_work_list(triage)
        chosen = select_work(rows, only="target", limit=2)
        assert [r["source"] for r in chosen] == ["o__target1/u.for",
                                                 "o__target2/u.for"]

    def test_a_limit_of_zero_is_no_limit(self, tmp_path):
        triage = write_triage(tmp_path / "t.csv", [
            {"source": f"o__{i}/u.for", "stage": "transformed"} for i in range(5)])
        assert len(select_work(read_work_list(triage), limit=0)) == 5

    def test_a_row_naming_no_source_is_not_quietly_dropped(self, tmp_path):
        """It cannot be transformed, but it was selected. Dropping it during
        selection would shrink the denominator where nobody could see it."""
        triage = write_triage(tmp_path / "t.csv", [
            {"source": "", "stage": "transformed"},
            {"source": "o__a/u.for", "stage": "transformed"},
        ])
        rows = select_work(read_work_list(triage))
        assert len(rows) == 2
        cache = tmp_path / "cache"
        cache_a_source(cache, "o__a/u.for")
        plan = plan_work(rows, cache, FakeStore())
        settled = [o for o in plan.settled if o.outcome == OUTCOME_NOT_IN_CACHE]
        assert len(settled) == 1 and settled[0].reason
        assert plan.selected == 2


class TestCachedWorkIsReportedApartFromNewWork:
    def _one_row(self, tmp_path, identity="o__a/u.for"):
        triage = write_triage(tmp_path / "t.csv",
                              [{"source": identity, "stage": "transformed",
                                "ntens": "6"}])
        cache = tmp_path / "cache"
        cache_a_source(cache, identity)
        return select_work(read_work_list(triage)), cache

    def test_a_source_the_store_already_holds_is_not_transformed_again(self, tmp_path):
        """The store exists so a transform is paid for once. Re-running it
        would make a re-check of 199 sources cost what building them cost."""
        rows, cache = self._one_row(tmp_path)
        store = FakeStore()
        first = run_plan(plan_work(rows, cache, store), work_root=tmp_path / "w",
                         put=store.put, transform=transforms_cleanly)
        assert [o.outcome for o in first] == [OUTCOME_TRANSFORMED]

        second = plan_work(rows, cache, store)
        assert second.todo == []
        assert [o.outcome for o in second.settled] == [OUTCOME_CACHED]

    def test_an_entry_from_an_earlier_transform_is_built_again(self, tmp_path):
        """The store's key carries a fingerprint of the transform code. If a
        stale entry were served, an edit to the emitter would be reported as
        having changed nothing, which is the one answer nobody can check."""
        rows, cache = self._one_row(tmp_path)
        store = FakeStore(fingerprint="fingerprint-1")
        run_plan(plan_work(rows, cache, store), work_root=tmp_path / "w",
                 put=store.put, transform=transforms_cleanly)

        moved_on = FakeStore(fingerprint="fingerprint-2")
        moved_on.entries = dict(store.entries)
        assert len(plan_work(rows, cache, moved_on).todo) == 1

    def test_editing_the_source_bytes_builds_it_again(self, tmp_path):
        """The address is the bytes, not the identity: a source that changed
        under the same path is a different input to the same transform."""
        rows, cache = self._one_row(tmp_path)
        store = FakeStore()
        run_plan(plan_work(rows, cache, store), work_root=tmp_path / "w",
                 put=store.put, transform=transforms_cleanly)
        cache_a_source(cache, "o__a/u.for", SOURCE_TEXT + "C changed\n")
        assert len(plan_work(rows, cache, store).todo) == 1

    def test_force_transforms_a_source_the_store_already_holds(self, tmp_path):
        rows, cache = self._one_row(tmp_path)
        store = FakeStore()
        run_plan(plan_work(rows, cache, store), work_root=tmp_path / "w",
                 put=store.put, transform=transforms_cleanly)
        assert len(plan_work(rows, cache, store, force=True).todo) == 1

    def test_the_summary_never_pools_cached_work_with_work_it_did(self, tmp_path):
        """One "succeeded: 199" would let a run that did nothing report what
        the run that built the corpus reported."""
        triage = write_triage(tmp_path / "t.csv", [
            {"source": "o__a/u.for", "stage": "transformed"},
            {"source": "o__b/v.for", "stage": "transformed"},
        ])
        cache = tmp_path / "cache"
        cache_a_source(cache, "o__a/u.for")
        cache_a_source(cache, "o__b/v.for")
        rows = select_work(read_work_list(triage))
        store = FakeStore()
        run_plan(plan_work(rows[:1], cache, store), work_root=tmp_path / "w",
                 put=store.put, transform=transforms_cleanly)
        plan = plan_work(rows, cache, store)
        outcomes = run_plan(plan, work_root=tmp_path / "w", put=store.put,
                            transform=transforms_cleanly)
        summary = summarise(outcomes, selected=plan.selected)
        assert summary["transformed_now"] == 1
        assert summary["reused_from_store"] == 1
        assert "succeeded" not in summary
        assert summary["compiled_cleanly"] == {"transformed_now": 1,
                                               "reused_from_store": 1}

    def test_a_cached_row_costs_this_run_no_seconds(self, tmp_path):
        """The seconds column is time this run spent. Carrying the original
        run's duration forward would report work that did not happen."""
        rows, cache = self._one_row(tmp_path)
        store = FakeStore()
        run_plan(plan_work(rows, cache, store), work_root=tmp_path / "w",
                 put=store.put, transform=transforms_cleanly)
        plan = plan_work(rows, cache, store)
        assert summarise(plan.settled, selected=plan.selected)["seconds"] == 0.0

    def test_the_real_store_is_read_the_same_way_the_fake_is(self, tmp_path):
        """Guards the fake against drifting from TransformStore, which is what
        every other test here relies on being an honest stand-in."""
        from umat_oti.store import TransformStore
        from umat_oti.store.transform_store import file_digest

        cache = tmp_path / "cache"
        source = cache_a_source(cache, "o__a/u.for")
        out = tmp_path / "out"
        out.mkdir()
        (out / "u_oti.f90").write_text("      end\n", encoding="utf-8")
        rows = select_work(read_work_list(write_triage(
            tmp_path / "t.csv", [{"source": "o__a/u.for", "stage": "transformed",
                                  "ntens": "6"}])))

        store = TransformStore(root=tmp_path / "store", fingerprint="fp-1")
        assert len(plan_work(rows, cache, store).todo) == 1
        store.put("o__a/u.for", file_digest(source), out, out / "u_oti.f90",
                  {"compiled": True, "ntens": 6, "kinematics": "finite"})

        plan = plan_work(rows, cache, store)
        assert plan.todo == []
        assert [o.outcome for o in plan.settled] == [OUTCOME_CACHED]
        assert plan.settled[0].compiled is True
        assert plan.settled[0].kinematics == "finite"

        moved_on = TransformStore(root=tmp_path / "store", fingerprint="fp-2")
        assert len(plan_work(rows, cache, moved_on).todo) == 1


class TestAFailureKeepsItsReasonAndItsPlaceInTheDenominator:
    def _rows(self, tmp_path, identities):
        triage = write_triage(tmp_path / "t.csv", [
            {"source": i, "stage": "transformed", "ntens": "6"} for i in identities])
        cache = tmp_path / "cache"
        for identity in identities:
            cache_a_source(cache, identity)
        return select_work(read_work_list(triage)), cache

    def test_a_failed_transform_is_counted_and_says_why(self, tmp_path):
        """"6 failed" with no causes is a defect list nobody can act on, and
        naming the cause is the whole reason this batch exists."""
        rows, cache = self._rows(tmp_path, ["o__a/u.for"])
        store = FakeStore()
        plan = plan_work(rows, cache, store)
        outcomes = run_plan(plan, work_root=tmp_path / "w", put=store.put,
                            transform=fails_with("COMMON block bound has no "
                                                 "confirmed shape"))
        summary = summarise(outcomes, selected=plan.selected)
        assert summary["failed"] == 1
        assert summary["transformed_now"] == 0
        assert summary["failures"] == [
            {"source": "o__a/u.for", "triage_stage": "transformed",
             "reason": "COMMON block bound has no confirmed shape"}]
        assert store.puts == []

    def test_a_transform_that_states_no_reason_is_still_given_one(self, tmp_path):
        rows, cache = self._rows(tmp_path, ["o__a/u.for"])
        store = FakeStore()
        outcomes = run_plan(plan_work(rows, cache, store), work_root=tmp_path / "w",
                            put=store.put, transform=fails_with(""))
        assert outcomes[0].outcome == OUTCOME_FAILED
        assert outcomes[0].reason.strip()

    def test_a_crash_in_the_transform_is_a_failure_not_a_disappearance(self, tmp_path):
        """A source that crashes the transformer is its most useful finding.
        Letting the exception escape would abort the batch and lose the rest."""
        def explodes(item, work):
            raise RuntimeError("the scanner fell over")

        rows, cache = self._rows(tmp_path, ["o__a/u.for", "o__b/v.for"])
        store = FakeStore()

        def one_explodes(item, work):
            return explodes(item, work) if item.source_id == "o__a/u.for" \
                else transforms_cleanly(item, work)

        plan = plan_work(rows, cache, store)
        outcomes = run_plan(plan, work_root=tmp_path / "w", put=store.put,
                            transform=one_explodes)
        summary = summarise(outcomes, selected=plan.selected)
        assert summary["failed"] == 1 and summary["transformed_now"] == 1
        assert "the scanner fell over" in summary["failures"][0]["reason"]

    def test_a_store_that_refuses_an_entry_is_a_failure_not_a_success(self, tmp_path):
        """A transform whose output did not land is not reusable, and counting
        it as transformed would promise the next round a file that is not there."""
        rows, cache = self._rows(tmp_path, ["o__a/u.for"])
        store = FakeStore()

        def refuses(item, result):
            raise OSError("no space left on device")

        outcomes = run_plan(plan_work(rows, cache, store), work_root=tmp_path / "w",
                            put=refuses, transform=transforms_cleanly)
        assert outcomes[0].outcome == OUTCOME_FAILED
        assert "no space left" in outcomes[0].reason

    def test_a_source_missing_from_the_cache_is_reported_not_dropped(self, tmp_path):
        """The triage row exists, so the source was there once. Silence would
        turn a cache that lost a file into a batch that got smaller."""
        triage = write_triage(tmp_path / "t.csv", [
            {"source": "o__a/u.for", "stage": "transformed"},
            {"source": "o__gone/v.for", "stage": "transformed"},
        ])
        cache = tmp_path / "cache"
        cache_a_source(cache, "o__a/u.for")
        rows = select_work(read_work_list(triage))
        plan = plan_work(rows, cache, FakeStore())
        summary = summarise(plan.settled + [], selected=plan.selected)
        assert summary["not_in_cache"] == 1
        assert summary["not_in_cache_sources"] == ["o__gone/v.for"]
        assert plan.selected == 2

    def test_every_selected_row_reaches_exactly_one_outcome(self, tmp_path):
        """The denominator is the selection. If the outcomes stopped summing to
        it, a success rate would be being quoted over a number that moved."""
        identities = [f"o__{i}/u.for" for i in range(4)]
        rows, cache = self._rows(tmp_path, identities)
        rows.append({"source": "o__gone/v.for", "stage": "transformed", "ntens": "6"})
        store = FakeStore()

        def mixed(item, work):
            return transforms_cleanly(item, work) if item.source_id.endswith("0/u.for") \
                else fails_with("unsupported intrinsic")(item, work)

        plan = plan_work(rows, cache, store)
        outcomes = run_plan(plan, work_root=tmp_path / "w", put=store.put,
                            transform=mixed)
        summary = summarise(outcomes, selected=plan.selected)
        assert summary["selected"] == 5
        assert sum(summary["by_outcome"][name] for name in OUTCOMES) == 5
        assert summary["unaccounted"] == 0
        assert len({o.source_id for o in outcomes}) == 5

    def test_the_blocker_is_the_reason_when_the_report_has_one(self):
        assert reason_for_report({"blockers": ["no confirmed shape"],
                                  "warnings": ["something else"]}) \
            == "no confirmed shape"

    def test_an_anchor_the_transform_could_not_find_is_a_reason(self):
        """completion_issues is populated exactly when blockers and warnings
        are empty. Reading only those two reported seventeen sources as failing
        for no stated reason while the reason sat in the report unread."""
        reason = reason_for_report({"completion_issues": [
            {"kind": "missing_ddsdde_extraction_point"}]})
        assert "missing_ddsdde_extraction_point" in reason

    def test_a_report_with_nothing_in_it_still_yields_a_reason(self):
        assert reason_for_report({}).strip()

    def test_a_compile_that_was_skipped_is_not_a_compile_that_passed(self):
        """"skipped" and "compiled" are one field apart, and a check that did
        not run being read as a check that passed is how a source with no
        ABA_PARAM.INC stub was recorded as producing valid Fortran."""
        assert compiled_cleanly({"compilation": {"status": "compiled",
                                                 "returncode": 0}}) is True
        assert compiled_cleanly({"compilation": {"status": "skipped"}}) is False
        assert compiled_cleanly({"compilation": {"status": "not_requested"}}) is False
        assert compiled_cleanly({"compilation": {"status": "compiled",
                                                 "returncode": 2}}) is False
        assert compiled_cleanly({}) is False

    def test_no_machine_path_reaches_a_recorded_reason(self, tmp_path):
        """A compiler quotes the absolute path of every file it was handed, and
        the repository audit fails the build on one reaching committed output."""
        home = str(Path.home())
        item = SimpleNamespace(source_id="o__a/u.for", ntens=6, stage="transformed")
        outcome = record_outcome(
            item,
            TransformResult(source_id="o__a/u.for", ok=False,
                            reason=f"{home}/scratch/u.for:3: Error: bad line"),
            put=lambda i, r: None)
        assert home not in outcome.reason
        assert "Error: bad line" in outcome.reason
        assert home not in scrub(f"{home}/elsewhere/u.for")


class TestRunningTwiceDoesTheWorkOnce:
    def _corpus(self, tmp_path, count=3):
        identities = [f"o__{i}/u.for" for i in range(count)]
        triage = write_triage(tmp_path / "t.csv", [
            {"source": i, "stage": "transformed", "ntens": "6"} for i in identities])
        cache = tmp_path / "cache"
        for identity in identities:
            cache_a_source(cache, identity)
        return select_work(read_work_list(triage)), cache

    def test_the_second_run_transforms_nothing(self, tmp_path):
        """The store is only worth having if a re-run is free. never_called
        fails the test rather than quietly redoing the work."""
        rows, cache = self._corpus(tmp_path)
        store = FakeStore()
        run_plan(plan_work(rows, cache, store), work_root=tmp_path / "w",
                 put=store.put, transform=transforms_cleanly)
        assert len(store.puts) == 3

        plan = plan_work(rows, cache, store)
        outcomes = run_plan(plan, work_root=tmp_path / "w", put=store.put,
                            transform=never_called)
        summary = summarise(outcomes, selected=plan.selected)
        assert summary["transformed_now"] == 0
        assert summary["reused_from_store"] == 3
        assert summary["attempted"] == 0
        assert summary["nothing_to_do"] is True
        assert len(store.puts) == 3

    def test_the_second_run_says_it_did_nothing(self, tmp_path):
        """A run that did no work printing the same shape of summary as the run
        that built the corpus is how a reader comes to believe it re-checked."""
        rows, cache = self._corpus(tmp_path)
        store = FakeStore()
        run_plan(plan_work(rows, cache, store), work_root=tmp_path / "w",
                 put=store.put, transform=transforms_cleanly)
        plan = plan_work(rows, cache, store)
        text = "\n".join(report_lines(summarise(
            plan.settled, selected=plan.selected, fingerprint=store.fingerprint)))
        assert "nothing to transform" in text
        assert "already in the store" in text

    def test_the_denominator_is_the_same_on_both_runs(self, tmp_path):
        rows, cache = self._corpus(tmp_path)
        store = FakeStore()
        first_plan = plan_work(rows, cache, store)
        first = summarise(run_plan(first_plan, work_root=tmp_path / "w",
                                   put=store.put, transform=transforms_cleanly),
                          selected=first_plan.selected)
        second_plan = plan_work(rows, cache, store)
        second = summarise(second_plan.settled, selected=second_plan.selected)
        assert first["selected"] == second["selected"] == 3

    def test_a_failure_is_attempted_again_and_the_run_does_not_claim_idleness(self, tmp_path):
        """Only successes are stored, so a failed source is retried every run.
        Saying "nothing to do" while re-running six transforms would be false."""
        rows, cache = self._corpus(tmp_path, count=2)
        store = FakeStore()

        def one_fails(item, work):
            return fails_with("unsupported intrinsic")(item, work) \
                if item.source_id == "o__1/u.for" else transforms_cleanly(item, work)

        run_plan(plan_work(rows, cache, store), work_root=tmp_path / "w",
                 put=store.put, transform=one_fails)
        plan = plan_work(rows, cache, store)
        assert [i.source_id for i in plan.todo] == ["o__1/u.for"]
        summary = summarise(run_plan(plan, work_root=tmp_path / "w", put=store.put,
                                     transform=one_fails),
                            selected=plan.selected)
        assert summary["nothing_to_do"] is False
        assert summary["failed"] == 1
        assert summary["reused_from_store"] == 1
        assert summary["failures"][0]["reason"] == "unsupported intrinsic"


class TestEachSourceTransformsInItsOwnDirectory:
    def test_two_sources_sharing_a_basename_do_not_share_a_work_directory(self, tmp_path):
        """Both would write contract.json and ABA_PARAM.INC under the same
        names, and under --jobs the winner would depend on the timing."""
        first = SimpleNamespace(source_id="alice__growth/umat.f")
        second = SimpleNamespace(source_id="bob__plastic/umat.f")
        assert work_dir_for(tmp_path, first) != work_dir_for(tmp_path, second)

    def test_the_work_directory_is_one_level_under_the_root(self, tmp_path):
        """A separator carried over from the identity would put a worker's
        scratch space somewhere the caller never named."""
        made = work_dir_for(tmp_path, SimpleNamespace(source_id="o__a/deep/u.for"))
        assert made.parent == tmp_path

    def test_the_same_source_always_gets_the_same_directory(self, tmp_path):
        item = SimpleNamespace(source_id="o__a/u.for")
        assert work_dir_for(tmp_path, item) == work_dir_for(tmp_path, item)


@pytest.mark.skipif(multiprocessing.get_start_method() != "fork",
                    reason="the fake transform is picklable only under fork")
class TestParallelWorkIsAccountedForLikeSerialWork:
    def test_no_row_is_lost_when_the_work_is_spread_over_workers(self, tmp_path):
        """--jobs changes only who runs the transform. The store put stays in
        the parent, so the accounting must come out identical."""
        identities = [f"o__{i}/u.for" for i in range(4)]
        triage = write_triage(tmp_path / "t.csv", [
            {"source": i, "stage": "transformed", "ntens": "6"} for i in identities])
        cache = tmp_path / "cache"
        for identity in identities:
            cache_a_source(cache, identity)
        rows = select_work(read_work_list(triage))
        store = FakeStore()
        plan = plan_work(rows, cache, store)
        outcomes = run_plan(plan, work_root=tmp_path / "w", put=store.put,
                            transform=transforms_cleanly, jobs=2)
        summary = summarise(outcomes, selected=plan.selected)
        assert summary["transformed_now"] == 4
        assert summary["unaccounted"] == 0
        assert sorted(store.puts) == identities
