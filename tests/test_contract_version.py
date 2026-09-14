"""Both repositories say which contract they speak, and a mismatch is loud.

The failure being prevented: the two ends drift, a consumer reads a field that
has been renamed, ``.get()`` returns ``None``, and the wrong number surfaces
three layers away as a bad tangent. A version handshake turns that into one
message at the boundary naming both versions and both speakers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.contract import (CONTRACT_VERSION, ContractVersionError, SPEAKER,
                               contract_version_of, handshake, load_schema,
                               parse, require_compatible)
from umat_oti.contract.schema import SCHEMA_FILES
from umat_oti.contract.adapted import (adapt_v2_contract_versioned,
                                       kinematics_agree,
                                       require_adapter_contract_compatible,
                                       stamp_contract_version)
from umat_oti.services.contract_adapter import adapt_v2_contract


def test_this_repository_states_which_contract_it_speaks():
    assert handshake() == {"speaker": SPEAKER,
                           "contract_version": CONTRACT_VERSION}
    assert parse(CONTRACT_VERSION).major >= 1


def test_the_service_adapter_document_gets_the_contract_version_stamped_on():
    """The adapter predates the shared contract and its own bytes are left
    alone -- it is transform-side, and a single constant added to it moved the
    transform fingerprint off the one the frozen store was produced at, which
    would have marked all 237 stored transforms stale. So the version is
    stamped from the contract side, which is exempt from that fingerprint."""
    v2 = {
        "schema": "resasm_umat_transform_v2",
        "kinematics": "small_strain",
        "dimensions": {"ntens": 6, "nprops": 2, "nstatev": 0},
        "parameters": [{"name": "E", "props_index": 1}],
        "derivative": {"response": "STRESS", "export": "DSIGMA_DP"},
    }
    plain = adapt_v2_contract(v2, model="m", source_path="repo__x/u.f")
    assert "contract_version" not in plain.contract
    versioned = adapt_v2_contract_versioned(v2, model="m",
                                            source_path="repo__x/u.f")
    assert versioned.contract["contract_version"] == CONTRACT_VERSION
    # And everything the adapter decided is left exactly as it decided it.
    assert {k: v for k, v in versioned.contract.items()
            if k != "contract_version"} == plain.contract
    assert versioned.unmapped == plain.unmapped
    assert versioned.notes == plain.notes


def test_a_document_that_already_declares_a_version_is_not_restamped():
    """Restamping would erase a mismatch instead of reporting it."""
    assert stamp_contract_version({"a": 1})["contract_version"] == CONTRACT_VERSION
    stamp_contract_version({"contract_version": CONTRACT_VERSION})
    with pytest.raises(ContractVersionError) as exc:
        stamp_contract_version({"contract_version": "0.9.0"})
    assert "erase the mismatch" in str(exc.value)


def test_the_adapter_and_the_contract_agree_on_what_finite_strain_is_called():
    """The adapter cannot import the contract, so the two carry the word
    separately and this is what stops them drifting."""
    assert kinematics_agree()


def test_every_schema_declares_the_version_the_code_speaks():
    for name in SCHEMA_FILES:
        assert load_schema(name)["x-contract-version"] == CONTRACT_VERSION


def test_a_major_mismatch_is_refused_with_a_readable_message():
    ahead = f"{parse(CONTRACT_VERSION).major + 1}.0.0"
    with pytest.raises(ContractVersionError) as exc:
        require_compatible(ahead, speaker="Residual_Assembler")
    message = str(exc.value)
    assert ahead in message and CONTRACT_VERSION in message
    assert "Residual_Assembler" in message and SPEAKER in message
    assert "BREAKING" in message
    # The point of refusing rather than reading: the failure mode of reading
    # is a wrong number, not an exception.
    assert "wrong numbers" in message


def test_a_newer_minor_is_refused_because_this_reader_cannot_tell_what_it_missed():
    ahead = f"{parse(CONTRACT_VERSION).major}.{parse(CONTRACT_VERSION).minor + 1}.0"
    with pytest.raises(ContractVersionError) as exc:
        require_compatible(ahead, speaker="Residual_Assembler")
    assert "cannot tell" in str(exc.value)


def test_an_older_minor_is_read_but_its_new_fields_are_not_established():
    mine = parse(CONTRACT_VERSION)
    if mine.minor == 0:
        pytest.skip(f"contract is at {CONTRACT_VERSION}; there is no older "
                    f"minor to read, which is a fact about the version and "
                    f"not about the rule")
    note = require_compatible(f"{mine.major}.{mine.minor - 1}.0",
                              speaker="Residual_Assembler")
    assert "NOT ESTABLISHED" in note


def test_a_document_with_no_version_is_refused_rather_than_assumed_current():
    with pytest.raises(ContractVersionError) as exc:
        parse(None)
    assert "guessing" in str(exc.value)
    with pytest.raises(ContractVersionError):
        contract_version_of({"schema_version": "1.1"})
    with pytest.raises(ContractVersionError):
        parse("1.0")          # two parts is not a version; it is not padded


def test_the_handshake_lives_in_the_contract_not_in_transform_side_code():
    """The boundary check belongs where the boundary is defined, and the
    transform side must not import it: the contract is exempt from the
    transform fingerprint, so that import would let a contract edit change
    transform-side behaviour while every stored transform reported itself
    current."""
    import ast
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / "src" / "umat_oti" / \
        "services" / "contract_adapter.py"
    tree = ast.parse(source.read_text())
    reached = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import)
               for a in n.names]
    reached += [n.module or "" for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom)]
    assert not [m for m in reached if m.startswith("umat_oti.contract")]

    assert require_compatible(CONTRACT_VERSION,
                              speaker="Residual_Assembler") == ""
    with pytest.raises(ContractVersionError):
        require_compatible("0.9.0", speaker="Residual_Assembler")
    # And a 1.x consumer is refused by a 2.x producer, which is the whole
    # point of the bump: two terminal states it has never heard of, a
    # five-field row identity it would read as two, and five counts it would
    # read as one.
    with pytest.raises(ContractVersionError) as exc:
        require_compatible("1.0.0", speaker="Residual_Assembler")
    assert "BREAKING" in str(exc.value)
    with pytest.raises(ContractVersionError):
        require_adapter_contract_compatible({"schema_version": "1.1"},
                                            speaker="Residual_Assembler")


def test_the_breaking_change_policy_is_written_down_in_the_schema():
    """A version number nobody defined the meaning of is a number."""
    document = load_schema("umat_contract")
    policy = document["x-breaking-change"]
    for must_be_breaking in ("removing", "renaming", "required", "meaning"):
        assert must_be_breaking in policy.lower()
