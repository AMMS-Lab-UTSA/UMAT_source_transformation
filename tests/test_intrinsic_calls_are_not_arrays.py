"""MATMUL(A,B) and A(I,J) are the same shape to a reader that only knows names.

An intrinsic call site is indistinguishable from an array reference, so a
transformer that does not know the intrinsic reports it as a promoted variable
indexed on the stress path with no confirmed shape. Eleven of the thirty
sources blocked that way named MATMUL, TRANSPOSE or DCMPLX.

Widening the list is only safe because of the companion test: several standard
intrinsics -- SUM, INDEX, COUNT, SIZE, LEN, RANGE, SCALE, MERGE, TRIM -- are
also ordinary variable names, and a UMAT may keep an undeclared accumulator
called SUM under IMPLICIT REAL*8(A-H,O-Z). Demoting one of those would take a
real derivative silently to zero.
"""
from __future__ import annotations

import pytest

from umat_oti.core.roles import (
    INTRINSIC_CALL_NAMES, assigned_names, suggest_variable_roles,
)


class TestTheListCoversWhatLooksLikeIndexing:
    @pytest.mark.parametrize("name", [
        "MATMUL", "TRANSPOSE", "DOT_PRODUCT", "RESHAPE", "DCMPLX",
        "MAXVAL", "MINVAL", "SPREAD", "TRANSFER", "NORM2",
    ])
    def test_array_and_conversion_intrinsics_are_known(self, name):
        assert name in INTRINSIC_CALL_NAMES

    def test_the_elemental_intrinsics_are_still_known(self):
        for name in ("ABS", "SQRT", "SIN", "MOD", "SIGN"):
            assert name in INTRINSIC_CALL_NAMES


class TestAnAssignedNameIsAVariable:
    def test_a_scalar_assignment_is_found(self):
        assert "SUM" in assigned_names("      SUM = 0.D0\n")

    def test_an_indexed_assignment_is_found(self):
        assert "STRESS" in assigned_names("      STRESS(K1) = 1.D0\n")

    def test_a_comparison_is_not_an_assignment(self):
        assert assigned_names("      IF (A == B) THEN\n") == frozenset()

    def test_a_commented_assignment_is_not_an_assignment(self):
        assert assigned_names("C     SUM = 0.D0\n") == frozenset()

    def test_a_call_is_not_an_assignment(self):
        assert assigned_names("      CALL KMULT(A,B,C)\n") == frozenset()


def _roles(source_text: str, variables) -> dict[str, str]:
    analysis = {
        "detected_variables": variables,
        "region_summary": {"stress_path_variables":
                           [v["variable_name"] for v in variables]},
    }
    return {str(r["variable name"]): str(r["suggested OTIS role"])
            for r in suggest_variable_roles(analysis, source_text)}


def test_an_intrinsic_the_source_never_assigns_is_not_a_variable():
    source = ("      SUBROUTINE UMAT(STRESS,DSTRAN)\n"
              "      STRESS = MATMUL(A, DSTRAN)\n"
              "      END\n")
    roles = _roles(source, [{"variable_name": "MATMUL", "detected_type": "unknown",
                             "detected_usage": ["read"]}])
    assert roles["MATMUL"] == "Keep real"


def test_an_undeclared_accumulator_named_sum_keeps_its_derivative():
    """The case that makes a bare name list unsafe."""
    source = ("      SUBROUTINE UMAT(STRESS,DSTRAN)\n"
              "      SUM = 0.D0\n"
              "      DO I = 1, 6\n"
              "        SUM = SUM + DSTRAN(I)\n"
              "      END DO\n"
              "      STRESS = SUM\n"
              "      END\n")
    roles = _roles(source, [{"variable_name": "SUM", "detected_type": "unknown",
                             "detected_usage": ["read", "write"]}])
    assert roles["SUM"] != "Keep real", (
        "SUM is assigned here, so it is this source's variable, not the intrinsic")


def test_a_declared_array_named_size_is_not_demoted():
    """An explicit declaration wins, as it already did for the shorter list."""
    source = "      REAL*8 SIZE(6)\n      SIZE(1) = DSTRAN(1)\n"
    roles = _roles(source, [{"variable_name": "SIZE", "detected_type": "real*8",
                             "detected_shape": "6", "detected_usage": ["read", "write"]}])
    assert roles["SIZE"] != "Keep real"


def test_an_intrinsic_the_classifier_declined_to_judge_is_still_not_promoted():
    """"Unknown" is not an abstention downstream.

    The classifier declines to guess for a name it has only ever seen read,
    and the stress-path promotion that runs afterwards promotes it anyway. So
    MATMUL in "STRESS = MATMUL(DDSDDE, STRAN + DSTRAN)" was classified
    Unknown, promoted, and the call itself renamed -- STRESS_OTI =
    MATMUL_OTI(...) -- which gfortran calls an unclassifiable statement,
    because nothing declares MATMUL_OTI.
    """
    source = ("      SUBROUTINE UMAT(STRESS,DSTRAN,DDSDDE,STRAN)\n"
              "      DIMENSION STRESS(6),DSTRAN(6),DDSDDE(6,6),STRAN(6)\n"
              "      STRESS = MATMUL(DDSDDE, STRAN + DSTRAN)\n"
              "      END\n")
    roles = _roles(source, [{"variable_name": "MATMUL", "detected_type": "unknown",
                             "detected_usage": ["read"]}])
    assert roles["MATMUL"] == "Keep real"


def test_a_declared_variable_the_classifier_calls_unknown_is_left_alone():
    """The widening must not reach a name the source actually declares."""
    source = "      REAL*8 SUM(6)\n      SUM(1) = DSTRAN(1)\n"
    roles = _roles(source, [{"variable_name": "SUM", "detected_type": "real*8",
                             "detected_shape": "6", "detected_usage": ["read", "write"]}])
    assert roles["SUM"] != "Keep real"
