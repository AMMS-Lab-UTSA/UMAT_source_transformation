"""Places where the converted source kept the value and lost the derivative.

Each test here is named for the claim it makes, and each docstring carries the
number that was measured before and after the fix -- from gfortran on this
machine where a compiler settles it, and from the emitted text where the shape
of the statement is the whole of the question.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.fortran.parser import parse_fortran_file  # noqa: E402
from umat_oti.transform.helper_lifting import (  # noqa: E402
    _column_major_subscript,
    _data_to_assignments,
    _free_form_continuation_stitch,
    _integer_do_bounds_over_oti,
    _normalize_numeric_literals,
    _split_inline_if_statement,
    _wrap_oti_rhs_assigned_to_a_plain_variable,
    wrap_free_form,
)
from umat_oti.transform.source_transform import (  # noqa: E402
    GENERICS_THE_TRANSFORM_CALLS_ITSELF,
    _call_lines_reaching,
    _locals_colliding_with_the_oti_modules,
    _module_use_line,
    _overwritten_through_its_call_sites,
    _uncovered_ddsdde_blockers,
    _unsupported_intrinsic_blockers,
)

GFORTRAN = shutil.which("gfortran")
needs_gfortran = pytest.mark.skipif(GFORTRAN is None, reason="gfortran not on PATH")


# ---------------------------------------------------------------------------
# A one-line logical IF read as an assignment to a variable called IF
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.regression
def test_a_one_line_if_does_not_strip_the_derivative_from_the_statement_it_guards():
    """``IF (NSHR .GE. 1) STRESS_OUT(4) = SIGMA(1,2)`` keeps SIGMA whole.

    The assignment-shaped rewrites take a name, an optional parenthesised
    subscript and an ``=``. ``[^=]*`` inside that subscript is greedy enough to
    swallow ``(NSHR .GE. 1) STRESS_OUT(4)`` in one bite, so the target read as
    ``IF`` -- a name no routine holds as hypercomplex -- and the right-hand
    side was wrapped in REAL(), which discards every imaginary part.

    Measured on the emitted helper for
    keisuke58/pde-fem-biofilm/umat_biofilm_visco_phase2.f: before,

        IF (NSHR .GE. 1) STRESS_OUT(4) = REAL(SIGMA(1,2))

    after,

        IF (NSHR .GE. 1) STRESS_OUT(4) = SIGMA(1,2)

    with lines 130-132, whose assignments carry no inline IF, unchanged in
    both.
    """
    oti = {"SIGMA", "STRESS_OUT"}
    guarded = "IF (NSHR .GE. 1) STRESS_OUT(4) = SIGMA(1,2)"
    assert _wrap_oti_rhs_assigned_to_a_plain_variable(guarded, oti) == guarded

    # The conversion the rewrite exists for still happens, guard and all: NSS
    # is not hypercomplex here, so it still takes the real part.
    assert _wrap_oti_rhs_assigned_to_a_plain_variable(
        "IF (NSHR .GE. 1) NSS = SIGMA(3)", oti
    ) == "IF (NSHR .GE. 1) NSS = REAL(SIGMA(3))"
    # And the unguarded forms are untouched by the change.
    assert _wrap_oti_rhs_assigned_to_a_plain_variable(
        "STRESS_OUT(4) = SIGMA(1,2)", oti) == "STRESS_OUT(4) = SIGMA(1,2)"
    assert _wrap_oti_rhs_assigned_to_a_plain_variable(
        "NSS = SIGMA(3)", oti) == "NSS = REAL(SIGMA(3))"


@pytest.mark.unit
def test_a_block_if_is_not_mistaken_for_a_guarded_assignment():
    """``IF (X .GT. 0) THEN`` opens a block and assigns nothing."""
    prefix, rest = _split_inline_if_statement("IF (X .GT. 0) THEN")
    assert prefix == "IF (X .GT. 0)" and rest.strip() == "THEN"
    assert _split_inline_if_statement("STRESS(1) = 2.0D0") is None
    assert _wrap_oti_rhs_assigned_to_a_plain_variable(
        "IF (X .GT. 0) THEN", {"X"}) == "IF (X .GT. 0) THEN"


# ---------------------------------------------------------------------------
# Free-form statements written across several lines
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.regression
def test_a_free_form_statement_split_at_an_ampersand_is_stitched_before_lifting():
    """The helper lifter joined fixed-form continuations and not free-form ones.

    Five corpus sources were refused for it: two ``.for`` files written in free
    form with tab indentation (luisez1988's Viscoplastic-SSMC and
    Viscoplastic_MC_coupled), and three ``.f90`` (marioruiarruda's Hashin_3D,
    toruinaba's j2_isotropic_3d and yu_kinematic_ps). Four failed with "Cannot
    parse helper header", one with "PARAMETER entry missing '=': '&'".
    """
    lines = [
        "subroutine j2_isotropic_3d(E, nu, sigma_y0, H, &",
        "                           stress, statev, ddsdde)",
        "  ! a comment between continuations does not end the statement",
        "  real*8 :: E, nu, &",
        "            sigma_y0",
        "  stress = 0.0d0",
        "end subroutine j2_isotropic_3d",
    ]
    stitched = _free_form_continuation_stitch(lines)
    assert stitched[0] == (
        "subroutine j2_isotropic_3d(E, nu, sigma_y0, H, stress, statev, ddsdde)")
    assert "real*8 :: E, nu, sigma_y0" in stitched
    # The comment line contributes nothing and did not break the statement.
    assert not any(line.startswith("!") for line in stitched)


@pytest.mark.unit
@pytest.mark.regression
def test_wrap_free_form_never_promises_a_continuation_line_it_does_not_write():
    """A statement whose last safe break is its last character kept a bare "&".

    Measured on the lifted header of Hashin_3D's calc_interlaminar_damage:
    the wrap emitted ``... prest, presc) &`` with nothing after it, gfortran
    joined the next line -- ``use otim6n1, OTI_HELPER_DP => DP`` -- onto the
    header and reported "Syntax error in SUBROUTINE statement". With the
    dangling marker removed the whole file compiles (rc=0).
    """
    header = ("subroutine calc_interlaminar_damage_oti(statev, eij, nstatv, ntens, "
              "ndi, catlc, fat, fac, a, gt, gc, ueqt0, ueqc0, seqt0, seqc0, dt, dc, "
              "dvt, dvc, dmax, dto, dco, dvto, dvco, etat, etac, dtime, ueqt, ueqtu, "
              "ueqc, ueqcu, prest, presc)")
    wrapped = wrap_free_form(header).splitlines()
    assert len(wrapped) > 1, "the header is long enough to need wrapping"
    assert not wrapped[-1].rstrip().endswith("&"), wrapped[-1]
    assert all(line.rstrip().endswith("&") for line in wrapped[:-1])
    # What it wraps is still the same statement.
    assert "".join(line.rstrip().removesuffix("&").strip() + " "
                   for line in wrapped).split() == header.split()


# ---------------------------------------------------------------------------
# DATA giving a whole array its elements
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.regression
def test_a_data_statement_filling_a_whole_array_becomes_element_assignments():
    """``DATA A/ v1, v2, ... /`` for a DIMENSION A(12,12) is not a mismatch.

    harshaa765/UMATFile's UMAT.for initialises AMPLITUDE_FACTOR(12,12) from a
    144-value DATA list. Counting one name against 144 values raised
    "Unsupported DATA statement shape" and refused the source. The values go
    down in array element order, so element 13 is (1,2): measured in the
    emitted helper, AMPLITUDE_FACTOR(2,1) = 0.22D0 and AMPLITUDE_FACTOR(1,2) =
    0.22D0 for a matrix the author wrote symmetric, and the 144th is
    AMPLITUDE_FACTOR(12,12) = 0.08D0. The source now transforms and compiles
    (rc=0).
    """
    assert _column_major_subscript(0, (12, 12)) == "1,1"
    assert _column_major_subscript(1, (12, 12)) == "2,1"
    assert _column_major_subscript(12, (12, 12)) == "1,2"
    assert _column_major_subscript(143, (12, 12)) == "12,12"

    values = ", ".join(str(index) for index in range(1, 7))
    out = _data_to_assignments(f"A/ {values} /", {"A": (3, 2)})
    assert out == ["A(1,1) = 1", "A(2,1) = 2", "A(3,1) = 3",
                   "A(1,2) = 4", "A(2,2) = 5", "A(3,2) = 6"]
    # The forms that already worked still do, and an array whose extent this
    # routine cannot read is still refused rather than guessed at.
    assert _data_to_assignments("X, Y/ 1.0, 2.0 /", {}) == ["X = 1.0D0", "Y = 2.0D0"]
    with pytest.raises(ValueError):
        _data_to_assignments("A/ 1.0, 2.0, 3.0 /", {"A": ()})


# ---------------------------------------------------------------------------
# FORMAT edit descriptors read as real literals
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.regression
def test_a_format_statement_keeps_the_edit_descriptors_the_author_wrote():
    """``FORMAT(7(E24.8E3))`` came out ``E24.8D3``, which is not a descriptor.

    AnargyrosKarakalas/UMAT_3D writes its slip output with an E24.8E3
    descriptor. The literal promoter read ``8E3`` as a real literal and made it
    ``8D3``; gfortran answered "Period required in format specifier D at (1)",
    seven times. A FORMAT statement holds no arithmetic, so it is left alone.
    """
    oti = {"E"}
    assert _normalize_numeric_literals("11 FORMAT(7(E24.8E3))", oti) == "11 FORMAT(7(E24.8E3))"
    assert _normalize_numeric_literals("FORMAT(6(E24.8E3))", oti) == "FORMAT(6(E24.8E3))"
    # An ordinary expression still has its literals promoted.
    assert "D" in _normalize_numeric_literals("E = 1.0E3", oti).upper()


# ---------------------------------------------------------------------------
# DO bounds that were promoted with everything else
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.regression
def test_a_do_bound_that_was_promoted_is_converted_back_to_an_integer():
    """``DO I=1,X`` with X hypercomplex asks the loop for an OTI trip count.

    luisez1988's viscoplastic Mohr-Coulomb helpers compute ``X = N/2`` under
    ``IMPLICIT DOUBLE PRECISION (A-H,O-Z)`` and loop to it. Legal before the
    lift; after it, "End expression in DO loop at (1) must be INTEGER", twice
    per file. INT() of an OTI value is defined by oti_intrinsics, and a trip
    count is piecewise constant so it carries no derivative to lose.
    """
    oti = {"X"}
    assert _integer_do_bounds_over_oti("Do I=1,X", oti) == "Do I=1, INT(X)"
    assert _integer_do_bounds_over_oti("Do I=X+1,N", oti) == "Do I=INT(X+1), N"
    assert _integer_do_bounds_over_oti("DO 100 I=1,X", oti) == "DO 100 I=1, INT(X)"
    # An integer loop is byte-identical, and DO WHILE is not a bounded loop.
    assert _integer_do_bounds_over_oti("DO I=1,NTENS", oti) == "DO I=1,NTENS"
    assert _integer_do_bounds_over_oti("DO WHILE (X .GT. 0)", oti) == "DO WHILE (X .GT. 0)"


# ---------------------------------------------------------------------------
# Blockers that named the wrong cause
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.regression
def test_sign_is_not_refused_by_a_transform_whose_modules_define_it():
    """SIGN was on the unsupported list and has been supported throughout.

    oti_intrinsics declares SIGN for (OTI, OTI), (OTI, real) and (real, OTI),
    and the main transform has emitted and USEd that module since it gained
    one. Two corpus sources -- ahartloper/UVC_MatMod's UVCuniaxial.for and
    UVCuniaxial_IS.for -- were refused for it. SUM takes its place because
    nothing defines SUM over the type: with SIGN removed, UVCuniaxial.for
    transformed and then stopped at "'array' argument of 'sum' intrinsic at
    (1) must have a numeric type" on ALPHA_OTI = SUM(ALPHA_K_OTI(:)).
    """
    roles = {"seed": {"DSTRAN"}, "promote": {"ALPHA_K", "X"}}
    regions = [{"start_line": 1, "end_line": 3}]
    source = "      REAL*8 X\n      X = SIGN(1.0D0, X)\n      ALPHA = SUM(ALPHA_K(:))\n"
    blockers = _unsupported_intrinsic_blockers(source, roles, regions)
    assert not any("SIGN" in text for text in blockers), blockers
    assert any("SUM" in text for text in blockers), blockers


@pytest.mark.unit
def test_an_intrinsic_the_source_declares_as_its_own_variable_is_not_a_blocker():
    """A UMAT may keep an accumulator called SUM; that is not the intrinsic."""
    roles = {"seed": {"DSTRAN"}, "promote": {"X"}}
    regions = [{"start_line": 1, "end_line": 3}]
    declares_its_own = "      REAL*8 SUM\n      SUM = X\n      Y = SUM(2)\n"
    assert _unsupported_intrinsic_blockers(declares_its_own, roles, regions) == []


@pytest.mark.unit
@pytest.mark.regression
def test_a_local_shadowing_a_support_generic_is_renamed_on_import_not_refused():
    """Only the two generics the transform calls itself still refuse.

    sd104400/OPA_Modeling's UMAT_DPIsodwAniDM.for declares an INT and was
    refused outright; it now imports the module's INT under another name and
    reaches its next finding, a semantic check. mholla/growth's
    umat_ortho_stretch.f declares ``real*8 max(3)``, and there the refusal
    stands, because the transform emits its own MAX( in the SQRT guard and in
    that scope the call would reach the author's array: with the rename alone
    the emitted file failed with "Rank mismatch in array reference at (1)
    (2/1)".
    """
    assert GENERICS_THE_TRANSFORM_CALLS_ITSELF == {"MIN", "MAX"}
    assert GENERICS_THE_TRANSFORM_CALLS_ITSELF < set(
        __import__("umat_oti.transform.source_transform", fromlist=["x"]).OTI_MODULE_GENERICS)

    declares_int = "      REAL*8 INT(3)\n      INT(1) = 0.0D0\n"
    assert _locals_colliding_with_the_oti_modules(declares_int) == ["INT"]
    use_line = _module_use_line("fixed", "otim6n1", 6, ["INT"])
    assert "OTI_MODULE_INT => INT" in use_line
    assert "OTI_INTRINSIC_INT => INT" in use_line
    # Nothing shadowed means nothing renamed, so untouched sources keep
    # byte-identical output.
    assert _module_use_line("fixed", "otim6n1", 6, []) == _module_use_line("fixed", "otim6n1", 6)


# ---------------------------------------------------------------------------
# Placing a DDSDDE write that happens inside a routine the UMAT calls
# ---------------------------------------------------------------------------

_READS_DDSDDE_BACK = """\
      subroutine umat(stress,statev,ddsdde,stran,dstran,ntens,nstatv,
     &                props,nprops)
      implicit none
      integer ntens, nstatv, nprops, i, j
      real*8 stress(ntens), statev(nstatv), ddsdde(ntens,ntens)
      real*8 stran(ntens), dstran(ntens), props(nprops)
      do i = 1, ntens
        do j = 1, ntens
          ddsdde(i,j) = 0.d0
        end do
        ddsdde(i,i) = props(1)
      end do
      do i = 1, ntens
        do j = 1, ntens
          stress(i) = stress(i) + ddsdde(i,j)*dstran(j)
        end do
      end do
      return
      end
"""


_CONTINUED_CALL = """\
      subroutine umat(stress,statev,ddsdde,stran,dstran,ntens,nstatv,
     &                props,nprops)
      implicit none
      integer ntens, nstatv, nprops, i
      real*8 stress(ntens), statev(nstatv), ddsdde(ntens,ntens)
      real*8 stran(ntens), dstran(ntens), props(nprops)
      call themodel(stress,statev,ddsdde,stran,dstran,
     &              ntens,nstatv,props,
     &              nprops)
      return
      end

      subroutine themodel(stress,statev,ddsdde,stran,dstran,
     &                    ntens,nstatv,props,nprops)
      implicit none
      integer ntens, nstatv, nprops, i, j
      real*8 stress(ntens), statev(nstatv), ddsdde(ntens,ntens)
      real*8 stran(ntens), dstran(ntens), props(nprops)
      do i = 1, ntens
        stress(i) = stress(i) + props(1)*dstran(i)
      end do
      do i = 1, ntens
        do j = 1, ntens
          ddsdde(i,j) = 0.d0
        end do
        ddsdde(i,i) = props(1)
      end do
      return
      end
"""


@pytest.mark.unit
@pytest.mark.regression
def test_a_continued_call_is_placed_by_the_line_it_finishes_on(tmp_path):
    """A CALL is one program point however many lines it is written across.

    ``_call_lines_reaching`` returned every physical line of the statement and
    the placement test then judged each one separately, so a CALL spanning
    lines 7-9 failed a bracket the statement as a whole satisfies. Measured on
    damin225/short-crack-propagation-3d/input_clean/umat.f: the reaching call
    came back as [139, 140, 141, 142, 143, 144] against an extraction line of
    144, and the check answered False on 139.
    """
    path = tmp_path / "continued.f"
    path.write_text(_CONTINUED_CALL, encoding="utf-8")
    parsed = parse_fortran_file(path)
    lines = _call_lines_reaching(parsed, "UMAT", "THEMODEL")
    assert lines == [9], (
        "one line per reaching CALL, the line the statement finishes on")


@pytest.mark.unit
@pytest.mark.regression
def test_a_ddsdde_write_in_a_helper_is_not_refused_where_nothing_reads_ddsdde_back(tmp_path):
    """"After the stress update" was a stand-in for a hazard, not the hazard.

    The hazard is a stress update that reads DDSDDE back before the extraction
    overwrites it; ``ddsdde_stress_input_lines`` lists exactly those reads,
    over every logical line in the file. Ten of the sixteen corpus sources
    refused here have none at all -- prashanthgadwala's umat.f calls its whole
    model and returns, and its reaching call came back at line 61 against a
    last_stress_end of 67 -- and six do:
    vishalsubbiah/Abaqus-Multi-scale-modelling writes DDSDDE in EULCONV and
    then builds STRESS(I) from DDSDDE(I,J)*DSTRAN(J) at line 49, and stays
    refused.
    """
    path = tmp_path / "continued.f"
    path.write_text(_CONTINUED_CALL, encoding="utf-8")
    parsed = parse_fortran_file(path)
    # The DDSDDE writes are at lines 24-27, inside THEMODEL; the CALL that
    # reaches them finishes on line 9, and the stress region runs to 11.
    assert _call_lines_reaching(parsed, "UMAT", "THEMODEL") == [9]
    assert _overwritten_through_its_call_sites(
        [26], (1, 11), parsed, "UMAT", 11, 11, []) is True
    # One read of DDSDDE by the stress path and the old rule stands.
    assert _overwritten_through_its_call_sites(
        [26], (1, 11), parsed, "UMAT", 11, 11, [8]) is False
    # Reads not established is not a licence either.
    assert _overwritten_through_its_call_sites(
        [26], (1, 11), parsed, "UMAT", 11, 11, None) is False
    # And a call after the extraction point is refused whatever the reads say.
    assert _overwritten_through_its_call_sites(
        [26], (1, 11), parsed, "UMAT", 8, 8, []) is False


@pytest.mark.unit
def test_the_region_classifier_publishes_the_ddsdde_reads_the_check_needs():
    """The placement check reads a fact the classifier already computed."""
    from umat_oti.fortran.regions import detect_candidate_regions

    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "reads.f"
        path.write_text(_READS_DDSDDE_BACK, encoding="utf-8")
        summary = detect_candidate_regions(parse_fortran_file(path))["summary"]
    assert summary["ddsdde_stress_input_lines"], summary


# ---------------------------------------------------------------------------
# The same defect, compiled and run
# ---------------------------------------------------------------------------

_GUARDED_SHEAR_HELPER = """\
      SUBROUTINE SHEARCORE(DE,EG,ELAM,NSHR,SOUT)
      IMPLICIT REAL*8(A-H,O-Z)
      DIMENSION DE(6),SOUT(6)
      SOUT(1)=(ELAM+2.0D0*EG)*DE(1)
      SOUT(2)=(ELAM+2.0D0*EG)*DE(2)
      SOUT(3)=(ELAM+2.0D0*EG)*DE(3)
      IF (NSHR .GE. 1) SOUT(4)=EG*DE(4)
      IF (NSHR .GE. 2) SOUT(5)=EG*DE(5)
      IF (NSHR .GE. 3) SOUT(6)=EG*DE(6)
      RETURN
      END
"""

_LIFTED_DRIVER = """\
program drv
  use master_parameters, only: DP
  use otim6n1
  use oti_intrinsics
  use umat_oti_helpers
  implicit none
  type(ONUMM6N1) :: de(6), sout(6), eg, elam
  integer :: i
  do i = 1, 6
     de(i) = 0.0d0
     sout(i) = 0.0d0
  end do
  eg = 80.0d0
  elam = 120.0d0
  de(1) = 1.0d-4
  de(4) = 4.0d-4
  ! One seeded direction each, so GETIM(sout(i), j) is d sout(i) / d de(j).
  de(1)%e1 = 1.0d0
  de(4)%e4 = 1.0d0
  call shearcore_oti(de, eg, elam, 3, sout)
  write(*,'(4ES26.17)') sout(1)%R, sout(1)%e1, sout(4)%R, sout(4)%e4
end program drv
"""


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@needs_gfortran
def test_a_shear_term_written_under_an_inline_if_keeps_its_derivative_when_run(tmp_path):
    """The lifted helper returns d(shear stress)/d(shear strain), not zero.

    Before the fix the lifter emitted ``IF (NSHR .GE. 1) SOUT(4) =
    REAL(EG*DE(4))`` and the derivative was discarded while the value stayed
    right. Compiled and run here: sout(4) = 3.2000e-02 with derivative
    8.0000e+01 = EG, against 0.0 before.

    The same defect, measured on the corpus source it was found in
    (keisuke58/pde-fem-biofilm/umat_biofilm_visco_phase2.f) with a driver
    around its converted build: DDSDDE rows 4, 5 and 6 were identically zero
    in every entry, and DDSDDE(4,4) came out 1.1616e+00 after the fix against
    the author's own finite-difference 1.1802e+00, while STRESS was unchanged
    to 2.5e-16 in both.
    """
    from umat_oti.fortran.parser import parse_fortran_file
    from umat_oti.oti.module_generator import generate_otilib_module
    from umat_oti.transform.helper_lifting import lift_helper_set_source, wrap_free_form
    from umat_oti.transform.parameter_sensitivity_transform import _emit_intrinsic_extensions

    source = tmp_path / "shear.f"
    source.write_text(_GUARDED_SHEAR_HELPER, encoding="utf-8")
    parsed = parse_fortran_file(source)
    lifted = lift_helper_set_source(parsed, ["SHEARCORE"],
                                    module_name="otim6n1", type_name="ONUMM6N1")
    # The shape, before anything is compiled: the guarded assignment keeps its
    # hypercomplex right-hand side.
    assert "IF (NSHR .GE. 1) SOUT(4)=EG*DE(4)" in lifted.source.replace("  ", " ")
    assert "REAL(EG*DE(4))" not in lifted.source

    module = generate_otilib_module(output_dir=tmp_path, ntens=6, order=1)
    (tmp_path / "oti_intrinsics.f90").write_text(
        _emit_intrinsic_extensions(module.module_name, module.type_name), encoding="utf-8")
    (tmp_path / "umat_oti_helpers.f90").write_text(
        "module umat_oti_helpers\ncontains\n" + wrap_free_form(lifted.source)
        + "\nend module umat_oti_helpers\n", encoding="utf-8")
    (tmp_path / "drv.f90").write_text(_LIFTED_DRIVER, encoding="utf-8")

    units = ["master_parameters.f90", "real_utils.f90", f"{module.module_name}.f90",
             "oti_intrinsics.f90", "umat_oti_helpers.f90", "drv.f90"]
    done = subprocess.run(
        [GFORTRAN, "-ffree-form", "-ffree-line-length-none", "-w", "-I.", "-J.",
         *units, "-o", "drv"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stderr[-4000:]
    run = subprocess.run(["./drv"], cwd=str(tmp_path), capture_output=True,
                         text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    direct_value, direct_derivative, shear_value, shear_derivative = (
        float(x) for x in run.stdout.split())
    assert direct_value == pytest.approx(280.0 * 1.0e-4, rel=1e-12)
    assert direct_derivative == pytest.approx(280.0, rel=1e-12)
    assert shear_value == pytest.approx(80.0 * 4.0e-4, rel=1e-12)
    assert shear_derivative == pytest.approx(80.0, rel=1e-12), (
        "the guarded shear assignment lost its derivative")
