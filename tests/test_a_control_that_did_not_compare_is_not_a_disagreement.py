"""pass22: nine rows were primal_disagreed with ``routine_level_agrees`` true
and a Jacobian-matched job that never produced a comparison (a data file opened
by an unredirected path, a bundle declaring a module or a main program twice,
two extra cutbacks that made the runs walk other increments). The gate is not
decided: stage ``primal_control_not_decided``, ``primal_agreed`` null, contract
5.0.0. A control that compared and disagreed is still ``primal_disagreed``.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

from umat_oti.abaqus import terminal_states as T
from umat_oti.app.plain_language import PLAIN, unmapped_stages
from umat_oti.contract import CONTRACT_VERSION, validate
from umat_oti.contract.errors import ContractError
from umat_oti.contract.terminal import (PUBLISHED_OWNERS, translate_stage,
                                        vocabulary_gap)

pytestmark = pytest.mark.unit

TOOL = Path(__file__).resolve().parents[1] / "tools" / "verify_store_in_abaqus.py"
STATE = "primal_control_not_decided"


def _tool():
    spec = importlib.util.spec_from_file_location("verify_tool_for_stage", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_tool_for_stage"] = module
    spec.loader.exec_module(module)
    return module


def _evidence(V, **kw):
    base = dict(material_found=True, original_completed=True, transformed_completed=True,
                primal_agrees=None)
    base.update(kw)
    return V.StageEvidence(**base)


def test_an_undecided_control_is_its_own_stage_not_a_disagreement():
    V = _tool()
    assert V.classify_stage(_evidence(V, primal_control_undecided=True)) == STATE
    assert V.classify_stage(_evidence(V, primal_agrees=False)) == "primal_disagreed"
    assert V.classify_stage(_evidence(V, primal_agrees=None)) == "primal_disagreed"
    # a job that did not run is still the earlier rung
    assert V.classify_stage(_evidence(V, transformed_completed=False,
                                      primal_control_undecided=True)) == "transformed_job_failed"
    assert V.stage_rank(STATE) == V.stage_rank("transformed_job_failed") + 1
    assert V.stage_rank(STATE) < V.stage_rank("primal_disagreed")


@pytest.mark.parametrize("jacobian,expected", [
    ({"ran": True, "completed": False, "agrees": False, "reason": "did not complete"}, True),
    ({"ran": True, "completed": True, "agrees": False,
      "reason": "share 184 of 208 records"}, True),
    ({"ran": False, "agrees": False, "reason": "the UMAT entry could not be renamed"}, True),
    ({"ran": True, "completed": True, "agrees": False, "comparison": {"agrees": False, "calls": 12}}, False),
    ({"ran": True, "completed": True, "agrees": True, "comparison": {"agrees": True, "calls": 12}}, False),
])
def test_only_a_control_that_made_no_comparison_is_undecided(jacobian, expected):
    V = _tool()
    assert V.control_is_undecided({"established": True}, {"agrees": True}, jacobian) is expected


def test_a_routine_level_disagreement_or_an_unestablished_init_is_not_undecided():
    V = _tool()
    none = {"ran": False, "agrees": False}
    assert V.control_is_undecided({"established": True}, {"agrees": False}, none) is False
    assert V.control_is_undecided({"established": False}, {"agrees": True}, none) is False


def test_the_vocabulary_owns_the_new_state_and_publishes_it():
    assert STATE in T.INTERNAL and T.FROM_STAGE[STATE] == STATE
    assert PUBLISHED_OWNERS[STATE] == "INTERNAL" and STATE in T.MEANING
    assert not vocabulary_gap()["unpublished"] and not vocabulary_gap()["missing_here"]
    state = translate_stage(STATE, "the control did not compare")
    assert state.owner == "INTERNAL" and not state.finished and not state.verified
    error = ContractError.from_terminal(state)
    assert error.code == "internal.primal_control_not_decided" and error.owner == "INTERNAL"
    validate(error.as_dict(), "contract_error")


def test_the_record_validates_at_contract_5_and_the_gate_reads_not_established():
    assert CONTRACT_VERSION.startswith("5.")
    record = {
        "contract_version": CONTRACT_VERSION,
        "identity": {"path": "repo__x/src/umat.f", "sha256": "a" * 64},
        "terminal": {"state": STATE, "owner": "INTERNAL"},
        "evidence": {"abaqus_job_completed": True, "all_requested_outputs_present": True,
                     "complete_history_finite": True, "primal_agreed": None,
                     "derivatives_verified": None, "mechanically_informative": None},
    }
    from umat_oti.contract.schema import current_transform_generation
    record["transform_fingerprint"] = current_transform_generation()["transform_fingerprint"]
    validate(record, "umat_contract")
    from umat_oti.contract.gates import read_gates
    gates = read_gates(record)
    assert gates.primal_agreed.is_not_established()
    assert gates.primal_settled().is_not_established()


def test_a_reader_is_told_what_the_state_means_in_plain_words():
    assert STATE in PLAIN and PLAIN[STATE]["whose move"] == "this program"
    assert STATE not in unmapped_stages([STATE])


def test_a_comparison_of_no_calls_is_undecided_too():
    V = _tool()
    empty = {"ran": True, "completed": True, "agrees": False,
             "comparison": {"agrees": False, "calls": 0}}
    assert V.control_is_undecided({"established": True}, {"agrees": True}, empty) is True


def test_no_fully_verified_row_can_carry_an_undecided_gate():
    """A source in primal_control_not_decided can never count as verified: the
    verifier's stage cannot be ``verified`` while the control is undecided, and
    the contract reads a null primal gate as NOT ESTABLISHED -- never settled,
    so a record that said fully_verified beside it could not be driven from."""
    V = _tool()
    everything_else = dict(material_found=True, original_completed=True,
                           transformed_completed=True, primal_agrees=None,
                           tangent_verified=True, mechanically_informative=True,
                           primal_control_undecided=True)
    assert V.classify_stage(V.StageEvidence(**everything_else)) == STATE
    from umat_oti.contract.gates import read_gates
    gates = read_gates({"evidence": {
        "abaqus_job_completed": True, "all_requested_outputs_present": True,
        "complete_history_finite": True, "primal_agreed": None,
        "derivatives_verified": True, "mechanically_informative": True}})
    assert gates.settled().is_not_established() and not gates.settled().is_true()
    assert gates.primal_settled().is_not_established()


def test_in_the_recorded_rows_an_undecided_gate_is_never_a_verified_stage():
    """Over every row of the newest pass this machine holds: a row whose
    primal_decided_by names the undecided control is not at stage verified, and
    its primal gate is null."""
    import json
    from _workspace import WORKSPACE
    found = 0
    for path in sorted((WORKSPACE / "corpus_run").glob("pass2*/results/store_verification.jsonl")):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            evidence = row.get("evidence") or {}
            if evidence.get("primal_decided_by") == "jacobian_matched_not_decided":
                found += 1
                assert row["stage"] != "verified" and evidence.get("primal_agreed") is None
            if row["stage"] == "verified":
                assert evidence.get("primal_decided_by") != "jacobian_matched_not_decided"
                assert (row.get("primal_gate") or {}).get("agrees") is not None
    # nothing recorded yet carries it (pass22 predates the stage): the loop is
    # the guard for the pass that does
    assert found >= 0
