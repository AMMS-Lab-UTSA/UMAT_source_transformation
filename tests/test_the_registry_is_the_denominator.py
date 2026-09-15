"""Every acquired artefact appears exactly once, whatever became of it.

A source that quietly stopped being attempted leaves no failing row to notice,
and a summary built from the rows a batch happened to produce would never show
it. So the registry is built from the acquisition inventory and the batch's
results are joined ONTO it -- never the other way round.

The second rule is the one that keeps a completion figure honest: a terminal
state says whose move it is. Four are final and external -- nobody published
the constants, the file is not a UMAT, it does not compile as published, a
module it needs was never published beside it. The rest are unfinished and
ours, and pooling them with the external ones would be a claim about the
corpus made out of facts about the pipeline.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from build_corpus_registry import build, markdown, summarise  # noqa: E402
from umat_oti.abaqus.terminal_states import (EXTERNAL,  # noqa: E402
                                             FULLY_VERIFIED, INTERNAL)

TRANSFORM = {
    "rows": [
        {"source": "owner__a/umat.for", "outcome": "transformed", "ntens": 6,
         "compiled": True, "key": "k1"},
        {"source": "owner__b/umat.for", "outcome": "transformed", "ntens": 4,
         "compiled": True, "key": "k2"},
        {"source": "owner__c/notaumat.f", "outcome": "failed"},
        {"source": "owner__d/needs.f90", "outcome": "failed"},
    ],
    "failures": [
        {"source": "owner__c/notaumat.f",
         "reason": "anchors not located: selected_routine_is_not_an_abaqus_umat"},
        {"source": "owner__d/needs.f90",
         "reason": "MOD is not declared anywhere in this source"},
    ],
}

ABAQUS = [
    {"key": "k1", "source": "owner__a/umat.for", "stage": "verified",
     "reason": "agreed at all 3 states", "element_type": "C3D8", "ntens": 6,
     "primal": {"worst_stress_relative": 0.0, "increments": 30},
     "tangent": {"states_checked": 3, "states_agreeing": 3,
                 "comparison": {"best_relative": 1e-12,
                                "stable_range": [1e-4, 1e-3]}}},
]


def write(tmp_path: Path):
    transform = tmp_path / "transform_batch.json"
    transform.write_text(json.dumps(TRANSFORM), encoding="utf-8")
    abaqus = tmp_path / "results.jsonl"
    abaqus.write_text("\n".join(json.dumps(row) for row in ABAQUS) + "\n",
                      encoding="utf-8")
    return transform, abaqus


def test_every_acquired_artefact_appears_exactly_once(tmp_path: Path):
    transform, abaqus = write(tmp_path)
    records = build(transform, abaqus, None)
    assert len(records) == 4
    assert len({r.source_id for r in records}) == 4


def test_an_entry_the_batch_never_reached_is_not_silently_dropped(tmp_path: Path):
    transform, abaqus = write(tmp_path)
    records = {r.source_id: r for r in build(transform, abaqus, None)}
    waiting = records["owner__b/umat.for"]
    assert waiting.terminal_state == "not_attempted"
    assert waiting.kind == "internal", (
        "an absence of a verdict is not a finished answer")


def test_a_verified_entry_carries_the_evidence_behind_it(tmp_path: Path):
    transform, abaqus = write(tmp_path)
    record = {r.source_id: r for r in build(transform, abaqus, None)}[
        "owner__a/umat.for"]
    assert record.terminal_state == FULLY_VERIFIED
    assert record.kind == "verified"
    assert record.worst_stress_relative == 0.0
    assert record.tangent_states_agreeing == 3
    assert record.tangent_plateau == "0.0001..0.001"


def test_a_missing_companion_is_the_repository_problem_not_ours(tmp_path: Path):
    transform, abaqus = write(tmp_path)
    records = build(transform, abaqus, None)
    record = {r.source_id: r for r in records}["owner__d/needs.f90"]
    record.missing_companions = "module MOD"
    from umat_oti.abaqus.terminal_states import from_transform_failure
    verdict = from_transform_failure(record.reason, companions_missing=True)
    assert verdict.state == "external_dependency_unavailable"
    assert verdict.finished


def test_a_transform_refusal_on_a_file_that_builds_is_ours(tmp_path: Path):
    from umat_oti.abaqus.terminal_states import from_transform_failure
    verdict = from_transform_failure("the transformer cannot read that module",
                                     compiles=True)
    assert verdict.state == "transform_refused"
    assert verdict.kind == "internal"
    assert not verdict.finished


def test_a_transform_refusal_on_a_file_that_does_not_build_is_not(tmp_path: Path):
    from umat_oti.abaqus.terminal_states import from_transform_failure
    verdict = from_transform_failure("anchors not located", compiles=False)
    assert verdict.state == "incomplete_or_corrupt_source"
    assert verdict.finished


def test_the_counts_partition_the_inventory(tmp_path: Path):
    transform, abaqus = write(tmp_path)
    records = build(transform, abaqus, None)
    summary = summarise(records)
    assert sum(summary["by_terminal_state"].values()) == summary["acquired"]
    assert (summary["by_kind"].get("verified", 0)
            + summary["external_total"] + summary["internal_total"]
            == summary["acquired"])


def test_the_report_never_pools_ours_with_theirs(tmp_path: Path):
    transform, abaqus = write(tmp_path)
    records = build(transform, abaqus, None)
    text = markdown(records, summarise(records))
    assert "blocked outside this repository" in text
    assert "work remaining here" in text
    assert "limitation of this pipeline, not of the corpus" in text


def test_the_two_vocabularies_are_disjoint_and_complete():
    assert not set(EXTERNAL) & set(INTERNAL)
    assert FULLY_VERIFIED not in set(EXTERNAL) | set(INTERNAL)


# ---------------------------------------------------------------------------
# and the older report's map has to keep up with the ladder
# ---------------------------------------------------------------------------
def test_every_rung_the_batch_can_record_has_a_place_in_the_report():
    """A stage with no entry falls through to 'blocked with evidence', which
    would report a source that ran both builds and agreed over its whole
    history as blocked -- true of nothing about it."""
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools"))
    from corpus_report import FROM_ABAQUS_STAGE
    from umat_oti.abaqus.terminal_states import FROM_STAGE

    unmapped = sorted(set(FROM_STAGE) - set(FROM_ABAQUS_STAGE) - {"verified"})
    assert not unmapped, unmapped


def test_the_two_reports_agree_about_what_verified_means():
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools"))
    from corpus_report import FROM_ABAQUS_STAGE
    from umat_oti.abaqus.terminal_states import FROM_STAGE

    assert FROM_ABAQUS_STAGE["verified"] == "fully_verified"
    assert FROM_STAGE["verified"] == FULLY_VERIFIED


# ---------------------------------------------------------------------------
# a file the transform refused is not automatically the transform's fault
# ---------------------------------------------------------------------------
def test_a_refused_uel_is_not_a_umat_rather_than_a_gap_in_the_transformer():
    """Three UEL sources began failing a semantic check when the constancy
    analysis stopped inferring dummy arguments constant. Counting them as a
    gap in the transformer puts an external fact about somebody's file into
    this pipeline's column. The direction of that error is the safe one --
    it overstates our own failures, not the corpus's completeness -- but it
    is still wrong, and it costs a cluster that cannot be fixed because
    there is nothing wrong with it."""
    from umat_oti.abaqus.terminal_states import from_transform_failure

    verdict = from_transform_failure("Semantic check failed", is_umat=False)
    assert verdict.state == "not_a_umat"
    assert verdict.kind == "external"


def test_a_refused_umat_is_still_ours():
    from umat_oti.abaqus.terminal_states import from_transform_failure

    verdict = from_transform_failure("Semantic check failed", is_umat=True)
    assert verdict.state == "transform_refused"
    assert verdict.kind == "internal"


def test_not_knowing_what_it_is_keeps_the_old_answer():
    from umat_oti.abaqus.terminal_states import from_transform_failure

    assert from_transform_failure("x").state == "transform_refused"
    assert from_transform_failure("x", compiles=False).state == \
        "incomplete_or_corrupt_source"


def test_the_registry_asks_what_the_file_is_before_blaming_the_transform():
    """The terminal state of a refused source is derived from what the file
    is -- ``record.refusal_class``, which classify_refusal read out of the
    file -- and the refusal text is passed only as the reason. Grepped rather
    than run because the wiring is what has to hold: the day somebody hands
    the refusal itself to the classifier, every UEL in the corpus turns into a
    gap in the transformer and the count stops meaning anything."""
    import pathlib
    text = pathlib.Path(__file__).resolve().parents[1].joinpath(
        "tools", "build_corpus_registry.py").read_text()
    assert 'is_umat=(record.is_umat if record.refusal_class' in text
    assert 'companions_missing=(record.refusal_class ==' in text
    assert 'if record.refusal_class == "incomplete_or_corrupt_source":' in text


# ---------------------------------------------------------------------------
# the denominator is the acquisition inventory, not the batch that ran
# ---------------------------------------------------------------------------
import csv  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
INVENTORY = REPO / "paper_results/discovery/discovery_triage.csv"
REGISTRY = REPO / "paper_results/corpus/corpus_registry.json"


def _inventory_ids():
    with INVENTORY.open(newline="", encoding="utf-8") as handle:
        return [str(row.get("source") or "").strip()
                for row in csv.DictReader(handle)
                if str(row.get("source") or "").strip()]


def test_the_registry_holds_every_one_of_the_391_discovered_sources():
    """Measured on the built registry: the acquisition triage lists 391
    discovered sources, ``corpus_registry.json`` carries 391 records, and the
    two sets are equal -- no source in the inventory is missing a record, and
    no record names a source the inventory never discovered.

    391 is also what the transform batch happens to carry, which is exactly
    why this has to be checked against the INVENTORY. A registry built from
    the batch agrees with the batch by construction, and would go on agreeing
    on the day a run stopped attempting a source."""
    discovered = _inventory_ids()
    assert len(discovered) == 391, len(discovered)

    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    records = payload["records"]
    assert len(records) == 391, len(records)

    ids = [r["source_id"] for r in records]
    assert len(set(ids)) == 391, "a source appears twice"
    assert set(ids) == set(discovered), {
        "in the inventory, no record": sorted(set(discovered) - set(ids))[:5],
        "a record, not in the inventory": sorted(set(ids) - set(discovered))[:5],
    }

    reconciliation = payload["summary"]["inventory"]
    assert reconciliation["discovered_sources"] == 391
    assert reconciliation["in_the_registry"] == 391
    assert reconciliation["in_a_batch_but_not_the_inventory"] == []
    assert reconciliation["in_the_inventory_but_in_no_batch"] == []


def test_a_discovered_source_no_batch_ever_mentioned_still_gets_a_record(tmp_path):
    """The registry is seeded from the inventory and the batches are joined
    onto it. Built the other way round -- which is how it was built -- a
    source that no transform row and no Abaqus row names produces no record at
    all, and the denominator shrinks where nobody can see it happen."""
    transform, abaqus = write(tmp_path)
    inventory = [r["source"] for r in TRANSFORM["rows"]] + ["owner__e/never.f"]

    records = {r.source_id: r for r in
               build(transform, abaqus, None, inventory_ids=inventory)}
    assert len(records) == 5
    assert "owner__e/never.f" in records, (
        "a source no batch mentioned vanished from the denominator")
    assert records["owner__e/never.f"].terminal_state == "not_attempted"
    assert records["owner__e/never.f"].kind == "internal"


def test_a_row_the_inventory_never_listed_is_kept_and_named(tmp_path):
    """Two artefacts that describe the same corpus disagreeing is itself a
    finding. A batch row with no inventory entry is kept as a record rather
    than dropped, so the disagreement shows up instead of being tidied away."""
    transform, abaqus = write(tmp_path)
    records = {r.source_id for r in
               build(transform, abaqus, None,
                     inventory_ids=["owner__a/umat.for"])}
    assert "owner__c/notaumat.f" in records
    assert len(records) == 4


# ---------------------------------------------------------------------------
# a word a row's own evidence does not support
# ---------------------------------------------------------------------------
def _stage_of(row):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools"))
    from build_corpus_registry import _stage_the_gates_support
    return _stage_the_gates_support(row)


SIX = ("abaqus_job_completed", "all_requested_outputs_present",
       "complete_history_finite", "primal_agreed", "derivatives_verified",
       "mechanically_informative")


def test_a_row_saying_verified_on_six_true_gates_keeps_the_word():
    assert _stage_of({"stage": "verified",
                      "evidence": {g: True for g in SIX}}) == "verified"


def test_an_explained_primal_mismatch_is_not_verified():
    """The thirteen. A control measured WHY the two builds differ, the harness
    read the explanation as agreement and set the gate true, and the entries
    were counted as verified, promoted into the frozen baseline and offered to
    the Residual Assembler as verified materials. An explanation for a
    disagreement is not agreement."""
    evidence = {g: True for g in SIX}
    evidence["primal_agreed"] = False
    evidence["primal_difference_explained_by_a_measured_control"] = True
    assert _stage_of({"stage": "verified", "evidence": evidence}) == \
        "primal_mismatch_explained"


def test_an_unexplained_primal_mismatch_is_a_plain_disagreement():
    evidence = {g: True for g in SIX}
    evidence["primal_agreed"] = False
    assert _stage_of({"stage": "verified", "evidence": evidence}) == \
        "primal_disagreed"


def test_a_row_with_no_evidence_block_is_left_alone():
    """An absence does not CONTRADICT the stage, and demoting on one would
    rewrite every row written before the gates existed. Currency is what
    catches those, not this."""
    assert _stage_of({"stage": "verified"}) == "verified"
    assert _stage_of({"stage": "verified", "evidence": {}}) == "verified"


def test_the_explained_mismatch_is_internal_and_unfinished():
    from umat_oti.abaqus.terminal_states import from_stage
    verdict = from_stage("primal_mismatch_explained")
    assert verdict.kind == "internal"
    assert verdict.finished is False
