"""A Fortran real literal is one token, and no rewrite may reach inside it.

``1.d-12`` is a number. Read character by character it also looks like a digit,
a dot, a name, a minus sign and two more digits, and every rewrite this package
performs on source text works character by character. The consequence was
reported by gfortran on an externally authored source:

    XTOL_OTI = 1.D_OTI-12
    Error: Missing exponent in real number

from ``xtol = 1.d-12``, because that model calls a variable ``D`` and ``D`` was
being shadowed. The same hole had been opened before by the integer promoter,
which read the exponent digits of ``1.0D-6`` as a bare integer factor.

These tests hold the property rather than the two literals that exposed it: the
name being substituted is never special-cased here, and every shape a Fortran
real literal can take -- with and without a leading digit, with and without an
exponent, signed and unsigned, upper and lower case -- is checked against a
variable name that collides with its interior.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from umat_oti.fortran.literals import (
    atomic_real_literals,
    mask_real_literals,
    unmask_real_literals,
    without_real_literals,
)
from umat_oti.transform.helper_lifting import direction_renames
from umat_oti.transform.parameter_sensitivity_transform import (
    _colliding_direction_names,
)
from umat_oti.transform.source_transform import (
    _is_promoted_branch_line,
    _normalize_numeric_literals_in_oti_expression as _normalize,
    _replace_role_references,
)

#: Every shape a Fortran real literal takes, paired with the variable name that
#: its interior spells. None of these names is hypothetical: D is damage, E is a
#: modulus, D0 and E1 are initial values and moduli, and E2 is a second modulus.
LITERAL_AND_COLLIDING_NAME = [
    ("1.d-12", "D"),
    ("1.0D-6", "D"),
    ("3.8e-6", "E"),
    ("1.5E+8", "E"),
    (".5d0", "D0"),
    ("2.D0", "D0"),
    ("1.E2", "E2"),
    ("1.e-6", "E"),
    ("240.", "D"),
]


class TestRoleSubstitutionLeavesLiteralsAlone:
    """``_replace_role_references`` is the path that broke."""

    def test_the_reported_statement(self):
        """mholla/growth umats/umat_area_stretch.f line 77, verbatim."""
        assert _replace_role_references(
            "      xtol = 1.d-12", {"XTOL": "XTOL_OTI", "D": "D_OTI"}
        ) == "      XTOL_OTI = 1.d-12"

    @pytest.mark.parametrize("literal,name", LITERAL_AND_COLLIDING_NAME)
    def test_no_literal_shape_is_entered(self, literal, name):
        line = f"      X = {literal}"
        assert _replace_role_references(line, {name: f"{name}_OTI"}) == line

    @pytest.mark.parametrize("literal,name", LITERAL_AND_COLLIDING_NAME)
    def test_a_real_reference_beside_the_literal_is_still_rewritten(self, literal, name):
        """Atomicity must not cost the substitution its job."""
        assert _replace_role_references(
            f"      X = {name}*{literal}", {name: f"{name}_OTI"}
        ) == f"      X = {name}_OTI*{literal}"

    def test_the_case_of_the_literal_is_preserved(self):
        """Restored from the captured text, not re-emitted."""
        assert _replace_role_references(
            "      A = 1.d-12 + 2.D0 + 3.e5", {"D": "D_OTI", "D0": "D0_OTI"}
        ) == "      A = 1.d-12 + 2.D0 + 3.e5"

    def test_several_literals_on_one_line_are_all_restored(self):
        assert _replace_role_references(
            "      A = D*1.d-12 + D*2.5D-3 + D*4.0", {"D": "D_OTI"}
        ) == "      A = D_OTI*1.d-12 + D_OTI*2.5D-3 + D_OTI*4.0"

    def test_an_array_subscript_is_not_a_literal(self):
        assert _replace_role_references(
            "      A = D(1)+E(2)", {"D": "D_OTI", "E": "E_OTI"}
        ) == "      A = D_OTI(1)+E_OTI(2)"


class TestSeedScansSeeNoNameInsideALiteral:
    """A rename decided by a scan is as wrong as one applied by a rewrite."""

    def test_a_branch_on_a_tolerance_mentions_no_promoted_variable(self):
        assert _is_promoted_branch_line(
            "      IF (ABS(RES).GT.1.D-12) GO TO 200", {"D": "D_OTI"}) is False

    def test_a_branch_on_the_variable_itself_still_counts(self):
        assert _is_promoted_branch_line(
            "      IF (D.GT.1.D-12) GO TO 200", {"D": "D_OTI"}) is True

    def test_a_literal_is_not_a_use_of_a_direction_constant(self):
        assert _colliding_direction_names("      X = 1.E1 + Y\n", 2) == ()
        assert direction_renames("otim2n1", ["      X = 1.E1 + Y"]) == ""

    def test_a_genuine_use_of_a_direction_constant_still_collides(self):
        assert _colliding_direction_names("      E1 = 2.0\n", 2) == ("E1",)
        assert "OTI_E1 => E1" in direction_renames("otim2n1", ["      E1 = 2.0"])


class TestIntegerPromotionStopsAtTheLiteralBoundary:
    """The digits of an exponent are part of the literal, not a factor."""

    @pytest.mark.parametrize("literal", [lit for lit, _ in LITERAL_AND_COLLIDING_NAME])
    def test_no_literal_gains_a_suffix(self, literal):
        line = f"      A_OTI = {literal}*B_OTI"
        # 240. is the one shape the promoter is supposed to complete.
        expected = line.replace("240.*", "240.0D0*")
        assert _normalize(line) == expected

    def test_a_variable_named_like_an_exponent_letter_does_not_block_promotion(self):
        """The lookbehind this replaces was wrong in the other direction too.

        ``(?<![eEdD][+-])`` was added to keep the promoter off exponent digits.
        It reads spelling, not position, so it also fired on ``D-6*Y_OTI`` --
        an ordinary variable D, minus six times Y -- and left an INTEGER factor
        the OTI library has no overload for.
        """
        assert _normalize("      A_OTI = D-6*Y_OTI") == "      A_OTI = D-6.0D0*Y_OTI"
        assert _normalize("      A_OTI = E+3*Y_OTI") == "      A_OTI = E+3.0D0*Y_OTI"

    def test_a_genuine_integer_factor_is_still_promoted(self):
        assert _normalize("A_OTI = 2*PI*X_OTI") == "A_OTI = 2.0D0*PI*X_OTI"
        assert _normalize("A_OTI = X_OTI/4") == "A_OTI = X_OTI/4.0D0"

    def test_an_integer_factor_next_to_a_literal_is_promoted(self):
        assert _normalize("A_OTI = 1.5D-8*3*B_OTI") == "A_OTI = 1.5D-8*3.0D0*B_OTI"


class TestTheMaskItself:
    def test_masking_then_unmasking_is_the_identity(self):
        text = "      A = 1.d-12 + .5D0*B - 3.8e-6/2.D0 + 4. + 7"
        masked, store = mask_real_literals(text)
        assert unmask_real_literals(masked, store) == text

    def test_a_placeholder_is_neither_a_name_nor_a_number(self):
        masked = without_real_literals("      X = 1.d-12")
        assert "d" not in masked and "12" not in masked
        assert "X" in masked

    def test_an_identifier_ending_in_digits_is_not_a_literal(self):
        assert without_real_literals("      X2 = Y2") == "      X2 = Y2"

    def test_the_decorator_passes_the_remaining_arguments_through(self):
        @atomic_real_literals
        def shout(text: str, suffix: str) -> str:
            return text.replace("d", suffix)

        assert shout("a = 1.d-12 and d", "!") == "a = 1.d-12 an! !"


DAMAGE_UMAT = """\
      SUBROUTINE UMAT(STRESS, STATEV, DDSDDE, SSE, SPD, SCD, RPL,
     1 DDSDDT, DRPLDE, DRPLDT, STRAN, DSTRAN, TIME, DTIME, TEMP,
     2 DTEMP, PREDEF, DPRED, CMNAME, NDI, NSHR, NTENS, NSTATV, PROPS,
     3 NPROPS, COORDS, DROT, PNEWDT, CELENT, DFGRD0, DFGRD1, NOEL,
     4 NPT, LAYER, KSPT, KSTEP, KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS), STATEV(NSTATV), DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS), DRPLDE(NTENS), STRAN(NTENS), DSTRAN(NTENS),
     2 TIME(2), PREDEF(1), DPRED(1), PROPS(NPROPS), COORDS(3),
     3 DROT(3,3), DFGRD0(3,3), DFGRD1(3,3)
      XTOL = 1.D-12
      EMOD = PROPS(1)
      ENU = PROPS(2)
      EG = EMOD/(2.0D0*(1.0D0+ENU))
      ELAM = EMOD*ENU/((1.0D0+ENU)*(1.0D0-2.0D0*ENU))
      D = STATEV(1)
      IF (D .LT. XTOL) D = 0.0D0
      DO K1 = 1, NTENS
        DO K2 = 1, NTENS
          DDSDDE(K2,K1) = 0.0D0
        END DO
      END DO
      DO K1 = 1, NDI
        DO K2 = 1, NDI
          DDSDDE(K2,K1) = ELAM
        END DO
        DDSDDE(K1,K1) = ELAM + 2.0D0*EG
      END DO
      DO K1 = NDI+1, NTENS
        DDSDDE(K1,K1) = EG
      END DO
      DO K1 = 1, NTENS
        DO K2 = 1, NTENS
          STRESS(K1)=STRESS(K1)+DDSDDE(K1,K2)*DSTRAN(K2)
        END DO
      END DO
      DO K1 = 1, NTENS
        STRESS(K1) = (1.0D0-D)*STRESS(K1)
      END DO
      STATEV(1) = D
      RETURN
      END
"""


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_umat_with_a_variable_named_D_and_a_D_exponent_compiles(tmp_path):
    """The whole point: gfortran, not a string comparison, settles this.

    A scalar damage variable called ``D`` and a convergence tolerance written
    ``1.D-12`` are both everyday UMAT idioms, and together they produced
    ``XTOL_OTI = 1.D_OTI-12``. Nothing downstream re-read the emitted text, so
    the run was reported as a completed transformation.
    """
    from umat_oti.app.engine import _build_contract
    from umat_oti.corpus.cli import _write_aba_param_stub
    from umat_oti.services.transformation import (
        TransformationOptions, run_transformation,
    )

    work = tmp_path / "work"
    work.mkdir()
    _write_aba_param_stub(work)
    source = work / "damage.f"
    source.write_text(DAMAGE_UMAT, encoding="utf-8")

    config, _finite = _build_contract("damage", "auto", "STRESS", "DDSDDE", 6, 1, source)
    contract_path = work / "contract.json"
    contract_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    assert "D" in config["variables"]["promote"], "the fixture must shadow D to be a test"

    out = work / "out"
    out.mkdir()
    _write_aba_param_stub(out)
    report, _code = run_transformation(
        contract_path, out, TransformationOptions(compile_generated=True))

    emitted = Path(report["transformed_source"]).read_text(encoding="utf-8")
    assert "1.D-12" in emitted, "the literal was rewritten"
    assert "D_OTI-12" not in emitted
    assert report["compilation"]["status"] == "compiled", report["compilation"]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_gfortran_agrees_that_the_broken_form_is_not_fortran(tmp_path):
    """Pins what the defect cost, so the fixture above is not merely a habit."""
    broken = tmp_path / "broken.f"
    broken.write_text("      SUBROUTINE S(X)\n      X = 1.D_OTI-12\n      RETURN\n      END\n",
                      encoding="utf-8")
    finished = subprocess.run(
        ["gfortran", "-fsyntax-only", "-ffixed-form", str(broken)],
        capture_output=True, text=True, cwd=tmp_path)
    assert finished.returncode != 0
    assert "exponent" in finished.stderr.lower()


class TestACharacterLiteralIsNotCode:
    """Text the author wrote for a reader is not a reference to anything.

    Harmless-looking, because the usual case is a diagnostic message. Not
    harmless when the string is compared: a UMAT that switches on CMNAME with
    IF (CMNAME(1:6) .EQ. 'ELAST1') stops matching the moment some promoted
    variable happens to be called ELAST1.
    """

    NAMES = {"STRESS": "STRESS_OTI", "DET": "DET_OTI", "ELAST1": "ELAST1_OTI"}

    def _rewrite(self, line: str) -> str:
        from umat_oti.transform.source_transform import _replace_role_references
        return _replace_role_references(line, self.NAMES)

    def test_a_message_keeps_the_words_the_author_wrote(self):
        assert self._rewrite("      WRITE(6,*) 'STRESS is negative'") == (
            "      WRITE(6,*) 'STRESS is negative'")

    def test_a_compared_string_keeps_its_value(self):
        assert self._rewrite("      IF (CMNAME(1:6) .EQ. 'ELAST1') THEN") == (
            "      IF (CMNAME(1:6) .EQ. 'ELAST1') THEN")

    def test_a_double_quoted_string_is_also_left_alone(self):
        assert self._rewrite('      WRITE(6,*) "DET too small"') == (
            '      WRITE(6,*) "DET too small"')

    def test_code_beside_a_string_is_still_rewritten(self):
        """Masking the string must not mask the statement around it."""
        assert self._rewrite("      WRITE(6,*) 'DET too small', DET") == (
            "      WRITE(6,*) 'DET too small', DET_OTI")

    def test_an_embedded_doubled_quote_does_not_end_the_literal_early(self):
        line = "      WRITE(6,*) 'DET''s value is small', DET"
        assert self._rewrite(line) == (
            "      WRITE(6,*) 'DET''s value is small', DET_OTI")

    def test_ordinary_code_is_unaffected(self):
        assert self._rewrite("      STRESS(1) = DET*2.0D0") == (
            "      STRESS_OTI(1) = DET_OTI*2.0D0")

    def test_real_literals_are_still_atomic_alongside_the_string_mask(self):
        assert self._rewrite("      XTOL = 1.d-12") == "      XTOL = 1.d-12"
