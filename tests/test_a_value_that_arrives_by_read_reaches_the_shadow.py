"""A value read from a file has no expression for the transform to rewrite.

Every other way a real variable gets a value is an assignment, and the
transform rewrites the assignment so the shadow beside it gets the value
too. An input statement is not an assignment: there is nothing to rewrite,
so the shadow keeps the zero it was initialised with and the converted build
computes the whole model with zeros where the author's tables should be.

Measured on Growth-Alex.for, which reads twelve tables of 7963 values each:
the ORIGINAL ran all 280 increments with finite stresses; the converted
build was non-finite at its first record, and the primal comparison reported
2800 non-finite values. The cause was not a disagreement about the
mathematics. The converted routine had never been given the data.
"""
from umat_oti.transform.source_transform import (
    _copy_real_shadow_lines, _joined_read_statement, _read_item_names,
    _read_shadow_sync)


def test_the_items_a_read_writes_are_the_ones_it_lists():
    assert _read_item_names("      read(301,*) Lambda1z0Imp") == ["LAMBDA1Z0IMP"]
    assert _read_item_names(
        "      READ(UNIT=5,FMT=*,IOSTAT=IOS) A, B(3), C") == ["A", "B", "C"]


def test_the_control_list_is_not_data():
    """Units, formats and specifiers are named inside the parentheses."""
    names = _read_item_names("      READ(IUNIT,FMT=FSPEC,IOSTAT=IOS) X")
    assert names == ["X"]
    assert "IUNIT" not in names and "IOS" not in names and "FSPEC" not in names


def test_a_write_is_not_a_read():
    assert _read_item_names("      WRITE(6,*) X") == []
    assert _read_item_names("      CALL SOMETHING(X)") == []


def test_a_continued_read_is_read_whole():
    statement, carried = _joined_read_statement(
        ["        read(301,*) A,", "     &  B"], 0, "fixed")
    assert _read_item_names(statement) == ["A", "B"]
    assert carried == [1]


def test_the_sync_is_emitted_after_the_read_and_only_there():
    body = ["      X = 1.0D0",
            "      read(301,*) TABLE",
            "      Y = TABLE(1)"]
    out = _read_shadow_sync(body, {"TABLE"}, {"TABLE": "(7963)"}, "fixed")
    assert out[0] == body[0]
    assert out[1] == body[1]
    synced = "\n".join(out[2:])
    assert "TABLE_OTI(OTI_HI) = TABLE(OTI_HI)" in synced
    assert out[-1] == body[2]


def test_a_read_into_something_with_no_shadow_adds_nothing():
    body = ["      read(301,*) SCRATCH"]
    assert _read_shadow_sync(body, {"TABLE"}, {}, "fixed") == body
    assert _read_shadow_sync(body, set(), {}, "fixed") == body


def test_a_continued_read_syncs_after_its_last_line():
    body = ["        read(301,*) A,", "     &  B", "        C = A(1)"]
    out = _read_shadow_sync(body, {"A", "B"}, {"A": "(3)", "B": "(3)"}, "fixed")
    assert out[0] == body[0] and out[1] == body[1]
    assert "A_OTI(OTI_HI) = A(OTI_HI)" in out[2] or "A_OTI" in "\n".join(out[2:5])
    assert out[-1] == body[2], "the statement after the READ must survive"
    assert "B_OTI" in "\n".join(out)


def test_a_scalar_shadow_is_copied_whole():
    assert _copy_real_shadow_lines("fixed", "T", "") == ["      T_OTI = T"]
