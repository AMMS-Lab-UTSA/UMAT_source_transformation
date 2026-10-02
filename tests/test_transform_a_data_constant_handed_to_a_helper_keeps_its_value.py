"""A DATA constant that reaches a lifted helper keeps its DATA value in its shadow.

GOH_Example.f (abuganza, Curie-G B2 cluster E): ``data xi/1,1,1,0,0,0/`` is the
Voigt identity. The classifier keeps a never-assigned DATA name real, but
``call move6to33(xi, ximat)`` hands it to a lifted helper, whose argument
surface gave it a shadow anyway -- SAVEd (DATA implies SAVE), so never zeroed
and never copied: XI_OTI stayed 0, the pressure term ``(...)*xi(ii)`` vanished,
and sigma_11 came back off by 0.085 (ulpK 3.6e13 in the replay of the recorded
Abaqus calls). The shadow is now copied from the real variable at entry.

Behavioural, against the ORIGINAL compiled on its own: STRESS/STATEV bitwise
over two increments, DDSDDE against central differences at three step sizes.
"""
import json
import shutil
import subprocess

import pytest

from test_transform_stress_lines_are_not_bridged_into_tangent_skips import DRIVER

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
      DIMENSION XI(6), XM(3,3)
      DATA XI/1.D0,1.D0,1.D0,0.D0,0.D0,0.D0/
      P=PROPS(1)*(DSTRAN(1)+DSTRAN(2)+DSTRAN(3))*(1.D0+STATEV(1))
      CALL MOVE6(XI,XM,P)
      DO K=1,NTENS
        STRESS(K)=STRESS(K)+P*XI(K)+PROPS(1)*DSTRAN(K)*XM(1,1)
      END DO
      DO K=1,NTENS
        DO L=1,NTENS
          DDSDDE(K,L)=0.D0
        END DO
      END DO
      STATEV(1)=STATEV(1)+0.1D0*DSTRAN(1)
      RETURN
      END
      SUBROUTINE MOVE6(V,A,S)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION V(6),A(3,3)
      A(1,1)=V(1)*(1.D0+S)
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


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_data_constant_handed_to_a_lifted_helper_keeps_its_value(tmp_path):
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
