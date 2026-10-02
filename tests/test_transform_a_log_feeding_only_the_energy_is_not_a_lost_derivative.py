"""GOH_Example.f's ``lnJe = REAL(LOG(DETFE_OTI))``: truncated where nothing differentiates it.

Curie-G (B2 cluster E) listed the truncation as a derivative loss. In the source
``lnJe`` reaches only SSE, the specific strain energy, which the transform returns
REAL and differentiates nowhere: STRESS, DDSDDE and STATEV do not read it. The
truncation is therefore exact for every output the transform claims. Where the
same logarithm DOES reach the stress, it must carry its derivative.

Behavioural, both shapes, against the ORIGINAL compiled on its own: STRESS and
STATEV bitwise over two increments, DDSDDE against central differences of the
original at three step sizes. (In GOH the transform truncates lnJe; in this
toy it carries it. Either is exact for the claimed outputs; what must never
happen is the stress-feeding shape losing it.)
"""
import json
import re
import shutil
import subprocess

import pytest

from test_transform_stress_lines_are_not_bridged_into_tangent_skips import DRIVER

HEAD = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      REAL*8 DETE, XLNJ
      DETE=1.D0+DSTRAN(1)+DSTRAN(2)+DSTRAN(3)+STATEV(1)
      XLNJ=DLOG(DETE)
"""
TAIL = """      DO K=1,NTENS
        DO L=1,NTENS
          DDSDDE(K,L)=0.D0
        END DO
      END DO
      STATEV(1)=STATEV(1)+0.1D0*DSTRAN(1)
      SSE=0.5D0*PROPS(1)*(DETE**2-1.D0)/2.D0-PROPS(1)*XLNJ
      RETURN
      END
"""
ENERGY_ONLY = HEAD + """      DO K=1,NTENS
        STRESS(K)=STRESS(K)+PROPS(1)*DETE*DSTRAN(K)
      END DO
""" + TAIL
STRESS_TOO = HEAD + """      DO K=1,NTENS
        STRESS(K)=STRESS(K)+PROPS(1)*(DETE+XLNJ)*DSTRAN(K)
      END DO
""" + TAIL


def _run(tmp_path, text):
    from umat_oti.services.transformation import run_transformation

    source = tmp_path / "material.for"
    source.write_text(text)
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
    (reference / "orig.for").write_text(text.replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(", 1))
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
    return next(output.glob("*_oti.for")).read_text()


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_log_feeding_only_the_energy_is_truncated_without_loss(tmp_path):
    _run(tmp_path, ENERGY_ONLY)


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_log_feeding_the_stress_carries_its_derivative(tmp_path):
    emitted = _run(tmp_path, STRESS_TOO)
    assert re.search(r"XLNJ_OTI\s*=", emitted, re.IGNORECASE), emitted
