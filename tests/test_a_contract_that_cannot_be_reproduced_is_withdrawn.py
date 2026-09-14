"""A frozen contract measured against a transform that no longer exists.

The collection held 67 materials, every one of them promoted under transform
fingerprint ``e4257779bd847cc4``. The current fingerprint is
``b0d27ee53c630500``, and the tangent numbers in those contracts were measured
against generated Fortran this repository no longer produces. 38 of the 67 are
still verified at the current fingerprint; 29 are not.

Leaving the 29 standing is the failure this guards. A frozen contract is a
claim that a regression may be compared against, and one that cannot be
reproduced is not a claim -- it is a number that will be agreed with or
disagreed with for reasons that have nothing to do with the code under test.

The record of what was claimed has to survive the claim, so the directory goes
and the reason stays: the fingerprint it was frozen at, the fingerprint that
replaced it, and the rung it reaches now.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from promote_verified_umats import (main, material_id,  # noqa: E402
                                    standing_materials, withdrawals)

pytestmark = pytest.mark.unit

OLD, NEW = "e4257779bd847cc4", "b0d27ee53c630500"

GATES = {"abaqus_job_completed": True, "all_requested_outputs_present": True,
         "complete_history_finite": True, "derivatives_verified": True,
         "primal_agreed": True, "mechanically_informative": True}


def _row(source, stage="verified", fingerprint=NEW, reason=""):
    return {
        "source": source, "key": source.replace("/", "_"), "stage": stage,
        "fingerprint": fingerprint, "reason": reason,
        "source_sha256": "0" * 64, "repository": source.split("/")[0],
        "evidence": dict(GATES), "complete_finite_verification_run": True,
        "history_grouping": {"original": {}, "transformed": {}},
        "element_type": "C3D8", "ntens": 6, "nstatv": 1, "props_count": 2,
        "kinematics": "small strain", "deck": "d.inp",
        "tangent": {"states_checked": 3, "states_agreeing": 3,
                    "comparison": {"best_relative": 1e-13}},
        "primal": {"worst_stress_relative": 0.0, "worst_state_relative": 0.0},
    }


def _collection(tmp_path, materials):
    """A collection standing at the OLD fingerprint, as the frozen one was."""
    root = tmp_path / "umat"
    root.mkdir()
    entries = []
    for source in materials:
        identifier = material_id(source)
        (root / identifier).mkdir()
        (root / identifier / "contract.json").write_text("{}")
        entries.append({"id": identifier, "source_id": source,
                        "repository": source.split("/")[0],
                        "transform_fingerprint": OLD,
                        "worst_tangent_relative": 5.0e-13,
                        "worst_stress_relative": 0.0,
                        "states_checked": 3, "states_agreeing": 3})
    (root / "registry.json").write_text(json.dumps(
        {"count": len(entries), "materials": entries}))
    return root


def _promote(root, tmp_path, rows, extra=()):
    results = tmp_path / "store_verification.jsonl"
    results.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return main(["--results", str(results), "--work-dir", str(tmp_path / "w"),
                 "--cache-dir", str(tmp_path / "c"), "--root", str(root),
                 *extra])


KEPT = "owner__a/kept.for"
GONE = "owner__b/gone.for"


def test_a_contract_the_run_no_longer_reproduces_is_taken_down(tmp_path):
    root = _collection(tmp_path, [KEPT, GONE])
    assert _promote(root, tmp_path, [
        _row(KEPT), _row(GONE, stage="primal_disagreed",
                         reason="worst stress difference 5.8e-03")]) == 0
    assert (root / material_id(KEPT)).is_dir()
    assert not (root / material_id(GONE)).exists()


def test_the_reason_survives_the_contract(tmp_path):
    root = _collection(tmp_path, [KEPT, GONE])
    _promote(root, tmp_path, [
        _row(KEPT), _row(GONE, stage="primal_disagreed",
                         reason="worst stress difference 5.8e-03")])
    taken, = json.loads((root / "withdrawn.json").read_text())["contracts"]
    assert taken["id"] == material_id(GONE)
    assert taken["source_id"] == GONE
    assert taken["frozen_at_fingerprint"] == OLD
    assert taken["withdrawn_at_fingerprint"] == NEW
    assert taken["reaches_now"] == "primal_disagreed"
    assert "5.8e-03" in taken["reason"]
    # The numbers that used to be evidence, kept as a record of the claim.
    assert taken["recorded_numbers_that_are_no_longer_evidence"][
        "worst_tangent_relative"] == 5.0e-13


def test_a_contract_the_run_never_reached_says_so_rather_than_inventing_one(
        tmp_path):
    """A source the pass never attempted is not a source the pass refused. It
    is still withdrawn -- nothing at the current fingerprint reproduces it --
    but the reason may not read as a verdict against the material."""
    root = _collection(tmp_path, [KEPT, GONE])
    _promote(root, tmp_path, [_row(KEPT)])
    taken, = json.loads((root / "withdrawn.json").read_text())["contracts"]
    assert taken["reaches_now"] == "not attempted in this run"
    assert "no evidence in this run speaks against the material" in \
        taken["reason"]


def test_everything_left_standing_carries_the_current_fingerprint(tmp_path):
    root = _collection(tmp_path, [KEPT, GONE])
    _promote(root, tmp_path, [_row(KEPT), _row(GONE, stage="tangent_not_verified")])
    registry = json.loads((root / "registry.json").read_text())
    assert registry["transform_fingerprint"] == NEW
    assert {m["transform_fingerprint"] for m in registry["materials"]} == {NEW}


def test_the_regression_baseline_is_the_promoted_set(tmp_path):
    """A baseline naming materials the collection no longer holds is a gate
    that can never pass."""
    root = _collection(tmp_path, [KEPT, GONE])
    _promote(root, tmp_path, [_row(KEPT), _row(GONE, stage="original_job_failed")])
    baseline = json.loads((root / "baseline.json").read_text())
    registry = json.loads((root / "registry.json").read_text())
    assert {e["id"] for e in baseline["entries"]} == \
        {m["id"] for m in registry["materials"]}
    assert baseline["transform_fingerprint"] == NEW


def test_a_partial_run_withdraws_nothing(tmp_path):
    """--limit looks at part of the corpus. Withdrawing on that evidence would
    take down contracts the run never considered."""
    root = _collection(tmp_path, [KEPT, GONE])
    _promote(root, tmp_path, [_row(KEPT), _row(GONE)], extra=["--limit", "1"])
    assert (root / material_id(GONE)).is_dir()
    assert not (root / "withdrawn.json").exists()


def test_a_partial_run_does_not_rewrite_the_gate_it_is_measured_by(tmp_path):
    root = _collection(tmp_path, [KEPT, GONE])
    (root / "baseline.json").write_text('{"entries": [{"id": "untouched"}]}')
    _promote(root, tmp_path, [_row(KEPT), _row(GONE)], extra=["--limit", "1"])
    assert json.loads((root / "baseline.json").read_text())[
        "entries"] == [{"id": "untouched"}]


def test_withdrawals_accumulate_across_promotions(tmp_path):
    """The account of what a collection used to claim is the one thing a
    reader comparing an old paper against it has to be able to find. A second
    promotion that took nothing down used to rewrite the file as though
    nothing had ever been withdrawn."""
    root = _collection(tmp_path, [KEPT, GONE])
    _promote(root, tmp_path, [_row(KEPT), _row(GONE, stage="primal_disagreed")])
    _promote(root, tmp_path, [_row(KEPT)])
    contracts = json.loads((root / "withdrawn.json").read_text())["contracts"]
    assert [c["id"] for c in contracts] == [material_id(GONE)]


def test_a_material_promoted_again_leaves_the_withdrawal_record(tmp_path):
    """It stands once more, so it is not a withdrawn contract."""
    root = _collection(tmp_path, [KEPT, GONE])
    _promote(root, tmp_path, [_row(KEPT), _row(GONE, stage="primal_disagreed")])
    _promote(root, tmp_path, [_row(KEPT), _row(GONE)])
    assert json.loads((root / "withdrawn.json").read_text())["contracts"] == []
    assert (root / material_id(GONE)).is_dir()


def test_a_directory_the_registry_lost_track_of_is_still_seen(tmp_path):
    """A contract standing with nothing on disk saying which run froze it."""
    root = _collection(tmp_path, [KEPT])
    (root / "orphan--material--00000000").mkdir()
    standing = standing_materials(root)
    assert "orphan--material--00000000" in standing
    assert "not in registry.json" in \
        standing["orphan--material--00000000"]["orphaned"]
    taken = withdrawals(root, standing, {material_id(KEPT)}, [_row(KEPT)],
                        NEW, apply=False)
    assert [entry["id"] for entry in taken] == ["orphan--material--00000000"]
