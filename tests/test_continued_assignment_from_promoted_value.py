"""A real variable assigned over several lines from a promoted value (2026-09-18).

The corpus re-transform at fingerprint 638939be1e431cb3 found one source that
had compiled at every earlier generation and no longer did. Keeping the inputs
of predictor-stiffness writes live (so the modulus assignments were no longer
commented out as "feeds only the old tangent") exposed a second defect: an
assignment to a kept-real variable whose right-hand side reads a promoted value
was rewritten from its FIRST PHYSICAL LINE only. The statement

        EMOD = PROPS(2) + (CURE - CRIT) / (1.0 - CRIT) *
     &         (PROPS(1) - PROPS(2))

became ``EMOD = REAL(PROPS(2) + (CURE_OTI - CRIT) / (1.0D0 - CRIT) *)`` with
the continuation line left dangling. The whole logical statement is now
rewritten and its continuation lines retired, as on the stress path.

The source below is written for this test (the corpus source that exposed it is
not redistributable). It is transformed with the corpus recipe, compiled, and
its stress is compared with the ORIGINAL source compiled separately and driven
along the same strain path while the cure degree crosses the threshold.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

from umat_oti.app.engine import _build_contract
from umat_oti.corpus.cli import _write_aba_param_stub
from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.validation.parameter_sensitivity_validation import (
    ABA_PARAM, build_original_driver, driver_source, replay,
)

pytestmark = [pytest.mark.regression, pytest.mark.fortran]

SOURCE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      PARAMETER (ZERO=0.D0, ONE=1.D0, TWO=2.D0, THREE=3.D0)
C     Linear elasticity whose modulus grows with a cure degree carried in
C     STATEV(1): below PROPS(4) the modulus is PROPS(2); above it the modulus
C     interpolates linearly to PROPS(1). The interpolation is one statement
C     written over two lines, which is the construct under test.
      CURE = STATEV(1)
      CRIT = PROPS(4)
      CURE = CURE + PROPS(5)*DTIME*(ONE - CURE)
      IF (CURE .LT. CRIT) THEN
        EMOD = PROPS(2)
      ELSE
        EMOD = PROPS(2) + (CURE - CRIT) / (1.0 - CRIT) *
     &         (PROPS(1) - PROPS(2))
      END IF
      ENU = PROPS(3)
      EBULK3 = EMOD/(ONE-TWO*ENU)
      EG2 = EMOD/(ONE+ENU)
      EG = EG2/TWO
      ELAM = (EBULK3-EG2)/THREE
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1) = ZERO
        END DO
      END DO
      DO K1=1,NDI
        DO K2=1,NDI
          DDSDDE(K2,K1) = ELAM
        END DO
        DDSDDE(K1,K1) = EG2 + ELAM
      END DO
      DO K1=NDI+1,NTENS
        DDSDDE(K1,K1) = EG
      END DO
      DO K1=1,NTENS
        DO K2=1,NTENS
          STRESS(K2) = STRESS(K2) + DDSDDE(K2,K1)*DSTRAN(K1)
        END DO
      END DO
      STATEV(1) = CURE
      RETURN
      END
"""

NTENS, NSTATV, NPROPS = 6, 1, 5
# E_cured, E_uncured, nu, critical cure, cure rate (per unit DTIME; the driver
# uses DTIME = 1): the cure degree is 0.3, 0.51, 0.657, ... so the threshold
# 0.4 is crossed at the second increment and both branches are exercised.
PROPS = [3000.0, 50.0, 0.35, 0.4, 0.3]
PATH = [[1.0e-3, -2.0e-4, -2.0e-4, 5.0e-4, 0.0, 3.0e-4]] * 5


def _transformed(tmp_path: Path) -> dict:
    work = tmp_path / "work"
    work.mkdir()
    staged = work / "cure_modulus.for"
    staged.write_text(SOURCE)
    _write_aba_param_stub(work)
    config, _finite = _build_contract("cure_modulus", "auto", "STRESS", "DDSDDE", NTENS, 1, staged)
    (work / "contract.json").write_text(json.dumps(config, indent=2))
    out = work / "out"
    out.mkdir()
    _write_aba_param_stub(out)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        report, _code = run_transformation(work / "contract.json", out,
                                           TransformationOptions(compile_generated=True))
    assert report.get("transform_success"), report.get("blockers")
    return report


def test_the_continued_statement_is_rewritten_whole_and_compiles(tmp_path):
    if not shutil.which("gfortran"):
        pytest.fail("gfortran is required for this regression")
    report = _transformed(tmp_path)
    compilation = report.get("compilation") or {}
    assert compilation.get("status") == "compiled", str(compilation.get("stderr"))[-2000:]
    lines = Path(report["transformed_source"]).read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if "EMOD = REAL(" in line)
    # join the fixed-form continuation the emitter wrote (column-6 marker)
    statement = lines[start].rstrip() + "".join(
        line[6:].strip() for line in lines[start + 1:start + 3]
        if len(line) > 6 and line[:5].strip() == "" and line[5] not in " 0")
    assert statement.replace(" ", "").endswith(
        "EMOD=REAL(PROPS(2)+(CURE_OTI-CRIT)/(1.0D0-CRIT)*(PROPS(1)-PROPS(2)))"), statement
    assert "C     OTIS-SKIP: &         (PROPS(1) - PROPS(2))" in lines


def test_the_transformed_stress_matches_the_original_across_the_threshold(tmp_path):
    if not shutil.which("gfortran"):
        pytest.fail("gfortran is required for this regression")
    report = _transformed(tmp_path)
    source = tmp_path / "cure_modulus.for"
    source.write_text(SOURCE)
    original = replay(build_original_driver(source, tmp_path / "original", ntens=NTENS,
                                            nstatv=NSTATV, nprops=NPROPS),
                      PROPS, PATH, ntens=NTENS, nstatv=NSTATV)
    work = tmp_path / "transformed"
    work.mkdir()
    for include in ("aba_param.inc", "ABA_PARAM.INC"):
        (work / include).write_text(ABA_PARAM)
    (work / "driver.f90").write_text(driver_source(ntens=NTENS, nstatv=NSTATV, nprops=NPROPS))
    combined = next(Path(report["transformed_source"]).parent.glob("*_oti_combined.f90"))
    subprocess.run(["gfortran", "-O0", "-ffree-line-length-none", "-I", str(work), "-c", str(combined),
                    "-o", "umat.o"], cwd=work, check=True, capture_output=True, text=True)
    subprocess.run(["gfortran", "driver.f90", "umat.o", "-o", "driver"], cwd=work, check=True,
                   capture_output=True, text=True)
    transformed = replay(work / "driver", PROPS, PATH, ntens=NTENS, nstatv=NSTATV)
    # the modulus jumps from 50 to about 1,000 across the threshold, so a
    # skipped or truncated interpolation shows as an O(1) relative difference
    cures = [row[0] for row in original.statev]
    assert cures[0] < PROPS[3] < cures[-1]
    scale = max(abs(v) for row in original.stress for v in row)
    worst = max(abs(a - b) for ra, rb in zip(original.stress, transformed.stress) for a, b in zip(ra, rb))
    assert worst <= 1e-12 * scale, (worst, scale)
