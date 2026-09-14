"""``primal_agreed: false`` beside ``stage: verified`` has to say what happened.

Thirteen pass11 entries are in that shape, and it is neither a contradiction
nor a loosened tolerance. The raw comparison flag never moves. What lets the
entry climb is a CONTROL that ran and measured something: either the author
declared a variable at single precision and the original with that one
declaration widened agrees with the converted build, or the model differs from
ITSELF by more than the two builds differ when the same source is compiled so
its arithmetic is reordered.

The registry publishes the chain as a flag with three values, and the third is
the point:

  True   a control ran and accounted for the difference
  False  a control ran and did NOT -- not the same answer as never asking
  None   no control was needed, which is every entry whose builds agreed

pass11 predates the batch writing that flag, so for that file it is DERIVED,
and the record says which of the two it was derived from. A derived field that
cannot be told from a recorded one is a field a reader cannot check.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from build_corpus_registry import CONTROL_GATE, _control_explanation  # noqa: E402

pytestmark = pytest.mark.unit


def test_a_recorded_flag_is_read_and_not_recomputed():
    """Once the batch writes it, the batch is the authority. A registry that
    went on deriving a field the batch now records would keep reporting its own
    derivation long after the two started disagreeing."""
    flag, where, _detail = _control_explanation(
        {"evidence": {CONTROL_GATE: True}, "primal": {"agrees": False}})
    assert flag is True
    assert where == f"read from evidence.{CONTROL_GATE}"


def test_a_recorded_false_is_kept_false():
    flag, where, _detail = _control_explanation(
        {"evidence": {CONTROL_GATE: False}, "primal": {"agrees": False}})
    assert flag is False and "read from" in where


def test_declared_precision_is_derived_with_the_control_named():
    """irfancn__Abaqus-UMAT-viscoelastic declares S at single precision; the
    original with that one declaration widened agrees with the converted build
    to 0.000e+00 over 280 increments."""
    flag, where, detail = _control_explanation({
        "primal": {"agrees": False,
                   "explained_by_declared_precision": True,
                   "worst_stress_relative": 6.499165075259156e-05},
        "precision_control": {"agrees": True, "ran": True,
                              "reason": "the original declares S at single "
                                        "precision and the OTI type is built "
                                        "over doubles"}})
    assert flag is True
    assert where == "derived from primal.explained_by_declared_precision"
    assert "single precision" in detail


def test_operation_order_is_derived_with_both_numbers_in_the_detail():
    """The claim is comparative and the detail has to carry both sides of it:
    the two builds differ by LESS than the model differs from itself."""
    flag, where, detail = _control_explanation({
        "primal": {"agrees": False, "explained_by_operation_order": True,
                   "own_sensitivity": 5.805e-03,
                   "worst_stress_relative": 3.127e-08},
        "association_control": {"ran": True, "measured": True,
                                "how": "reassociation"}})
    assert flag is True
    assert where == "derived from primal.explained_by_operation_order"
    assert "3.127e-08" in detail and "5.805e-03" in detail
    assert "reassociation" in detail


def test_a_control_that_ran_and_refuted_is_false_and_not_none():
    """Not-measured and measured-and-refuted are different answers. Leaving
    the second as None would report a control that ran as one that never
    happened, which is the more flattering of the two mistakes."""
    flag, where, detail = _control_explanation({
        "primal": {"agrees": False,
                   "own_sensitivity_unmeasured": "every way this harness has "
                                                 "of computing the same "
                                                 "mathematics differently "
                                                 "reproduced the original bit "
                                                 "for bit"},
        "association_control": {"ran": True, "measured": False,
                                "reason": "never perturbed"}})
    assert flag is False
    assert "did not account" in where
    assert "bit for bit" in detail


def test_an_entry_whose_builds_agreed_needs_no_control_and_gets_none():
    flag, where, detail = _control_explanation({"primal": {"agrees": True}})
    assert flag is None
    assert "no control was needed" in where
    assert detail == ""


def test_none_is_never_used_for_a_control_that_ran():
    """The one confusion the three-valued flag exists to prevent, pinned as
    its own statement: whenever a control block is present, the answer is a
    bool."""
    for control in ({"precision_control": {"agrees": False, "ran": True}},
                    {"association_control": {"ran": True, "measured": True}}):
        flag, _where, _detail = _control_explanation(
            {"primal": {"agrees": False}, **control})
        assert isinstance(flag, bool)
