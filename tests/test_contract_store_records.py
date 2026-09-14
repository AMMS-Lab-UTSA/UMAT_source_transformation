"""The whole frozen store, through the contract, with nothing dropped.

237 rows in, 237 accounted for: 234 become contract records that validate
against the schema, and 3 become conforming error envelopes naming why they
could not. There is no third outcome, because the third outcome is a row
quietly defaulted into a record that reads as a verdict it never earned.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from umat_oti.contract import (CONTRACT_VERSION, RecordError, SchemaViolation,
                               adapt_store_records, from_store_record,
                               validate)

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
STORE_FINGERPRINT = "b0d27ee53c630500"


@pytest.fixture(scope="module")
def rows() -> list:
    store = store_path()
    if store is None:
        pytest.skip(f"the frozen store ({STORE_RELATIVE}) is not on this "
                    f"machine; set {STORE_ENV} to point at one")
    return [json.loads(line) for line in store.read_text().splitlines() if line]


@pytest.fixture(scope="module")
def adapted(rows):
    return adapt_store_records(rows)


def test_every_row_is_accounted_for(rows, adapted):
    assert len(rows) == 237
    assert adapted.total == 237
    assert len(adapted.records) == 234
    assert len(adapted.errors) == 3


def test_every_adapted_record_validates_against_the_schema(adapted):
    for record in adapted.records:
        validate(record.as_dict(), "umat_contract", where=str(record.identity))


def test_every_refusal_validates_against_the_error_schema(adapted):
    for error in adapted.errors:
        validate(error, "contract_error")
        assert error["code"] == "contract.untranslatable_stage"
        # The boundary is what is wrong here -- not the corpus and not the
        # pipeline -- and CONTRACT is the only owner fixed by changing the
        # contract rather than by waiting on somebody or doing pipeline work.
        assert error["owner"] == "CONTRACT"
        assert error["detail"]["stage"] == "arguments_diverged_before_the_routine"
        assert not error["terminal"]


def test_a_refusal_never_silently_becomes_a_record(adapted, rows):
    refused_paths = {e["identity"]["path"] for e in adapted.errors}
    carried_paths = {r.identity.path for r in adapted.records}
    assert refused_paths and not (refused_paths & carried_paths)
    assert len(refused_paths | carried_paths) == 237


def test_every_record_declares_the_contract_version(adapted):
    assert all(r.contract_version == CONTRACT_VERSION for r in adapted.records)


def test_every_record_carries_the_transform_fingerprint(adapted):
    """Without it a consumer cannot tell whether a record's numbers predate a
    correction to the transform."""
    assert {r.transform_fingerprint for r in adapted.records} == \
        {STORE_FINGERPRINT}


def test_a_record_with_no_fingerprint_is_refused(rows):
    row = dict(next(r for r in rows if r["stage"] == "verified"))
    row.pop("fingerprint")
    with pytest.raises(RecordError) as exc:
        from_store_record(row)
    assert "predate a correction" in str(exc.value)


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------
def test_material_constants_never_travel_without_provenance(adapted):
    """"Do not invent arbitrary material constants" is only enforceable if a
    value that was read can be told from a value that was made up, and the
    provenance is the only thing that tells them apart."""
    with_props = [r for r in adapted.records if r.material.props]
    assert len(with_props) > 100
    for record in with_props:
        assert record.material.provenance.strip(), record.identity.path


def test_provenance_names_the_deck_the_block_and_the_constant_count(adapted):
    for record in adapted.records:
        if not record.material.props:
            continue
        provenance = record.material.provenance
        assert ".inp" in provenance
        assert "*MATERIAL" in provenance
        assert "constants" in provenance


def test_a_declared_depvar_is_distinguished_from_an_inferred_state_count(adapted):
    """An inferred count is a weaker claim than a declared one, and 'neither'
    is weaker still. Three answers, not a boolean."""
    declared = [r for r in adapted.records
                if r.material.nstatv_from_depvar.is_true()]
    inferred = [r for r in adapted.records
                if r.material.nstatv_from_depvar.is_false()]
    unknown = [r for r in adapted.records
               if r.material.nstatv_from_depvar.is_not_established()]
    assert declared and unknown
    assert len(declared) + len(inferred) + len(unknown) == 234
    for record in declared:
        assert "*DEPVAR" in record.material.provenance


def test_props_carried_with_no_provenance_are_refused(rows):
    row = dict(next(r for r in rows if r["stage"] == "verified"))
    manifest = dict(row["manifest"])
    manifest["props"] = [210000.0, 0.3]
    row["manifest"] = manifest
    row["material_provenance"] = ""
    manifest["material_provenance"] = ""
    with pytest.raises(RecordError) as exc:
        from_store_record(row)
    assert "indistinguishable from an invented one" in str(exc.value)


# ---------------------------------------------------------------------------
# convention, kinematics, counts
# ---------------------------------------------------------------------------
def test_the_tensor_convention_is_stated_and_never_assumed(adapted):
    """Engineering shear read as tensorial is wrong by a factor of two in
    three components and right everywhere else."""
    for record in adapted.records:
        if record.interface.ntens is None:
            assert record.convention.voigt_order == ()
            assert "not established" in record.convention.note
            continue
        assert record.convention.shear == "engineering"
        assert len(record.convention.voigt_order) == record.interface.ntens
    three_d = [r for r in adapted.records if r.interface.ntens == 6]
    assert three_d
    assert three_d[0].convention.voigt_order == ("11", "22", "33", "12", "13", "23")


def test_an_unrecognised_kinematics_value_is_refused_not_guessed(rows):
    """Small strain seeds DSTRAN; finite strain must seed the deformation
    gradient. Guessing differentiates the wrong quantity."""
    row = dict(next(r for r in rows if r["stage"] == "verified"))
    row["kinematics"] = "updated_lagrangian"
    with pytest.raises(RecordError) as exc:
        from_store_record(row)
    assert "differentiates the wrong quantity" in str(exc.value)


def test_the_derivative_seed_follows_the_kinematics(adapted):
    for record in adapted.records:
        if record.kinematics.regime == "small strain":
            assert record.derivatives.seed == "DSTRAN"
        elif record.kinematics.finite_strain:
            assert record.derivatives.seed == "DFGRD1"
        else:
            assert record.derivatives.seed == ""


def test_the_derivative_section_restates_the_gate_and_does_not_re_decide_it(adapted):
    for record in adapted.records:
        assert record.derivatives.verified == record.evidence.derivatives_verified


def test_a_component_count_that_does_not_add_up_is_refused(rows):
    row = dict(next(r for r in rows
                    if r["stage"] == "verified" and r.get("manifest")))
    manifest = dict(row["manifest"])
    manifest["ndi"], manifest["nshr"] = 3, 2       # ntens is 6
    row["manifest"] = manifest
    with pytest.raises(RecordError) as exc:
        from_store_record(row)
    assert "sizing an array from one of them" in str(exc.value)


# ---------------------------------------------------------------------------
# usability, three-state
# ---------------------------------------------------------------------------
def test_whether_the_assembler_may_drive_itself_from_an_entry_is_three_state(adapted):
    usable, unmeasured, refused = [], [], []
    for record in adapted.records:
        answer, why = record.usable_by_the_residual_assembler()
        if answer.is_true():
            usable.append(record)
        elif answer.is_not_established():
            unmeasured.append((record, why))
        else:
            refused.append((record, why))
    assert len(usable) + len(unmeasured) + len(refused) == 234
    # A refusal is a finding; an unmeasured entry is a queue item; and the
    # contract does not merge them, because the work they imply is different.
    assert usable and refused
    assert all(w for _, w in refused), "a refusal without a reason is not one"
    for record in usable:
        assert record.terminal.verified
        assert record.evidence.settled().is_true()
    assert len(usable) == 55


def test_the_raw_primal_comparison_never_moves(adapted):
    """13 of the 55 verified entries have ``primal_agreed`` measured FALSE.
    Their verdicts rest on a control having measured WHY -- twelve on the
    model differing from itself by at least as much when its own arithmetic
    is reordered, one on the author's own declared precision. So the settled
    primal is true for all 55 while the RAW comparison is true for 42, and
    both answers stay readable: "did the two builds produce the same numbers?"
    and "is the difference between them accounted for?" are different
    questions and a reader must not get one when they asked the other."""
    verified = [r for r in adapted.records if r.terminal.verified]
    assert len(verified) == 55
    raw_true = [r for r in verified if r.evidence.conjunction().is_true()]
    assert len(raw_true) == 42
    explained = [r for r in verified if r.evidence.primal_agreed.is_false()]
    assert len(explained) == 13
    for record in explained:
        assert record.evidence.primal_settled().is_true()
        seventh = record.evidence \
            .primal_difference_explained_by_a_measured_control
        assert seventh.is_true()
        assert "explained_by_" in seventh.why
        assert record.evidence.settled().is_true()
        assert record.evidence.conjunction().is_false()


def test_an_unexplained_disagreement_is_never_a_verification():
    """The branch that matters: the builds disagreed and nothing says whether
    a control explained it. That is NOT ESTABLISHED, and NOT ESTABLISHED is
    not a pass."""
    from umat_oti.contract import EvidenceGates, Tri
    unexplained = EvidenceGates(primal_agreed=Tri(False))
    assert unexplained.primal_settled().is_not_established()
    assert not unexplained.primal_settled().is_true()
    assert unexplained.settled().is_not_established()
    measured_and_unexplained = EvidenceGates(
        primal_agreed=Tri(False),
        primal_difference_explained_by_a_measured_control=Tri(False))
    assert measured_and_unexplained.primal_settled().is_false()


def test_the_seventh_field_is_recovered_from_the_record_never_invented(adapted):
    """A run made before the field existed recorded the same fact elsewhere.
    Reading it is a read; producing TRUE from an absence would not be."""
    from umat_oti.contract import SEVENTH
    counts = {"true": 0, "false": 0, "not-established": 0}
    for record in adapted.records:
        counts[getattr(record.evidence, SEVENTH).spelling()] += 1
    assert counts["true"] == 19
    assert counts["false"] == 61      # 64 rows - the 3 refused, all of them false
    assert counts["not-established"] == 154
    # And never true where the builds agreed: there was no difference to explain.
    for record in adapted.records:
        if record.evidence.primal_agreed.is_true():
            assert getattr(record.evidence, SEVENTH).is_not_established()


def test_a_verified_entry_whose_gates_were_never_measured_is_not_usable():
    """The null-reads-as-a-pass defect, as a whole record rather than a field."""
    from umat_oti.contract import (EvidenceGates, Interface, Kinematics,
                                   MaterialProperties, TensorConvention,
                                   ContractRecord, DerivativeCapability,
                                   Formulation, TerminalState, UmatIdentity)
    record = ContractRecord(
        identity=UmatIdentity.of("repo__x/umat.f", "a" * 64),
        transform_fingerprint="b0d27ee53c630500",
        terminal=TerminalState("fully_verified", "NONE"),
        evidence=EvidenceGates(),          # every gate not established
        material=MaterialProperties(), interface=Interface(ntens=6),
        convention=TensorConvention.for_ntens(6), kinematics=Kinematics(),
        formulation=Formulation(), derivatives=DerivativeCapability())
    answer, why = record.usable_by_the_residual_assembler()
    assert answer.is_not_established()
    assert not answer.is_true()
    assert "never measured" in why
