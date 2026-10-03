"""A name split across a fixed-form continuation stays one name in a lifted helper.

Blanks are insignificant in fixed form. Jeff97's shell sources end a line
``...G12*G23*G3`` and continue ``1+G13*G21*G32...``: the name is ``G31``. The
lifter stitched continuations with a blank, so the free-form helper read
``G3 1+...`` and the Petal and SeaShell provider builds failed on
"G3 1.0D0" (Noether's B8 RA run). The lifter now closes the break up between
name characters, as the emitter's own join does, but keeps the blank after a
keyword (``CALL`` / ``FOO(X)``).

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
    "      DO K=1,NTENS\n"
    "        CALL KSOFT(STRESS(K),DSTRAN(K),PROPS(1))\n"
    "      END DO\n"
    "      STATEV(1)=STATEV(1)+STRESS(1)\n"
    "      RETURN\n"
    "      END\n"
    "      SUBROUTINE KSOFT(S,DE,E)\n"
    "      INCLUDE 'ABA_PARAM.INC'\n"
    "      G31=1.D0+DE\n"
    "      CALL\n"
    "     & ADDTO(S, E*DE*G3\n"
    "     &1)\n"
    "      RETURN\n"
    "      END\n"
    "      SUBROUTINE ADDTO(S,X)\n"
    "      INCLUDE 'ABA_PARAM.INC'\n"
    "      S=S+X\n"
    "      RETURN\n"
    "      END\n")

RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("KSOFT(", "KSOFTORIG("),
           ("ADDTO(", "ADDTOORIG(")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_name_split_across_a_continuation_line_is_one_name(tmp_path):
    output = check_against_original(tmp_path, SOURCE, ".for", RENAMES, ["1000.0d0"])
    helpers = (output / "umat_oti_helpers.f90").read_text().upper()
    assert "G31" in helpers and "G3 1" not in helpers


def test_a_character_literal_across_a_continuation_keeps_the_compilers_columns():
    """gfortran pads the first line to column 72 and resumes at column 7."""
    from umat_oti.transform.helper_lifting import _continuation_stitch

    lines = ["      WRITE(*,*) '#ERROR: RGBV IS NOT AVAILABLE IN KINEMATIC HAR",
             "     &DENING'"]
    assert _continuation_stitch(lines, "fixed") == [
        "      WRITE(*,*) '#ERROR: RGBV IS NOT AVAILABLE IN KINEMATIC HAR        DENING'"]


def test_a_keyword_before_a_break_keeps_its_blank():
    from umat_oti.transform.helper_lifting import _continuation_stitch

    assert _continuation_stitch(["      CALL", "     & FOO(X)"], "fixed") == ["      CALL FOO(X)"]
