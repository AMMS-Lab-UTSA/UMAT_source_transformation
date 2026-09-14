"""Three answers, and the one that must never be mistaken for a pass.

The defect this file exists to prevent is a single character wide::

    if record["evidence"]["derivatives_verified"]:

A gate nobody measured is written ``null``, ``null`` is falsy, and a
*measured failure* and *nothing ever measured it* become the same branch. The
mirror of it -- ``is not False`` -- is worse, because it reads not-established
as a verification claim about a material nobody verified.

So :class:`Tri` raises on truthiness rather than answering it.
"""
from __future__ import annotations

import pytest

from umat_oti.contract import (FALSE, NOT_ESTABLISHED, TRUE, Tri,
                               TristateError, all_true, read, read_path)


def test_a_three_state_answer_refuses_to_be_a_two_state_one():
    with pytest.raises(TristateError) as exc:
        bool(NOT_ESTABLISHED)
    assert "not-established" in str(exc.value)
    # And the message says which question the reader should have asked.
    for question in ("is_true", "is_false", "is_not_established"):
        assert question in str(exc.value)


def test_even_a_true_answer_refuses_truthiness():
    """Not only the null one. If ``if tri:`` worked for true and raised for
    null, every call site would be written and tested against a true value and
    would blow up the first time something went unmeasured -- in production,
    on the record that mattered."""
    with pytest.raises(TristateError):
        bool(TRUE)
    with pytest.raises(TristateError):
        bool(FALSE)


def test_a_missing_key_and_a_null_key_are_the_same_answer():
    assert read({"gate": None}, "gate").is_not_established()
    assert read({}, "gate").is_not_established()
    assert read(None, "gate").is_not_established()
    assert read({"gate": None}, "gate") == read({}, "gate")


def test_null_is_not_a_pass_and_not_a_failure():
    unmeasured = read({}, "derivatives_verified")
    assert not unmeasured.is_true()
    assert not unmeasured.is_false()
    assert unmeasured.is_not_established()
    assert not unmeasured.is_measured()


def test_a_truthy_string_cannot_get_into_a_gate():
    """'0', 'false' and 'no' are all truthy strings in Python, and each one
    has silently passed a gate somewhere."""
    for smuggled in ("true", "false", "no", "0", 1, 0):
        with pytest.raises(TristateError):
            read({"gate": smuggled}, "gate")


def test_conjunction_keeps_the_third_state():
    # A measured failure is a failure whatever else is unknown.
    assert all_true(TRUE, FALSE, NOT_ESTABLISHED).is_false()
    # A conjunction with an unmeasured term has not been established either.
    assert all_true(TRUE, TRUE, NOT_ESTABLISHED).is_not_established()
    assert all_true(TRUE, TRUE).is_true()


def test_read_path_walks_blocks_that_may_not_exist():
    assert read_path({"a": {"b": True}}, "a", "b").is_true()
    assert read_path({"a": {}}, "a", "b").is_not_established()
    assert read_path({}, "a", "b").is_not_established()


def test_the_reason_travels_with_the_answer():
    answer = read({}, "primal_agreed")
    assert "absent" in answer.why
    assert read({"primal_agreed": None}, "primal_agreed").why.endswith("is null")
