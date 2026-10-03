"""A tab anywhere in the fixed-form label field starts a statement in column 7.

ifort and gfortran read `` <TAB>  IF (...) THEN`` and ``<5 blanks><TAB>  X = ...``
as statements. The emitter and the lifter expanded only a tab in column 1, so
column 6 held a letter and the line was read as a continuation and glued onto
the statement above: ``temp = tempsv (noel.eq.1) then`` in the lifted helpers
of SinglePointSimulator's MODIFIED_JC.f, ``.../DETSIGMAEQH(K,J)= ...`` in
MechMater's UMAT_visco_FGJD_2026.for, and the wellbore.f build failure in
cbgeo-archives/hpc-scripts. Both now use the parser's rule.

Behavioural, against the separately compiled original: primal bitwise, DDSDDE
against central differences at h = 1e-4, 1e-5, 1e-6.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original

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
    "      E=PROPS(1)\n"
    "      DO K=1,NTENS\n"
    "        CALL KSOFT(STRESS(K),DSTRAN(K),E,G)\n"
    "     \t  STRESS(K)=STRESS(K)+G*DSTRAN(MOD(K,NTENS)+1)\n"
    "      END DO\n"
    "      STATEV(1)=STATEV(1)+STRESS(1)\n"
    "      RETURN\n"
    "      END\n"
    "      SUBROUTINE KSOFT(S,DE,E,G)\n"
    "      INCLUDE 'ABA_PARAM.INC'\n"
    "      G=0.3D0*E\n"
    " \t  IF (DE.GT.0.D0) THEN\n"
    "        G=0.4D0*E\n"
    "      END IF\n"
    "      S=S+E*DE*(1.D0+10.D0*DE*DE)\n"
    "      RETURN\n"
    "      END\n")

RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("KSOFT(", "KSOFTORIG(")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_tab_after_a_blank_in_the_label_field_starts_a_statement(tmp_path):
    check_against_original(tmp_path, SOURCE, ".for", RENAMES, ["1000.0d0"])
