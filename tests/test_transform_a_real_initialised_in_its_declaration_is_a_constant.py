"""A REAL local given its value in its declaration, and never written, stays a REAL constant.

``DOUBLE PRECISION :: ZERO=0.D0, ONE=1.D0`` in a lifted helper came out as
``type(ONUMM6N1) :: ZERO=0.D0``, which gfortran rejects; MechMater's
UMAT_visco_FGJD_2026.for and UMAT_viscohybrid_FGJD_2026.for declare their
constants that way in DAMAGEVAR. The lifter now declares such a name
PARAMETER when nothing in the routine writes it, and refuses by name one that
is written. Also: ``double precision : : damping`` (blanks are insignificant
in fixed form) came out ``type(ONUMM6N1) :: : : damping``.

Behavioural, against the separately compiled original: primal bitwise, DDSDDE
against central differences at h = 1e-4, 1e-5, 1e-6.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original, transform

SOURCE = (
    "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,\n"
    "     1 RPL,DDSDDT,DRPLDE,DRPLDT,\n"
    "     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,\n"
    "     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,\n"
    "     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)\n"
    "      INCLUDE 'ABA_PARAM.INC'\n"
    "      CHARACTER*80 CMNAME\n"
    "      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),\n"
    "     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),\n"
    "     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),\n"
    "     3 DFGRD0(3,3),DFGRD1(3,3)\n"
    "      DO K=1,NTENS\n"
    "        CALL KSOFT(STRESS(K),DSTRAN(K),PROPS(1))\n"
    "      END DO\n"
    "      STATEV(1)=STATEV(1)+STRESS(1)\n"
    "      RETURN\n"
    "      END\n"
    "      SUBROUTINE KSOFT(S,DE,E)\n"
    "      IMPLICIT NONE\n"
    "      DOUBLE PRECISION S, DE, E\n"
    "      DOUBLE PRECISION : : DAMPING\n"
    "      DOUBLE PRECISION :: ONE=1.D0, TEN=10.D0\n"
    "      DAMPING = 0.5D0\n"
    "%(write)s"
    "      S=S+E*DE*(ONE+TEN*DE*DE)*DAMPING\n"
    "      RETURN\n"
    "      END\n")

RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("KSOFT(", "KSOFTORIG(")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_an_initialised_real_never_written_is_kept_a_real_constant(tmp_path):
    output = check_against_original(tmp_path, SOURCE % {"write": ""}, ".for", RENAMES, ["1000.0d0"])
    helpers = (output / "umat_oti_helpers.f90").read_text().upper()
    assert "PARAMETER :: ONE = 1.D0, TEN = 10.D0" in helpers
    assert ": :" not in helpers


def test_an_initialised_real_that_is_written_is_refused_by_name(tmp_path):
    from umat_oti.transform.helper_lifting import HelperLiftingError

    try:
        summary, code = transform(tmp_path, SOURCE % {"write": "      TEN = TEN + 1.D0\n"}, ".for")
    except HelperLiftingError as refusal:
        text = str(refusal)
    else:
        assert code != 0
        text = str(summary)
    assert "gives TEN a value in its declaration" in text


FUNCTION_WRITE = SOURCE.replace("      S=S+E*DE*(ONE+TEN*DE*DE)*DAMPING\n",
                                "      DAMPING = DAMPING*BUMP(TEN)\n"
                                "      S=S+E*DE*(ONE+TEN*DE*DE)*DAMPING\n") + (
    "      DOUBLE PRECISION FUNCTION BUMP(X)\n"
    "      DOUBLE PRECISION X\n"
    "      X = X + 1.D0\n"
    "      BUMP = 1.D0\n"
    "      END\n")


def test_an_initialised_real_written_through_a_function_reference_is_refused(tmp_path):
    """Vera's B8 re-review C1: X = BUMP(TEN), BUMP writing its argument."""
    from umat_oti.transform.helper_lifting import HelperLiftingError

    try:
        summary, code = transform(tmp_path, FUNCTION_WRITE % {"write": ""}, ".for")
    except HelperLiftingError as refusal:
        text = str(refusal)
    else:
        assert code != 0
        text = str(summary)
    assert "gives TEN a value in its declaration" in text
