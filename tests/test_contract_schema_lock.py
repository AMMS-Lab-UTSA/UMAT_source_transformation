"""The shared files are locked, and the schemas refuse what they must refuse.

Two different guards, for two different failures:

* the **lock** catches a shared contract file edited without the version being
  bumped, within one repository;
* the **version handshake** catches the two repositories being at different
  versions of the contract.

Neither substitutes for the other: a repository can only digest its own copies.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from umat_oti.contract import (CONTRACT_VERSION, LockMismatch, SchemaViolation,
                               compute_lock, load_schema, validate, verify_lock)
from umat_oti.contract.schema import (SCHEMA_DIR, SCHEMA_FILES, SHARED_FILES,
                                      read_lock)

STORE_FINGERPRINT = "b0d27ee53c630500"


def _record(**overrides) -> dict:
    base = {
        "contract_version": CONTRACT_VERSION,
        "identity": {"path": "repo__x/src/umat.f", "sha256": "a" * 64},
        "transform_fingerprint": STORE_FINGERPRINT,
        "terminal": {"state": "fully_verified", "owner": "NONE"},
        "evidence": {name: True for name in
                     ("abaqus_job_completed", "all_requested_outputs_present",
                      "complete_history_finite", "primal_agreed",
                      "derivatives_verified", "mechanically_informative")},
    }
    base.update(overrides)
    return base


def test_the_lock_matches_what_is_on_disk():
    verify_lock()
    assert read_lock()["combined"] == compute_lock()["combined"]
    assert read_lock()["contract_version"] == CONTRACT_VERSION


def test_the_lock_covers_the_three_state_reader_as_well_as_the_schemas():
    """A reimplementation of the three-state reader on the other side is
    exactly where "null reads as a pass" comes back, so the reader is a shared
    contract file and not an implementation detail of one repository."""
    assert "tristate.py" in SHARED_FILES
    assert set(SCHEMA_FILES.values()) < set(SHARED_FILES)
    assert set(read_lock()["files"]) == set(SHARED_FILES)


def test_an_edited_shared_file_without_a_regenerated_lock_is_refused(tmp_path):
    for name in SHARED_FILES:
        source = (SCHEMA_DIR / name) if name.endswith(".json") \
            else (SCHEMA_DIR.parent / name)
        (tmp_path / name).write_bytes(source.read_bytes())
    (tmp_path / "contract_lock.json").write_text(
        json.dumps(compute_lock(tmp_path)))
    verify_lock(tmp_path)
    target = tmp_path / "umat_contract_v1.schema.json"
    target.write_text(target.read_text().replace('"minLength": 1',
                                                 '"minLength": 0', 1))
    with pytest.raises(LockMismatch) as exc:
        verify_lock(tmp_path)
    assert "umat_contract_v1.schema.json" in str(exc.value)
    assert "bump the version" in str(exc.value)


# ---------------------------------------------------------------------------
# what the schema must refuse
# ---------------------------------------------------------------------------
def test_a_conforming_record_validates():
    validate(_record(), "umat_contract")


def test_the_schema_refuses_a_bare_basename_identity():
    with pytest.raises(SchemaViolation) as exc:
        validate(_record(identity={"path": "umat.f", "sha256": "a" * 64}),
                 "umat_contract")
    assert "identity/path" in str(exc.value)


def test_the_schema_refuses_an_identity_with_no_digest():
    with pytest.raises(SchemaViolation):
        validate(_record(identity={"path": "repo__x/umat.f"}), "umat_contract")
    with pytest.raises(SchemaViolation):
        validate(_record(identity={"path": "repo__x/umat.f",
                                   "sha256": "NOTADIGEST"}), "umat_contract")


def test_the_schema_refuses_a_null_rendered_as_a_pass():
    """The worst defect this system can ship. A gate must be true, false or
    null, and a string or a number -- each of which is truthy -- is refused
    before it can reach a reader."""
    for smuggled in ("true", "yes", 1, "not established", [], {}):
        with pytest.raises(SchemaViolation) as exc:
            validate(_record(evidence={"primal_agreed": smuggled}),
                     "umat_contract")
        assert "primal_agreed" in str(exc.value)


def test_the_schema_refuses_a_seventh_field_beside_an_agreeing_primal():
    """A control cannot explain a difference there was none of."""
    with pytest.raises(SchemaViolation):
        validate(_record(evidence={
            "primal_agreed": True,
            "primal_difference_explained_by_a_measured_control": True}),
            "umat_contract")
    # Null there is the correct answer and must validate.
    validate(_record(evidence={
        "primal_agreed": True,
        "primal_difference_explained_by_a_measured_control": None}),
        "umat_contract")


def test_the_schema_refuses_an_unknown_gate_so_a_typo_cannot_pass_silently():
    with pytest.raises(SchemaViolation):
        validate(_record(evidence={"primal_agree": True}), "umat_contract")


def test_the_schema_refuses_an_owner_the_vocabulary_disagrees_with():
    with pytest.raises(SchemaViolation) as exc:
        validate(_record(terminal={"state": "transform_refused",
                                   "owner": "EXTERNAL"}), "umat_contract")
    assert "terminal" in str(exc.value)
    with pytest.raises(SchemaViolation):
        validate(_record(terminal={"state": "not_a_umat", "owner": "INTERNAL"}),
                 "umat_contract")
    with pytest.raises(SchemaViolation):
        validate(_record(terminal={"state": "fully_verified",
                                   "owner": "EXTERNAL"}), "umat_contract")


def test_the_schema_refuses_a_terminal_state_outside_the_vocabulary():
    with pytest.raises(SchemaViolation):
        validate(_record(terminal={"state": "a_state_nobody_published",
                                   "owner": "INTERNAL"}), "umat_contract")


def test_the_schema_refuses_the_owner_arguments_diverged_used_to_have():
    """EXTERNAL at 2.0.0, INTERNAL from 3.0.0. The arguments that parted were
    computed from each build's own earlier outputs on this project's deck, so
    a record still booking it against the author's file is refused."""
    with pytest.raises(SchemaViolation):
        validate(_record(terminal={"state": "arguments_diverged_before_the_routine",
                                   "owner": "EXTERNAL"}), "umat_contract")
    validate(_record(terminal={"state": "arguments_diverged_before_the_routine",
                               "owner": "INTERNAL"}), "umat_contract")


def test_the_schema_refuses_material_constants_with_no_provenance():
    with pytest.raises(SchemaViolation) as exc:
        validate(_record(material={"props": [210000.0, 0.3]}), "umat_contract")
    assert "material" in str(exc.value)
    validate(_record(material={"props": [210000.0, 0.3],
                               "provenance": "job.inp *MATERIAL Steel: 2 "
                                             "constants, *DEPVAR 0"}),
             "umat_contract")
    # And an empty props list needs none: there is nothing to account for.
    validate(_record(material={"props": []}), "umat_contract")


def test_the_schema_refuses_a_record_with_no_transform_fingerprint():
    record = _record()
    del record["transform_fingerprint"]
    with pytest.raises(SchemaViolation):
        validate(record, "umat_contract")


def test_the_schema_refuses_a_fixture_reference_with_no_fingerprint():
    with pytest.raises(SchemaViolation):
        validate(_record(fixtures=[{"path": "tests/fixtures/verified/a.json"}]),
                 "umat_contract")


def test_the_error_schema_refuses_an_owner_that_contradicts_the_code():
    validate({"code": "internal.transform_refused", "owner": "INTERNAL",
              "message": "the transform refused"}, "contract_error")
    with pytest.raises(SchemaViolation) as exc:
        validate({"code": "internal.transform_refused", "owner": "EXTERNAL",
                  "message": "the transform refused"}, "contract_error")
    assert "owner" in str(exc.value)


def test_the_error_schema_refuses_a_message_free_error():
    with pytest.raises(SchemaViolation):
        validate({"code": "internal.harness_error", "owner": "INTERNAL",
                  "message": ""}, "contract_error")


def test_a_schema_whose_version_disagrees_with_the_code_is_refused(tmp_path):
    from umat_oti.contract import ContractVersionError
    from umat_oti.contract import schema as schema_module
    document = load_schema("umat_contract")
    document["x-contract-version"] = "9.9.9"
    target = SCHEMA_DIR / "umat_contract_v1.schema.json"
    original = target.read_text()
    try:
        target.write_text(json.dumps(document))
        with pytest.raises(ContractVersionError) as exc:
            load_schema("umat_contract")
        assert "9.9.9" in str(exc.value)
    finally:
        target.write_text(original)
    verify_lock()
