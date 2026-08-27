"""Finite-strain driving, and the UMAT interface facts a source may omit."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from umat_oti.transform.helper_lifting import UMAT_ARGUMENT_SHAPES
from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract, _emit_driver, _emit_intrinsic_extensions,
    compile_generic_ps, run_generic_ps, transform_umat_for_parameter_sensitivity,
)
from umat_oti.validation.parameter_sensitivity_validation import (
    build_original_driver, driver_source, replay,
)

#: A finite-strain UMAT that reads DFGRD1 and nothing else, and that omits the
#: DIMENSION for COORDS and DROT and never declares CMNAME -- all three things
#: real published sources do.
FINITE_STRAIN_UMAT = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),DFGRD0(3,3),DFGRD1(3,3)
      EMOD=PROPS(1)
      DET=DFGRD1(1,1)*DFGRD1(2,2)*DFGRD1(3,3)
      DO K1=1,3
        STRESS(K1)=+(EMOD*(DFGRD1(K1,K1)-1.0D0))
      END DO
      STATEV(1)=DET
      RETURN
      END
"""


def test_interface_shapes_cover_the_array_arguments():
    for name in ("STRESS", "STATEV", "DDSDDE", "COORDS", "DROT",
                 "DFGRD0", "DFGRD1", "TIME"):
        assert name in UMAT_ARGUMENT_SHAPES, name
    assert UMAT_ARGUMENT_SHAPES["COORDS"] == "3"
    assert UMAT_ARGUMENT_SHAPES["DROT"] == "3,3"


def test_reference_driver_reads_a_gradient_only_when_asked():
    small = driver_source(ntens=6, nstatv=1, nprops=2, finite_strain=False)
    finite = driver_source(ntens=6, nstatv=1, nprops=2, finite_strain=True)
    assert "DFGRDINC" not in small
    assert "DFGRDINC" in finite and "DFGRD0=DFGRD1" in finite


def test_oti_driver_advances_the_gradient(tmp_path):
    """Regression: a finite-strain UMAT saw an unchanging identity.

    Holding DFGRD at the identity makes a hyperelastic model return zero stress
    for every increment, which looks like a successful run with trivial output
    rather than a driver that never applied any deformation.
    """
    contract = GenericPSContract(
        name="fs", umat_source_path=tmp_path / "u.for",
        parameters=(("EMOD", 1),), parameter_values=(1.0,),
        state_variables=(("SDV1", 1),), ntens=6, nstatv=1, ndi=3, nshr=3,
        dstran_per_increment=(0.0,) * 6, n_increments=3, static_props=(1.0,),
        deformation_gradient_increment=(1e-3, 0, 0, 0, 0, 0, 0, 0, 0))
    driver = _emit_driver(contract, "otim", "oti_real")
    assert "DFGRD1 = DFGRD1 + DFGRDINC" in driver
    assert "DFGRD0 = DFGRD1" in driver
    body = driver[driver.index("DO INC = 1, N_INC"):]
    assert body.index("DFGRD0 = DFGRD1") < body.index("CALL umat_oti")


def test_intrinsic_module_supplies_unary_plus():
    """Regression: "Operand of unary numeric operator '+' is UNKNOWN".

    The generated module defines the binary operators and unary minus, but not
    unary plus, so an ordinary cofactor expression failed to compile.
    """
    # Unary plus now comes from the generated algebra, beside the unary minus
    # it was always missing next to, so that it exists on every path rather
    # than only where this extension module is emitted. Defining it in both
    # places made the generic ambiguous and nothing compiled.
    from umat_oti.oti.module_generator import _extra_overloads  # noqa: PLC0415

    interface_block, body = _extra_overloads(2, 1)
    assert "ONUMM2N1_UNARY_PLUS" in interface_block
    assert "OPERATOR(+)" in interface_block
    assert "RES = A" in body

    text = _emit_intrinsic_extensions("otim2n1", "ONUMM2N1")
    assert "oti_unary_plus" not in text, (
        "two definitions of unary plus make the generic ambiguous")
    assert "OPERATOR(+)" in text

    # The export list stays restricted. An earlier version re-exported the
    # generated module's direction constants and collided with a source's own
    # E1 and E2, so what matters is that only intrinsic names leave the module
    # -- not that the list has one particular length. Every PUBLIC line counts,
    # not just the first: reading one line would let a second line export
    # anything at all.
    names = {name.strip()
             for line in text.splitlines() if line.strip().startswith("PUBLIC ::")
             for name in line.split("::", 1)[1].split(",")}
    assert names <= {"MIN", "MAX", "SIGN", "NINT", "INT", "ABS", "SQRT",
                     "ASSIGNMENT(=)", "OPERATOR(+)", "OPERATOR(-)",
                     "OPERATOR(*)", "OPERATOR(/)"}, f"unexpected export: {names}"
    assert {"MIN", "MAX", "SIGN", "OPERATOR(+)"} <= names


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_finite_strain_source_transforms_compiles_runs_and_deforms(tmp_path):
    """The whole path, checked by execution rather than by reading the output.

    The source omits COORDS and DROT dimensions, never declares CMNAME, uses
    unary plus, and reads only DFGRD1 -- each of which broke the pipeline
    separately.
    """
    source = tmp_path / "u.for"
    source.write_text(FINITE_STRAIN_UMAT, encoding="utf-8")
    gradient = (1e-3, 0, 0, 0, 0, 0, 0, 0, 0)

    original = build_original_driver(source, tmp_path / "ref", ntens=6, nstatv=1,
                                     nprops=1, finite_strain=True)
    replayed = replay(original, [1000.0], [[0.0] * 6] * 5, ntens=6, nstatv=1,
                      deformation_gradient_increment=list(gradient))
    # The determinant must grow: a driver that never deformed anything leaves it
    # at exactly one for every increment.
    determinants = [row[0] for row in replayed.statev]
    assert determinants[0] > 1.0 and determinants[-1] > determinants[0]

    contract = GenericPSContract(
        name="fs", umat_source_path=source, parameters=(("EMOD", 1),),
        parameter_values=(1000.0,), state_variables=(("SDV1", 1),),
        ntens=6, nstatv=1, ndi=3, nshr=3, dstran_per_increment=(0.0,) * 6,
        n_increments=5, static_props=(1000.0,),
        deformation_gradient_increment=gradient)
    layout = transform_umat_for_parameter_sensitivity(
        contract=contract, output_dir=tmp_path / "oti")
    result = run_generic_ps(compile_generic_ps(layout))
    assert result.returncode == 0, result.stderr

    rows = result.primal_csv.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 6
    first = [float(v) for v in rows[1].split(",")[2:]]
    last = [float(v) for v in rows[5].split(",")[2:]]
    assert last[0] > first[0] > 0.0, "the transformed build did not deform either"
