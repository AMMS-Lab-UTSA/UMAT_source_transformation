"""Corpus failure classes found by the job-layout compile census, batch B1.

Each test is one class, written as a small source with the construct that
stopped a corpus entry, and asserts behaviour: the stored output compiles in
the job layout (``transform_all.job_layout_compile``), a value computed through
the new OTI forms is the right value with the right derivative, or a
refusal names the construct, the place and what to do. The census itself is
``corpus_campaign/batches/B1/ada/census``.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from transform_all import WorkItem, transform_one

pytestmark = [pytest.mark.regression, pytest.mark.fortran]

HEADER = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
"""

TANGENT = """      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=0.D0
        END DO
        DDSDDE(K1,K1)=EMOD
      END DO
"""


def _gfortran():
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")


def _transform(tmp_path: Path, text: str, name: str = "umat.for",
               extra: dict[str, str] | None = None):
    from umat_oti.corpus.cli import _write_aba_param_stub

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / name
    source.write_text(text, encoding="utf-8")
    for relative, content in (extra or {}).items():
        target = inputs / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _write_aba_param_stub(inputs)
    item = WorkItem(source_id=f"fixture__{tmp_path.name}/{name}", path=source,
                    sha256=hashlib.sha256(source.read_bytes()).hexdigest(), ntens=6)
    return transform_one(item, tmp_path / "work")


def _assert_builds(result):
    assert result.ok, result.reason
    assert result.metadata["compiled"] is True, result.metadata["compile_error"]


# --- a READ with a continuation, and a READ in another routine -------------

def test_a_continued_read_into_state_is_synced_once_and_builds(tmp_path):
    """shayansss/hml: the continuation of a READ was written twice."""
    _gfortran()
    body = (HEADER +
            "      EMOD=PROPS(1)\n"
            "      IF (KINC.EQ.-1) THEN\n"
            "        READ(28,*) STATEV(1),\n"
            "     1   STATEV(2)\n"
            "      END IF\n"
            "      DO K1=1,NTENS\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*STATEV(1)*DSTRAN(K1)\n"
            "      END DO\n" + TANGENT +
            "      RETURN\n      END\n")
    result = _transform(tmp_path, body)
    _assert_builds(result)
    emitted = Path(result.entry_source).read_text()
    assert emitted.count("STATEV(2)") == 1


def test_a_read_in_another_routine_gets_no_sync(tmp_path):
    """The READ in SDVINI: no shadow exists there to be synced."""
    _gfortran()
    body = ("      SUBROUTINE SDVINI(STATEV,COORDS,NSTATV,NCRDS,NOEL,NPT,\n"
            "     1 LAYER,KSPT)\n"
            "      INCLUDE 'ABA_PARAM.INC'\n"
            "      DIMENSION STATEV(NSTATV),COORDS(NCRDS)\n"
            "      READ(28,*) STATEV(1),\n"
            "     1   STATEV(2)\n"
            "      RETURN\n      END\n" + HEADER +
            "      EMOD=PROPS(1)*(1.D0+STATEV(1))\n"
            "      DO K1=1,NTENS\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*DSTRAN(K1)\n"
            "      END DO\n" + TANGENT +
            "      RETURN\n      END\n")
    result = _transform(tmp_path, body)
    _assert_builds(result)


# --- an automatic shadow under a blanket SAVE ------------------------------

def test_a_blanket_save_does_not_save_an_automatic_shadow(tmp_path):
    """MCM-QMUL/PhaseFieldComp: SAVE DSTRAN_OTI with DSTRAN_OTI(NTENS)."""
    _gfortran()
    body = (HEADER.replace("      CHARACTER*80 CMNAME\n",
                           "      CHARACTER*80 CMNAME\n      SAVE\n") +
            "      DIMENSION EDEV(NTENS)\n"
            "      EMOD=PROPS(1)\n"
            "      DO K1=1,NTENS\n"
            "        EDEV(K1)=DSTRAN(K1)\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*EDEV(K1)\n"
            "      END DO\n" + TANGENT +
            "      RETURN\n      END\n")
    result = _transform(tmp_path, body)
    _assert_builds(result)


# --- an include shipped beside the source ----------------------------------

def test_an_include_beside_the_source_reaches_the_transform(tmp_path):
    """Woowinehouse/sanisand: the copy in the work directory had lost macro.h."""
    _gfortran()
    body = (HEADER.replace("      CHARACTER*80 CMNAME\n",
                           "      CHARACTER*80 CMNAME\n"
                           "      INCLUDE 'inc/material.inc'\n") +
            "      EMOD=PROPS(1)*SCALE\n"
            "      DO K1=1,NTENS\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*DSTRAN(K1)\n"
            "      END DO\n" + TANGENT +
            "      RETURN\n      END\n")
    result = _transform(tmp_path, body,
                        extra={"inc/material.inc": "      PARAMETER (SCALE=1.0D0)\n"})
    _assert_builds(result)
    import json
    bundle = json.loads((Path(result.out_dir) / "dependency_bundle.json").read_text())
    assert bundle["missing_includes"] == []


# --- intrinsics: DSINH in the UMAT itself, SUM over a run-time extent ------

def test_a_typed_hyperbolic_specific_in_the_umat_builds(tmp_path):
    """bessagroup/f3dasm_simulate: DSINH of a differentiated value."""
    _gfortran()
    body = (HEADER +
            "      EMOD=PROPS(1)\n"
            "      DO K1=1,NTENS\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*DSINH(DSTRAN(K1))\n"
            "      END DO\n" + TANGENT +
            "      RETURN\n      END\n")
    _assert_builds(_transform(tmp_path, body))


def test_sum_of_a_differentiated_array_transforms_and_builds(tmp_path):
    """Fourteen sources were refused for SUM; the whole-array form now has an OTI form."""
    _gfortran()
    body = (HEADER +
            "      EMOD=PROPS(1)\n"
            "      TR=SUM(DSTRAN(1:NDI))\n"
            "      DO K1=1,NTENS\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*DSTRAN(K1)\n"
            "      END DO\n"
            "      DO K1=1,NDI\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*TR\n"
            "      END DO\n" + TANGENT +
            "      RETURN\n      END\n")
    _assert_builds(_transform(tmp_path, body))


def test_sum_with_dim_is_refused_by_name_with_a_remedy(tmp_path):
    body = (HEADER +
            "      DIMENSION A(3,3)\n"
            "      EMOD=PROPS(1)\n"
            "      A=0.D0\n"
            "      A(1,1)=DSTRAN(1)\n"
            "      B=MAXVAL(SUM(A,DIM=1))\n"
            "      DO K1=1,NTENS\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*DSTRAN(K1)*B\n"
            "      END DO\n" + TANGENT +
            "      RETURN\n      END\n")
    result = _transform(tmp_path, body)
    assert not result.ok
    assert "SUM" in result.reason and "DIM" in result.reason
    assert "line" in result.reason and "What to do" in result.reason


# --- a REAL function handed a shadow ---------------------------------------

def test_a_real_function_handed_a_shadow_is_refused(tmp_path):
    """bessagroup's JE_OTI = det(DFGRD1_OTI), and czmHealing's PP(AD1_OTI)."""
    body = (HEADER +
            "      EMOD=PROPS(1)\n"
            "      DO K1=1,NTENS\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*PP(DSTRAN(K1))\n"
            "      END DO\n" + TANGENT +
            "      RETURN\n      END\n"
            "      REAL*8 FUNCTION PP(A)\n"
            "      REAL*8 A\n"
            "      PP=(A+ABS(A))*0.5D0\n"
            "      RETURN\n      END\n")
    result = _transform(tmp_path, body)
    if result.ok:
        # Acceptable only if PP was actually lifted, i.e. the build is OTI
        # all the way through: no reference to the REAL PP with a shadow.
        from umat_oti.transform.source_transform import (
            oti_arguments_into_untransformed_functions,
        )
        emitted = Path(result.entry_source).read_text()
        assert oti_arguments_into_untransformed_functions(emitted, "fixed") == []
    else:
        assert "function PP" in result.reason
        assert "What to do" in result.reason


# --- the new OTI forms compute the right numbers ---------------------------

PROGRAM = """program check
  use master_parameters, only: DP
  use {module}
  use oti_intrinsics
  implicit none
  type({type_name}) :: x, v(3), m(2,2), s, n, s2, n2
  x = 2.0_DP + E1
  v = (/ OTI_VALUE(1.0_DP), OTI_VALUE(x), OTI_VALUE(3) /)
  s = SUM(v)
  n = NORM2(v)
  m(1,:) = (/ OTI_VALUE(x), OTI_VALUE(1.0_DP) /)
  m(2,:) = (/ OTI_VALUE(0.5), OTI_VALUE(x*x) /)
  write(*,'(4ES24.16)') s%R, s%E1, n%R, n%E1
  s2 = SUM(m)
  n2 = NORM2(m)
  write(*,'(4ES24.16)') s2%R, s2%E1, n2%R, n2%E1
end program check
"""


def test_sum_norm2_and_mixed_constructors_are_exact(tmp_path):
    """Values and first derivatives against the analytical ones, at x = 2."""
    _gfortran()
    body = (HEADER + "      EMOD=PROPS(1)\n"
            "      DO K1=1,NTENS\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*DSTRAN(K1)\n"
            "      END DO\n" + TANGENT + "      RETURN\n      END\n")
    result = _transform(tmp_path, body)
    _assert_builds(result)
    out = Path(result.out_dir)
    module = next(p.stem for p in out.glob("otim*.f90"))
    type_name = module.replace("otim", "ONUMM").upper()
    build = tmp_path / "build"
    build.mkdir()
    for unit in ("master_parameters.f90", "real_utils.f90", f"{module}.f90",
                 "oti_intrinsics.f90"):
        shutil.copy2(out / unit, build / unit)
    (build / "check.f90").write_text(PROGRAM.format(module=module, type_name=type_name))
    units = ["master_parameters.f90", "real_utils.f90", f"{module}.f90",
             "oti_intrinsics.f90", "check.f90"]
    done = subprocess.run(["gfortran", "-ffree-line-length-none", *units, "-o", "check"],
                          cwd=build, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    run = subprocess.run(["./check"], cwd=build, capture_output=True, text=True)
    first, second = ([float(v) for v in line.split()] for line in run.stdout.splitlines()[:2])
    x = 2.0
    # v = (1, x, 3): SUM = 4 + x, d/dx = 1; NORM2 = sqrt(10 + x^2), d/dx = x/NORM2
    norm = (10 + x * x) ** 0.5
    assert first == pytest.approx([4 + x, 1.0, norm, x / norm], rel=1e-14, abs=1e-14)
    # m = [[x, 1], [0.5, x^2]]: SUM = x + 1.5 + x^2, d = 1 + 2x;
    # NORM2 = sqrt(x^2 + 1.25 + x^4), d = (x + 2x^3)/NORM2
    fro = (x * x + 1.25 + x ** 4) ** 0.5
    assert second == pytest.approx([x + 1.5 + x * x, 1 + 2 * x, fro,
                                    (x + 2 * x ** 3) / fro], rel=1e-14, abs=1e-14)


# --- lifted helper: mixed constructor, declared TINY, wrapped ** ----------

HELPER_UMAT = HEADER + """      DIMENSION V(3)
      EMOD=PROPS(1)
      CALL FILL(DSTRAN(1),V)
      DO K1=1,NTENS
        STRESS(K1)=STRESS(K1)+EMOD*DSTRAN(K1)*(V(1)+V(2)+V(3))
      END DO
""" + TANGENT + """      RETURN
      END
      SUBROUTINE FILL(PR,V)
      INCLUDE 'ABA_PARAM.INC'
      DOUBLE PRECISION, PARAMETER :: TINY = 1.0D-15
      DIMENSION V(3)
      V = (/ 1.0D0, -PR, 0.0D0 /)
      V(3) = 0.5D0*(V(1)**2.0D0-(V(2)**2.0D0+V(1)**2.0D0+V(2)**2.0D0+V(1)**2.0D0+V(2)**2.0D0+V(1)**2.0D0+V(2)**2.0D0+V(1)**2.0D0+V(2)**2.0D0))
      RETURN
      END
"""


def test_a_lifted_helper_with_the_three_constructs_builds(tmp_path):
    """AnargyrosKarakalas, luisez1988 and keisuke58 in one helper."""
    _gfortran()
    result = _transform(tmp_path, HELPER_UMAT)
    _assert_builds(result)


# --- an include shipped under another case --------------------------------

def test_an_include_shipped_in_another_case_is_found(tmp_path):
    """jpsferreira/UMAT-ABAQUS: INCLUDE 'PARAM_UMAT.INC', file param_umat.inc."""
    _gfortran()
    body = (HEADER.replace("      CHARACTER*80 CMNAME\n",
                           "      CHARACTER*80 CMNAME\n"
                           "      INCLUDE 'PARAM_UMAT.INC'\n") +
            "      EMOD=PROPS(1)*SCALE\n"
            "      CALL ADDS(STRESS,DSTRAN,EMOD,NTENS)\n" + TANGENT +
            "      RETURN\n      END\n"
            "      SUBROUTINE ADDS(S,D,E,N)\n"
            "      INCLUDE 'ABA_PARAM.INC'\n"
            "      INCLUDE 'PARAM_UMAT.INC'\n"
            "      DIMENSION S(N),D(N)\n"
            "      DO K=1,N\n"
            "        S(K)=S(K)+E*D(K)*SCALE\n"
            "      END DO\n"
            "      RETURN\n      END\n")
    result = _transform(tmp_path, body,
                        extra={"param_umat.inc": "      PARAMETER (SCALE=1.0D0)\n"})
    _assert_builds(result)


# --- an INTEGER selection matrix against a differentiated one --------------

def test_matmul_of_a_differentiated_and_an_integer_matrix_builds(tmp_path):
    """baw-de/poroMechanicalFoam: MATMUL(ASMALL, EXT) with EXT INTEGER."""
    _gfortran()
    body = (HEADER +
            "      DIMENSION A(3,3), B(3,3)\n"
            "      INTEGER IEXT(3,3)\n"
            "      EMOD=PROPS(1)\n"
            "      IEXT=0\n"
            "      IEXT(1,1)=1\n      IEXT(2,2)=1\n      IEXT(3,3)=1\n"
            "      A=0.D0\n"
            "      A(1,1)=DSTRAN(1)\n      A(2,2)=DSTRAN(2)\n      A(3,3)=DSTRAN(3)\n"
            "      B=MATMUL(A,IEXT)\n"
            "      DO K1=1,3\n"
            "        STRESS(K1)=STRESS(K1)+EMOD*B(K1,K1)\n"
            "      END DO\n" + TANGENT +
            "      RETURN\n      END\n")
    _assert_builds(_transform(tmp_path, body))


# --- a one-component (scalar) interface is refused, not mis-emitted --------

def test_a_scalar_stress_interface_is_refused_with_its_line(tmp_path):
    """phhannequart/UMAT_sma_hannequart: DOUBLE PRECISION STRESS, DSTRAN."""
    body = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      IMPLICIT NONE
      CHARACTER*80 CMNAME
      INTEGER NDI,NSHR,NTENS,NSTATV,NPROPS,NOEL,NPT,LAYER,KSPT,KSTEP,KINC
      DOUBLE PRECISION STRESS, STRAN, DSTRAN, DDSDDE
      DOUBLE PRECISION STATEV(NSTATV),SSE,SPD,SCD,RPL,DDSDDT(1),DRPLDE(1)
      DOUBLE PRECISION DRPLDT,TIME(2),DTIME,TEMP,DTEMP,PREDEF(1),DPRED(1)
      DOUBLE PRECISION PROPS(NPROPS),COORDS(3),DROT(3,3),PNEWDT,CELENT
      DOUBLE PRECISION DFGRD0(3,3),DFGRD1(3,3)
      STRESS=STRESS+PROPS(1)*DSTRAN
      DDSDDE=PROPS(1)
      RETURN
      END
"""
    result = _transform(tmp_path, body)
    assert not result.ok
    assert "declared as a scalar" in result.reason
    assert "line 8" in result.reason and "What to do" in result.reason
