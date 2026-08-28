"""Where the transform writes its outputs when the file holds more than one routine.

A UMAT is often shipped inside a larger file -- below a UEL, below a stack of
element helpers -- and everything the transform emits has to land inside the
routine it was asked to transform. The failure this guards against is silent:
the emitted code is valid Fortran in the wrong subprogram, and the flags that
track "already inserted" are set either way, so nothing downstream reports a
gap.
"""
from __future__ import annotations

import json

from umat_oti.app.engine import _build_contract
from umat_oti.services.transformation import TransformationOptions, run_transformation

#: A UEL that calls a UMAT defined below it, in the shape the discovered
#: element files take. The element routine returns long before the material
#: routine begins, and it reads the deformation gradient the material routine
#: never touches. The arithmetic is only enough to make those two facts real.
UEL_ABOVE_UMAT = """\
      SUBROUTINE UEL(RHS,AMATRX,SVARS,ENERGY,NDOFEL,NRHS,NSVARS,
     1 PROPS,NPROPS,COORDS,MCRD,NNODE,U,DU,V,A,JTYPE,TIME,DTIME,
     2 KSTEP,KINC,JELEM,PARAMS,NDLOAD,JDLTYP,ADLMAG,PREDEF,NPREDF,
     3 LFLAGS,MLVARX,DDLMAG,MDLOAD,PNEWDT,JPROPS,NJPROP,PERIOD)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION RHS(MLVARX,*),AMATRX(NDOFEL,NDOFEL),PROPS(*),
     1 SVARS(*),ENERGY(8),COORDS(MCRD,NNODE),U(NDOFEL),DU(MLVARX,*),
     2 V(NDOFEL),A(NDOFEL),TIME(2),PARAMS(*),JDLTYP(MDLOAD,*),
     3 ADLMAG(MDLOAD,*),DDLMAG(MDLOAD,*),PREDEF(2,NPREDF,NNODE),
     4 LFLAGS(*),JPROPS(*)
      DIMENSION USTRESS(6),USTATEV(4),UDDSDDE(6,6),USTRAN(6),
     1 UDSTRAN(6),UDFGRD1(3,3),UDROT(3,3),UCOORDS(3)
      PARAMETER (ZERO=0.D0, ONE=1.D0)
      DO K1=1, 6
        UDSTRAN(K1)=DU(K1,1)
      END DO
      UDFGRD1(1,1)=ONE+UDSTRAN(1)
      CALL UMAT(USTRESS,USTATEV,UDDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,USTRAN,UDSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,
     2 DPRED,CMNAME,3,3,6,4,PROPS,NPROPS,UCOORDS,UDROT,PNEWDT,
     3 CELENT,UDFGRD1,UDFGRD1,JELEM,1,1,1,KSTEP,KINC)
      DO K1=1, 6
        RHS(K1,1)=-USTRESS(K1)
      END DO
      RETURN
      END
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),TIME(2),
     2 PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      PARAMETER (ZERO=0.D0, ONE=1.D0, TWO=2.D0, THREE=3.D0)
      EMOD=PROPS(1)
      ENU=PROPS(2)
      EBULK3=EMOD/(ONE-TWO*ENU)
      EG2=EMOD/(ONE+ENU)
      EG=EG2/TWO
      ELAM=(EBULK3-EG2)/THREE
      DO K1=1, 3
        DO K2=1, 3
          DDSDDE(K2,K1)=ELAM
        END DO
        DDSDDE(K1,K1)=EG2+ELAM
      END DO
      DO K1=4, NTENS
        DDSDDE(K1,K1)=EG
      END DO
      DO K1=1, NTENS
        DO K2=1, NTENS
          STRESS(K1)=STRESS(K1)+DDSDDE(K1,K2)*DSTRAN(K2)
        END DO
      END DO
      RETURN
      END
"""


def _transform(tmp_path):
    src = tmp_path / "uel_above_umat.for"
    src.write_text(UEL_ABOVE_UMAT, encoding="utf-8")
    config, _finite = _build_contract("uel_above_umat", "auto", "STRESS",
                                      "DDSDDE", 6, 1, src)
    config_path = tmp_path / "contract.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    summary, _ = run_transformation(config_path, tmp_path / "out",
                                    TransformationOptions(compile_generated=False))
    generated = next((tmp_path / "out").glob("*_oti.for"))
    return summary, generated.read_text(encoding="utf-8").splitlines()


def _routine_containing(lines: list[str], index: int) -> str:
    """Name of the last program unit opened at or before ``index``."""
    name = ""
    for line in lines[:index + 1]:
        stripped = line.strip().upper()
        if stripped.startswith("SUBROUTINE "):
            name = stripped.split()[1].split("(")[0]
    return name


def _line_index(lines: list[str], needle: str) -> int:
    for index, line in enumerate(lines):
        if needle in line:
            return index
    raise AssertionError(f"{needle!r} was never emitted")


def test_the_real_output_copy_lands_in_the_material_routine(tmp_path):
    """Not at the element routine's RETURN, which comes first in the file."""
    _summary, lines = _transform(tmp_path)
    index = _line_index(lines, "STRESS(OTI_I) = REAL(STRESS_OTI(OTI_I))")
    assert _routine_containing(lines, index) == "UMAT"


def test_the_tangent_extraction_lands_in_the_material_routine(tmp_path):
    """STRESS_OTI is not in scope in the element routine; DDSDDE is not either."""
    _summary, lines = _transform(tmp_path)
    index = _line_index(lines, "GETIM(STRESS_OTI(OTI_I),OTI_J)")
    assert _routine_containing(lines, index) == "UMAT"


def test_the_element_routine_is_left_alone(tmp_path):
    """It is not the routine under transformation, so nothing is emitted into it."""
    _summary, lines = _transform(tmp_path)
    umat_start = _line_index(lines, "SUBROUTINE UMAT")
    emitted_above = [line for line in lines[:umat_start]
                     if "_OTI" in line.upper() or "GETIM" in line.upper()]
    assert emitted_above == []


def test_the_element_routines_gradient_is_not_on_the_material_stress_path(tmp_path):
    """UDFGRD1 is read in the UEL and nowhere in the UMAT.

    Spanning the finite-strain region from the first line reading a
    deformation gradient to the end of the stress update once covered both
    routines, which put the element routine's own calls on the material
    stress path.
    """
    summary, _lines = _transform(tmp_path)
    assert summary.get("transform_success") is True, summary.get("warnings")


def test_the_whole_file_transforms_without_a_blocker_or_a_warning(tmp_path):
    summary, _lines = _transform(tmp_path)
    assert summary.get("blockers") in (None, [], ())
    assert summary.get("warnings") in (None, [], ())
