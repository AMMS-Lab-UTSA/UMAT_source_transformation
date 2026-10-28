"""Performance measurements for UMAT_OTI_SoftwareX_V11.

Nothing here is taken from a prior run. Every number is measured now, on this
machine, and each measurement is reported with its repetition count, its median
and its full spread. Costs that occur once (module generation, transformation,
compilation) are reported separately from costs that recur per material-point
evaluation.

Usage:  python src/benchmark.py            (writes bench/bench.json and a table)
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from math import comb
from pathlib import Path
from statistics import median

REPO = Path("/home/claude/repo")
sys.path.insert(0, str(REPO / "src"))

OUT = Path("bench")
OUT.mkdir(exist_ok=True)

FC = shutil.which("gfortran")
REPS_FAST = 3
REPS_SLOW = 2


def timed(fn, reps):
    ts = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    return {"reps": reps, "median_s": median(ts), "min_s": min(ts), "max_s": max(ts)}


def environment():
    cpu = ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    mem_kb = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                mem_kb = int(line.split()[1])
                break
    except OSError:
        pass
    gv = subprocess.run([FC, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    return {
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "memory_GiB": round(mem_kb / 1048576, 1),
        "os": platform.platform(),
        "python": platform.python_version(),
        "fortran_compiler": gv,
        "compile_flags": "-O1 -std=legacy",
        "abaqus": "not installed on this machine",
        "repo_commit": subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                                      capture_output=True, text=True).stdout.strip(),
    }


# ------------------------------------------------------------------ OTI runtime
def oti_module_scaling():
    from umat_oti.oti.module_generator import generate_otilib_module
    rows = []
    cases = [(n, 1) for n in (4, 6, 10, 20, 30, 35)] + [(6, k) for k in (2, 3, 4)] + [(12, 2), (36, 1)]
    for n, k in cases:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)

            def gen():
                generate_otilib_module(output_dir=d, ntens=n, order=k)

            try:
                t = timed(gen, REPS_SLOW if n * k > 60 else REPS_FAST)
            except Exception as exc:                      # refused by the generator
                rows.append({"directions": n, "order": k,
                             "stored_coefficients": comb(n + k, k),
                             "refused": f"{type(exc).__name__}: {exc}"})
                print(f"  N={n:4d} K={k}  REFUSED: {exc}")
                continue
            src = sorted(d.glob(f"otim{n}n{k}.f90"))
            path = src[0] if src else None
            lines = len(path.read_text().splitlines()) if path else 0
            kib = path.stat().st_size / 1024 if path else 0.0
            comp = None
            if FC and path is not None and lines < 60000:
                objdir = d / "obj"
                objdir.mkdir(exist_ok=True)

                def build():
                    subprocess.run(
                        [FC, "-c", "-O1", "-std=legacy", "-ffree-line-length-none",
                         str(REPO / "src/umat_oti/oti/support/master_parameters.f90"),
                         "-J", str(objdir), "-o", str(objdir / "mp.o")],
                        check=True, capture_output=True)
                    subprocess.run(
                        [FC, "-c", "-O1", "-std=legacy", "-ffree-line-length-none",
                         str(path), "-I", str(objdir), "-J", str(objdir),
                         "-o", str(objdir / "oti.o")],
                        check=True, capture_output=True)

                try:
                    comp = timed(build, 1)
                except subprocess.CalledProcessError as exc:
                    comp = {"error": exc.stderr.decode()[-300:]}
            rows.append({
                "directions": n, "order": k,
                "stored_coefficients": comb(n + k, k),
                "module_lines": lines, "module_KiB": round(kib, 1),
                "generate": t, "compile": comp,
            })
            print(f"  N={n:4d} K={k}  coeffs={comb(n+k,k):7d}  lines={lines:7d}  "
                  f"gen={t['median_s']:7.2f}s  "
                  f"compile={comp['median_s']:7.2f}s" if comp and "median_s" in comp
                  else f"  N={n:4d} K={k}  coeffs={comb(n+k,k):7d}  lines={lines:7d}  "
                       f"gen={t['median_s']:7.2f}s  compile=n/a")
    return rows


# --------------------------------------------------------------- transformation
def transformation_and_compilation():
    from umat_oti.cli_json import main as cli_main
    contract = REPO / "examples/j2_actual_higher_order.json"
    out = {}
    for label, order_note in [("j2_order4", "as shipped, order 4")]:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run"

            def run():
                if d.exists():
                    shutil.rmtree(d)
                cli_main(["--config", str(contract), "--out", str(d)])

            cwd = os.getcwd()
            os.chdir(REPO)
            try:
                t = timed(run, REPS_SLOW)
            finally:
                os.chdir(cwd)
            emitted = sorted(p.name for p in d.iterdir())
            hint = d / "compile_hint.sh"
            ct = None
            if FC and hint.exists():
                def build():
                    subprocess.run(["bash", str(hint)], cwd=d, check=True,
                                   capture_output=True)
                try:
                    ct = timed(build, 1)
                except subprocess.CalledProcessError as exc:
                    ct = {"error": exc.stderr.decode()[-400:]}
            out[label] = {"note": order_note, "transform": t, "compile": ct,
                          "emitted_files": emitted}
            print(f"  transform {label}: median {t['median_s']:.2f} s "
                  f"({t['min_s']:.2f}-{t['max_s']:.2f}); "
                  f"compile {ct['median_s']:.2f} s" if ct and "median_s" in ct
                  else f"  transform {label}: median {t['median_s']:.2f} s; compile n/a")
    return out


# ----------------------------------------------- per-evaluation material-point cost
DRIVER = r"""
      PROGRAM MPDRV
      IMPLICIT NONE
      INTEGER, PARAMETER :: NT=6, NS=1, NP=4
      DOUBLE PRECISION STRESS(NT),STATEV(NS),DDSDDE(NT,NT),DDSDDT(NT)
      DOUBLE PRECISION DRPLDE(NT),STRAN(NT),DSTRAN(NT),TIME(2),PREDEF(1)
      DOUBLE PRECISION DPRED(1),PROPS(NP),COORDS(3),DROT(3,3)
      DOUBLE PRECISION DFGRD0(3,3),DFGRD1(3,3)
      DOUBLE PRECISION SSE,SPD,SCD,RPL,DRPLDT,DTIME,TEMP,DTEMP,PNEWDT
      DOUBLE PRECISION CELENT, ACC
      CHARACTER*80 CMNAME
      INTEGER I,J,K,NREP,NINC
      NREP = %REP%
      NINC = 20
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
      DO K=1,NREP
        DO I=1,NT
          STRESS(I)=0.0D0
          STRAN(I)=0.0D0
          DSTRAN(I)=0.0D0
        END DO
        STATEV(1)=0.0D0
        DSTRAN(1)=1.0D-4
        DO J=1,NINC
          CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,
     1     DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2     CMNAME,3,3,NT,NS,PROPS,NP,COORDS,DROT,PNEWDT,CELENT,
     3     DFGRD0,DFGRD1,1,1,1,1,1,J)
          DO I=1,NT
            STRAN(I)=STRAN(I)+DSTRAN(I)
          END DO
        END DO
        ACC=ACC+STRESS(1)+DDSDDE(1,1)
      END DO
      WRITE(*,*) ACC
      END
"""


def evaluation_cost():
    """Cost of one material-point increment: original real build vs the
    transformed OTI build, both driven over the same 20-increment path."""
    from umat_oti.cli_json import main as cli_main
    if not FC:
        return {"error": "no Fortran compiler"}
    contract = REPO / "examples/j2_actual_higher_order.json"
    results = {}
    work = Path(tempfile.mkdtemp(prefix="umat_oti_bench_"))
    try:
        gen = work / "gen"
        cwd = os.getcwd()
        os.chdir(REPO)
        try:
            cli_main(["--config", str(contract), "--out", str(gen)])
        finally:
            os.chdir(cwd)

        NREP = 20000
        drv = DRIVER.replace("%REP%", str(NREP))
        # ---- original
        odir = work / "orig"
        odir.mkdir()
        (odir / "drv.f").write_text(drv)
        (odir / "ABA_PARAM.INC").write_text(
            "      IMPLICIT REAL*8(A-H,O-Z)\n      PARAMETER (NPRECD=2)\n")
        subprocess.run([FC, "-O1", "-std=legacy", "-ffixed-line-length-none",
                        "-I", str(odir),
                        str(REPO / "UMATs/UMATs/generic_ps/j2_props.f"),
                        str(odir / "drv.f"), "-o", str(odir / "a.out")],
                       check=True, capture_output=True, cwd=odir)
        results["original_real"] = timed(
            lambda: subprocess.run([str(odir / "a.out")], check=True,
                                   capture_output=True, cwd=odir), REPS_SLOW)

        # ---- transformed (order 4 as shipped, and order 1 rebuilt)
        for label, order in (("transformed_order4", 4), ("transformed_order1", 1)):
            tdir = work / label
            tdir.mkdir()
            if order == 4:
                src = gen
            else:
                cfg = json.loads(contract.read_text())
                cfg["derivatives"][0]["order"] = 1
                cfg["derivatives"][0]["target"] = "DDSDDE"
                cfg["validation"]["order"] = 1
                p = work / "j2_order1.json"
                # keep the relative source path resolvable
                cfg["source"] = str(REPO / "UMATs/UMATs/generic_ps/j2_props.f")
                p.write_text(json.dumps(cfg))
                src = work / "gen1"
                os.chdir(REPO)
                try:
                    cli_main(["--config", str(p), "--out", str(src)])
                finally:
                    os.chdir(cwd)
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy(f, tdir / f.name)
            (tdir / "drv.f").write_text(drv)
            (tdir / "ABA_PARAM.INC").write_text(
                "      IMPLICIT REAL*8(A-H,O-Z)\n      PARAMETER (NPRECD=2)\n")
            units = [u for u in (tdir / "compile_order.txt").read_text().split()]
            cmd = [FC, "-O1", "-std=legacy", "-ffree-line-length-none",
                   "-ffixed-line-length-none", "-I", str(tdir), "-J", str(tdir)]
            cmd += [str(tdir / u) for u in units] + [str(tdir / "drv.f"),
                                                     "-o", str(tdir / "a.out")]
            r = subprocess.run(cmd, capture_output=True, cwd=tdir)
            if r.returncode != 0:
                results[label] = {"error": r.stderr.decode()[-600:]}
                continue
            env = dict(os.environ)
            results[label] = timed(
                lambda: subprocess.run([str(tdir / "a.out")], check=True,
                                       capture_output=True, cwd=tdir, env=env),
                REPS_SLOW)
        results["_note"] = (f"{NREP} repetitions of a 20-increment uniaxial path "
                            f"= {NREP * 20} UMAT calls per timed run; "
                            "the reported time is for the whole executable, "
                            "including process start-up (< 5 ms).")
        results["_umat_calls_per_run"] = NREP * 20
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return results


if __name__ == "__main__":
    print("environment")
    env = environment()
    for k, v in env.items():
        print(f"  {k}: {v}")
    print("\nOTI runtime module generation and compilation")
    scaling = oti_module_scaling()
    print("\ntransformation and compilation of the J2 example")
    tc = transformation_and_compilation()
    print("\nper-evaluation material-point cost")
    ev = evaluation_cost()
    print(json.dumps(ev, indent=1)[:2000])
    payload = {"environment": env, "oti_module_scaling": scaling,
               "transformation": tc, "evaluation": ev}
    (OUT / "bench.json").write_text(json.dumps(payload, indent=1))
    print("\nwrote bench/bench.json")
