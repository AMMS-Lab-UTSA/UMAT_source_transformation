"""``DOUBLE PRECISION :: RESTOL = 1.0D-09`` must not become ``RESTOL_OTI = 0.0D0``.

MechMater's FGJD viscoelastic UMAT tests its Newton loop against a tolerance
declared with an initialiser. The classifier promoted the tolerance, the
emitter zeroed its shadow and nothing copied the initial value in, so
``ABS(NORMRES_OTI).LT.RESTOL_OTI`` was never true: the loop never exited, the
solver cut the increment back until Abaqus gave up (transformed_job_failed).
Rule (B20 RULES.md R8): a name initialised in its declaration is a compile-time
constant exactly as a DATA-initialised name is: never assigned, it stays real
with its initialiser; initialised and also assigned, it keeps the existing
refusal (a shadow cannot be given the declared value). PARAMETER names and
INTENT dummies are not initialised names.
"""
import re
from pathlib import Path

import pytest

from _b20_support import transform_text, failed_checks
from umat_oti.core.roles import data_initialised_names

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
      DOUBLE PRECISION :: TOL = 1.0D-09
      DOUBLE PRECISION EMOD, RES, X
      EMOD = PROPS(1)
%(RESET)s      X = DSTRAN(1)
      DO ITER = 1, 50
        RES = EMOD*X - DSTRAN(1)*EMOD*0.5D0
        IF (ABS(RES).LT.TOL) GO TO 100
        X = X - RES/EMOD
      END DO
  100 CONTINUE
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+EMOD*DSTRAN(I)*(1.D0+X)
      END DO
      DO I=1,NTENS
        DO J=1,NTENS
          DDSDDE(I,J)=0.D0
        END DO
        DDSDDE(I,I)=EMOD
      END DO
      RETURN
      END
"""
FGJD = (Path(__file__).resolve().parents[2] / "discovery_cache" /
        "MechMater-project__UMAT_finitestrain_viscoelasticity_withdamage" / "UMAT_visco_FGJD_2026.for")


def test_the_names_are_read_from_declarations():
    found = data_initialised_names(
        "      DOUBLE PRECISION :: A = 1.0D-9, B, C(3) = (/1.,2.,3./)\n"
        "      INTEGER, PARAMETER :: N = 3\n"
        "      REAL(8), INTENT(IN) :: Q\n"
        "      real*8 :: R = 1.0/3.0, S = 2.D0\n"
        "      DATA XI /1.D0/\n")
    assert found == {"A", "C", "R", "S", "XI"}


def test_an_initialised_tolerance_that_is_never_assigned_stays_real(tmp_path):
    report = transform_text(tmp_path, HEAD % {"RESET": ""}, ".for")
    assert report["transform_success"], failed_checks(report)
    emitted = Path(report["transformed_source"]).read_text()
    assert re.search(r"\.LT\.TOL\b", emitted, re.IGNORECASE)
    assert not re.search(r"\bTOL_OTI\s*=\s*0", emitted, re.IGNORECASE)
    assert "TOL = 1.0D-09" in emitted


def test_canary_an_initialised_name_that_is_also_assigned_is_still_refused(tmp_path):
    reset = "      TOL = 1.0D-9*(1.D0+DSTRAN(1)**2)\n"      # differentiated, so promoted
    report = transform_text(tmp_path, HEAD % {"RESET": reset}, ".for")
    assert not report["transform_success"]
    assert "TOL takes its starting value" in " ".join(report["blockers"])
    assert "initialised at line" in " ".join(report["blockers"])


@pytest.mark.skipif(not FGJD.is_file(), reason="needs the discovery cache")
def test_the_fgjd_viscoelastic_newton_tolerance_is_the_authors(tmp_path):
    report = transform_text(tmp_path, FGJD.read_text(errors="replace"), ".for")
    assert report["transform_success"], failed_checks(report)
    emitted = Path(report["transformed_source"]).read_text()
    assert re.search(r"\.LT\.RESTOL\b", emitted, re.IGNORECASE)
    assert not re.search(r"\bRESTOL_OTI\b", emitted, re.IGNORECASE)
