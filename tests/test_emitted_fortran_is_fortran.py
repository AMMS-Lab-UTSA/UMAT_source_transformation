"""Defects that produce a file the transform calls successful and gfortran does not.

Nothing downstream re-reads the emitted text, so a statement that is not
Fortran is reported as a completed transformation. Each of these was found by
compiling what the transformer wrote for an externally authored source.
"""
from __future__ import annotations

import pytest

from umat_oti.core.roles import common_block_names
from umat_oti.transform.source_transform import (
    _bound,
    _is_continuation_line,
    _normalize_numeric_literals_in_oti_expression as _normalize,
    _variable_shapes,
)


class TestExponentsAreNotIntegers:
    """The digits of an exponent are part of the literal, not a factor."""

    def test_a_signed_lowercase_exponent_survives(self):
        assert _normalize("F1_OTI = 3.8019047483079793e-6*Sin(X_OTI)") == (
            "F1_OTI = 3.8019047483079793e-6*Sin(X_OTI)")

    def test_a_signed_double_exponent_survives(self):
        assert _normalize("A_OTI = 1.5D-8*B_OTI") == "A_OTI = 1.5D-8*B_OTI"

    def test_a_positive_signed_exponent_survives(self):
        assert _normalize("A_OTI = 1.5E+8*B_OTI") == "A_OTI = 1.5E+8*B_OTI"

    def test_an_unsigned_exponent_was_already_safe(self):
        assert _normalize("A_OTI = 1.0E5*B_OTI") == "A_OTI = 1.0E5*B_OTI"

    def test_a_genuine_integer_factor_is_still_promoted(self):
        """The rule this guard narrows still does its job."""
        assert _normalize("A_OTI = 2*PI*X_OTI") == "A_OTI = 2.0D0*PI*X_OTI"
        assert _normalize("A_OTI = X_OTI/4") == "A_OTI = X_OTI/4.0D0"


class TestACommentIsNeverAContinuation:
    """Column 1 settles it before column 6 is looked at."""

    def test_prose_whose_sixth_character_is_a_letter(self):
        # "C store coordinate from STATEV" -- the "r" of "store" is in column 6.
        assert _is_continuation_line("C store coordinate from STATEV", "fixed") is False

    def test_a_real_continuation_is_still_one(self):
        assert _is_continuation_line("     1 + B", "fixed") is True
        assert _is_continuation_line("     & + B", "fixed") is True

    def test_a_statement_line_is_not_one(self):
        assert _is_continuation_line("      A = B", "fixed") is False

    def test_free_form_ampersand_in_a_comment_does_not_continue(self):
        assert _is_continuation_line("! & not code", "free") is False
        assert _is_continuation_line("     & real continuation", "free") is True


class TestCommonBlockNames:
    def test_a_dimensioned_name_is_found(self):
        assert common_block_names(
            "      COMMON /DLoadUSER/ ReadDetF(NElem, NGauss)") == {"READDETF"}

    def test_the_blank_form_is_read(self):
        assert common_block_names("      COMMON // A, B(3,4)") == {"A", "B"}

    def test_a_block_boundary_separates_names_as_a_comma_does(self):
        assert common_block_names("      COMMON /X/ A, B(3,4) /Y/ C") == {"A", "B", "C"}

    def test_a_commented_common_declares_nothing(self):
        assert common_block_names("C     COMMON /X/ NOPE") == frozenset()
        assert common_block_names("!     COMMON /X/ NOPE") == frozenset()

    def test_a_source_without_common_yields_nothing(self):
        assert common_block_names("      REAL*8 A\n      A = 1.0") == frozenset()

    def test_no_source_text_yields_nothing(self):
        assert common_block_names(None) == frozenset()


class TestTheSourcesOwnBoundIsUsed:
    """NTENS and NSTATV are Abaqus's names, not names a source must use."""

    def _config(self, declared_shape: str) -> dict:
        return {"variable_roles": {
            "STATEV": {"detected_shape": declared_shape, "selected_role": "Promote"}}}

    def test_a_source_that_declares_nstatev_keeps_nstatev(self):
        shapes = _variable_shapes(self._config("NSTATEV"),
                                  {"statev": "STATEV"}, 6)
        assert shapes["STATEV"] == "NSTATEV"

    def test_a_source_that_declares_nothing_falls_back_to_the_convention(self):
        shapes = _variable_shapes(self._config(""), {"statev": "STATEV"}, 6)
        assert shapes["STATEV"] == "NSTATV"

    def test_the_copy_loop_counts_to_the_same_bound(self):
        assert _bound({"STATEV": "NSTATEV"}, "STATEV", "NSTATV") == "NSTATEV"

    def test_a_rank_two_shape_falls_back_rather_than_becoming_a_loop_bound(self):
        """DO OTI_I = 1, "3,3" is not a loop; the convention is the safe answer."""
        assert _bound({"A": "3,3"}, "A", "NSTATV") == "NSTATV"

    def test_an_assumed_size_bound_falls_back(self):
        """DO OTI_I = 1, * is a syntax error, and seven sources produced it."""
        assert _bound({"SVARS": "*"}, "SVARS", "NSTATV") == "NSTATV"


class TestACommonNameIsNotPromoted:
    """Promoting one changes a storage layout shared with routines untouched here."""

    def _roles(self, source_text: str) -> dict[str, str]:
        from umat_oti.core.roles import suggest_variable_roles
        analysis = {
            "detected_variables": [
                {"variable_name": "READDETF", "detected_type": "real",
                 "detected_shape": "NELEM,NGAUSS", "detected_usage": ["write"]},
                {"variable_name": "DETF", "detected_type": "real",
                 "detected_usage": ["read", "write"]},
            ],
            "region_summary": {"stress_path_variables": ["READDETF", "DETF"]},
        }
        return {str(row["variable name"]): str(row["suggested OTIS role"])
                for row in suggest_variable_roles(analysis, source_text)}

    SOURCE = (
        "      SUBROUTINE UMAT(STRESS)\n"
        "      COMMON /DLoadUSER/ ReadDetF(NElem, NGauss)\n"
        "      ReadDetF(NOEL, NPT) = DetF\n"
        "      END\n")

    def test_the_common_name_is_kept_real(self):
        assert self._roles(self.SOURCE)["READDETF"] == "Keep real"

    def test_a_name_outside_the_block_is_unaffected(self):
        assert self._roles(self.SOURCE)["DETF"] != "Keep real"

    def test_without_the_common_statement_it_would_be_promoted(self):
        """The guard is what changes the answer, not the name."""
        without = self.SOURCE.replace(
            "      COMMON /DLoadUSER/ ReadDetF(NElem, NGauss)\n", "")
        assert self._roles(without)["READDETF"] != "Keep real"
