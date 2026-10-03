"""ROTSIG called ahead of the stress update with a shadowed argument is lifted.

materialsguy's UMATPlasticity.f rotates its stored strains with
``CALL ROTSIG(STATEV(1), DROT, EELAS, 2, NDI, NSHR)`` before the stress
update. The emitter handed ROTSIG STATEV_OTI and EELAS_OTI, but only callees
the file defines were offered to the lifter outside the stress interval, so
ROTSIG was not lifted and the leak check refused the source -- for a solver
utility whose body this transform supplies. The supplied utilities are now
offered the same way.

The toy hands ROTSIG a 6-long array and a non-trivial rotation (a 36.87
degree turn about 3), so the rotated strains are not zero and reach the
stress (Vera, B8 re-review C2: STATEV(1) with NSTATV=2 read out of bounds,
and the driver's DROT=0 zeroed the output). Behavioural, against the
separately compiled original (with the same ROTSIG body): primal bitwise, DDSDDE against central differences at three step sizes.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original
from umat_oti.transform.abaqus_utility_definitions import ROTSIG_DEFINITION

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
    "     3 DFGRD0(3,3),DFGRD1(3,3),EELAS(6),SV(6),R(3,3)\n"
    "      C=0.8D0\n"
    "      S=0.6D0\n"
    "      R(1,1)=C\n"
    "      R(1,2)=-S\n"
    "      R(1,3)=0.D0\n"
    "      R(2,1)=S\n"
    "      R(2,2)=C\n"
    "      R(2,3)=0.D0\n"
    "      R(3,1)=0.D0\n"
    "      R(3,2)=0.D0\n"
    "      R(3,3)=1.D0\n"
    "      DO K=1,6\n"
    "        SV(K)=STATEV(1)*0.01D0*K\n"
    "      END DO\n"
    "      CALL ROTSIG(SV,R,EELAS,2,NDI,NSHR)\n"
    "      DO K=1,NTENS\n"
    "        EELAS(K)=EELAS(K)+DSTRAN(K)\n"
    "        STRESS(K)=STRESS(K)+PROPS(1)*EELAS(K)*(1.D0+5.D0*EELAS(K))\n"
    "      END DO\n"
    "      STATEV(1)=STATEV(1)+EELAS(1)\n"
    "      RETURN\n"
    "      END\n")

RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("ROTSIG(", "ROTSIGORIG(")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_rotsig_ahead_of_the_stress_update_is_lifted_and_agrees(tmp_path):
    # The transform supplies ROTSIG itself; the reference needs a body to link.
    output = check_against_original(tmp_path, SOURCE, ".for",
                                    [*RENAMES, ("      RETURN\n      END\n",
                                                "      RETURN\n      END\n" + ROTSIG_DEFINITION.replace(
                                                    "ROTSIG(", "ROTSIGORIG("))], ["1000.0d0"])
    assert "ROTSIG_OTI(SV" in next(output.glob("*_oti.for")).read_text().upper().replace(" ", "")
