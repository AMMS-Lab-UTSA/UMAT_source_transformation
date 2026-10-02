"""Lifted helpers keep what the Fortran meant, and functions on the stress path lift.

One UMAT exercises the B2 lifter/transform fixes together, each a defect seen
in the corpus:

* ``DATA FIRST /.TRUE./`` + ``SAVE`` (Vera B1 toy a1): the lifted body put
  SAVE after an executable line (compile error) and re-ran the DATA
  assignment on every call (a first-call switch reset each time). Here a
  SAVEd call counter must count 1, 2, 3 across three increments.
* ``REALV(1)=0.`` was read as the declaration ``REAL V(1)=0.``
  (UMAT_KLP_RK5_hybrid's KUMATCHECKS).
* ``CHARACTER(16) TAG`` + ``PARAMETER (TAG=...)`` was declared twice
  (jpsferreira umat_general.for).
* ``CALL STDB_ABQERR`` / ``CALL XIT`` in a helper refused the lift outright;
  they now pass through (nothing differentiated flows through them).
* A FUNCTION called from the stress update with differentiated arguments
  (UVCmultiaxial's DOTPROD6) was refused for the leak; it is lifted and the
  reference renamed.
* ``MAX``/``MIN`` with three arguments over OTI values matched no specific.
* ``a=1; b=2`` on one fixed-form line was wrapped onto a continuation.

Behavioural: STRESS/STATEV of the transformed build equal the ORIGINAL's
(compiled on its own) bitwise over three increments, and DDSDDE equals the
closed-form tangent of the model at each increment.
"""
import json
import shutil
import subprocess

import numpy as np
import pytest

SOURCE = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      CALL HELPER(STRESS,DSTRAN,PROPS,NTENS,STATEV)
      DO K=1,NTENS
        STRESS(K)=STRESS(K)+0.1D0*DOTP(DSTRAN,DSTRAN,NTENS)*DSTRAN(K)
      END DO
      Q1=MAX(DSTRAN(1),DSTRAN(2),0.D0); Q2=MIN(DSTRAN(3),DSTRAN(4),1.D0)
      STRESS(1)=STRESS(1)+PROPS(1)*(Q1+Q2)
      DO K=1,NTENS
        DO L=1,NTENS
          DDSDDE(K,L)=0.D0
        END DO
      END DO
      RETURN
      END
      DOUBLE PRECISION FUNCTION DOTP(A,B,N)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION A(N),B(N)
      DOTP=0.D0
      DO K=1,N
        DOTP=DOTP+A(K)*B(K)
      END DO
      RETURN
      END
      SUBROUTINE HELPER(S,DE,P,N,SV)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION S(N),DE(N),P(*),SV(*),REALV(2),INTV(1)
      CHARACTER*8 CHARV(1)
      CHARACTER(16) TAG
      PARAMETER (TAG='helper')
      LOGICAL FIRST
      SAVE FIRST, COUNT
      DATA FIRST /.TRUE./
      REALV(1)=0.
      INTV(1)=0
      CHARV(1)=TAG(1:8)
      IF (FIRST) THEN
        COUNT=0.D0
        FIRST=.FALSE.
      END IF
      COUNT=COUNT+1.D0
      SV(1)=COUNT
      IF (P(1).LT.0.D0) CALL STDB_ABQERR(-3,'negative',INTV,REALV,
     1 CHARV)
      IF (P(1).LT.0.D0) CALL XIT
      DO K=1,N
        S(K)=S(K)+P(1)*DE(K)*(1.D0+DE(K)**2)*COUNT
      END DO
      RETURN
      END
"""

DRIVER = """program check
implicit none
real(8) :: stress(6), statev(1), ddsdde(6,6), dstran(6), props(1), stran(6)
real(8) :: s0(6), x0(1), dd(6,6)
real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3,3), dfgrd0(3,3), dfgrd1(3,3)
real(8) :: sse, spd, scd, rpl, drpldt, dtime, temp, dtemp, pnewdt, celent, ddsddt(6), drplde(6)
real(8) :: path(6,3)
character(len=80) :: cmname
integer :: inc, k
props = (/ 200.0d0 /)
path(:,1) = (/ 0.02d0, -0.01d0, 0.005d0, 0.003d0, -0.002d0, 0.001d0 /)
path(:,2) = (/ -0.01d0, 0.03d0, -0.004d0, 0.006d0, 0.002d0, -0.003d0 /)
path(:,3) = (/ 0.015d0, 0.012d0, 0.007d0, -0.002d0, 0.004d0, 0.002d0 /)
time = 0; dtime = 1; temp = 0; dtemp = 0; predef = 0; dpred = 0; coords = 0
drot = 0; dfgrd0 = 0; dfgrd1 = 0; celent = 1; pnewdt = 1; cmname = 'MAT'; stran = 0
stress = 0; statev = 0; s0 = 0; x0 = 0
do inc = 1, 3
  dstran = path(:, inc)
  ddsdde = 0
  call umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
            stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 1, &
            props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, inc)
  dd = 0
  call umatorig(s0, x0, dd, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 1, &
                props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, inc)
  write(*, '(A,I0,7Z17)') 'OTIBITS ', inc, stress, statev
  write(*, '(A,I0,7Z17)') 'ORIGBITS ', inc, s0, x0
  do k = 1, 6
    write(*, '(A,I0,1X,I0,6ES25.16)') 'DDSDDE ', inc, k, ddsdde(k, :)
  end do
end do
end program
subroutine stdb_abqerr(lop, string, intv, realv, charv)
  integer :: lop, intv(*)
  real(8) :: realv(*)
  character(len=*) :: string, charv(*)
  stop 9
end subroutine stdb_abqerr
subroutine xit
  stop 9
end subroutine xit
"""


def _closed_form_tangent(de: np.ndarray, count: float, e: float) -> np.ndarray:
    tangent = np.diag(e * (1 + 3 * de**2) * count)
    tangent += 0.1 * (np.dot(de, de) * np.eye(6) + 2 * np.outer(de, de))
    q1 = int(np.argmax([de[0], de[1], 0.0]))
    if q1 < 2:
        tangent[0, q1] += e
    q2 = int(np.argmin([de[2], de[3], 1.0]))
    if q2 < 2:
        tangent[0, 2 + q2] += e
    return tangent


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_lifted_helpers_and_functions_reproduce_the_original(tmp_path):
    from umat_oti.services.transformation import run_transformation

    source = tmp_path / "material.for"
    source.write_text(SOURCE)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    raw = {"schema_version": "1.1", "source": str(source), "entry_routine": "UMAT", "ntens": 6,
           "derivatives": [{"target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1}],
           "material_point_driver": {"dstran_per_increment": None, "nstatv": None}}
    (tmp_path / "contract.json").write_text(json.dumps(raw))
    output = tmp_path / "out"
    summary, code = run_transformation(tmp_path / "contract.json", output)
    assert code == 0, summary
    helpers = (output / "umat_oti_helpers.f90").read_text().lower()
    assert "function dotp_oti" in helpers and "subroutine helper_oti" in helpers
    shutil.copy(tmp_path / "ABA_PARAM.INC", output / "ABA_PARAM.INC")
    built = subprocess.run([str(output / "compile_hint.sh")], capture_output=True, text=True, cwd=output)
    assert built.returncode == 0, built.stdout + built.stderr
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(tmp_path / "ABA_PARAM.INC", reference / "ABA_PARAM.INC")
    import re
    renamed = re.sub(r"\bDOTP\b", "DOTPR", re.sub(r"\bHELPER\b", "HELPERR",
                     SOURCE.replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(", 1)))
    (reference / "orig.for").write_text(renamed)
    subprocess.run(["gfortran", "-O0", "-std=legacy", f"-I{reference}", "-c", "orig.for", "-o", "orig.o"],
                   check=True, capture_output=True, text=True, cwd=reference)
    (tmp_path / "driver.f90").write_text(DRIVER)
    subprocess.run(["gfortran", "-ffree-line-length-none", "driver.f90",
                    *[str(p) for p in output.glob("*.o")], str(reference / "orig.o"), "-o", "check"],
                   check=True, capture_output=True, text=True, cwd=tmp_path)
    lines = subprocess.run([str(tmp_path / "check")], check=True, capture_output=True,
                           text=True, cwd=tmp_path).stdout.splitlines()
    bits = {(r.split()[0], int(r.split()[1])): r.split()[2:] for r in lines if r.startswith(("OTIBITS", "ORIGBITS"))}
    paths = np.array([[0.02, -0.01, 0.005, 0.003, -0.002, 0.001],
                      [-0.01, 0.03, -0.004, 0.006, 0.002, -0.003],
                      [0.015, 0.012, 0.007, -0.002, 0.004, 0.002]])
    for inc in (1, 2, 3):
        assert bits[("OTIBITS", inc)] == bits[("ORIGBITS", inc)], inc
        tangent = np.array([[float(v) for v in r.split()[3:]] for r in lines
                            if r.startswith(f"DDSDDE {inc} ")])
        expected = _closed_form_tangent(paths[inc - 1], float(inc), 200.0)
        np.testing.assert_allclose(tangent, expected, rtol=1e-12, atol=1e-12)
