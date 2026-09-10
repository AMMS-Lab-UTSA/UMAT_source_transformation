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
