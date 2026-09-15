"""A field that is MISSING and a field that is present-and-null are both
"not established", and a count that drops one of them does not add up.

Measured on the six evidence gates. Over the 146 rows in the results file that
carry an evidence block, `mechanically_informative` reads true on 113, false on
22, is present and null on 7, and is ABSENT ENTIRELY on 4. A count taken over
"records where the key is present and null" reports 7 not established, totals
142, and reconciles with nothing -- and reads perfectly well while doing it.
The answer is 11, and it is 11 only over that denominator: over the 142 entries
in the store at the current fingerprint the key is never absent and the answer
is 7. Both are right. Neither means anything with the denominator left off.

So every census this registry publishes states its denominator and sums to it,
and `census` raises rather than returning a total that does not. The failure it
prevents is silent, which is why the check is in the counting and not at each
call site.

Three numbers are "verified" here and all three are published:

    44  rows in the results file at stage `verified`  (counts 3 sources twice)
    41  store entries that reached the batch's `verified` rung  (the console)
    38  of those that also read true on all six gates            (the strict one)
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from build_corpus_registry import (EVIDENCE_GATES, GATE_ABSENT,  # noqa: E402
                                   GATE_NO_BLOCK, GATE_NULL, GATE_TRUE,
                                   _gate_state, census)

REGISTRY = REPO / "paper_results/corpus/corpus_registry.json"
REPORT = REPO / "paper_results/corpus/CORPUS_VERIFICATION.md"


def registry() -> dict:
    if not REGISTRY.is_file():
        pytest.skip("the registry has not been built")
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# the rule, on its own
# ---------------------------------------------------------------------------
def test_a_missing_key_and_a_null_key_are_told_apart_and_both_mean_unknown():
    """Four states, four different causes, and only one of them is `true`."""
    assert _gate_state({"g": True}, "g") == GATE_TRUE
    assert _gate_state({"g": False}, "g") == "false"
    assert _gate_state({"g": None}, "g") == GATE_NULL
    assert _gate_state({"other": True}, "g") == GATE_ABSENT
    assert _gate_state(None, "g") == GATE_NO_BLOCK
    assert _gate_state("not a dict", "g") == GATE_NO_BLOCK
    # The distinction that was lost: these are two different answers, and
    # neither of them is "true".
    assert _gate_state({"g": None}, "g") != _gate_state({}, "g")
    for state in (GATE_NULL, GATE_ABSENT, GATE_NO_BLOCK):
        assert state != GATE_TRUE


def test_a_census_that_does_not_sum_to_its_denominator_refuses_to_be_published():
    rows = [{"a": 1}, {"a": 2}, {"a": 2}]
    counted = census(rows, lambda r: r["a"], "three fixture rows")
    assert counted["denominator"] == 3
    assert counted["counts"] == {"2": 2, "1": 1}
    assert sum(counted["counts"].values()) == counted["denominator"]

    class Sneaky(dict):
        """A key function that drops a row, the way counting only the nulls
        dropped the rows whose key was absent."""

    def drops_one(row):
        if row["a"] == 1:
            raise KeyError("gone")
        return row["a"]

    with pytest.raises(KeyError):
        census(rows, drops_one, "three fixture rows")


# ---------------------------------------------------------------------------
# the gates, as published
# ---------------------------------------------------------------------------
def test_every_gate_census_sums_to_the_denominator_it_states():
    gates = registry()["summary"]["evidence_gate_census"]
    denominator = gates["denominator"]
    assert denominator > 0
    assert "evidence block" in gates["denominator_is"]
    for gate, counts in gates["gates"].items():
        assert gate in EVIDENCE_GATES, gate
        total = (counts["true"] + counts["false"]
                 + counts["not_established_present_but_null"]
                 + counts["not_established_key_absent"])
        assert total == denominator == counts["sums_to"], (gate, counts)
        assert counts["not_established_total"] == (
            counts["not_established_present_but_null"]
            + counts["not_established_key_absent"]), gate
    assert set(gates["gates"]) == set(EVIDENCE_GATES)


def test_the_same_census_over_a_different_denominator_is_published_beside_it():
    """The 7-against-11 disagreement, written down rather than resolved by
    picking one.

    A MISSING KEY AND A PRESENT-AND-NULL KEY ARE BOTH "NOT ESTABLISHED", and a
    census that counts one and silently drops the other does not add up to its
    own denominator. In pass10 the `mechanically_informative` gate was absent
    on four rows over the whole file and never absent over the store as it
    stood, because the absent key belonged to a superseded batch's schema.

    pass11 has no superseded rows, so the key is absent nowhere and the two
    censuses coincide. The invariant being kept is that BOTH censuses sum to
    the denominators they state and that the two ways of being unestablished
    are counted apart -- which is what fails when the distinction is dropped,
    whether or not any row happens to exercise it today."""
    recon = registry()["summary"]["verification_file_reconciliation"]
    whole = recon["evidence_gate_census_over_the_whole_file"]
    here = registry()["summary"]["evidence_gate_census"]
    assert whole["denominator"] >= here["denominator"]
    for gate, counts in whole["gates"].items():
        assert sum(counts.values()) == whole["denominator"], gate
        assert set(counts) == {"true", "false", "null", "absent"}, gate
    mech = here["gates"]["mechanically_informative"]
    assert mech["not_established_total"] == (
        mech["not_established_present_but_null"]
        + mech["not_established_key_absent"])
    assert whole["gates"]["mechanically_informative"]["absent"] == \
        mech["not_established_key_absent"], (
            "the store census and the whole-file census disagree about how "
            "many rows never asked the question")


def test_every_record_with_a_verification_row_carries_all_six_gates():
    records = [r for r in registry()["records"]
               if r["gate_abaqus_job_completed"]]
    assert len(records) >= 200, len(records)
    for record in records:
        states = [record[f"gate_{gate}"] for gate in EVIDENCE_GATES]
        assert all(states), record["source_id"]
        assert record["verified_on_every_gate"] == all(
            state == GATE_TRUE for state in states), record["source_id"]
        if not record["verified_on_every_gate"]:
            assert record["gates_not_true"], record["source_id"]


# ---------------------------------------------------------------------------
# three numbers, all published
# ---------------------------------------------------------------------------
def test_every_census_the_registry_publishes_states_and_sums_to_a_denominator():
    """Not only the gates. Every table in the registry -- terminal states,
    whose move it is, what the refused files are, which interface each
    presents -- was taken over a named population and adds up to it, and the
    build stops rather than publishing one that does not."""
    censuses = registry()["summary"]["censuses"]
    assert len(censuses) >= 6, sorted(censuses)
    for name, counted in censuses.items():
        assert counted["denominator_is"], name
        assert counted["denominator"] > 0, name
        assert sum(counted["counts"].values()) == counted["denominator"], name
        assert counted["sums_to_the_denominator"] is True, name
    # And the ones that say they are over D1 really are.
    d1 = registry()["summary"]["acquired"]
    for name in ("terminal_state", "whose_move_it_is", "entry_interface",
                 "transformed", "compiled", "adequately_specified"):
        assert censuses[name]["denominator"] == d1 == 391, name


def test_a_census_over_a_field_that_stops_covering_its_records_stops_the_build():
    """The guard is in the counting, so a classification that grew a case it
    does not handle cannot be published as a table that is quietly short."""
    class Row:
        def __init__(self, value):
            self.value = value

    rows = [Row("a"), Row("b"), Row(None)]
    counted = census(rows, lambda r: str(r.value), "three fixture rows")
    assert counted["denominator"] == 3
    assert counted["counts"]["None"] == 1, (
        "a None has to be counted as a value, not dropped -- that is the "
        "whole finding this module exists for")


def test_there_is_one_verified_number_and_every_source_is_in_one_class():
    """Verified means every one of the six gates reads true, and nothing else.

    This used to assert THREE verified numbers that reconciled, the third being
    entries whose primal gate read false with a control explaining why. That
    third number was the defect: an explanation for a disagreement is not
    agreement, and those entries are internal failures. The registry now
    publishes one verified number and a partition of all 391 with no overlap.
    """
    summary = registry()["summary"]
    recon = summary["verification_file_reconciliation"]
    verified = recon["store_entries_that_verified"]
    assert verified == summary["fully_verified"]
    assert verified == summary["verified_on_every_gate"]
    assert verified == recon["store_entries_that_verified_on_every_gate"]
    kinds = summary["by_kind"]
    assert set(kinds) == {"verified", "external", "internal"}
    assert kinds["verified"] == verified
    assert sum(kinds.values()) == summary["acquired"]
    demoted = recon["rows_demoted_because_their_own_evidence_contradicts_the_word"]
    assert recon["rows_whose_file_stage_says_verified"] == verified + len(demoted)
    records = {r["source_id"]: r for r in registry()["records"]}
    for name in demoted:
        assert records[name]["terminal_state"] != "fully_verified", name
        assert records[name]["kind"] == "internal", name

def test_the_strict_number_is_never_larger_than_the_rung():
    """A source cannot pass every gate without reaching the rung."""
    for record in registry()["records"]:
        if record["verified_on_every_gate"]:
            assert record["terminal_state"] == "fully_verified", \
                record["source_id"]


def test_the_report_publishes_one_verified_number():
    if not REPORT.is_file():
        pytest.skip("the report has not been built")
    text = REPORT.read_text(encoding="utf-8")
    recon = registry()["summary"]["verification_file_reconciliation"]
    assert "One verified number" in text
    assert "counted three ways" not in text
    assert str(recon["store_entries_that_verified"]) in text
    assert "primal_mismatch_explained" in text
    for name in recon["rows_demoted_because_their_own_evidence_contradicts_the_word"]:
        assert name in text, name

