"""A UMAT may use names the OTI module also defines.

E1, E2 and E3 are ordinary names for elastic moduli. The generated OTI module
exports named constants with exactly those names for its imaginary directions,
and the lifted UMAT imported the module unqualified, so a UMAT that assigns to
its own E1 failed to compile with

    Error: Named constant 'e1' in variable definition context (assignment)

Seeding happens in the driver, never inside the lifted routine, so the direction
constants are not needed there and the import can rename them away.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract,
    _colliding_direction_names,
    _wrap_lifted_in_module,
    compile_generic_ps,
    oti_direction_names,
    run_generic_ps,
    transform_umat_for_parameter_sensitivity,
)

#: Small-strain isotropic elasticity that keeps its shear modulus in E1 and its
#: Lame constant in E2 -- both names the OTI module uses for directions.
COLLIDING_UMAT = """\
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
      EMOD=PROPS(1)
      ENU=PROPS(2)
      E1=EMOD/(2.0D0*(1.0D0+ENU))
      E2=EMOD*ENU/((1.0D0+ENU)*(1.0D0-2.0D0*ENU))
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=0.0D0
        END DO
      END DO
      DO K1=1,NDI
        DO K2=1,NDI
          DDSDDE(K2,K1)=E2
        END DO
        DDSDDE(K1,K1)=E2+2.0D0*E1
      END DO
      DO K1=NDI+1,NTENS
        DDSDDE(K1,K1)=E1
      END DO
      DO K1=1,NTENS
        DO K2=1,NTENS
          STRESS(K1)=STRESS(K1)+DDSDDE(K1,K2)*DSTRAN(K2)
        END DO
      END DO
      STATEV(1)=E1
      RETURN
      END
"""


def test_direction_names_follow_the_module_convention():
    assert oti_direction_names(3) == ("E1", "E2", "E3")


def test_collision_detection_ignores_comments_and_substrings():
    body = "      X=EFFE1(K1)\n      Y=1.0 ! E2 mentioned only in a comment\n      E3=2.0\n"
    assert _colliding_direction_names(body, 3) == ("E3",)


def test_wrapper_renames_only_the_colliding_constants():
    header = _wrap_lifted_in_module("      E1=1.0_DP\n", module_name="otim2n1", n_param=2)
    assert "USE otim2n1, OTI_E1 => E1" in header
    assert "OTI_E2" not in header


def test_wrapper_leaves_a_clean_import_alone():
    header = _wrap_lifted_in_module("      SIG=EMOD*STRAN\n", module_name="otim2n1", n_param=2)
    assert "USE otim2n1\n" in header
    assert "=>" not in header


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_umat_using_E1_transforms_compiles_and_runs(tmp_path):
    """The whole point: this must reach a running executable, not just transform."""
    source = tmp_path / "colliding.for"
    source.write_text(COLLIDING_UMAT, encoding="utf-8")
    contract = GenericPSContract(
        name="colliding", umat_source_path=source,
        parameters=(("EMOD", 1), ("ENU", 2)),
        parameter_values=(200000.0, 0.3),
        state_variables=(("SHEAR", 1),),
        ntens=6, nstatv=1, ndi=3, nshr=3,
        dstran_per_increment=(1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        n_increments=3, static_props=(200000.0, 0.3))
    layout = transform_umat_for_parameter_sensitivity(
        contract=contract, output_dir=tmp_path / "out")
    lifted = layout.lifted_umat.read_text(encoding="utf-8")
    assert "OTI_E1 => E1" in lifted and "OTI_E2 => E2" in lifted

    executable = compile_generic_ps(layout)
    result = run_generic_ps(executable)
    assert result.returncode == 0, result.stderr
    assert result.dsigma_csv.is_file()
    rows = result.dsigma_csv.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) > 1, "the run produced no stress-sensitivity rows"


MIXED_INTRINSIC_UMAT = COLLIDING_UMAT.replace(
    "      ENU=PROPS(2)",
    "      ENU=MIN(PROPS(2),ENUMAX)").replace(
    "      EMOD=PROPS(1)",
    "      ENUMAX=0.4999D0\n      EMOD=MAX(PROPS(1),1.0D0)")


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_mixed_oti_and_real_min_max_compile_and_run(tmp_path):
    """Regression: MIN(oti, real) had no matching specific interface.

    The generated OTI module defines MIN and MAX for two OTI operands only, but
    clamping against a REAL constant is an everyday UMAT idiom --
    ``ENU=MIN(PROPS(2),ENUMAX)`` is what exposed it in UMAT_PCO. gfortran
    reported the generic as not matching any specific intrinsic interface, which
    reads like a transformation bug and is a missing overload.
    """
    source = tmp_path / "mixed.for"
    source.write_text(MIXED_INTRINSIC_UMAT, encoding="utf-8")
    contract = GenericPSContract(
        name="mixed", umat_source_path=source,
        parameters=(("EMOD", 1), ("ENU", 2)),
        parameter_values=(200000.0, 0.3),
        state_variables=(("SHEAR", 1),),
        ntens=6, nstatv=1, ndi=3, nshr=3,
        dstran_per_increment=(1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        n_increments=3, static_props=(200000.0, 0.3))
    layout = transform_umat_for_parameter_sensitivity(
        contract=contract, output_dir=tmp_path / "out")
    assert (layout.root / "oti_intrinsics.f90").is_file()

    executable = compile_generic_ps(layout)
    result = run_generic_ps(executable)
    assert result.returncode == 0, result.stderr
    rows = result.dsigma_csv.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) > 1


def test_intrinsic_extension_module_declares_the_mixed_forms(tmp_path):
    from umat_oti.transform.parameter_sensitivity_transform import (
        _emit_intrinsic_extensions,
    )

    text = _emit_intrinsic_extensions("otim2n1", "ONUMM2N1")
    for name in ("oti_min_or", "oti_min_ro", "oti_max_or", "oti_max_ro",
                 "oti_sign_oo", "oti_sign_or"):
        assert name in text, name
    # A real constant contributes no derivative, so the selected operand is
    # returned whole rather than rebuilt from its real part.
    assert "RES = B" in text and "RES = A" in text
