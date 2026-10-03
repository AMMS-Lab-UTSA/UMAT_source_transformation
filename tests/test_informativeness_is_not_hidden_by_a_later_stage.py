"""stage_supported_by_gates: a row failing BOTH derivatives_verified and
mechanically_informative reported tangent_not_verified, a later stage that
hid the informativeness gate (Scout; the shell-growth trio, Vera B10
pass21). The informativeness failure is now the stage; a gate never measured
is "not established", not "not informative"; rows where informative is true
keep their stage."""
import pytest

from umat_oti.abaqus.terminal_states import ACCEPTANCE_GATES, stage_supported_by_gates

pytestmark = pytest.mark.unit


def _row(**gates):
    evidence = {gate: True for gate in ACCEPTANCE_GATES}
    evidence.update(gates)
    return {"stage": "verified", "evidence": evidence}


def test_an_uninformative_experiment_is_the_stage_not_the_tangent():
    row = _row(derivatives_verified=False, mechanically_informative=False)
    assert stage_supported_by_gates(row) == "experiment_not_informative"


def test_an_informativeness_never_measured_is_not_established():
    row = _row(derivatives_verified=False, mechanically_informative=None)
    assert stage_supported_by_gates(row) == "informativeness_not_established"
    assert stage_supported_by_gates(_row(mechanically_informative=None)) == \
        "informativeness_not_established"


def test_rows_where_informative_is_true_keep_their_stage():
    assert stage_supported_by_gates(_row(derivatives_verified=False)) == "tangent_not_verified"
    assert stage_supported_by_gates(_row()) == "verified"
    assert stage_supported_by_gates(_row(primal_agreed=False)) == "primal_disagreed"
    # the primal gate still comes first
    assert stage_supported_by_gates(_row(primal_agreed=False,
                                         mechanically_informative=False)) == "primal_disagreed"
