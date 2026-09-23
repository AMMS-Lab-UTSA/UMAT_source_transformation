"""What the lifter must and must not rewrite.

Every case here is paired: the rewrite that has to happen, and the neighbouring
construct that must be left alone. All four defects these pin were found by
compiling a real crystal-plasticity UMAT, and each of them looked like a
one-character difference in the generated Fortran.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from umat_oti.fortran.parser import parse_fortran_file, parse_function_subprograms
from umat_oti.oti.module_generator import _guard_pow_at_zero_base
from umat_oti.transform.helper_lifting import (
    _normalize_numeric_literals,
    _routine_callees,
    _strip_fixed_form_comment,
    lift_helper_set_source,
)
from umat_oti.transform.parameter_sensitivity_transform import (
    _closure_including_umat,
    _emit_intrinsic_extensions,
)


def test_lifting_preserves_specification_types_and_basis_collisions(tmp_path):
    import shutil
    import subprocess
    from umat_oti.oti.module_generator import generate_otilib_module

    source = tmp_path / "specs.f90"
    imported = tmp_path / "input_flags.f90"
    imported.write_text("module input_flags\nlogical :: read_fields=.true.\nend module input_flags\n")
    (tmp_path / "positions.inc").write_text("integer, parameter :: position=2\n")
    source.write_text("""subroutine specs(value)
use iso_fortran_env, only: int32
use input_flags, only: should_read => read_fields
implicit none
include 'positions.inc'
real(8) :: value, Ee(2)
logical, parameter :: printErrors = .false.
logical :: enabled(2)
character(len=1), parameter :: UPLO = 'U'
integer(int32), allocatable :: IWORK(:)
allocate(IWORK(2))
IWORK=1
Ee=value
value=Ee(position)
enabled=.true.
if (should_read) should_read=.false.
if (any(enabled) .and. dot_product(Ee,Ee)>0.d0) value=Ee(1)
if (.not.printErrors .and. UPLO == 'U') value=Ee(1)+IWORK(1)
deallocate(IWORK)
end subroutine specs
""")
    lifted = lift_helper_set_source(parse_fortran_file(source), ["SPECS"],
                                    module_name="otim14n1", type_name="ONUMM14N1").source
    assert "logical, parameter :: printErrors = .false." in lifted
    assert "character(len=1), parameter :: UPLO = 'U'" in lifted
    assert "integer(int32), allocatable :: IWORK(:)" in lifted
    assert "OTI_EE => EE" in lifted
    assert "if (should_read) should_read=.false." in lifted
    assert lifted.index("use iso_fortran_env") < lifted.index("implicit type")
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required for compiled declaration check")
    module = generate_otilib_module(output_dir=tmp_path, ntens=14)
    intrinsics = tmp_path / "oti_intrinsics.f90"
    intrinsics.write_text(_emit_intrinsic_extensions(module.module_name, module.type_name))
    helper = tmp_path / "helper.f90"
    helper.write_text(lifted)
    built = subprocess.run(["gfortran", "-c", "-ffree-line-length-none",
                            str(module.master_parameters_path), str(module.real_utils_path),
                            str(module.module_path), str(intrinsics), str(imported), str(helper)],
                           cwd=tmp_path, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    driver = tmp_path / "intrinsics_check.f90"
    driver.write_text("""program intrinsics_check
use otim14n1
use oti_intrinsics
implicit none
type(ONUMM14N1) :: values(2), result_values(2), power_value
real(DP) :: signs(2)
values(1)=-2.0_DP+E1
values(2)=3.0_DP+E1
result_values=abs(values)
if (any(abs(real(result_values)-[2.0_DP,3.0_DP])>1.e-12_DP)) stop 1
if (abs(getim(result_values(1),1)+1.0_DP)>1.e-12_DP) stop 2
if (abs(getim(result_values(2),1)-1.0_DP)>1.e-12_DP) stop 3
signs=sign(1.0_DP,values)
if (any(signs/=[-1.0_DP,1.0_DP])) stop 4
result_values=sign(values,-1.0_DP)
if (abs(getim(result_values(2),1)+1.0_DP)>1.e-12_DP) stop 5
result_values=sign(values,values)
if (abs(getim(result_values(1),1)-1.0_DP)>1.e-12_DP) stop 6
power_value=0.5**values(2)
if (abs(real(power_value)-0.125_DP)>1.e-12_DP) stop 7
if (abs(getim(power_value,1)-0.125_DP*log(0.5_DP))>1.e-12_DP) stop 8
if (tiny(values(1))/=tiny(1.0_DP)) stop 9
end program intrinsics_check
""")
    executable = tmp_path / "intrinsics_check"
    linked = subprocess.run(["gfortran", "-ffree-line-length-none", str(driver),
                             "master_parameters.o", "real_utils.o", f"{module.module_name}.o",
                             "oti_intrinsics.o", "-o", str(executable)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert linked.returncode == 0, linked.stderr
    checked = subprocess.run([str(executable)], cwd=tmp_path, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr


# --------------------------------------------------------------------------
# statement labels are not numeric literals
# --------------------------------------------------------------------------

@pytest.mark.parametrize("statement", ["GO TO 1000", "GOTO 20", "ASSIGN 10 TO LTARG"])
def test_statement_labels_are_not_promoted_to_real_literals(statement: str):
    assert _normalize_numeric_literals(statement, {"TO", "LTARG"}) == statement


@pytest.mark.parametrize(
    "statement,expected",
    [("X = 1", "X = 1.0D0"), ("X = Y*2", "X = Y*2.0D0"), ("X = 3 + Y", "X = 3.0D0 + Y"),
     ("X = Y(1:2*3)", "X = Y(1:2*3)"),
     ("X = reshape(Y,(/3,3/))", "X = reshape(Y,(/3,3/))")],
)
def test_bare_integers_in_expressions_are_still_promoted(statement: str, expected: str):
    assert _normalize_numeric_literals(statement, {"X", "Y"}) == expected


# --------------------------------------------------------------------------
# a bang inside a character literal is not a comment
# --------------------------------------------------------------------------

def test_bang_inside_a_character_literal_is_kept():
    line = "      WRITE (6,*) 'no slip plane!'"
    assert _strip_fixed_form_comment(line) == line


def test_trailing_comment_is_still_stripped():
    assert _strip_fixed_form_comment("      X = Y ! note").rstrip() == "      X = Y"


def test_full_line_comment_is_still_dropped():
    assert _strip_fixed_form_comment("C     commentary") == ""


# --------------------------------------------------------------------------
# function subprograms: lifted, but not where the name means something else
# --------------------------------------------------------------------------

SOURCE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,JSTEP,KINC)
      IMPLICIT REAL*8 (A-H,O-Z)
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 STRAN(NTENS),DSTRAN(NTENS),PROPS(NPROPS)
      EXTERNAL FLOW, XIT
      CALL KHELP(STRESS,PROPS)
      STRESS(1)=FLOW(PROPS(1))
      GO TO 1000
 1000 CONTINUE
      RETURN
      END
      SUBROUTINE KHELP(S,P)
      IMPLICIT REAL*8 (A-H,O-Z)
      DIMENSION S(6),P(2),FLOW(3)
      FLOW(1)=P(1)
      S(1)=FLOW(1)
      WRITE (6,*) 'FLOW(1) is done!'
      RETURN
      END
      REAL*8 FUNCTION FLOW(X)
      IMPLICIT REAL*8 (A-H,O-Z)
      FLOW=2.0D0*X
      RETURN
      END
"""


@pytest.fixture()
def lifted(tmp_path: Path) -> str:
    source = tmp_path / "umat.for"
    source.write_text(SOURCE, encoding="utf-8")
    parsed = parse_fortran_file(source)
    closure = _closure_including_umat(parsed)
    assert set(closure) == {"UMAT", "KHELP", "FLOW"}
    return lift_helper_set_source(
        parsed, closure, module_name="otim2n1", type_name="ONUMM2N1").source


def test_function_subprograms_are_parsed_separately_from_subroutines(tmp_path: Path):
    source = tmp_path / "umat.for"
    source.write_text(SOURCE, encoding="utf-8")
    parsed = parse_fortran_file(source)
    assert [r.upper_name for r in parsed.subroutines] == ["UMAT", "KHELP"]
    assert [f.upper_name for f in parse_function_subprograms(parsed.logical_lines)] == ["FLOW"]


def test_function_reference_pulls_the_definition_into_the_closure(lifted: str):
    assert "function flow_oti(x) result(flow)" in lifted
    assert "type(ONUMM2N1) :: flow" in lifted
    assert "end function flow_oti" in lifted


def test_function_reference_at_the_call_site_is_renamed(lifted: str):
    assert "STRESS(1)=FLOW_OTI(PROPS(1))" in lifted


def test_a_local_array_of_the_same_name_is_left_alone(lifted: str):
    assert "FLOW(1)=P(1)" in lifted
    assert "S(1)=FLOW(1)" in lifted
    assert "FLOW_OTI(1)" not in lifted


def test_a_function_name_inside_a_character_literal_is_left_alone(lifted: str):
    assert "'FLOW(1) is done!'" in lifted


def test_a_lifted_name_is_dropped_from_external_but_a_real_one_is_kept(lifted: str):
    assert "external :: XIT" in lifted
    assert "external :: FLOW" not in lifted


def test_a_statement_label_survives_lifting(lifted: str):
    assert "GO TO 1000" in lifted
    assert "1000.0D0" not in lifted


def test_callee_scan_without_function_names_is_unchanged(tmp_path: Path):
    source = tmp_path / "umat.for"
    source.write_text(SOURCE, encoding="utf-8")
    parsed = parse_fortran_file(source)
    umat = next(r for r in parsed.subroutines if r.upper_name == "UMAT")
    lines = parsed.text.splitlines()
    assert _routine_callees(umat, parsed.form, lines) == ("KHELP",)
    assert _routine_callees(umat, parsed.form, lines,
                            function_names={"FLOW"}) == ("KHELP", "FLOW")


# --------------------------------------------------------------------------
# mixed-kind arithmetic and assignment
# --------------------------------------------------------------------------

def test_intrinsic_extensions_supply_mixed_kind_operators_and_assignment():
    emitted = _emit_intrinsic_extensions("otim6n1", "ONUMM6N1")
    for suffix in ("add", "sub", "mul", "div"):
        for order in ("io", "oi", "so", "os"):
            assert f"FUNCTION oti_{suffix}_{order}(A, B)" in emitted
    assert "INTEGER, INTENT(IN) :: A" in emitted
    assert "REAL(KIND=4), INTENT(IN) :: A" in emitted
    assert "INTERFACE ASSIGNMENT(=)" in emitted
    assert "SUBROUTINE oti_assign_s(RES, LHS)" in emitted
    assert "SUBROUTINE oti_assign_i(RES, LHS)" in emitted
    # widening only: nothing here rounds a value to single precision
    assert "SNGL(" not in emitted
    assert "REAL(A, KIND=4)" not in emitted


# --------------------------------------------------------------------------
# X**Y at a zero base
# --------------------------------------------------------------------------

FIRST_ORDER_POW = """\
  ELEMENTAL FUNCTION ONUMM2N1_POW_OO(X,Y) RESULT(RES)
    REAL(DP) :: DER0_0,DER1_0,DER1_1
    DER0_0 = X%R**Y%R
    DER1_0 = X%R**Y%R*Y%R/X%R
    DER1_1 = X%R**Y%R*LOG(X%R)

    RES = F2EVAL(X,Y,DER0_0,DER1_0,DER1_1)
  END FUNCTION ONUMM2N1_POW_OO
"""


def test_zero_base_power_is_guarded_at_first_order():
    guarded = _guard_pow_at_zero_base(FIRST_ORDER_POW)
    assert "IF (X%R == 0.0_DP) THEN" in guarded
    assert "DER1_0 = Y%R*X%R**(Y%R - 1.0_DP)" in guarded
    # the non-degenerate branch keeps the generator's own expressions, so every
    # evaluation at a non-zero base is bit-for-bit what it was
    assert "DER1_0 = X%R**Y%R*Y%R/X%R" in guarded
    assert "DER1_1 = X%R**Y%R*LOG(X%R)" in guarded


def test_higher_order_power_block_is_left_untouched():
    higher = FIRST_ORDER_POW.replace(
        "    DER1_1 = X%R**Y%R*LOG(X%R)\n",
        "    DER1_1 = X%R**Y%R*LOG(X%R)\n    DER2_0 = X%R**Y%R*Y%R/X%R\n")
    assert _guard_pow_at_zero_base(higher) == higher


def test_a_helper_that_calls_back_into_the_selected_routine_is_refused():
    """The lifted body is OTI-typed and the selected routine is not.

    Letting the call through passes hypercomplex values to REAL dummy
    arguments across an implicit interface: it links, it runs, and it reads
    whatever those words happen to mean as REALs. Nothing downstream would
    notice, so the closure refuses rather than rewriting around it.
    """
    from umat_oti.transform.helper_lifting import HelperLiftingError, helper_lift_closure
    from umat_oti.fortran.parser import logical_lines_from_text, parse_subroutines
    from umat_oti.core.model import ParsedFortranSource
    from pathlib import Path

    text = """\
      SUBROUTINE UMAT(STRESS,DSTRAN,PROPS)
      DIMENSION STRESS(6),DSTRAN(6),PROPS(2)
      CALL KHELPER(STRESS,DSTRAN,PROPS)
      RETURN
      END
      SUBROUTINE KHELPER(S,D,P)
      DIMENSION S(6),D(6),P(2)
      CALL UMAT(S,D,P)
      RETURN
      END
"""
    lines = logical_lines_from_text(text, "fixed")
    parsed = ParsedFortranSource(Path("x.f"), "fixed", text, lines,
                                 parse_subroutines(lines))
    with pytest.raises(HelperLiftingError, match="calls back into UMAT"):
        helper_lift_closure(parsed, ["KHELPER"], selected_umat="UMAT")


FIRST_ORDER_POW_OR = """  FUNCTION ONUMM6N1_POW_OR(X,E) RESULT(RES)
    DER0 = X%R**E
    IF ((E-0)/=0.0d0) THEN
      DER1 = E*X%R**(E - 1)
    END IF
    RES = FEVAL(X,DER0,DER1)
"""


def test_a_real_exponent_power_survives_a_zero_base():
    """SQRT is written X**0.5_DP, so it goes through POW_OR.

    Its first partial at a zero base is 0.5*0**(-0.5) -- Inf -- and FEVAL
    multiplies that by the argument's perturbation. Where the perturbation is
    zero the product is Inf*0 = NaN, and the NaN reaches the primal through
    the norms built on it: one UMAT's stress Newton stopped converging on the
    first plastic increment because an equivalent-strain routine takes the square
    root of a plastic strain that is still exactly zero.
    """
    from umat_oti.oti.module_generator import _guard_pow_or_at_zero_base

    guarded = _guard_pow_or_at_zero_base(FIRST_ORDER_POW_OR)
    assert "IF (.NOT. (ABS(DER1) < HUGE(1.0_DP))) DER1 = 0.0_DP" in guarded
    # The value is untouched, and the partial is still computed the same way;
    # only a non-finite result is dropped.
    assert "DER0 = X%R**E" in guarded
    assert "DER1 = E*X%R**(E - 1)" in guarded


def test_a_power_that_is_already_guarded_is_not_guarded_twice():
    from umat_oti.oti.module_generator import _guard_pow_or_at_zero_base

    once = _guard_pow_or_at_zero_base(FIRST_ORDER_POW_OR)
    assert _guard_pow_or_at_zero_base(once) == once
