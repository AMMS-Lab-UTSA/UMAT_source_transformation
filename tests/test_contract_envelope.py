"""An envelope is not a verdict, and 237 is not 42.

``ServiceResult.ok`` means the service RAN. It is true of every entry the
service managed to look at, including every entry it looked at and refused.
Reading it as the answer offered all 237 corpus materials to the Residual
Assembler as verified, when 42 are true on all six gates and 55 reach a
verified terminal state.

A boolean that is true 237 times out of 237 is not a filter; it is the absence
of one. So the two facts carry different names and different types, and the
one that is not a verdict cannot be used as a condition at all.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from umat_oti.contract import (FORBIDDEN_AS_A_VERDICT, NOT_ESTABLISHED,
                               SUCCESS_FIELD, VERDICT_FIELD, CallEnvelope,
                               EnvelopeError, SchemaViolation, Tri,
                               TristateError, adapt_store_records, validate,
                               verdict_of)

STORE_RELATIVE = Path("corpus_run") / "pass11" / "results" / \
    "store_verification.jsonl"


def _store():
    override = os.environ.get("UMAT_OTI_STORE")
    if override and Path(override).is_file():
        return [json.loads(l) for l in Path(override).read_text().splitlines() if l]
    root = Path(__file__).resolve().parents[1]
    for base in (root, root.parent, root.parent.parent):
        candidate = base / STORE_RELATIVE
        if candidate.is_file():
            return [json.loads(l) for l in
                    candidate.read_text().splitlines() if l]
    return None


@pytest.fixture(scope="module")
def rows():
    store = _store()
    if store is None:
        pytest.skip(f"the frozen store ({STORE_RELATIVE}) is not on this machine")
    return store


# ---------------------------------------------------------------------------
def test_the_two_fields_have_different_names():
    assert SUCCESS_FIELD == "call_succeeded"
    assert VERDICT_FIELD == "verdict"
    assert SUCCESS_FIELD != "ok"


def test_the_verdict_cannot_be_used_as_a_condition():
    """Different names would not be enough: two booleans side by side are two
    things that look alike, and a reader reaches for whichever looks like
    success. One of them not being usable as a condition is what makes the
    confusion impossible rather than merely discouraged."""
    envelope = CallEnvelope(service="verify", call_succeeded=True,
                            subject="umat.f", verdict=Tri(False))
    assert envelope.call_succeeded is True
    with pytest.raises(TristateError):
        bool(envelope.verdict)


def test_a_bool_verdict_is_refused_at_construction():
    with pytest.raises(EnvelopeError) as exc:
        CallEnvelope(service="s", call_succeeded=True, verdict=True)
    assert "237 entries whose call succeeded" in str(exc.value)


def test_a_call_that_did_not_run_may_not_carry_a_verdict():
    """A claim made by a call that did not finish."""
    CallEnvelope(service="s", call_succeeded=False, verdict=NOT_ESTABLISHED)
    with pytest.raises(EnvelopeError) as exc:
        CallEnvelope(service="s", call_succeeded=False, verdict=Tri(True))
    assert "did not finish" in str(exc.value)


def test_a_successful_call_with_a_failing_verdict_is_the_normal_case():
    """A verification that ran perfectly and found the derivatives wrong."""
    envelope = CallEnvelope(service="verify", call_succeeded=True,
                            subject="umat.f", verdict=Tri(False),
                            verdict_reason="derivatives disagreed")
    assert envelope.ran
    assert envelope.verdict.is_false()
    assert "the call succeeded" in envelope.describe()
    assert "the verdict about umat.f is false" in envelope.describe()


def test_ok_is_never_read_as_a_verdict():
    for shape in ({"ok": True}, {"ok": True, "outcome": "refused"},
                  {"success": True}, {"passed": True}, {"status": "done"}):
        with pytest.raises(EnvelopeError) as exc:
            verdict_of(shape)
        assert VERDICT_FIELD in str(exc.value)
    assert "ok" in FORBIDDEN_AS_A_VERDICT
    assert "whether the service RAN" in FORBIDDEN_AS_A_VERDICT["ok"]


def test_a_payload_with_no_verdict_raises_rather_than_shrugging():
    """Answering NOT ESTABLISHED there would hide the misreading: the caller
    asked a question this payload does not answer."""
    with pytest.raises(EnvelopeError) as exc:
        verdict_of({"service": "verify"})
    assert "nothing that could be mistaken for one" in str(exc.value)


def test_a_stated_verdict_is_read_three_state():
    assert verdict_of({VERDICT_FIELD: True}).is_true()
    assert verdict_of({VERDICT_FIELD: False}).is_false()
    assert verdict_of({VERDICT_FIELD: None}).is_not_established()
    with pytest.raises(EnvelopeError):
        verdict_of({VERDICT_FIELD: "true"})


def test_wrapping_a_service_result_requires_the_verdict_separately():
    """There is nothing in a service result that answers it, so the caller
    must supply it -- which is what stops ``ok`` being pressed into service."""
    payload = {"schema": "umat-oti/service-result/1", "service": "verify",
               "ok": True, "outcome": "completed", "problems": []}
    envelope = CallEnvelope.from_service_result(
        payload, verdict=Tri(False), verdict_reason="primal disagreed",
        subject="umat.f")
    assert envelope.call_succeeded is True
    assert envelope.verdict.is_false()
    with pytest.raises(TypeError):
        CallEnvelope.from_service_result(payload)      # verdict is required


def test_the_schema_refuses_an_envelope_carrying_ok():
    base = {"contract_version": "2.0.0",
            "identity": {"path": "repo__x/u.f", "sha256": "a" * 64},
            "transform_fingerprint": "b0d27ee53c630500",
            "terminal": {"state": "fully_verified", "owner": "NONE"},
            "evidence": {}}
    good = dict(base, envelope={"service": "verify", "call_succeeded": True,
                                "verdict": None})
    validate(good, "umat_contract")
    bad = dict(base, envelope={"service": "verify", "call_succeeded": True,
                               "verdict": None, "ok": True})
    with pytest.raises(SchemaViolation) as exc:
        validate(bad, "umat_contract")
    assert "envelope" in str(exc.value)


def test_the_schema_refuses_a_non_three_state_verdict():
    base = {"contract_version": "2.0.0",
            "identity": {"path": "repo__x/u.f", "sha256": "a" * 64},
            "transform_fingerprint": "b0d27ee53c630500",
            "terminal": {"state": "fully_verified", "owner": "NONE"},
            "evidence": {}}
    for smuggled in ("true", 1, "verified"):
        with pytest.raises(SchemaViolation):
            validate(dict(base, envelope={"service": "v", "call_succeeded": True,
                                          "verdict": smuggled}),
                     "umat_contract")


# ---------------------------------------------------------------------------
# the numbers, on the real store
# ---------------------------------------------------------------------------
def test_every_call_succeeded_and_that_is_not_a_verdict_about_any_of_them(rows):
    """The measurement behind the rule.

    All 237 rows are entries a service looked at. Wrapping each in an envelope
    whose call succeeded gives 237 successful calls -- and three different,
    much smaller numbers when the question asked is about the materials.
    """
    assert len(rows) == 237
    envelopes = [CallEnvelope(service="verify", call_succeeded=True,
                              subject=row["source"],
                              verdict=NOT_ESTABLISHED)
                 for row in rows]
    assert sum(1 for e in envelopes if e.call_succeeded) == 237
    # And not one of those 237 is a verdict.
    assert all(e.verdict.is_not_established() for e in envelopes)
    assert sum(1 for e in envelopes if e.verdict.is_true()) == 0


def test_three_numbers_never_one(rows):
    """55, 42 and 13, and they are three different questions.

    55 reached a verified TERMINAL STATE.
    42 are true on all six gates RAW.
    13 carry primal_agreed FALSE with a control that measured why, and
       42 + 13 = 55 -- which is the chain, not a coincidence.
    """
    from umat_oti.contract import SEVENTH
    adapted = adapt_store_records(rows)
    verified = [r for r in adapted.records if r.terminal.verified]
    raw_true = [r for r in verified if r.evidence.conjunction().is_true()]
    explained = [r for r in verified if r.evidence.primal_agreed.is_false()]

    assert len(verified) == 55
    assert len(raw_true) == 42
    assert len(explained) == 13
    assert len(raw_true) + len(explained) == len(verified)

    # Every one of the 13 has the seventh field measured TRUE -- a control ran
    # and explained the difference. Without that they would be 13 unexplained
    # disagreements sitting inside a verified count.
    for record in explained:
        assert getattr(record.evidence, SEVENTH).is_true()
        assert record.evidence.primal_settled().is_true()
        assert record.evidence.conjunction().is_false()

    # And none of the three is 237.
    assert len(adapted.records) + len(adapted.errors) == 237
    for count in (len(verified), len(raw_true), len(explained)):
        assert count != 237


def test_an_envelope_per_entry_does_not_become_a_verified_count(rows):
    """The failure, reproduced and then prevented."""
    adapted = adapt_store_records(rows)
    envelopes = []
    for record in adapted.records:
        answer, why = record.usable_by_the_residual_assembler()
        envelopes.append(CallEnvelope(
            service="verify", call_succeeded=True,
            subject=record.identity.path, verdict=answer, verdict_reason=why))
    assert len(envelopes) == len(adapted.records)
    assert all(e.call_succeeded for e in envelopes)
    offered = [e for e in envelopes if e.verdict.is_true()]
    assert len(offered) == 55
    assert len(offered) < len(envelopes)
    # The count a reader would have got from the envelope alone:
    assert sum(1 for e in envelopes if e.call_succeeded) != len(offered)
