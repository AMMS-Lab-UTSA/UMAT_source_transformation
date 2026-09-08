"""An exit code is a claim, and a gate has to earn it.

`verify_store_in_abaqus.py` used to `return 0` unconditionally -- after
printing a summary in which most entries had failed. Anything reading that
exit code, a CI job or a promotion step, was told the run had passed.

The split is: `inventory` surveys and always exits 0, because every stage in
it including a failure is an answer to the question it asks; `regression` and
`qualification` are gates and must fail when a required check fails, is
blocked, or is absent. Missing Abaqus is not a pass, and an entry that
silently stopped being attempted is exactly what a regression exists to catch.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from verify_store_in_abaqus import (exit_verdict,  # noqa: E402
                                    required_entries)


def _row(source, stage):
    return {"source": source, "stage": stage}


OK = [_row("a.for", "verified"), _row("b.for", "verified")]
MIXED = [_row("a.for", "verified"), _row("b.for", "primal_disagreed")]


# ---- inventory ----------------------------------------------------------
def test_inventory_always_exits_zero_and_says_so():
    assert exit_verdict("inventory", MIXED, set()).code == 0
    assert "not a verdict" in " ".join(exit_verdict("inventory", MIXED, set()).lines)


def test_inventory_over_nothing_is_still_zero():
    assert exit_verdict("inventory", [], set()).code == 0


# ---- regression fails on what matters ------------------------------------
def test_a_required_entry_that_failed_fails_the_run():
    verdict = exit_verdict("regression", MIXED, {"b.for"})
    assert verdict.code == 1
    assert any("FAIL primal_disagreed: b.for" in line for line in verdict.lines)


def test_a_required_entry_missing_from_the_run_fails_it():
    """An entry that stopped being attempted leaves no failing row to notice,
    which is exactly why it has to be checked for by name."""
    verdict = exit_verdict("regression", OK, {"a.for", "gone.for"})
    assert verdict.code == 1
    assert any("missing: gone.for" in line for line in verdict.lines)


def test_an_empty_selection_fails_a_gate():
    """A filter that matches nothing produces a clean run that proves
    nothing, and used to exit 0."""
    verdict = exit_verdict("regression", [], {"a.for"})
    assert verdict.code == 2 and "proves nothing" in " ".join(verdict.lines)


def test_a_blocked_entry_is_a_failure_not_an_exemption():
    """Missing Abaqus, a refused manifest, an unbuildable support library --
    none of them may become a pass."""
    for blocked in ("needs_material_data", "manifest_refused",
                    "support_build_failed", "original_job_failed",
                    "waits_for_input"):
        verdict = exit_verdict("regression", [_row("a.for", blocked)], {"a.for"})
        assert verdict.code == 1, blocked


def test_all_required_verified_passes():
    assert exit_verdict("regression", OK, {"a.for", "b.for"}).code == 0


def test_a_regression_with_no_required_set_says_what_it_cannot_tell():
    verdict = exit_verdict("regression", MIXED, set())
    assert "WARNING" in " ".join(verdict.lines)
    assert "stopped being attempted" in " ".join(verdict.lines)


# ---- qualification requires everything it attempted ----------------------
def test_qualification_requires_every_attempted_entry():
    assert exit_verdict("qualification", MIXED, set()).code == 1
    assert exit_verdict("qualification", OK, set()).code == 0


# ---- where the required set comes from -----------------------------------
class _Args:
    def __init__(self, require="", baseline=None):
        self.require, self.baseline = require, baseline


def test_require_names_entries_directly():
    assert required_entries(_Args(require="a.for, b.for"), []) == {"a.for", "b.for"}


def test_a_baseline_supplies_the_entries_that_verified(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"entries": [
        _row("a.for", "verified"), _row("b.for", "primal_disagreed")]}))
    assert required_entries(_Args(baseline=path), []) == {"a.for"}


def test_require_wins_over_a_baseline(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"entries": [_row("a.for", "verified")]}))
    assert required_entries(_Args(require="z.for", baseline=path), []) == {"z.for"}


def test_an_unreadable_baseline_stops_the_run(tmp_path):
    """Silently continuing with an empty required set would turn a promotion
    gate into a no-op that exits 0."""
    import pytest
    with pytest.raises(SystemExit):
        required_entries(_Args(baseline=tmp_path / "absent.json"), [])
