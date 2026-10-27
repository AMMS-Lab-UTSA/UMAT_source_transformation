"""Generate the paired Abaqus decks, user-subroutine files and job directories (Ada, 2026-10-27).

Usage (from the workspace root):
    refreeze/venv/2ae2ee0/Scripts/python.exe evidence/2ae2ee0/abaqus_parity/scripts/make_inputs.py

Writes, under evidence/2ae2ee0/abaqus_parity/:
  decks/<model>_<case>.inp           one deck per model and loading case (identical for both builds)
  build/<model>_<build>/user.for     the routine with UMAT renamed UMAT_INNER, plus the recording wrapper
                                     (compiled and linked by scripts/build_usublib.py)
  jobs/<model>_<case>_<build>/       job directory: deck copy, abaqus_v6.env, run.bat

Geometry: one C3D8 unit cube, NLGEOM=NO (small strain). Nodes 1..8 at
(0,0,0) (1,0,0) (1,1,0) (0,1,0) (0,0,1) (1,0,1) (1,1,1) (0,1,1).

Cases "ext", "shear" and "mixed" prescribe all 24 nodal DOFs in every step from one
homogeneous small-strain tensor eps: u_i(X) = eps_ij X_j. Each DOF receives exactly one
value per step, so there are no conflicting prescriptions and no free DOF. Case "uniax"
is the only one with free DOFs; they are named in its deck and in REPORT.md.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NODES = {1: (0, 0, 0), 2: (1, 0, 0), 3: (1, 1, 0), 4: (0, 1, 0),
         5: (0, 0, 1), 6: (1, 0, 1), 7: (1, 1, 1), 8: (0, 1, 1)}

MODELS = {
    # name: (source, transformed entry, props, names)
    "modelA": ("src/j2_props.f", "transform/j2_props/j2_props_oti.f",
               (200000.0, 0.3, 250.0, 2000.0), "E XNU SIGY0 H"),
    "r1": ("src/umat_j2_voce.f", "transform/umat_j2_voce/umat_j2_voce_oti.f",
           (200000.0, 0.3, 250.0, 1000.0, 150.0, 20.0), "YMOD PNU SIGY0 HLIN QSAT BSAT"),
}

INC = 10  # fixed increments per step (*STATIC, DIRECT)


def strain(e11=0.0, e22=0.0, e33=0.0, g12=0.0, g13=0.0, g23=0.0):
    """Symmetric small-strain tensor from Voigt components with ENGINEERING shear."""
    return ((e11, g12 / 2, g13 / 2), (g12 / 2, e22, g23 / 2), (g13 / 2, g23 / 2, e33))


def iso_ext(e):
    """Isochoric extension: eps = e * diag(1, -1/2, -1/2)."""
    return strain(e, -0.5 * e, -0.5 * e)


# Each case: list of (step label, target total strain at end of step). The prescribed
# displacement ramps linearly from the previous step's value (Abaqus default for *STATIC).
CASES = {
    "ext": [("load", iso_ext(3e-3)), ("unload", iso_ext(0.5e-3)), ("reload", iso_ext(4e-3))],
    "shear": [("load", strain(g12=5e-3)), ("unload", strain(g12=1e-3)), ("reload", strain(g12=7e-3))],
    "mixed": [("extend", iso_ext(2e-3)),
              ("shear_at_fixed_ext", strain(2e-3, -1e-3, -1e-3, g12=4e-3)),
              ("unload_both", strain()),
              ("reload_both", strain(3e-3, -1.5e-3, -1.5e-3, g12=6e-3))],
}
# Uniaxial-stress case: axial displacement of face X1 only (other faces as named below).
UNIAX = [("load", 3e-3), ("unload", 0.5e-3), ("reload", 4e-3)]


def header(model: str, case: str, description: str) -> list[str]:
    props = MODELS[model][2]
    lines = [f"*HEADING", f"Paired primal-parity deck: model={model} case={case}. {description}",
             "*PREPRINT, ECHO=NO, MODEL=NO, HISTORY=NO, CONTACT=NO",
             "*NODE"]
    lines += [f"{n}, {x:.1f}, {y:.1f}, {z:.1f}" for n, (x, y, z) in NODES.items()]
    lines += ["*ELEMENT, TYPE=C3D8, ELSET=CUBE", "1, 1, 2, 3, 4, 5, 6, 7, 8"]
    for n in NODES:
        lines += [f"*NSET, NSET=N{n}", f"{n}"]
    lines += ["*NSET, NSET=ALLN", "1, 2, 3, 4, 5, 6, 7, 8",
              "*SOLID SECTION, ELSET=CUBE, MATERIAL=UMATMAT", "",
              "*MATERIAL, NAME=UMATMAT",
              "*DEPVAR", "1",
              f"*USER MATERIAL, CONSTANTS={len(props)}",
              ", ".join(repr(float(p)) for p in props)]
    return lines


def output_block() -> list[str]:
    return ["*OUTPUT, FIELD, FREQUENCY=1",
            "*NODE OUTPUT", "U, RF",
            "*ELEMENT OUTPUT, ELSET=CUBE", "S, E, SDV",
            "*NODE PRINT, NSET=ALLN, FREQUENCY=1, TOTALS=YES", "U, RF",
            "*EL PRINT, ELSET=CUBE, FREQUENCY=1", "S, SDV",
            "*NODE FILE, NSET=ALLN, FREQUENCY=1", "U, RF",
            "*EL FILE, ELSET=CUBE, FREQUENCY=1", "S, SDV"]


def static_step(label: str) -> list[str]:
    return [f"*STEP, NAME={label}, NLGEOM=NO, INC={INC}",
            "*STATIC, DIRECT", f"{1.0 / INC!r}, 1.0"]


def homogeneous_deck(model: str, case: str) -> str:
    lines = header(model, case,
                   "All 24 nodal DOFs prescribed in every step from u_i = eps_ij X_j (one value per DOF).")
    for label, eps in CASES[case]:
        lines += static_step(label)
        lines += ["*BOUNDARY, OP=MOD"]
        for n, X in NODES.items():
            for i in range(3):
                u = sum(eps[i][j] * X[j] for j in range(3))
                lines.append(f"N{n}, {i + 1}, {i + 1}, {u!r}")
        lines += output_block() + ["*END STEP"]
    return "\n".join(lines) + "\n"


def uniax_deck(model: str) -> str:
    x0 = [1, 4, 5, 8]   # X = 0 face: u1 = 0
    y0 = [1, 2, 5, 6]   # Y = 0 face: u2 = 0
    z0 = [1, 2, 3, 4]   # Z = 0 face: u3 = 0
    x1 = [2, 3, 6, 7]   # X = 1 face: u1 = prescribed axial displacement
    lines = header(model, "uniax",
                   "Symmetry faces X0(u1=0), Y0(u2=0), Z0(u3=0); face X1 u1 prescribed; "
                   "faces Y1 and Z1 traction-free; free DOFs: u2 at nodes 3,4,7,8 and u3 at nodes 5,6,7,8.")
    for label, d in UNIAX:
        lines += static_step(label)
        lines += ["*BOUNDARY, OP=MOD"]
        lines += [f"N{n}, 1, 1, 0.0" for n in x0]
        lines += [f"N{n}, 2, 2, 0.0" for n in y0]
        lines += [f"N{n}, 3, 3, 0.0" for n in z0]
        lines += [f"N{n}, 1, 1, {d!r}" for n in x1]
        lines += output_block() + ["*END STEP"]
    return "\n".join(lines) + "\n"


WRAPPER = """
C ======================================================================
C  Recording wrapper added identically to BOTH builds by
C  evidence/2ae2ee0/abaqus_parity/scripts/make_inputs.py. It calls the
C  routine under test once, unchanged, and appends one full-precision
C  record per call to the file named by env. var. PARITY_CALLS.
C ======================================================================
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      CHARACTER*512 FNAME
      INTEGER LENF, KSTAT, KI, KJ
      LOGICAL LOPEN
      SAVE LOPEN
      DATA LOPEN /.FALSE./
      CALL UMAT_INNER(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      IF (.NOT. LOPEN) THEN
         CALL GET_ENVIRONMENT_VARIABLE('PARITY_CALLS', FNAME, LENF,
     1        KSTAT)
         IF (KSTAT .NE. 0 .OR. LENF .EQ. 0) FNAME = 'parity_calls.txt'
         OPEN(UNIT=117, FILE=TRIM(FNAME), STATUS='REPLACE',
     1        ACTION='WRITE', FORM='FORMATTED', RECL=8192)
         LOPEN = .TRUE.
      END IF
      WRITE(117, '(4I6,1P,64E25.16E3)') KSTEP, KINC, NOEL, NPT,
     1  TIME(1), TIME(2), DTIME, PNEWDT,
     2  (STRAN(KI), KI=1,6), (DSTRAN(KI), KI=1,6),
     3  (STRESS(KI), KI=1,6), STATEV(1),
     4  ((DDSDDE(KI,KJ), KI=1,6), KJ=1,6)
      FLUSH(117)
      RETURN
      END
"""

ENV_SETUP = r"""@echo off
setlocal
set "PATH=C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0;C:\SIMULIA\Commands"
"""


def user_source(model: str, build: str) -> str:
    rel = MODELS[model][0] if build == "orig" else MODELS[model][1]
    text = (ROOT / rel).read_text(encoding="utf-8")
    renamed, n = re.subn(r"(?im)^(\s+SUBROUTINE\s+)UMAT(\s*\()", r"\1UMAT_INNER\2", text)
    if n != 1:
        raise SystemExit(f"{rel}: expected one SUBROUTINE UMAT, found {n}")
    if re.search(r"(?i)END\s+SUBROUTINE\s+UMAT\b", renamed):
        raise SystemExit(f"{rel}: has END SUBROUTINE UMAT; rename it too")
    return renamed.rstrip("\n") + "\n" + WRAPPER


def env_file(model: str, build: str) -> str:
    """Job-local abaqus_v6.env: load the prebuilt standardU.dll of this build (scripts/build_usublib.py)."""
    bdir = (ROOT / "build" / f"{model}_{build}").resolve()
    return ("# Job-local environment (Ada, abaqus_parity). Non-standard linking: see scripts/build_usublib.py.\n"
            f"usub_lib_dir = r'{bdir}'\n")


def run_bat(job: str, model: str, build: str) -> str:
    """Run one job with the build's usub_lib_dir library; no user= (Abaqus cannot compile here)."""
    jdir = (ROOT / "jobs" / job).resolve()
    return "\r\n".join([ENV_SETUP, f'cd /d "{jdir}"',
                        f'set "PARITY_CALLS={jdir}\{job}_calls.txt"',
                        f'call abaqus job={job} input={job}.inp cpus=1 interactive ask_delete=OFF > console.txt 2>&1',
                        "exit /b %ERRORLEVEL%"]) + "\r\n"


def main() -> int:
    (ROOT / "decks").mkdir(exist_ok=True)
    for model in MODELS:
        decks = {c: homogeneous_deck(model, c) for c in CASES}
        decks["uniax"] = uniax_deck(model)
        for case, text in decks.items():
            (ROOT / "decks" / f"{model}_{case}.inp").write_text(text, encoding="utf-8", newline="\n")
        for build in ("orig", "oti"):
            bdir = ROOT / "build" / f"{model}_{build}"
            bdir.mkdir(parents=True, exist_ok=True)
            (bdir / "user.for").write_text(user_source(model, build), encoding="utf-8", newline="\n")
            for case, text in decks.items():
                job = f"{model}_{case}_{build}"
                jdir = ROOT / "jobs" / job
                jdir.mkdir(parents=True, exist_ok=True)
                (jdir / f"{job}.inp").write_text(text, encoding="utf-8", newline="\n")
                (jdir / "abaqus_v6.env").write_text(env_file(model, build), encoding="utf-8", newline="\n")
                (jdir / "run.bat").write_text(run_bat(job, model, build), encoding="utf-8", newline="")
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
