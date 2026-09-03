"""The evidence file must not let three different claims read as one.

An entry that compiled, an entry that agreed at one material point offline, and
an entry verified in Abaqus are three different statements, and the weakest of
them is the easiest to quote. These hold the recorder to reporting each under
its own name, keeping every count out of the whole selection, and carrying the
caveats that stop an agreement rate being read as more than it is.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from record_batch_evidence import (                          # noqa: E402
    abaqus_summary, build, gate_summary, transform_summary)


def test_a_transform_is_not_reported_as_a_verification():
    """Compiling proves the output is Fortran and nothing else."""
    block = transform_summary({"summary": {"transformed_now": 199, "failed": 0}})
    assert "Compiling is not verification" in block["note"]
    assert "verified" not in {k.lower() for k in block}


def test_cached_work_is_kept_apart_from_work_that_was_done():
    """Pooling them turns "we did not re-check these" into "these passed"."""
    block = transform_summary({"summary": {
        "transformed_now": 12, "reused_from_store": 187, "failed": 0}})
    assert block["transformed_now"] == 12
    assert block["already_in_the_store"] == 187


def test_the_gate_says_what_it_is_not():
    block = gate_summary({"summary": {"entries": 199, "agreed": 84}})
    assert "not Abaqus verification" in block["what_this_is"]


def test_only_the_last_rung_counts_as_verified():
    rows = [{"stage": "verified", "source": "a/u.for"},
            {"stage": "tangent_not_verified", "source": "b/u.for"},
            {"stage": "primal_disagreed", "source": "c/u.for"},
            {"stage": "needs_material_data", "source": "d/u.for"}]
    block = abaqus_summary(rows)
    assert block["verified"] == 1
    assert block["verified_sources"] == ["a/u.for"]
    assert block["attempted"] == 4


def test_every_attempted_entry_stays_in_the_denominator():
    """An agreement rate over the rows that happened to work says nothing."""
    rows = [{"stage": "verified"}, {"stage": "needs_material_data"},
            {"stage": "harness_error"}, {"stage": "support_build_failed"}]
    block = abaqus_summary(rows)
    assert block["attempted"] == 4
    assert sum(block["by_stage"].values()) == 4


def test_a_row_with_no_stage_is_counted_not_dropped():
    block = abaqus_summary([{"stage": "verified"}, {}])
    assert block["attempted"] == 2
    assert sum(block["by_stage"].values()) == 2


def test_a_harness_error_is_named_as_a_statement_about_the_run():
    block = abaqus_summary([{"stage": "harness_error"}])
    assert "not about the model" in block["note"]


def test_the_deck_sharing_caveat_travels_with_the_result():
    """144 of 158 paired sources share a deck; the rate must not read as
    "verified against the author's own material"."""
    record = build(None, None, [{"stage": "verified"}])
    joined = " ".join(record["caveats"])
    assert "share their deck" in joined
    assert "proposed_needs_review" in joined


def test_the_licence_caveat_about_the_exit_code_is_stated():
    record = build(None, None, [])
    assert any("exit code" in caveat for caveat in record["caveats"])


def test_a_missing_report_is_reported_as_missing_not_as_zero():
    """Converting an absent stage to zero would flatter every total."""
    record = build(None, None, [])
    assert record["transform"] == {"available": False}
    assert record["abaqus"] == {"available": False}


def test_the_record_is_serialisable_without_non_finite_values():
    record = build({"summary": {"transformed_now": 1}}, {"summary": {}},
                   [{"stage": "verified"}])
    json.dumps(record, allow_nan=False)


def test_the_reproduction_commands_are_named():
    record = build(None, None, [])
    assert any("batch-transform" in line for line in record["reproduce"])
    assert any("batch-abaqus" in line for line in record["reproduce"])
