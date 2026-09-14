"""The six gates stay six, stay three-state, and the seventh stays beside them.

Three rules, each with a cost behind it:

*Six, never one.* A single "verified" boolean cannot say which of six things
was established, and a reader shown one cannot check it.

*Three-state, with no truthiness shortcut.* A missing key and a null key are
BOTH not-established, and they are kept apart underneath because "this batch's
schema never asked" and "the run asked and could not answer" are different
facts. Merging them published 7 where the answer was 11.

*The seventh is not one of the six.* ``primal_agreed`` false beside
``stage: verified`` is a chain, not a contradiction: a control ran and measured
something. The raw comparison flag never moves.

The numbers here are executed against the real pass11 file where it is present:
237 records, 55 at stage verified, 42 true on all six.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from umat_oti.services.gates import (  # noqa: E402
    FALSE, GATES, NOT_ESTABLISHED, RAW_ABSENT, RAW_NO_BLOCK, RAW_NULL, SEVENTH,
    TRUE, CensusDoesNotSum, census, read_gate, read_gates, read_seventh,
)

pytestmark = pytest.mark.unit

#: The real verification run. Derived from the checkout rather than written
#: out, so this file carries no absolute path into somebody else's home.
#: ``UMAT_OTI_CORPUS_RUN`` overrides it; every test using it skips when absent.
PASS11 = Path(os.environ.get(
    "UMAT_OTI_CORPUS_RUN",
    str(Path(__file__).resolve().parents[1].parent / "corpus_run" / "pass11"
        / "results" / "store_verification.jsonl")))
ALL_TRUE = {gate: True for gate in GATES}


def _records():
    if not PASS11.is_file():
        pytest.skip(f"{PASS11} is not on this machine")
    return [json.loads(line) for line in
            PASS11.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_there_are_six_gates_and_they_are_named():
    assert len(GATES) == 6
    assert GATES == (
        "abaqus_job_completed",
        "all_requested_outputs_present",
        "complete_history_finite",
        "primal_agreed",
        "derivatives_verified",
        "mechanically_informative",
    )
    assert SEVENTH not in GATES, "the seventh is carried beside the six"


def test_a_missing_key_and_a_null_key_are_both_not_established():
    missing = read_gate({"primal_agreed": True}, "derivatives_verified")
    null = read_gate({"derivatives_verified": None}, "derivatives_verified")
    no_block = read_gate(None, "derivatives_verified")

    for reading in (missing, null, no_block):
        assert reading.reading == NOT_ESTABLISHED
        assert reading.established is False
        assert reading.held is False, "not established is never a pass"

    # And the three are kept apart underneath.
    assert missing.raw == RAW_ABSENT
    assert null.raw == RAW_NULL
    assert no_block.raw == RAW_NO_BLOCK
    assert len({missing.raw, null.raw, no_block.raw}) == 3
    assert missing.why != null.why != no_block.why


def test_there_is_no_truthiness_shortcut():
    """Only ``True`` is true and only ``False`` is false. Everything else is
    a measurement nobody made, whatever Python thinks of its truth value."""
    for value in (0, 1, "", "no", [], {}, 0.0, "false"):
        reading = read_gate({"primal_agreed": value}, "primal_agreed")
        assert reading.reading == NOT_ESTABLISHED, value
        assert reading.raw == RAW_NULL, value
    assert read_gate({"primal_agreed": True}, "primal_agreed").reading == TRUE
    assert read_gate({"primal_agreed": False}, "primal_agreed").reading == FALSE


def test_unknown_is_never_verified():
    """Five gates true and one never measured may not be called verified."""
    evidence = dict(ALL_TRUE)
    evidence["mechanically_informative"] = None
    gates = read_gates({"evidence": evidence, "stage": "verified"})
    assert gates.all_six_hold is False
    claim = gates.what_may_be_claimed()
    assert claim["may_be_called_verified"] is False
    assert claim["gates_never_established"] == ["mechanically_informative"]
    assert len(claim["gates_that_hold"]) == 5


def test_a_census_that_does_not_sum_refuses_to_be_published(monkeypatch):
    """The guard that was missing when 7 was published and 11 was the answer.

    A reading the counter does not know about falls out of the total rather
    than into a neighbouring bucket, so the arithmetic check fires and the
    census refuses instead of returning a number that is quietly short.
    """
    from umat_oti.services import gates as gates_module

    rows = [{"evidence": dict(ALL_TRUE)} for _ in range(3)]

    good = census(rows, "primal_agreed")
    assert good["sums_to"] == good["denominator"] == 3
    assert good["true"] == 3
    assert good["a_missing_key_and_a_null_key_are_both"] == NOT_ESTABLISHED

    monkeypatch.setattr(gates_module, "_raw_state",
                        lambda evidence, gate: "a_state_nobody_declared")
    with pytest.raises(CensusDoesNotSum) as raised:
        census(rows, "primal_agreed")
    assert "does not sum" in str(raised.value) or "adds to 0" in str(raised.value)
    assert "a_state_nobody_declared" in str(raised.value)


def test_the_census_separates_null_from_absent_from_no_block():
    rows = [
        {"evidence": {"primal_agreed": True}},
        {"evidence": {"primal_agreed": False}},
        {"evidence": {"primal_agreed": None}},
        {"evidence": {"derivatives_verified": True}},   # key absent
        {},                                              # no evidence block
    ]
    tally = census(rows, "primal_agreed")
    assert tally["true"] == 1
    assert tally["false"] == 1
    assert tally["not_established_present_but_null"] == 1
    assert tally["not_established_key_absent"] == 1
    assert tally["not_established_no_evidence_block"] == 1
    assert tally["not_established_total"] == 3
    assert tally["sums_to"] == 5 == tally["denominator"]


def test_the_seventh_is_three_valued_and_null_means_no_control_was_needed():
    explained = read_seventh({"evidence": {**ALL_TRUE,
                                           "primal_agreed": False,
                                           SEVENTH: True}})
    assert explained.reading == TRUE

    refuted = read_seventh({"evidence": {**ALL_TRUE,
                                         "primal_agreed": False,
                                         SEVENTH: False}})
    assert refuted.reading == FALSE
    assert refuted.reading != NOT_ESTABLISHED, (
        "measured-and-refuted is not the same answer as not-measured")

    agreed = read_seventh({"evidence": dict(ALL_TRUE)})
    assert agreed.reading == NOT_ESTABLISHED
    assert "no control was needed" in agreed.why


def test_the_raw_primal_flag_never_moves_when_the_seventh_explains_it():
    record = {"evidence": {**ALL_TRUE, "primal_agreed": False},
              "primal": {"explained_by_operation_order": True},
              "association_control": {"ran": True, "measured": True},
              "stage": "verified"}
    gates = read_gates(record)
    assert gates["primal_agreed"].reading == FALSE, (
        "an explanation is a second fact, never an edit to the first")
    assert gates.seventh.reading == TRUE
    assert gates.all_six_hold is False
    assert "conditioning" in gates.seventh.why


@pytest.mark.integration
def test_the_real_pass11_file_reads_237_55_and_42():
    """The figures in the record, reproduced by this module rather than quoted."""
    records = _records()
    assert len(records) == 237

    at_stage_verified = sum(1 for r in records if r.get("stage") == "verified")
    true_on_all_six = sum(1 for r in records if read_gates(r).all_six_hold)
    assert at_stage_verified == 55
    assert true_on_all_six == 42
    assert at_stage_verified != true_on_all_six, (
        "these are different counts and must never be reported as one number")

    # The thirteen in between, which are the seventh field's whole reason.
    both = [r for r in records
            if r.get("stage") == "verified" and not read_gates(r).all_six_hold]
    assert len(both) == 13
    for record in both:
        gates = read_gates(record)
        assert gates["primal_agreed"].reading == FALSE
        assert gates.seventh.reading == TRUE, (
            "a gate reading false beside a verdict has to say why")


@pytest.mark.integration
def test_every_gate_census_over_pass11_sums_to_237():
    records = _records()
    for gate in GATES:
        tally = census(records, gate)
        assert tally["sums_to"] == 237, gate
        assert tally["denominator"] == 237, gate
    # The one gate with a present-but-null reading in this pass.
    informative = census(records, "mechanically_informative")
    assert informative["not_established_present_but_null"] == 6
    assert informative["not_established_key_absent"] == 0
    assert informative["not_established_no_evidence_block"] == 93
    assert informative["not_established_total"] == 99
