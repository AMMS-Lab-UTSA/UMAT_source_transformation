"""How one side tells the other that something is wrong, machine-readably.

A bare message string cannot be switched on, cannot be counted, and cannot be
told apart from another error with similar wording -- which is how two
different failures end up in one bucket and one of them never gets fixed.

Every error crossing this boundary answers three questions: whose problem it
is, whether it is terminal, and what is still true. The third matters because
an error does not erase the gates measured before it, and a consumer forced to
treat a late failure as though nothing had been measured throws away evidence
that was paid for.
"""
from __future__ import annotations

import pytest

from umat_oti.contract import (CODES, CONTRACT_OWNER, EXTERNAL_OWNER,
                               INTERNAL_OWNER, ContractError, SchemaViolation,
                               TerminalState, UmatIdentity, error_dict,
                               validate)
from umat_oti.contract.errors import ERROR_OWNERS


def test_every_code_is_namespaced_by_its_owner():
    for code in CODES:
        prefix = code.split(".", 1)[0]
        assert prefix in ("contract", "external", "internal"), code
        assert CODES[code].strip(), f"{code} has no gloss"


def test_a_code_namespaced_one_way_cannot_declare_the_other_owner():
    """An internal limitation transmitted as an external blocker claims
    somebody else's file is at fault for this project's gap; the reverse hides
    work behind a published-source excuse. Neither is carried."""
    with pytest.raises(ValueError) as exc:
        ContractError(code="internal.transform_refused", owner=EXTERNAL_OWNER,
                      message="the transform refused")
    assert "at fault for this project's gap" in str(exc.value)
    with pytest.raises(ValueError):
        ContractError(code="external.not_a_umat", owner=INTERNAL_OWNER,
                      message="not a umat")
    with pytest.raises(ValueError):
        ContractError(code="contract.schema_violation", owner=INTERNAL_OWNER,
                      message="bad record")


def test_an_owner_outside_the_three_is_refused():
    with pytest.raises(ValueError) as exc:
        ContractError(code="internal.harness_error", owner="SOMEBODY",
                      message="x")
    assert "cannot be routed" in str(exc.value)
    assert set(ERROR_OWNERS) == {EXTERNAL_OWNER, INTERNAL_OWNER, CONTRACT_OWNER}


def test_the_contract_owner_is_kept_apart_from_the_other_two():
    """It is the only one of the three fixed by changing the contract rather
    than by waiting on an upstream author or doing pipeline work."""
    assert CONTRACT_OWNER not in (EXTERNAL_OWNER, INTERNAL_OWNER)
    assert any(c.startswith("contract.") for c in CODES)
    for code in ("contract.version_mismatch", "contract.untranslatable_stage",
                 "contract.null_read_as_pass",
                 "contract.fixture_fingerprint_mismatch",
                 "contract.provenance_missing"):
        assert code in CODES


def test_an_error_with_no_message_is_refused():
    with pytest.raises(ValueError) as exc:
        ContractError(code="internal.harness_error", owner=INTERNAL_OWNER,
                      message="   ")
    assert "a person can act on" in str(exc.value)


def test_a_terminal_state_becomes_an_error_with_the_same_owner():
    external = TerminalState("not_a_umat", EXTERNAL_OWNER, "the entry is UEL")
    error = ContractError.from_terminal(external)
    assert error.owner == EXTERNAL_OWNER
    assert error.code.startswith("external.")
    assert error.terminal is True
    assert error.detail["terminal_state"] == "not_a_umat"

    internal = TerminalState("transform_refused", INTERNAL_OWNER, "no rule")
    error = ContractError.from_terminal(internal)
    assert error.owner == INTERNAL_OWNER
    assert error.code.startswith("internal.")
    # Unfinished and ours: not terminal, because it is work.
    assert error.terminal is False


def test_a_verified_entry_never_becomes_an_error():
    """Building an error envelope around fully_verified would put a verified
    entry into a failure count."""
    with pytest.raises(ValueError) as exc:
        ContractError.from_terminal(TerminalState("fully_verified", "NONE"))
    assert "not an error" in str(exc.value)


def test_every_terminal_state_maps_to_a_code_that_validates():
    from umat_oti.contract import known_states

    for state, owner in known_states().items():
        if state == "fully_verified":
            continue
        error = ContractError.from_terminal(
            TerminalState(state, owner, reason=f"reached {state}"),
            identity=UmatIdentity.of("repo__x/u.f", "a" * 64))
        assert error.code in CODES, f"{state} -> {error.code}"
        validate(error.as_dict(), "contract_error")


def test_what_was_established_survives_the_error():
    """An error does not erase the gates measured before it."""
    error = ContractError(
        code="internal.derivative_not_verified", owner=INTERNAL_OWNER,
        message="the finite difference could not resolve one",
        established={"abaqus_job_completed": True, "primal_agreed": True,
                     "mechanically_informative": None})
    payload = error.as_dict()
    validate(payload, "contract_error")
    assert payload["established"]["primal_agreed"] is True
    # And an unmeasured one stays unmeasured rather than becoming false.
    assert payload["established"]["mechanically_informative"] is None


def test_established_may_not_smuggle_a_truthy_non_boolean():
    error = ContractError(code="internal.harness_error", owner=INTERNAL_OWNER,
                          message="x", established={"primal_agreed": "true"})
    with pytest.raises(SchemaViolation):
        validate(error.as_dict(), "contract_error")


def test_the_shorthand_infers_the_owner_from_the_namespace():
    payload = error_dict("external.no_material_data",
                         "no deck declares this routine's constants",
                         terminal=True, repository="Somebody__thing")
    assert payload["owner"] == EXTERNAL_OWNER
    assert payload["detail"]["repository"] == "Somebody__thing"
    validate(payload, "contract_error")
    assert error_dict("internal.job_failed", "the job did not run")["owner"] \
        == INTERNAL_OWNER
