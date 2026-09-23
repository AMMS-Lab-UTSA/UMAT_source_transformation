"""COMMON blocks and repeated constants, as a lifted helper must handle them.

Both cases come from compiling an anisotropic viscoplastic UMAT whose
helpers share seven COMMON blocks with the UMAT, and one of whose routines
declares two constants that its own INCLUDE declares again. Each is paired
here with the neighbouring construct that must still be rewritten.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from umat_oti.fortran.parser import parse_fortran_file
from umat_oti.oti.module_generator import generate_otilib_module
from umat_oti.transform.helper_lifting import (
    HelperLiftingError,
    lift_helper_set_source,
)
from umat_oti.transform.parameter_sensitivity_transform import _emit_intrinsic_extensions


def _lift(source_path):
    return lift_helper_set_source(
        parse_fortran_file(source_path), ["SHARED"],
        module_name="otim14n1", type_name="ONUMM14N1").source


def test_a_common_member_keeps_the_type_the_block_was_laid_out_with(tmp_path):
    """A COMMON block is storage two routines agree on.

    The UMAT keeps its half real, because the main transform refuses to
    promote a name in a COMMON block. A lifted helper that promoted its half
    would be describing the same bytes as a different type -- and gfortran
    stops before that, because a derived type in COMMON needs SEQUENCE.
    """
    source = tmp_path / "shared.f90"
    source.write_text("""subroutine shared(value)
      real(8) :: value
      real(8) :: fld_dia(4), scratch(4)
      real(8) :: coeffsY0
      integer :: counter
      COMMON/fieldStats/ fld_dia, coeffsY0
      COMMON/counters/ counter
      scratch = fld_dia*value
      value = scratch(1) + coeffsY0 + counter
      end subroutine shared
""")
    lifted = _lift(source)

    # The shared names keep the block's own type ...
    assert "real(8) :: fld_dia(4)" in lifted
    assert "real(8) :: coeffsY0" in lifted
    # ... and the local declared on the same statement is still promoted.
    assert "type(ONUMM14N1) :: scratch(4)" in lifted
    # COMMON is a specification statement, so it precedes the executable part.
    assert lifted.index("COMMON/fieldStats/") < lifted.index("scratch = ")
    assert "type(ONUMM14N1) :: fld_dia" not in lifted


def test_a_common_member_the_source_never_declared_is_not_typed_by_the_implicit_rule(tmp_path):
    """The lifted body says "implicit type(OTI) (a-h,o-z)".

    An undeclared COMMON member falls under that rule and lands back in the
    block as a derived type, which is the same defect by another route.
    """
    source = tmp_path / "shared.f90"
    source.write_text("""subroutine shared(value)
      real(8) :: value
      COMMON/fieldStats/ dia_mean, area(3)
      value = dia_mean + area(1)
      end subroutine shared
""")
    lifted = _lift(source)
    assert "real(8) :: dia_mean" in lifted
    assert "real(8) :: area(3)" in lifted


def test_a_lifted_helper_and_its_caller_agree_about_the_block(tmp_path):
    """The pair compiled together, which is the only check that settles it."""
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required for the shared-storage compile check")
    source = tmp_path / "shared.f90"
    source.write_text("""subroutine shared(value)
      real(8) :: value
      real(8) :: fld_dia(4)
      COMMON/fieldStats/ fld_dia
      value = fld_dia(1)*value
      end subroutine shared
""")
    lifted = _lift(source)
    module = generate_otilib_module(output_dir=tmp_path, ntens=14)
    (tmp_path / "oti_intrinsics.f90").write_text(
        _emit_intrinsic_extensions(module.module_name, module.type_name))
    (tmp_path / "helper.f90").write_text(lifted)
    # The caller keeps the block real, exactly as the main transform leaves it.
    (tmp_path / "caller.f90").write_text("""subroutine caller()
      real(8) :: fld_dia(4)
      COMMON/fieldStats/ fld_dia
      fld_dia = 1.d0
      end subroutine caller
""")
    built = subprocess.run(
        ["gfortran", "-c", "-ffree-line-length-none",
         str(module.master_parameters_path), str(module.real_utils_path),
         str(module.module_path), "oti_intrinsics.f90", "caller.f90", "helper.f90"],
        cwd=tmp_path, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr


def test_a_constant_declared_twice_over_is_declared_once(tmp_path):
    """A routine may declare a constant and INCLUDE a file that declares it again.

    Repeating a definition verbatim says nothing new, so the repeat is
    dropped; without that gfortran stops on "Symbol already has basic type".
    """
    source = tmp_path / "shared.f90"
    (tmp_path / "constants.inc").write_text(
        "      real(8), parameter :: REF_LEN=2.5d0\n"
        "      real(8), parameter :: REF_STRESS = 4.0d0\n")
    source.write_text("""subroutine shared(value)
      real(8) :: value
      real(8), parameter :: REF_LEN=2.5d0
      include 'constants.inc'
      value = value/REF_LEN*REF_STRESS
      end subroutine shared
""")
    lifted = _lift(source)
    assert lifted.count("REF_LEN=2.5d0") == 1
    # The constant that was only declared once is still declared.
    assert "REF_STRESS = 4.0d0" in lifted


def test_two_different_values_for_one_constant_are_refused_rather_than_resolved(tmp_path):
    """Which value the routine means is not something the transform can decide."""
    source = tmp_path / "shared.f90"
    (tmp_path / "constants.inc").write_text(
        "      real(8), parameter :: REF_LEN=99.0d0\n")
    source.write_text("""subroutine shared(value)
      real(8) :: value
      real(8), parameter :: REF_LEN=2.5d0
      include 'constants.inc'
      value = value/REF_LEN
      end subroutine shared
""")
    with pytest.raises(HelperLiftingError, match="REF_LEN"):
        _lift(source)


def test_a_name_used_only_as_a_subscript_is_not_promoted(tmp_path):
    """A subscript is a position in an array, so it carries no derivative.

    One UMAT indexes its state array with a name declared nowhere.
    The source's implicit rule made it REAL, which Fortran accepts as a
    subscript; the lifted body's ``implicit type(OTI) (a-h,o-z)`` made it
    hypercomplex, which gfortran rejects with "Array index must be of INTEGER
    type, found DERIVED".
    """
    source = tmp_path / "shared.f90"
    source.write_text("""subroutine shared(value, state)
      real(8) :: value, state(8)
      state(posStress) = value
      value = value*2.d0
      end subroutine shared
""")
    lifted = _lift(source)
    assert "real(8) :: posstress" in lifted.lower()
    assert "type(ONUMM14N1) :: posStress" not in lifted


def test_a_name_that_is_also_a_value_is_still_promoted(tmp_path):
    """The paired case: a name is only an index if that is all the source does
    with it. ``weight`` indexes an array here and is also arithmetic, so it
    carries a derivative and must keep the differentiated type."""
    source = tmp_path / "shared.f90"
    source.write_text("""subroutine shared(value, state)
      real(8) :: value, state(8)
      weight = value*3.d0
      value = state(1) + weight
      end subroutine shared
""")
    lifted = _lift(source)
    assert "real(8) :: weight" not in lifted.lower()


def test_the_main_transform_drops_a_constant_its_own_include_repeats(tmp_path):
    """The same rule as the lifted helpers, on the transformed UMAT itself.

    The UMAT keeps its INCLUDE statements and lets the compiler expand them,
    so a routine that declares a constant inline and includes a file declaring
    the same one gets it twice. The inline copy is commented out rather than
    deleted, because the include is shared with routines that have no
    declaration of their own.
    """
    from umat_oti.transform.source_transform import _drop_constants_an_include_repeats

    (tmp_path / "constants.inc").write_text(
        "      real(8), parameter :: REF_LEN=2.5d0\n")
    source = """      subroutine scaleByConstants(value)
      real(8) :: value
      real(8), parameter :: REF_LEN=2.5d0
      INCLUDE 'constants.inc'
      value = value/REF_LEN
      end subroutine scaleByConstants
"""
    rewritten, notes = _drop_constants_an_include_repeats(source, tmp_path)
    assert "! UMAT-OTI: real(8), parameter :: REF_LEN=2.5d0" in rewritten
    assert "INCLUDE 'constants.inc'" in rewritten
    assert notes and "REF_LEN" in notes[0]


def test_a_constant_no_include_repeats_is_untouched(tmp_path):
    from umat_oti.transform.source_transform import _drop_constants_an_include_repeats

    (tmp_path / "constants.inc").write_text(
        "      real(8), parameter :: REF_STRESS=4.0d0\n")
    source = """      subroutine scaleByConstants(value)
      real(8) :: value
      real(8), parameter :: REF_LEN=2.5d0
      INCLUDE 'constants.inc'
      value = value/REF_LEN*REF_STRESS
      end subroutine scaleByConstants
"""
    rewritten, notes = _drop_constants_an_include_repeats(source, tmp_path)
    assert "! UMAT-OTI:" not in rewritten
    assert notes == []


def test_a_different_value_for_the_same_name_is_left_for_the_compiler(tmp_path):
    """Two values for one constant is a contradiction the transform must not
    resolve by picking one."""
    from umat_oti.transform.source_transform import _drop_constants_an_include_repeats

    (tmp_path / "constants.inc").write_text(
        "      real(8), parameter :: REF_LEN=99.0d0\n")
    source = """      subroutine scaleByConstants(value)
      real(8) :: value
      real(8), parameter :: REF_LEN=2.5d0
      INCLUDE 'constants.inc'
      value = value/REF_LEN
      end subroutine scaleByConstants
"""
    rewritten, notes = _drop_constants_an_include_repeats(source, tmp_path)
    assert "! UMAT-OTI:" not in rewritten
    assert notes == []


def test_an_intrinsic_name_inside_a_string_is_not_a_variable(tmp_path):
    """The paired case for the USE-clause rename.

    A WRITE of " - max increment:" mentions no variable called MAX, and
    renaming MAX on that took the overload away from a routine whose every
    use of it was an ordinary call.
    """
    from umat_oti.transform.helper_lifting import intrinsic_renames

    assert intrinsic_renames([
        "write(*,*) ' - max increment:', maxval(abs(F_tau))",
        "TolStress = max(RelTolStress*vm2ndPK,minTolStress)",
    ]) == ""


def test_an_intrinsic_name_used_as_data_is_renamed_on_import(tmp_path):
    """UMAT_HIN's LU decomposition reads a variable it calls TINY. Imported
    unqualified, that name is the module's generic and gfortran answers
    "Cannot assign to a named constant"."""
    from umat_oti.transform.helper_lifting import intrinsic_renames

    assert intrinsic_renames(
        ["IF(A(J,J).EQ.0.0D0) A(J,J)=TINY"]) == ", OTI_TINY => TINY"


def test_a_constant_passed_to_an_oti_dummy_is_promoted(tmp_path):
    """Two lifted helpers must agree about the type of an argument.

    Each is lifted on its own, so the two ends are decided independently: a
    PARAMETER stays REAL where it is declared (real times hypercomplex is an
    overload the module has), while the callee that receives it has no
    declaration of its own and takes ``implicit type(OTI) (a-h,o-z)``. The
    helpers of one viscoplastic UMAT do this twice; the callee reads 96
    doubles where one was written, and the program aborts inside free().
    """
    from umat_oti.transform.helper_lifting import reconcile_helper_argument_types

    body = """subroutine caller_oti(x)
    use otim95n1, OTI_HELPER_DP => DP
    use oti_intrinsics
    implicit type(ONUMM95N1) (a-h,o-z)
    implicit integer (i-n)
    real(8), parameter :: TOL_A=0.005d0
    x = x*2.0D0
    call callee_oti(x, TOL_A)
end subroutine caller_oti

subroutine callee_oti(a, tol_a)
    use otim95n1, OTI_HELPER_DP => DP
    use oti_intrinsics
    implicit type(ONUMM95N1) (a-h,o-z)
    implicit integer (i-n)
    type(ONUMM95N1) :: a, TOL_A
    a = a + TOL_A
end subroutine callee_oti
"""
    out = reconcile_helper_argument_types(body, "ONUMM95N1")
    assert "type(ONUMM95N1) :: OTI_CONST_TOL_A" in out
    assert "call callee_oti(x, OTI_CONST_TOL_A)" in out
    # The constant keeps its own type for the arithmetic around it ...
    assert "real(8), parameter :: TOL_A=0.005d0" in out
    # ... and the copy is set in the executable part, not among declarations.
    assign = out.upper().index("OTI_CONST_TOL_A = TOL_A")
    assert assign > out.upper().index("X = X*2.0D0")


def test_a_constant_whose_dummy_is_already_real_is_left_alone(tmp_path):
    """The paired case: no mismatch, no promotion."""
    from umat_oti.transform.helper_lifting import reconcile_helper_argument_types

    body = """subroutine caller_oti(x)
    use oti_intrinsics
    implicit type(ONUMM95N1) (a-h,o-z)
    implicit integer (i-n)
    real(8), parameter :: nsteps_tol=0.005d0
    call callee_oti(x, nsteps_tol)
end subroutine caller_oti

subroutine callee_oti(a, nsteps_tol)
    use oti_intrinsics
    implicit type(ONUMM95N1) (a-h,o-z)
    implicit integer (i-n)
    type(ONUMM95N1) :: a
    real(8) :: nsteps_tol
    a = a + nsteps_tol
end subroutine callee_oti
"""
    out = reconcile_helper_argument_types(body, "ONUMM95N1")
    assert "OTI_CONST_" not in out


def test_a_named_constant_is_never_promoted():
    """A PARAMETER cannot be assigned, so its shadow never gets the value.

    The same defect the DATA guard exists to stop, by the other spelling a
    Fortran constant has. the model scales its crack-initiation stress by
    ``REF_STRESS = 4.0d0`` and ``REF_AREA = 0.5d0``; promoted, REF_STRESS_OTI
    was declared, set to 0.0D0 and then divided by. Every semantic check
    passed and the first increment reaching the expression divided by zero,
    which arrived as a NaN in the stress Newton and cut the increment back
    forever.
    """
    from umat_oti.core.roles import parameter_constant_names

    source = """      real(8), parameter :: REF_STRESS = 4.0d0
      real(8), parameter :: REF_AREA = 0.5d0
      real(8), parameter :: REF_LEN=2.5d0, REF_VOL=1.0d6
      integer, parameter :: indicesTensorToVoigt(3,3) = reshape((/1,4,5/),(/3,3/))
      REAL TWO, HALF
      PARAMETER (TWO = 2.0D0, HALF = 0.5D0)
      real(8) :: stressScale
"""
    found = parameter_constant_names(source)
    assert {"REF_STRESS", "REF_AREA", "REF_LEN", "REF_VOL",
            "INDICESTENSORTOVOIGT", "TWO", "HALF"} <= found
    # The paired case: an ordinary variable is not a constant.
    assert "STRESSSCALE" not in found


def test_a_commented_parameter_is_not_a_constant():
    """The declaration that is not there. A commented-out PARAMETER keeps a
    live variable of the same name out of the differentiated set otherwise."""
    from umat_oti.core.roles import parameter_constant_names

    assert parameter_constant_names(
        "!     real(8), parameter :: REF_STRESS = 4.0d0\n") == frozenset()


def test_a_constant_declared_in_an_include_is_still_a_constant(tmp_path):
    """Every guard in roles.py works by finding a declaration, and the
    transform leaves INCLUDE statements for the compiler to expand -- so a
    declaration written in an include was invisible to all of them.

    One viscoplastic UMAT keeps two scaling constants in an include. Both were
    promoted and their shadows divided by while still zero.
    """
    from umat_oti.core.roles import parameter_constant_names, source_text_with_includes

    (tmp_path / "constants.inc").write_text(
        "      real(8), parameter :: REF_STRESS = 4.0d0\n"
        "      real(8), parameter :: REF_AREA = 0.5d0\n")
    source = "      SUBROUTINE X()\n      INCLUDE 'constants.inc'\n      END\n"
    seen = parameter_constant_names(source_text_with_includes(source, tmp_path))
    assert {"REF_STRESS", "REF_AREA"} <= seen
    # Without the expansion the classifier sees nothing, which is the bug.
    assert parameter_constant_names(source) == frozenset()


def test_a_commented_include_is_not_expanded(tmp_path):
    from umat_oti.core.roles import parameter_constant_names, source_text_with_includes

    (tmp_path / "constants.inc").write_text("      real(8), parameter :: REF_STRESS = 4.0d0\n")
    assert parameter_constant_names(source_text_with_includes(
        "!     INCLUDE 'constants.inc'\n", tmp_path)) == frozenset()


def test_a_missing_include_is_skipped_not_raised(tmp_path):
    from umat_oti.core.roles import source_text_with_includes

    source = "      INCLUDE 'nowhere.inc'\n"
    assert source_text_with_includes(source, tmp_path) == source
