"""Part two of the V11 performance measurements: per-evaluation material-point cost.

Builds three executables over the same 20-increment uniaxial path and times them:
  original    the untransformed J2 UMAT, real arithmetic, no derivative
  oti_order1  the transformed UMAT at order 1 (DDSDDE through the interface)
  fd_ddsdde   the original UMAT driven by centred differences to form the same
              6x6 tangent (12 extra increment evaluations per increment)

The order-4 build is attempted separately and its outcome recorded, because the
generated type carries 211 stored coefficients and the compiler cost is the point.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from statistics import median

REPO = Path("/home/claude/repo")
sys.path.insert(0, str(REPO / "src"))
FC = shutil.which("gfortran")
OUT = Path("bench")
OUT.mkdir(exist_ok=True)

ABA = "      IMPLICIT REAL*8(A-H,O-Z)\n      PARAMETER (NPRECD=2)\n"

COMMON_DECL = r"""
      INTEGER, PARAMETER :: NT=6, NS=1, NP=4
      DOUBLE PRECISION STRESS(NT),STATEV(NS),DDSDDE(NT,NT),DDSDDT(NT)
      DOUBLE PRECISION DRPLDE(NT),STRAN(NT),DSTRAN(NT),TIME(2),PREDEF(1)
      DOUBLE PRECISION DPRED(1),PROPS(NP),COORDS(3),DROT(3,3)
      DOUBLE PRECISION DFGRD0(3,3),DFGRD1(3,3)
      DOUBLE PRECISION SSE,SPD,SCD,RPL,DRPLDT,DTIME,TEMP,DTEMP,PNEWDT
      DOUBLE PRECISION CELENT,ACC,S0(NT),V0(NS),SP(NT),SM(NT),HSTEP
      CHARACTER*80 CMNAME
      INTEGER I,J,K,L,NREP,NINC
"""

SETUP = r"""
      NREP = %REP%
      NINC = 20
      HSTEP = 1.0D-8
      PROPS(1)=200000.0D0
      PROPS(2)=0.3D0
      PROPS(3)=250.0D0
      PROPS(4)=2000.0D0
      DTIME=1.0D0
      TEMP=293.15D0
      DTEMP=0.0D0
      PNEWDT=1.0D0
      CELENT=1.0D0
      CMNAME='J2'
      ACC=0.0D0
      DO I=1,3
        DO J=1,3
          DROT(I,J)=0.0D0
          DFGRD0(I,J)=0.0D0
          DFGRD1(I,J)=0.0D0
        END DO
        DROT(I,I)=1.0D0
        DFGRD0(I,I)=1.0D0
        DFGRD1(I,I)=1.0D0
      END DO
"""

CALL = r"""          CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,
     1     DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2     CMNAME,3,3,NT,NS,PROPS,NP,COORDS,DROT,PNEWDT,CELENT,
     3     DFGRD0,DFGRD1,1,1,1,1,1,J)
"""

DRIVER_PLAIN = ("      PROGRAM MPDRV\n      IMPLICIT NONE\n" + COMMON_DECL + SETUP + r"""
      DO K=1,NREP
        DO I=1,NT
          STRESS(I)=0.0D0
          STRAN(I)=0.0D0
          DSTRAN(I)=0.0D0
        END DO
        STATEV(1)=0.0D0
        DSTRAN(1)=1.0D-4
        DO J=1,NINC
""" + CALL + r"""          DO I=1,NT
            STRAN(I)=STRAN(I)+DSTRAN(I)
          END DO
        END DO
        ACC=ACC+STRESS(1)+DDSDDE(1,1)
      END DO
      WRITE(*,*) ACC
      END
""")

# Centred differences over the strain increment, re-running the increment from
# the same start-of-increment state, exactly as a tangent reference would.
DRIVER_FD = ("      PROGRAM MPDRV\n      IMPLICIT NONE\n" + COMMON_DECL + SETUP + r"""
      DO K=1,NREP
        DO I=1,NT
          STRESS(I)=0.0D0
          STRAN(I)=0.0D0
          DSTRAN(I)=0.0D0
        END DO
        STATEV(1)=0.0D0
        DSTRAN(1)=1.0D-4
        DO J=1,NINC
          DO I=1,NT
            S0(I)=STRESS(I)
          END DO
          V0(1)=STATEV(1)
          DO L=1,NT
            DO I=1,NT
              STRESS(I)=S0(I)
            END DO
            STATEV(1)=V0(1)
            DSTRAN(L)=DSTRAN(L)+HSTEP
""" + CALL + r"""            DO I=1,NT
              SP(I)=STRESS(I)
            END DO
            DSTRAN(L)=DSTRAN(L)-2.0D0*HSTEP
            DO I=1,NT
              STRESS(I)=S0(I)
            END DO
            STATEV(1)=V0(1)
""" + CALL + r"""            DO I=1,NT
              SM(I)=STRESS(I)
            END DO
            DSTRAN(L)=DSTRAN(L)+HSTEP
            DO I=1,NT
              DDSDDE(I,L)=(SP(I)-SM(I))/(2.0D0*HSTEP)
            END DO
          END DO
          DO I=1,NT
            STRESS(I)=S0(I)
          END DO
          STATEV(1)=V0(1)
""" + CALL + r"""          DO I=1,NT
            STRAN(I)=STRAN(I)+DSTRAN(I)
          END DO
        END DO
        ACC=ACC+STRESS(1)+DDSDDE(1,1)
      END DO
      WRITE(*,*) ACC
      END
""")


def timed(fn, reps):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return {"reps": reps, "median_s": round(median(ts), 4),
            "min_s": round(min(ts), 4), "max_s": round(max(ts), 4)}


def build_order1(work: Path) -> Path:
    """Transform the J2 source at order 1 and return the generated directory."""
    from umat_oti.cli_json import main as cli_main
    cfg = json.loads((REPO / "examples/j2_actual_higher_order.json").read_text())
    cfg["source"] = str(REPO / "UMATs/UMATs/generic_ps/j2_props.f")
    cfg["derivatives"] = [{"id": "material_tangent", "target": "DDSDDE",
                           "seed": "DSTRAN", "response": "STRESS", "order": 1}]
    cfg["validation"]["order"] = 1
    p = work / "j2_order1.json"
    p.write_text(json.dumps(cfg, indent=1))
    gen = work / "gen1"
    cwd = os.getcwd()
    os.chdir(REPO)
    try:
        t0 = time.perf_counter()
        cli_main(["--config", str(p), "--out", str(gen)])
        dt = time.perf_counter() - t0
    finally:
        os.chdir(cwd)
    return gen, dt


def compile_plain(work: Path, driver_src: str, name: str, timeout=900):
    d = work / name
    d.mkdir()
    (d / "drv.f").write_text(driver_src)
    (d / "ABA_PARAM.INC").write_text(ABA)
    t0 = time.perf_counter()
    r = subprocess.run([FC, "-O1", "-std=legacy", "-ffixed-line-length-none",
                        "-I", str(d), str(REPO / "UMATs/UMATs/generic_ps/j2_props.f"),
                        str(d / "drv.f"), "-o", str(d / "a.out")],
                       capture_output=True, cwd=d, timeout=timeout)
    dt = time.perf_counter() - t0
    if r.returncode:
        return None, {"error": r.stderr.decode()[-500:]}
    return d, {"compile_s": round(dt, 3)}


def compile_oti(work: Path, gen: Path, driver_src: str, name: str, timeout=1800):
    d = work / name
    d.mkdir()
    for f in gen.iterdir():
        if f.is_file():
            shutil.copy(f, d / f.name)
    (d / "drv.f").write_text(driver_src)
    (d / "ABA_PARAM.INC").write_text(ABA)
    units = (d / "compile_order.txt").read_text().split()
    cmd = [FC, "-O1", "-std=legacy", "-ffree-line-length-none",
           "-ffixed-line-length-none", "-I", str(d), "-J", str(d)]
    cmd += [str(d / u) for u in units] + [str(d / "drv.f"), "-o", str(d / "a.out")]
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, capture_output=True, cwd=d, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, {"error": f"compilation exceeded {timeout} s on this machine"}
    dt = time.perf_counter() - t0
    if r.returncode:
        return None, {"error": r.stderr.decode()[-600:]}
    return d, {"compile_s": round(dt, 3)}


def main():
    NREP = 20000
    plain = DRIVER_PLAIN.replace("%REP%", str(NREP))
    fd = DRIVER_FD.replace("%REP%", str(NREP))
    work = Path(tempfile.mkdtemp(prefix="umat_oti_bench2_"))
    res = {"umat_calls_per_run_primal": NREP * 20,
           "umat_calls_per_run_fd": NREP * 20 * 13,
           "repetitions_of_the_20_increment_path": NREP}
    try:
        d, info = compile_plain(work, plain, "orig")
        res["original_real"] = dict(info)
        if d:
            res["original_real"].update(timed(
                lambda: subprocess.run([str(d / "a.out")], check=True,
                                       capture_output=True, cwd=d), 3))
        print("original:", res["original_real"])

        d, info = compile_plain(work, fd, "fd")
        res["centred_fd_tangent"] = dict(info)
        if d:
            res["centred_fd_tangent"].update(timed(
                lambda: subprocess.run([str(d / "a.out")], check=True,
                                       capture_output=True, cwd=d), 3))
        print("fd:", res["centred_fd_tangent"])

        gen1, tdt = build_order1(work)
        res["transform_order1_s"] = round(tdt, 3)
        d, info = compile_oti(work, gen1, plain, "oti1")
        res["oti_order1"] = dict(info)
        if d:
            res["oti_order1"].update(timed(
                lambda: subprocess.run([str(d / "a.out")], check=True,
                                       capture_output=True, cwd=d), 3))
        print("oti order 1:", res["oti_order1"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    (OUT / "bench2.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
