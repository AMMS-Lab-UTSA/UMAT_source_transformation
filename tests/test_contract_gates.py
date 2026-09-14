"""Six gates, never one boolean -- and the seventh field that explains a false one.

Each of the six answers a question the others do not. A job that "completed
successfully" is a statement about the solver, not about the routine it
called; a history that is finite over the window carried is not a history
that is finite end to end; a primal that agreed about a material sitting near
its initial state agreed about the part every build gets right. Collapsing
them into one ``verified`` flag deletes every one of those distinctions, and
each was bought with a run that looked fine and was not.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from umat_oti.contract import (ALL_FIELDS, GATES, SEVENTH, EvidenceGates,
                               NOT_ESTABLISHED, Tri, TristateError, read_gates)
from umat_oti.contract.gates import GateError

#: The frozen store this contract is validated against. Located relative to
#: the checkout rather than written as an absolute path: an absolute one is
#: true on exactly one computer, and a test that silently skips everywhere
#: else is a test that proves nothing everywhere else. ``UMAT_OTI_STORE``
#: overrides it for a checkout laid out differently.
STORE_ENV = "UMAT_OTI_STORE"
STORE_RELATIVE = Path("corpus_run") / "pass11" / "results" / \
    "store_verification.jsonl"


def store_path() -> Path | None:
    """The store, or ``None`` when this machine does not have it."""
    override = os.environ.get(STORE_ENV)
    if override:
        return Path(override) if Path(override).is_file() else None
    root = Path(__file__).resolve().parents[1]
    for base in (root, root.parent, root.parent.parent):
        candidate = base / STORE_RELATIVE
        if candidate.is_file():
            return candidate
    return None


@pytest.fixture(scope="module")
def rows() -> list:
    store = store_path()
    if store is None:
        pytest.skip(f"the frozen store ({STORE_RELATIVE}) is not on this "
                    f"machine; set {STORE_ENV} to point at one")
    return [json.loads(line) for line in store.read_text().splitlines() if line]


def test_there_are_exactly_six_gates_and_they_are_named():
    assert GATES == (
        "abaqus_job_completed",
        "all_requested_outputs_present",
        "complete_history_finite",
        "primal_agreed",
        "derivatives_verified",
        "mechanically_informative",
    )
    assert len(GATES) == 6


def test_the_seventh_is_a_field_and_not_a_seventh_gate():
    """It never makes a verdict better; it says why a false one is still a
    verdict. Counting it among the gates would make 'a control ran' look like
    evidence of the material rather than evidence about the difference."""
    assert SEVENTH not in GATES
    assert ALL_FIELDS == GATES + (SEVENTH,)


def test_there_is_no_summary_boolean_that_would_hide_the_six():
    gates = EvidenceGates()
    for hidden in ("passed", "ok", "verified", "all_gates_passed", "success"):
        assert not hasattr(gates, hidden), (
            f"{hidden!r} would answer 'did this verify?' with one bit and "
            f"delete the six distinctions the gates were bought with")


def test_the_conjunction_is_three_state_and_cannot_be_used_as_a_bool():
    all_measured = EvidenceGates(**{n: Tri(True) for n in ALL_FIELDS[:6]},
                                 **{SEVENTH: NOT_ESTABLISHED})
    assert all_measured.conjunction().is_true()
    with pytest.raises(TristateError):
        bool(all_measured.conjunction())


def test_one_unmeasured_gate_makes_the_conjunction_unestablished_not_false():
    gates = EvidenceGates(**{n: Tri(True) for n in GATES[:5]})
    assert gates.conjunction().is_not_established()
    assert gates.not_established() == ("mechanically_informative",)
    assert gates.failing() == ()


def test_one_failed_gate_makes_the_conjunction_false_even_beside_an_unmeasured_one():
    gates = EvidenceGates(primal_agreed=Tri(False))
    assert gates.conjunction().is_false()
    assert gates.failing() == ("primal_agreed",)


def test_a_control_cannot_explain_a_difference_there_was_none_of():
    ok, why = EvidenceGates(primal_agreed=Tri(True),
                            **{SEVENTH: Tri(True)}).seventh_is_consistent()
    assert not ok
    assert "no control is needed" in why.lower()
    # Where the primal disagreed, all three answers are legal.
    for answer in (Tri(True), Tri(False), NOT_ESTABLISHED):
        ok, _ = EvidenceGates(primal_agreed=Tri(False),
                              **{SEVENTH: answer}).seventh_is_consistent()
        assert ok


def test_an_absent_evidence_block_leaves_every_gate_not_established():
    gates = read_gates({"stage": "not_a_umat"})
    assert gates.not_established() == GATES
    assert gates.measured() == ()
    for name in ALL_FIELDS:
        assert getattr(gates, name).is_not_established()
        assert "no evidence block" in getattr(gates, name).why


def test_a_non_object_evidence_block_is_refused_not_coerced():
    with pytest.raises(GateError):
        read_gates({"evidence": True})
    with pytest.raises(GateError):
        read_gates({"evidence": "verified"})


def test_the_top_level_informative_block_supplies_a_reason_never_the_answer():
    """A block saying ``informative: true`` beside an evidence gate that is
    null would be the block overruling the gate."""
    gates = read_gates({"evidence": {"mechanically_informative": None},
                        "mechanically_informative": {"informative": True,
                                                     "reason": "r"}})
    assert gates.mechanically_informative.is_not_established()
    carried = read_gates({"evidence": {"mechanically_informative": True},
                          "mechanically_informative": {"informative": True,
                                                       "reason": "because"}})
    assert carried.mechanically_informative.is_true()
    assert carried.mechanically_informative.why == "because"


# ---------------------------------------------------------------------------
# what the real store says
# ---------------------------------------------------------------------------
def test_the_frozen_store_carries_six_gates_and_not_the_seventh(rows):
    """Measured, and it is the three-state rule doing its job.

    Every one of the 144 evidence blocks in the frozen store has exactly the
    six gates. The seventh field does not appear in any of the 237 rows: the
    run predates it. Under this contract that reads NOT ESTABLISHED for all
    237, which is the truth -- not 'no control was needed', which is what a
    reader defaulting it to null-means-fine would conclude, and not 'the
    control failed', which is what a falsy default would conclude.
    """
    with_evidence = [r for r in rows if isinstance(r.get("evidence"), dict)]
    assert len(with_evidence) == 144
    assert all(set(r["evidence"]) == set(GATES) for r in with_evidence)
    assert not any(SEVENTH in json.dumps(r) for r in rows)

    # So where the builds AGREED -- 61 rows, no control needed -- the field is
    # NOT ESTABLISHED, which is the truth. Not "no control was needed", which
    # is what a null-means-fine reader would conclude, and not "the control
    # failed", which is what a falsy default would conclude.
    agreed = [r for r in rows
              if read_gates(r).primal_agreed.is_true()]
    assert len(agreed) == 61
    for row in agreed:
        assert getattr(read_gates(row), SEVENTH).is_not_established()


def test_every_real_row_reads_three_state_without_raising(rows):
    counts = {name: {"true": 0, "false": 0, "not-established": 0}
              for name in ALL_FIELDS}
    for row in rows:
        for name, answer in read_gates(row).all_seven().items():
            counts[name][answer.spelling()] += 1
    # The gates genuinely disagree with one another; the distinctions are real.
    assert counts["abaqus_job_completed"]["true"] == 144
    assert counts["complete_history_finite"] == {"true": 139, "false": 5,
                                                 "not-established": 93}
    assert counts["primal_agreed"] == {"true": 61, "false": 83,
                                       "not-established": 93}
    assert counts["derivatives_verified"] == {"true": 60, "false": 84,
                                              "not-established": 93}
    assert counts["mechanically_informative"] == {"true": 128, "false": 10,
                                                  "not-established": 99}
    # The seventh is recovered from primal.explained_by_* where the run
    # recorded it there -- a read, never an invention. 83 rows have a measured
    # false primal; 19 of them carry a measured explanation and 64 do not.
    assert counts[SEVENTH] == {"true": 19, "false": 64, "not-established": 154}
    assert counts[SEVENTH]["true"] + counts[SEVENTH]["false"] == \
        counts["primal_agreed"]["false"] == 83


def test_a_gate_that_is_null_in_the_real_store_is_not_a_pass(rows):
    """Six rows carry ``mechanically_informative: null`` INSIDE an evidence
    block that has the other five. That is the exact shape the rule is about:
    a null sitting beside measured values, where a truthiness test would read
    it as a failure and a ``is not False`` test would read it as a pass."""
    nulls = [r for r in rows
             if isinstance(r.get("evidence"), dict)
             and r["evidence"].get("mechanically_informative") is None
             and "mechanically_informative" in r["evidence"]]
    assert len(nulls) == 6
    unestablished, refused = [], []
    for row in nulls:
        gates = read_gates(row)
        answer = gates.mechanically_informative
        assert answer.is_not_established()
        assert not answer.is_true() and not answer.is_false()
        assert gates.not_established() == ("mechanically_informative",)
        assert "mechanically_informative" not in gates.failing()
        (unestablished if gates.conjunction().is_not_established()
         else refused).append(row["stage"])

    # Five of the six also have gates measured FALSE, and a measured failure
    # dominates an unmeasured term -- so the conjunction is false, while the
    # unmeasured gate stays reported apart from the failed ones and a reader
    # is never told the null was what failed.
    assert sorted(refused) == ["primal_disagreed"] * 3 + \
        ["tangent_not_verified"] * 2

    # And the sixth is the whole rule in one row: nothing about it failed, the
    # only unresolved gate is the null one, and its conjunction is
    # NOT ESTABLISHED. A truthiness test would call that row a failure; an
    # ``is not False`` test would call it verified. It is neither, and the
    # pipeline's own terminal state agrees -- informativeness_not_established.
    assert unestablished == ["informativeness_not_established"]


def test_an_unmeasured_gate_beside_only_passes_is_unestablished_not_false():
    """The other half of the rule above, so that 'false' in the real rows is
    not mistaken for the conjunction ignoring nulls."""
    gates = EvidenceGates(**{n: Tri(True) for n in GATES if
                             n != "mechanically_informative"})
    assert gates.conjunction().is_not_established()
