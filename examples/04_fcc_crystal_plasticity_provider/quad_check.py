#!/usr/bin/env python
"""Example 4: settle one tiny entry with a quad-precision build of the ORIGINAL.

The verifier judges every derivative entry against centred finite differences
of the original UMAT in double precision. For an entry many orders of magnitude
below the rest of its column, round-off in the double-precision stress limits
how well those differences can resolve it. This script compiles the ORIGINAL
FCC UMAT twice, once in double precision and once with every REAL*8 promoted
to 16-byte reals (``gfortran -freal-8-real-16``), and prints the centred
difference of one stress component with respect to one parameter over a step
ladder, for the first increments of the tension-with-shear path.

Run from the repository root (needs gfortran only):

    python examples/04_fcc_crystal_plasticity_provider/quad_check.py

The defaults reproduce the entry discussed in the README: dS22/dC11 at the
shipped constants (g0 = 16, gsat = 40, h0 = 300). ``--props``, ``--slot``,
``--component`` and ``--increments`` choose others.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
UMAT = REPO / "parameter_sensitivity" / "models" / "m6_fcc" / "umat.for"
SHIPPED = [168000.0, 121000.0, 75000.0, 16.0, 40.0, 300.0, 2.0, 1.4, 0.001, 0.05]
INCREMENT = [1.0e-4, 0.0, 0.0, 1.0e-4, 0.0, 0.0]
ABA_PARAM = "      IMPLICIT REAL*8(A-H,O-Z)\n      PARAMETER (NPRECD=2)\n"
LADDERS = {
    "double": [1e-2, 3.1622776601683794e-3, 1e-3, 3.1622776601683794e-4, 1e-4],
    "quad": [1e-2, 1e-4, 1e-6, 1e-8, 1e-10],
}

DRIVER = """\
! Centred differences of the ORIGINAL UMAT in the precision of kind WP.
! stdin: 10 props, parameter slot, number of steps, relative steps,
! number of increments, then one DSTRAN row per increment.
! stdout: step, increment, then the 6 stress derivatives.
PROGRAM qdriver
  IMPLICIT NONE
  INTEGER, PARAMETER :: WP = KIND(1.0D0)   ! 16 bytes under -freal-8-real-16
  INTEGER, PARAMETER :: NTENS=6, NSTATV=12, NPROPS=10
  REAL(WP) :: PROPS(NPROPS), P(NPROPS), H, REL(20), PATH(6,200)
  REAL(WP) :: SP(6,200), SM(6,200)
  INTEGER :: SLOT, NSTEP, NINC, I, K
  READ(*,*) PROPS
  READ(*,*) SLOT
  READ(*,*) NSTEP
  READ(*,*) (REL(I), I=1,NSTEP)
  READ(*,*) NINC
  DO K=1,NINC
    READ(*,*) PATH(:,K)
  END DO
  DO I=1,NSTEP
    H = REL(I)*ABS(PROPS(SLOT))
    P = PROPS; P(SLOT) = P(SLOT) + H
    CALL RUN(P, SP)
    P = PROPS; P(SLOT) = P(SLOT) - H
    CALL RUN(P, SM)
    DO K=1,NINC
      WRITE(*,'(ES12.3,1X,I4,6(1X,ES44.34E3))') REL(I), K, (SP(:,K)-SM(:,K))/(2*H)
    END DO
  END DO
CONTAINS
  SUBROUTINE RUN(PR, S)
    REAL(WP), INTENT(IN) :: PR(NPROPS)
    REAL(WP), INTENT(OUT) :: S(6,200)
    REAL(WP) :: STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),SSE,SPD,SCD,RPL
    REAL(WP) :: DDSDDT(NTENS),DRPLDE(NTENS),DRPLDT,STRAN(NTENS),DSTRAN(NTENS)
    REAL(WP) :: TIME(2),DTIME,TEMP,DTEMP,PREDEF(1),DPRED(1),COORDS(3)
    REAL(WP) :: DROT(3,3),PNEWDT,CELENT,DFGRD0(3,3),DFGRD1(3,3),PC(NPROPS)
    INTEGER :: NDI,NSHR,NOEL,NPT,LAYER,KSPT,KSTEP,KINC,J
    CHARACTER(80) :: CMNAME
    PC = PR
    STRESS=0;STATEV=0;DDSDDE=0;STRAN=0;DSTRAN=0;SSE=0;SPD=0;SCD=0;RPL=0
    DDSDDT=0;DRPLDE=0;DRPLDT=0;TIME=0;DTIME=1;TEMP=293.15D0;DTEMP=0;PREDEF=0;DPRED=0
    COORDS=0;DROT=0;DFGRD0=0;DFGRD1=0
    DO J=1,3
      DROT(J,J)=1;DFGRD0(J,J)=1;DFGRD1(J,J)=1
    END DO
    PNEWDT=1;CELENT=1;CMNAME='Q';NDI=3;NSHR=3;NOEL=1;NPT=1;LAYER=1;KSPT=1;KSTEP=1
    DO KINC=1,NINC
      DSTRAN = PATH(:,KINC)
      CALL UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,DRPLDT, &
        STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV, &
        PC,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      S(:,KINC) = STRESS
      STRAN=STRAN+DSTRAN;TIME=TIME+DTIME
    END DO
  END SUBROUTINE RUN
END PROGRAM qdriver
"""


def build(work: Path, name: str, flags: list[str]) -> Path:
    exe = work / name
    for source, obj in ((UMAT, f"umat_{name}.o"), (work / "qdriver.f90", f"driver_{name}.o")):
        subprocess.run(["gfortran", "-O0", *flags, "-I", str(work), "-c", str(source), "-o", obj],
                       cwd=work, check=True)
    subprocess.run(["gfortran", *flags, f"umat_{name}.o", f"driver_{name}.o", "-o", name],
                   cwd=work, check=True)
    return exe


def differences(exe: Path, props, slot: int, steps, increments: int):
    text = " ".join(map(repr, props)) + f"\n{slot}\n{len(steps)}\n"
    text += " ".join(map(repr, steps)) + f"\n{increments}\n"
    text += "\n".join(" ".join(map(repr, INCREMENT)) for _ in range(increments)) + "\n"
    out = subprocess.run([str(exe)], input=text, capture_output=True, text=True, check=True).stdout
    return [line.split() for line in out.splitlines()]


def main(argv=None) -> int:
    sys.dont_write_bytecode = True  # leave no __pycache__ in the examples folder
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", type=Path,
                        default=REPO / "umat_oti_workspace" / "examples" / "04_fcc" / "quad_check")
    parser.add_argument("--props", type=float, nargs=10, default=SHIPPED)
    parser.add_argument("--slot", type=int, default=1, help="PROPS index of the parameter (1 = C11)")
    parser.add_argument("--component", type=int, default=2, help="stress component (2 = S22)")
    parser.add_argument("--increments", type=int, default=3)
    args = parser.parse_args(argv)
    if shutil.which("gfortran") is None:
        print("blocked_by_external_dependency: gfortran is not on PATH", file=sys.stderr)
        return 2
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    (work / "qdriver.f90").write_text(DRIVER)
    for include in ("aba_param.inc", "ABA_PARAM.INC"):
        (work / include).write_text(ABA_PARAM)
    builds = {"double": build(work, "double", []), "quad": build(work, "quad", ["-freal-8-real-16"])}
    print(f"d STRESS({args.component}) / d PROPS({args.slot}), centred differences of the ORIGINAL")
    for label, exe in builds.items():
        print(f"\n{label} precision")
        print(f"  {'relative step':>14}  {'increment':>9}  derivative")
        for row in differences(exe, args.props, args.slot, LADDERS[label], args.increments):
            print(f"  {float(row[0]):>14.3e}  {row[1]:>9}  {float(row[1 + args.component]):+.10e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
