"""Every acquired entry appears once, and the counts are the inventory.

A file that was acquired and then quietly stopped being attempted leaves no
failing row to notice. A summary built from the rows a batch happened to
produce would never show it, and the total would look complete while being
short. So the inventory is the denominator and the statuses partition it: if
they do not add up, the report says so and, in strict mode, fails.

The status model is non-overlapping and only `fully_verified` counts.
Compiling is not working; running is not verified.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from corpus_report import (BLOCKED, FROM_ABAQUS_STAGE, NOT_A_UMAT,  # noqa: E402
                           STATUSES, build, counts, reconcile)


def _transform(tmp_path, rows, failures=()):
    path = tmp_path / "transform.json"
    path.write_text(json.dumps({"rows": list(rows), "failures": list(failures)}))
    return path


def _abaqus(tmp_path, rows):
    path = tmp_path / "abaqus.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return path


# ---- the statuses partition the inventory -------------------------------
def test_every_acquired_entry_appears_exactly_once(tmp_path):
    transform = _transform(tmp_path, [
        {"source": "a/x.for", "outcome": "transformed"},
        {"source": "b/y.for", "outcome": "transformed"}],
        failures=[{"source": "c/z.for", "reason": "did not transform"}])
    entries, _ = build(transform, None, None)
    assert [e.source_id for e in entries] == ["a/x.for", "b/y.for", "c/z.for"]


def test_the_counts_add_up_to_the_inventory(tmp_path):
    transform = _transform(tmp_path, [{"source": f"r/{i}.for",
                                       "outcome": "transformed"}
                                      for i in range(5)])
    entries, _ = build(transform, None, None)
    assert sum(counts(entries).values()) == len(entries)
    assert reconcile(entries, counts(entries)) == []


def test_a_short_tally_is_reported_rather_than_printed_as_a_total(tmp_path):
    transform = _transform(tmp_path, [{"source": "a/x.for", "outcome": "transformed"}])
    entries, _ = build(transform, None, None)
    problems = reconcile(entries, {"fully_verified": 0})
    assert problems and "unaccounted for" in problems[0]


# ---- only fully_verified counts ------------------------------------------
def test_only_the_last_stage_maps_to_fully_verified():
    verified = [stage for stage, status in FROM_ABAQUS_STAGE.items()
                if status == "fully_verified"]
    assert verified == ["verified"]


def test_running_is_not_verified():
    """A job that ran and then disagreed is not a partial pass."""
    assert FROM_ABAQUS_STAGE["primal_disagreed"] == "abaqus_transformed_passed"
    assert FROM_ABAQUS_STAGE["tangent_not_verified"] == "primal_parity_passed"


def test_not_a_umat_and_blocked_are_not_rungs():
    assert NOT_A_UMAT not in STATUSES and BLOCKED not in STATUSES


def test_fully_verified_is_the_last_rung():
    assert STATUSES[-1] == "fully_verified"


# ---- the collection and the report cannot disagree -----------------------
def test_a_promoted_entry_that_is_not_fully_verified_is_a_problem(tmp_path):
    transform = _transform(tmp_path, [{"source": "a/x.for", "outcome": "transformed"}])
    abaqus = _abaqus(tmp_path, [{"source": "a/x.for", "stage": "primal_disagreed"}])
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"materials": [
        {"source_id": "a/x.for", "id": "a-x"}]}))
    _entries, problems = build(transform, abaqus, registry)
    assert any("not fully_verified" in p for p in problems)


def test_a_fully_verified_entry_that_was_not_promoted_is_a_problem(tmp_path):
    """Evidence sitting outside the collection is how a result gets lost."""
    transform = _transform(tmp_path, [{"source": "a/x.for", "outcome": "transformed"}])
    abaqus = _abaqus(tmp_path, [{"source": "a/x.for", "stage": "verified"}])
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"materials": []}))
    _entries, problems = build(transform, abaqus, registry)
    assert any("was not promoted" in p for p in problems)


def test_a_promoted_entry_missing_from_the_inventory_is_a_problem(tmp_path):
    transform = _transform(tmp_path, [{"source": "a/x.for", "outcome": "transformed"}])
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"materials": [
        {"source_id": "gone/y.for", "id": "gone-y"}]}))
    _entries, problems = build(transform, None, registry)
    assert any("not in the corpus inventory" in p for p in problems)


# ---- an entry that never reached Abaqus is still classified --------------
def test_an_entry_that_never_reached_abaqus_keeps_its_place(tmp_path):
    """It stays in the inventory at the furthest state it got to, rather
    than vanishing because no Abaqus row mentions it."""
    transform = _transform(tmp_path, [{"source": "a/x.for", "outcome": "transformed"}],
                           failures=[{"source": "b/y.for", "reason": "blocked"}])
    abaqus = _abaqus(tmp_path, [{"source": "a/x.for", "stage": "verified"}])
    entries, _ = build(transform, abaqus, None)
    by_id = {e.source_id: e for e in entries}
    assert by_id["a/x.for"].status == "fully_verified"
    assert by_id["b/y.for"].status == "acquired"
    assert by_id["b/y.for"].reason == "blocked"
