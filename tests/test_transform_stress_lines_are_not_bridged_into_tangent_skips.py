"""A tangent-only helper call does not drag the stress path's lines out with it.

GOH_Example.f (Curie-G, B2 cluster E): ``call move6to33(fginv,fginvmat)``
feeds only the author's tangent, so it is skipped. The skip region was then
grown backwards over every statement whose result the call reads -- the six
``fginv(i)=...`` lines -- although FGINV also feeds FE and through it the
stress. They were commented out, FGINV_OTI stayed zero, and the transformed
routine took LOG(0). A bridge now stops at any statement on the stress path.

Behavioural: the same shape, transformed, against the ORIGINAL compiled on its
own -- STRESS bitwise over two increments, DDSDDE against central differences.
"""
import json
import shutil
import subprocess

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
      DIMENSION FGI(6), FGIM(3,3)
      G=1.D0+STATEV(1)
      FGI(1)=1.D0/G+DSTRAN(1)
      FGI(2)=1.D0/G+DSTRAN(2)
      FGI(3)=1.D0/G+DSTRAN(3)
      FGI(4)=DSTRAN(4)
      FGI(5)=DSTRAN(5)
      FGI(6)=DSTRAN(6)
      CALL MOVE6(FGI,FGIM)
      DO K=1,NTENS
        STRESS(K)=STRESS(K)+PROPS(1)*LOG(FGI(MIN(K,3)))*FGI(K)
      END DO
      DO K=1,NTENS
        DO L=1,NTENS
          DDSDDE(K,L)=0.D0
        END DO
        DDSDDE(K,K)=PROPS(1)*FGIM(1,1)
      END DO
      STATEV(1)=STATEV(1)+DSTRAN(1)
      RETURN
      END
      SUBROUTINE MOVE6(V,A)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION V(6),A(3,3)
      A(1,1)=V(1)
      A(2,2)=V(2)
      A(3,3)=V(3)
      A(1,2)=V(4)
      A(2,1)=V(4)
      A(1,3)=V(5)
      A(3,1)=V(5)
      A(2,3)=V(6)
      A(3,2)=V(6)
      RETURN
      END
"""

DRIVER = """program check
implicit none
real(8) :: stress(6), statev(1), ddsdde(6,6), dstran(6), props(1), stran(6)
real(8) :: s0(6), x0(1), sp(6), sm(6), xp(1), xm(1), dd(6,6), h
real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3,3), dfgrd0(3,3), dfgrd1(3,3)
real(8) :: sse, spd, scd, rpl, drpldt, dtime, temp, dtemp, pnewdt, celent, ddsddt(6), drplde(6)
character(len=80) :: cmname
integer :: inc, j, s, k
props = (/ 50.0d0 /)
time = 0; dtime = 1; temp = 0; dtemp = 0; predef = 0; dpred = 0; coords = 0
drot = 0; dfgrd0 = 0; dfgrd1 = 0; celent = 1; pnewdt = 1; cmname = 'MAT'; stran = 0
stress = 0; statev = 0.2d0; s0 = 0; x0 = 0.2d0
do inc = 1, 2
  dstran = (/ 2.0d-2, -1.0d-2, 0.5d-2, 0.3d-2, -0.2d-2, 0.1d-2 /) * inc
  do j = 1, 6
    do s = 4, 6
      h = 10.0d0**(-s)
      sp = s0; xp = x0; dstran(j) = dstran(j) + h
      call orig(sp, xp, dstran)
      dstran(j) = dstran(j) - 2*h
      sm = s0; xm = x0
      call orig(sm, xm, dstran)
      dstran(j) = dstran(j) + h
      write(*, '(A,I0,1X,I0,1X,I0,6ES25.16)') 'FD ', inc, j, s, (sp - sm)/(2*h)
    end do
  end do
  ddsdde = 0
  call umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
            stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 1, &
            props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, inc)
  call orig(s0, x0, dstran)
  write(*, '(A,I0,7Z17)') 'OTIBITS ', inc, stress, statev
  write(*, '(A,I0,7Z17)') 'ORIGBITS ', inc, s0, x0
  do k = 1, 6
    write(*, '(A,I0,1X,I0,6ES25.16)') 'DDSDDE ', inc, k, ddsdde(k, :)
  end do
end do
contains
  subroutine orig(sout, xout, de)
    real(8), intent(inout) :: sout(6), xout(1)
    real(8), intent(in) :: de(6)
    dd = 0
    call umatorig(sout, xout, dd, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                  stran, de, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 1, &
                  props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, 1)
  end subroutine orig
end program
"""


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_stress_path_lines_before_a_skipped_helper_call_stay_live(tmp_path):
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
    shutil.copy(tmp_path / "ABA_PARAM.INC", output / "ABA_PARAM.INC")
    subprocess.run([str(output / "compile_hint.sh")], check=True, capture_output=True, text=True, cwd=output)
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(tmp_path / "ABA_PARAM.INC", reference / "ABA_PARAM.INC")
    (reference / "orig.for").write_text(SOURCE.replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(", 1)
                                        .replace("SUBROUTINE MOVE6(", "SUBROUTINE MOVE6R(")
                                        .replace("CALL MOVE6(", "CALL MOVE6R("))
    subprocess.run(["gfortran", "-O0", "-std=legacy", f"-I{reference}", "-c", "orig.for", "-o", "orig.o"],
                   check=True, capture_output=True, text=True, cwd=reference)
    (tmp_path / "driver.f90").write_text(DRIVER)
    subprocess.run(["gfortran", "-ffree-line-length-none", "driver.f90",
                    *[str(p) for p in output.glob("*.o")], str(reference / "orig.o"), "-o", "check"],
                   check=True, capture_output=True, text=True, cwd=tmp_path)
    lines = subprocess.run([str(tmp_path / "check")], check=True, capture_output=True,
                           text=True, cwd=tmp_path).stdout.splitlines()
    bits = {(r.split()[0], int(r.split()[1])): r.split()[2:] for r in lines if r.startswith(("OTIBITS", "ORIGBITS"))}
    tangent = {(int(r.split()[1]), int(r.split()[2])): [float(v) for v in r.split()[3:]]
               for r in lines if r.startswith("DDSDDE ")}
    fd: dict = {}
    for row in lines:
        if row.startswith("FD "):
            _, inc, j, s, *values = row.split()
            fd.setdefault((int(inc), int(j)), {})[int(s)] = [float(v) for v in values]
    for inc in (1, 2):
        assert bits[("OTIBITS", inc)] == bits[("ORIGBITS", inc)], inc
        for j in range(1, 7):
            steps = fd[(inc, j)]
            scale = max(1.0, max(abs(v) for v in steps[5]))
            assert max(abs(a - b) for a, b in zip(steps[4], steps[5])) <= 1e-6 * scale
            for k in range(6):
                assert abs(tangent[(inc, k + 1)][j - 1] - steps[6][k]) <= 1e-6 * scale, (inc, k, j)


CURING = "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,\n     1 RPL,DDSDDT,DRPLDE,DRPLDT,\n     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,\n     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,\n     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)\n      INCLUDE 'ABA_PARAM.INC'\n      CHARACTER*80 CMNAME\n      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),\n     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),\n     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),\n     3 DFGRD0(3,3),DFGRD1(3,3)\n      CURE=STATEV(1)\n      CALL CURING(CURE, RATE)\n      DO K=1,NTENS\n        STRESS(K)=STRESS(K)+PROPS(1)*DSTRAN(K)*(1.D0+RATE)\n      END DO\n      STATEV(1)=CURE+RATE*DTIME\n      DO K=1,NTENS\n        DO L=1,NTENS\n          DDSDDE(K,L)=0.D0\n        END DO\n      END DO\n      RETURN\n      END\n      SUBROUTINE CURING(CURE, RATE)\n      INCLUDE 'ABA_PARAM.INC'\n      DOUBLE PRECISION CURE, RATE, XM, CMAX\n      XM = 0.40\n      CMAX = 0.98\n      RATE = 0.057*((1.0-CURE/CMAX)**1.4)*((CURE/CMAX)**XM)\n      RETURN\n      END\n"


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_literal_constant_exponent_keeps_the_zero_base_finite(tmp_path):
    """Worlthen curing (Curie-G cluster E): ``(cure/cmax)**m`` at cure = 0.

    m holds only the literal 0.40. Lifted as an OTI value the power went
    OTI**OTI, through LOG(0), and returned a non-finite value where the
    source returns 0. Kept REAL(8) -- it carries no derivative -- the power is
    OTI**REAL, whose zero base is defined. The transformed STRESS/STATEV must
    equal the original's bitwise from a zero cure state.
    """
    from umat_oti.services.transformation import run_transformation
    from umat_oti.transform.helper_lifting import _literal_constant_locals
    from umat_oti.fortran.parser import logical_lines_from_text

    source = tmp_path / "material.for"
    source.write_text(CURING)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    raw = {"schema_version": "1.1", "source": str(source), "entry_routine": "UMAT", "ntens": 6,
           "derivatives": [{"target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1}],
           "material_point_driver": {"dstran_per_increment": None, "nstatv": None}}
    (tmp_path / "contract.json").write_text(json.dumps(raw))
    output = tmp_path / "out"
    summary, code = run_transformation(tmp_path / "contract.json", output)
    assert code == 0, summary
    helpers = (output / "umat_oti_helpers.f90").read_text().lower()
    assert "real(8) :: xm" in helpers.replace("cmax, xm", "xm") or "real(8) :: cmax, xm" in helpers
    shutil.copy(tmp_path / "ABA_PARAM.INC", output / "ABA_PARAM.INC")
    subprocess.run([str(output / "compile_hint.sh")], check=True, capture_output=True, text=True, cwd=output)
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(tmp_path / "ABA_PARAM.INC", reference / "ABA_PARAM.INC")
    (reference / "orig.for").write_text(CURING.replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(", 1)
                                        .replace("SUBROUTINE CURING(", "SUBROUTINE CURINGR(")
                                        .replace("CALL CURING(", "CALL CURINGR("))
    subprocess.run(["gfortran", "-O0", "-std=legacy", f"-I{reference}", "-c", "orig.for", "-o", "orig.o"],
                   check=True, capture_output=True, text=True, cwd=reference)
    driver = DRIVER.replace("statev = 0.2d0; s0 = 0; x0 = 0.2d0", "statev = 0.0d0; s0 = 0; x0 = 0.0d0")
    (tmp_path / "driver.f90").write_text(driver)
    subprocess.run(["gfortran", "-ffree-line-length-none", "driver.f90",
                    *[str(p) for p in output.glob("*.o")], str(reference / "orig.o"), "-o", "check"],
                   check=True, capture_output=True, text=True, cwd=tmp_path)
    lines = subprocess.run([str(tmp_path / "check")], check=True, capture_output=True,
                           text=True, cwd=tmp_path).stdout.splitlines()
    bits = {(r.split()[0], int(r.split()[1])): r.split()[2:] for r in lines if r.startswith(("OTIBITS", "ORIGBITS"))}
    for inc in (1, 2):
        assert bits[("OTIBITS", inc)] == bits[("ORIGBITS", inc)], inc
    tangent = [float(v) for r in lines if r.startswith("DDSDDE ") for v in r.split()[3:]]
    assert all(v == v and abs(v) < 1e300 for v in tangent)
