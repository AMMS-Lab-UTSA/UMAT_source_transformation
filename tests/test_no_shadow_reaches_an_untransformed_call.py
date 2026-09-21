"""A hypercomplex value handed to a routine that still takes REALs.

Fortran's implicit interface makes it compile. gfortran emits at most
-Wargument-mismatch and exits 0, so the file is reported as a successful
transformation -- and the callee then reads an ONUMM element, seven doubles,
as a single REAL and computes the whole constitutive response on
reinterpreted memory. One discovered source returned a wrong stress and a NaN
tangent that way with all seventeen semantic checks passing.
"""
from __future__ import annotations

import pytest

from umat_oti.transform.source_transform import (
    oti_arguments_into_untransformed_calls as leaks,
)

SOURCE = (
    "      SUBROUTINE UMAT(STRESS)\n"
    "      CALL CALCDET33(DFGRD1_OTI, DETJ)\n"
    "      CALL KCLEAR(A_OTI, 3, 3)\n"
    "      CALL MYHELPER(STRESS_OTI)\n"
    "C     CALL COMMENTED(X_OTI)\n"
    "      CALL PLAIN(STRESS)\n"
    "      END\n"
    "      SUBROUTINE MYHELPER(S)\n"
    "      TYPE(ONUMM6N1) :: S(6)\n"
    "      END\n")

#: The same file with MYHELPER left as the author wrote it -- defined here,
#: and never rewritten to the hypercomplex type.
SOURCE_WITH_AN_UNTRANSFORMED_SIBLING = SOURCE.replace(
    "      TYPE(ONUMM6N1) :: S(6)\n", "      IMPLICIT REAL*8(A-H,O-Z)\n")


def _names(source, lifted=None):
    return {callee for callee, _ in leaks(source, "fixed", lifted or set())}


class TestWhatCounts:
    def test_an_external_callee_taking_a_shadow_is_reported(self):
        assert "CALCDET33" in _names(SOURCE)

    def test_the_argument_is_named_too_so_the_message_can_say_which(self):
        assert ("CALCDET33", "DFGRD1_OTI") in leaks(SOURCE, "fixed", set())

    def test_a_routine_defined_in_the_same_file_and_rewritten_with_it_is_safe(self):
        assert "MYHELPER" not in _names(SOURCE)

    def test_a_routine_defined_in_the_same_file_but_not_rewritten_is_reported(self):
        """"Defined here" was being read as "transformed here", and is not.

        A helper the lift did not take keeps its REAL body and sits in the
        transformed file beside the UMAT, whose CALL to it has been rewritten
        to hand it hypercomplex arrays. Measured on a six-component linear
        elastic UMAT whose shear terms live in such a helper: the transform
        reported success with no blockers and no warnings, gfortran exited 0,
        and the converted build returned STRESS = (2.8e-2, 0, 0, 0, 0, 0)
        against (2.8e-2, 5.6e-2, 8.4e-2, 3.2e-2, 4.0e-2, 4.8e-2) and a DDSDDE
        whose only non-zero entry was (1,1) = 2.8e+02. Eleven of the 250
        sources the transform store held as successful are in this shape, six
        of them recorded as compiling cleanly.
        """
        assert "MYHELPER" in _names(SOURCE_WITH_AN_UNTRANSFORMED_SIBLING)

    def test_an_inlineable_helper_is_safe(self):
        """No call survives inlining, so there is nothing to mismatch."""
        assert "KCLEAR" not in _names(SOURCE)

    def test_a_call_with_no_shadow_argument_is_not_reported(self):
        assert "PLAIN" not in _names(SOURCE)

    def test_a_commented_call_is_not_a_call(self):
        assert "COMMENTED" not in _names(SOURCE)


class TestWhatIsAlreadySafe:
    """The rewritten call is the safe case, and must not read as the unsafe one."""

    REWRITTEN = ("      SUBROUTINE UMAT(STRESS)\n"
                 "      CALL DETMATRIX_OTI(F_OTI, DETF_OTI)\n"
                 "      END\n")

    def test_a_call_pointed_at_a_lifted_body_is_safe(self):
        assert _names(self.REWRITTEN, {"DETMATRIX"}) == set()

    def test_without_the_suffix_rule_every_lifted_helper_would_be_condemned(self):
        """Guards the fix: the lifted set holds original names, not _OTI ones."""
        assert "DETMATRIX_OTI" not in _names(self.REWRITTEN, {"DETMATRIX"})

    def test_a_suffixed_call_to_something_never_lifted_is_still_reported(self):
        assert "MYSTERY_OTI" in _names(
            "      CALL MYSTERY_OTI(A_OTI)\n", set())


def test_a_lifted_helper_named_directly_is_safe():
    assert _names("      CALL KHELPER(A_OTI)\n", {"KHELPER"}) == set()


def test_every_leak_is_reported_once_per_callee_and_argument():
    source = ("      CALL EXT(A_OTI)\n" * 3) + "      CALL EXT(B_OTI)\n"
    found = leaks(source, "fixed", set())
    assert sorted(found) == [("EXT", "A_OTI"), ("EXT", "B_OTI")]


@pytest.mark.parametrize("define_helper", [False, True])
def test_missing_helper_stops_the_pipeline_before_code_generation(tmp_path, define_helper):
    from umat_oti.services.jacobian_request import run_jacobian_transform

    source = tmp_path / "missing_helper.f90"
    text = """subroutine umat(stress, dstran, ddsdde, ntens)
implicit none
integer :: ntens, component
real(8) :: stress(ntens), dstran(ntens), ddsdde(ntens,ntens)
do component = 1, ntens
  stress(component) = stress(component) + dstran(component)
    call material_update(stress, dstran, ntens)
end do
ddsdde = 0.0d0
end subroutine umat
"""
    if define_helper:
        text += """subroutine material_update(stress, dstran, ntens)
implicit none
integer :: ntens
real(8) :: stress(ntens), dstran(ntens)
call missing_dependency(stress, dstran, ntens)
end subroutine material_update
"""
    source.write_text(text, encoding="utf-8")
    output = tmp_path / "out"
    run = run_jacobian_transform(source, output, ntens=6, compile_generated=True)

    assert not run.succeeded
    missing = "MISSING_DEPENDENCY" if define_helper else "MATERIAL_UPDATE"
    assert any(missing in message for message in run.report["blockers"])
    assert run.report["generated_files"] == []
    assert not list(output.glob("*.f90"))
    assert not (output / "compile_hint.sh").exists()
    assert run.transformed_source is None
    assert run.drop_in_source is None
    assert not any("pass-through used" in message for message in run.report["warnings"])


class TestTheAbaqusUtilityExemption:
    """Only the routines that report, and only because a message is bounded."""

    def test_a_diagnostic_utility_does_not_cost_a_whole_umat(self):
        assert _names("      CALL STDB_ABQERR(-1,'bad',INTV,STRESS_OTI,CHARV)\n",
                      set()) == set()

    @pytest.mark.parametrize("callee", ["SPRINC", "SPRIND", "SINV", "ROTSIG"])
    def test_a_utility_that_returns_into_the_stress_path_is_still_reported(self, callee):
        """These hand back principal stresses, invariants and rotated tensors.

        Exempting them would hide a truncated derivative, which is the defect
        this check exists to find -- not a garbled message.
        """
        assert callee in _names(f"      CALL {callee}(STRESS_OTI, PS, LSTR, NDI, NSHR)\n",
                                set())

    def test_an_unknown_external_routine_is_not_exempted_by_looking_official(self):
        assert "GETSOMETHINGELSE" in _names(
            "      CALL GETSOMETHINGELSE(STRESS_OTI)\n", set())
