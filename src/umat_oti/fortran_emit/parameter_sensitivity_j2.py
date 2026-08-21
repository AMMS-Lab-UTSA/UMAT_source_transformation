"""Generate a PROPS-seeded OTI Fortran material-point driver for the
SoftwareX J2 parameter-sensitivity case.

This module is the actual PROPS-seeded OTI Fortran generation demanded by
Priority 1 of the SoftwareX continuation prompt. It produces a self-contained
Fortran build tree that:

* uses the repository's on-demand OTI algebra module ``otim4n1``,
* declares an OTI-lifted J2 UMAT (``j2_umat_oti``) whose ``PROPS`` argument
  is typed as ``ONUMM4N1(4)``, so seeding PROPS with the four canonical OTI
  directions makes ``d STRESS / d PROPS`` and ``d STATEV / d PROPS`` come
  out via ``GETIM`` extraction,
* declares a Fortran driver program (``j2_driver``) that replays the whole
  loading path, preserves the OTI imaginary coefficients of ``STATEV``
  across every increment, extracts ``DSIGMA_DP`` / ``DSTATEV_DP`` per
  increment, and writes them to CSV,
* ships a ``Makefile`` so a normal ``gfortran`` compile + run is enough to
  produce OTI-generated ``DSIGMA_DP`` / ``DSTATEV_DP`` data.

The Python API exposes three steps:

    generate_j2_oti_build(output_dir)   -> BuildLayout
    compile_j2_oti_build(layout)        -> Path (executable)
    run_j2_oti_driver(executable, ...)  -> RunResult

Nothing in this module fabricates a derivative. The Fortran driver's output
is the OTI result; the Python centered-FD reference lives elsewhere. The
comparison + verification lives in
:func:`compare_oti_vs_fd`.

The design intentionally covers **one** derivative request kind
(``parameter_sensitivity`` for J2). The higher-order-strain case lives in
its own module. This satisfies the SoftwareX rule that "The public program
may internally generate separate optimized builds for strain derivatives,
parameter sensitivities, and local Jacobians ..."; both drivers must
remain compatible with the same unified ``DerivativeRequest`` API.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from umat_oti.oti.module_generator import generate_otilib_module


PARAMETER_NAMES = ("E", "NU", "SIGY0", "H")
STATE_NAMES = ("EQPLAS",)
NTENS_J2 = 6


@dataclass
class BuildLayout:
    """Paths inside a generated OTI build directory."""

    root: Path
    master_parameters: Path
    real_utils: Path
    otim_module: Path
    j2_umat_oti: Path
    j2_driver: Path
    makefile: Path


@dataclass
class RunResult:
    executable: Path
    stdout: str
    stderr: str
    returncode: int
    primal_csv: Path
    dsigma_csv: Path
    dstatev_csv: Path


# ---------------------------------------------------------------------------
# 1. Emit the Fortran build tree
# ---------------------------------------------------------------------------

def generate_j2_oti_build(output_dir: Path | str) -> BuildLayout:
    """Emit the full build tree for the PROPS-seeded OTI J2 driver."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    module_result = generate_otilib_module(
        output_dir=output_dir, ntens=len(PARAMETER_NAMES), order=1
    )

    j2_umat_oti = output_dir / "j2_umat_oti.f90"
    j2_umat_oti.write_text(_j2_umat_oti_source(), encoding="utf-8")

    j2_driver = output_dir / "j2_driver.f90"
    j2_driver.write_text(_j2_driver_source(), encoding="utf-8")

    makefile = output_dir / "Makefile"
    makefile.write_text(_makefile_source(module_result.module_name), encoding="utf-8")

    return BuildLayout(
        root=output_dir,
        master_parameters=module_result.master_parameters_path,
        real_utils=module_result.real_utils_path,
        otim_module=module_result.module_path,
        j2_umat_oti=j2_umat_oti,
        j2_driver=j2_driver,
        makefile=makefile,
    )


def compile_j2_oti_build(layout: BuildLayout, *, gfortran: str = "gfortran") -> Path:
    """Invoke ``gfortran`` (or a caller-supplied compiler) to build the driver."""
    if shutil.which(gfortran) is None:
        raise RuntimeError(
            f"Fortran compiler {gfortran!r} not on PATH. Install gfortran "
            "(module load gcc on ARC) and rerun."
        )
    proc = subprocess.run(
        ["make", f"FC={gfortran}"],
        cwd=str(layout.root),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "gfortran build failed.\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    exe = layout.root / "j2_driver"
    if not exe.is_file():
        raise RuntimeError(f"driver executable not produced at {exe}")
    return exe


def run_j2_oti_driver(
    executable: Path,
    *,
    out_dir: Optional[Path] = None,
) -> RunResult:
    """Run the compiled OTI J2 driver, returning the emitted CSV paths."""
    out_dir = Path(out_dir) if out_dir is not None else executable.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(executable)],
        cwd=str(out_dir),
        check=False,
        capture_output=True,
        text=True,
    )
    return RunResult(
        executable=executable,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        primal_csv=out_dir / "primal_stress_state_OTI.csv",
        dsigma_csv=out_dir / "DSIGMA_DP_OTI.csv",
        dstatev_csv=out_dir / "DSTATEV_DP_OTI.csv",
    )


# ---------------------------------------------------------------------------
# 2. OTI vs. FD comparison
# ---------------------------------------------------------------------------

def compare_oti_vs_fd(
    *,
    oti_dsigma_csv: Path,
    oti_dstatev_csv: Path,
    fd_dsigma_csv: Path,
    fd_dstatev_csv: Path,
    output_csv: Path,
) -> dict:
    """Produce a per-cell comparison CSV and a summary dict.

    Each row of the produced CSV contains ``increment``, ``array``,
    ``row``, ``column``, ``parameter``, ``oti``, ``fd``, ``abs_diff``,
    ``rel_diff``.
    """
    oti_sigma = _read_sensitivity_csv(oti_dsigma_csv)
    fd_sigma = _read_sensitivity_csv(fd_dsigma_csv)
    oti_state = _read_sensitivity_csv(oti_dstatev_csv)
    fd_state = _read_sensitivity_csv(fd_dstatev_csv)

    header_oti = oti_sigma["header"]
    header_fd = fd_sigma["header"]
    if header_oti != header_fd:
        raise RuntimeError(
            f"OTI ({header_oti}) and FD ({header_fd}) DSIGMA headers differ"
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    max_abs = 0.0
    max_rel = 0.0
    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["increment", "array", "row_or_state", "parameter", "oti", "fd", "abs_diff", "rel_diff"]
        )
        for array_label, oti_rows, fd_rows in (
            ("DSIGMA_DP", oti_sigma["rows"], fd_sigma["rows"]),
            ("DSTATEV_DP", oti_state["rows"], fd_state["rows"]),
        ):
            for oti_row, fd_row in zip(oti_rows, fd_rows):
                inc = oti_row[0]
                row_label = oti_row[1]
                # Skip the method column (index 2), value columns start at 3.
                for j, param in enumerate(PARAMETER_NAMES, start=3):
                    oti_val = float(oti_row[j])
                    fd_val = float(fd_row[j])
                    ad = abs(oti_val - fd_val)
                    scale = max(abs(oti_val), abs(fd_val), 1.0)
                    rd = ad / scale
                    if ad > max_abs:
                        max_abs = ad
                    if rd > max_rel:
                        max_rel = rd
                    writer.writerow(
                        [inc, array_label, row_label, param,
                         f"{oti_val:.10e}", f"{fd_val:.10e}",
                         f"{ad:.3e}", f"{rd:.3e}"]
                    )
    return {"max_abs_diff": max_abs, "max_rel_diff": max_rel}


def _read_sensitivity_csv(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = [row for row in reader]
    return {"header": header, "rows": rows}


# ---------------------------------------------------------------------------
# 3. Fortran sources (as strings)
# ---------------------------------------------------------------------------

def _j2_umat_oti_source() -> str:
    """OTI-lifted J2 small-strain radial-return UMAT (NTENS=6).

    All storage-typed arguments are ``TYPE(ONUMM4N1)``: PROPS carries the
    seeded OTI directions, STRESS and STATEV carry the propagated OTI
    coefficients. No physics is changed relative to the reference J2
    algorithm; only the types are lifted.
    """
    return r"""!===============================================================
! PROPS-seeded OTI J2 UMAT (small-strain, radial return, isotropic hardening).
!
! Interfaces:
!   PROPS(4) is TYPE(ONUMM4N1) so callers may seed E, NU, SIGY0, H with
!   distinct OTI directions to obtain DSIGMA_DP and DSTATEV_DP via GETIM.
!   STRESS(6), STATEV(1), DSTRAN(6) are TYPE(ONUMM4N1) so the OTI state
!   carries forward correctly between increments.
!
! Ordering (Voigt engineering-shear on strain columns):
!   1: 11, 2: 22, 3: 33, 4: 12 (gamma), 5: 13 (gamma), 6: 23 (gamma).
!===============================================================
MODULE j2_umat_oti_mod
  USE master_parameters, ONLY: DP
  USE otim4n1
  IMPLICIT NONE
  PRIVATE
  PUBLIC :: j2_umat_oti

CONTAINS

  SUBROUTINE j2_umat_oti(STRESS, STATEV, PROPS, DSTRAN)
    TYPE(ONUMM4N1), INTENT(INOUT) :: STRESS(6)
    TYPE(ONUMM4N1), INTENT(INOUT) :: STATEV(1)
    TYPE(ONUMM4N1), INTENT(IN)    :: PROPS(4)
    TYPE(ONUMM4N1), INTENT(IN)    :: DSTRAN(6)

    TYPE(ONUMM4N1) :: E_, NU_, SIGY0_, H_
    TYPE(ONUMM4N1) :: LAM, MU, TWOMU
    TYPE(ONUMM4N1) :: STRESS_TRIAL(6)
    TYPE(ONUMM4N1) :: DEV_TRIAL(6)
    TYPE(ONUMM4N1) :: Q_TRIAL, EQPLAS_N, SIGMA_Y, PHI
    TYPE(ONUMM4N1) :: DGAMMA, SCALE_, P_TRIAL
    INTEGER :: I

    E_    = PROPS(1)
    NU_   = PROPS(2)
    SIGY0_= PROPS(3)
    H_    = PROPS(4)

    ! Lame parameters (isotropic).
    LAM   = E_ * NU_ / ((1.0_DP + NU_) * (1.0_DP - 2.0_DP * NU_))
    MU    = E_ / (2.0_DP * (1.0_DP + NU_))
    TWOMU = 2.0_DP * MU

    ! Elastic trial stress (Voigt engineering-shear; DSTRAN uses gamma on 4..6).
    STRESS_TRIAL(1) = STRESS(1) + (LAM + TWOMU) * DSTRAN(1) + LAM * DSTRAN(2) + LAM * DSTRAN(3)
    STRESS_TRIAL(2) = STRESS(2) + LAM * DSTRAN(1) + (LAM + TWOMU) * DSTRAN(2) + LAM * DSTRAN(3)
    STRESS_TRIAL(3) = STRESS(3) + LAM * DSTRAN(1) + LAM * DSTRAN(2) + (LAM + TWOMU) * DSTRAN(3)
    STRESS_TRIAL(4) = STRESS(4) + MU * DSTRAN(4)
    STRESS_TRIAL(5) = STRESS(5) + MU * DSTRAN(5)
    STRESS_TRIAL(6) = STRESS(6) + MU * DSTRAN(6)

    ! Deviator.
    P_TRIAL = (STRESS_TRIAL(1) + STRESS_TRIAL(2) + STRESS_TRIAL(3)) / 3.0_DP
    DEV_TRIAL(1) = STRESS_TRIAL(1) - P_TRIAL
    DEV_TRIAL(2) = STRESS_TRIAL(2) - P_TRIAL
    DEV_TRIAL(3) = STRESS_TRIAL(3) - P_TRIAL
    DEV_TRIAL(4) = STRESS_TRIAL(4)
    DEV_TRIAL(5) = STRESS_TRIAL(5)
    DEV_TRIAL(6) = STRESS_TRIAL(6)

    ! q_trial = sqrt(3/2 s_ii s_ii + 3 s_ij s_ij) with engineering shear.
    Q_TRIAL = SQRT(1.5_DP * (DEV_TRIAL(1)*DEV_TRIAL(1) + DEV_TRIAL(2)*DEV_TRIAL(2) + DEV_TRIAL(3)*DEV_TRIAL(3)) &
                   + 3.0_DP * (DEV_TRIAL(4)*DEV_TRIAL(4) + DEV_TRIAL(5)*DEV_TRIAL(5) + DEV_TRIAL(6)*DEV_TRIAL(6)))

    EQPLAS_N = STATEV(1)
    SIGMA_Y  = SIGY0_ + H_ * EQPLAS_N
    PHI      = Q_TRIAL - SIGMA_Y

    IF (PHI%R <= 0.0_DP) THEN
       ! Elastic increment.
       DO I = 1, 6
          STRESS(I) = STRESS_TRIAL(I)
       END DO
    ELSE
       ! Radial return (closed form for linear isotropic hardening).
       DGAMMA = PHI / (3.0_DP * MU + H_)
       SCALE_ = 3.0_DP * MU * DGAMMA / Q_TRIAL
       STRESS(1) = DEV_TRIAL(1) * (1.0_DP - SCALE_) + P_TRIAL
       STRESS(2) = DEV_TRIAL(2) * (1.0_DP - SCALE_) + P_TRIAL
       STRESS(3) = DEV_TRIAL(3) * (1.0_DP - SCALE_) + P_TRIAL
       STRESS(4) = DEV_TRIAL(4) * (1.0_DP - SCALE_)
       STRESS(5) = DEV_TRIAL(5) * (1.0_DP - SCALE_)
       STRESS(6) = DEV_TRIAL(6) * (1.0_DP - SCALE_)
       STATEV(1) = EQPLAS_N + DGAMMA
    END IF
  END SUBROUTINE j2_umat_oti

END MODULE j2_umat_oti_mod
"""


def _j2_driver_source() -> str:
    """Driver program: seed PROPS, replay SoftwareX loading path, dump CSVs."""
    return r"""!===============================================================
! Driver: PROPS-seeded OTI J2 material-point simulation.
!
! Seeds PROPS = (E, NU, SIGY0, H) with the four OTI directions
!   PROPS(1) = 200000  + E1
!   PROPS(2) = 0.3     + E2
!   PROPS(3) = 250     + E3
!   PROPS(4) = 2000    + E4
! and replays the SoftwareX uniaxial-tension loading path (20 increments
! of dstran11 = 1.5e-4). At every increment we call j2_umat_oti and
! extract DSIGMA_DP(:, k) = GETIM(STRESS(:), k) and
! DSTATEV_DP(:, k) = GETIM(STATEV(:), k) via the module's GETIM overload.
!
! The imaginary coefficients of STRESS and STATEV carry the parameter
! sensitivities and are propagated between increments without being
! flushed back to real values. This is the "OTI-state propagation"
! guarantee required by Priority 2.
!===============================================================
PROGRAM j2_driver
  USE master_parameters, ONLY: DP
  USE otim4n1
  USE j2_umat_oti_mod, ONLY: j2_umat_oti
  IMPLICIT NONE

  INTEGER, PARAMETER :: N_INC = 20
  REAL(DP), PARAMETER :: DSTRAN11 = 1.5E-4_DP
  REAL(DP), PARAMETER :: E_VAL = 200000.0_DP
  REAL(DP), PARAMETER :: NU_VAL = 0.3_DP
  REAL(DP), PARAMETER :: SIGY0_VAL = 250.0_DP
  REAL(DP), PARAMETER :: H_VAL = 2000.0_DP

  TYPE(ONUMM4N1) :: STRESS(6), STATEV(1), PROPS(4), DSTRAN(6)
  REAL(DP) :: dsigma(6, 4), dstatev(1, 4)
  INTEGER :: I, K, INC
  INTEGER :: U_PRIMAL, U_SIGMA, U_STATE
  LOGICAL :: yielded

  ! Seed PROPS with the four OTI directions on top of the operating point.
  PROPS(1) = E_VAL     + E1
  PROPS(2) = NU_VAL    + E2
  PROPS(3) = SIGY0_VAL + E3
  PROPS(4) = H_VAL     + E4

  DO I = 1, 6
     STRESS(I) = 0.0_DP
     DSTRAN(I) = 0.0_DP
  END DO
  STATEV(1) = 0.0_DP

  OPEN(NEWUNIT=U_PRIMAL, FILE="primal_stress_state_OTI.csv", STATUS="REPLACE", ACTION="WRITE")
  WRITE(U_PRIMAL, '(A)') "increment,yielded,method,stress_1,stress_2,stress_3,stress_4,stress_5,stress_6,EQPLAS"

  OPEN(NEWUNIT=U_SIGMA, FILE="DSIGMA_DP_OTI.csv", STATUS="REPLACE", ACTION="WRITE")
  WRITE(U_SIGMA, '(A)') "increment,stress_component,method,E,NU,SIGY0,H"

  OPEN(NEWUNIT=U_STATE, FILE="DSTATEV_DP_OTI.csv", STATUS="REPLACE", ACTION="WRITE")
  WRITE(U_STATE, '(A)') "increment,state_variable,method,E,NU,SIGY0,H"

  DO INC = 1, N_INC
     ! Purely axial dstran11 step; DSTRAN is a plain real bump so no OTI
     ! direction is added to it. The only OTI direction lives in PROPS.
     DSTRAN(1) = DSTRAN11
     DO I = 2, 6
        DSTRAN(I) = 0.0_DP
     END DO

     CALL j2_umat_oti(STRESS, STATEV, PROPS, DSTRAN)

     yielded = (STATEV(1)%R > 0.0_DP)

     DO I = 1, 6
        DO K = 1, 4
           dsigma(I, K) = GETIM(STRESS(I), K)
        END DO
     END DO
     DO I = 1, 1
        DO K = 1, 4
           dstatev(I, K) = GETIM(STATEV(I), K)
        END DO
     END DO

     WRITE(U_PRIMAL, '(I0,A,A,A,A,6(A,ES23.15),A,ES23.15)') &
         INC, ",", MERGE("yes", "no ", yielded), ",", "oti", &
         (",", STRESS(I)%R, I=1,6), ",", STATEV(1)%R

     DO I = 1, 6
        WRITE(U_SIGMA, '(I0,A,I0,A,A,4(A,ES23.15))') &
            INC, ",", I, ",", "oti", &
            (",", dsigma(I, K), K=1, 4)
     END DO
     WRITE(U_STATE, '(I0,A,A,A,A,4(A,ES23.15))') &
         INC, ",", "EQPLAS", ",", "oti", &
         (",", dstatev(1, K), K=1, 4)
  END DO

  CLOSE(U_PRIMAL)
  CLOSE(U_SIGMA)
  CLOSE(U_STATE)
END PROGRAM j2_driver
"""


def _makefile_source(module_name: str) -> str:
    """Small Makefile: compile support first, then the module, then the driver.

    The compile order matters because ``otim4n1`` USEs ``master_parameters``
    and ``real_utils``, and ``j2_umat_oti_mod`` USEs ``otim4n1``.
    """
    return f"""FC      ?= gfortran
FCFLAGS ?= -O2 -std=f2008 -ffree-line-length-none
LDFLAGS ?=

.PHONY: all clean

all: j2_driver

master_parameters.o: master_parameters.f90
\t$(FC) $(FCFLAGS) -c $<

real_utils.o: real_utils.f90 master_parameters.o
\t$(FC) $(FCFLAGS) -c $<

{module_name}.o: {module_name}.f90 master_parameters.o real_utils.o
\t$(FC) $(FCFLAGS) -c $<

j2_umat_oti.o: j2_umat_oti.f90 {module_name}.o
\t$(FC) $(FCFLAGS) -c $<

j2_driver.o: j2_driver.f90 j2_umat_oti.o {module_name}.o
\t$(FC) $(FCFLAGS) -c $<

j2_driver: master_parameters.o real_utils.o {module_name}.o j2_umat_oti.o j2_driver.o
\t$(FC) $(FCFLAGS) $^ -o $@ $(LDFLAGS)

clean:
\trm -f *.o *.mod j2_driver *.csv
"""


__all__ = [
    "BuildLayout",
    "PARAMETER_NAMES",
    "RunResult",
    "compare_oti_vs_fd",
    "compile_j2_oti_build",
    "generate_j2_oti_build",
    "run_j2_oti_driver",
]
