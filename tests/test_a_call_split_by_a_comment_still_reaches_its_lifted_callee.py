"""``CALL name ! comment`` with the argument list on the next line names the lifted callee.

theysy's MML_U2 writes

        CALL STRESS_UPDATE  ! ITERATIVE STRESS UPDATE METHOD
       1 (STAT_VAR,EQPLAS,STRESS,DDSDDE,ITER)

The statement transformer sees one physical line at a time, with the comment
stripped; the line is the bare name, which matched neither the call-with-
arguments pattern nor the continuation-opener pattern (both need a "("), so
the callee kept its real name while the actuals on the next line were
hypercomplex shadows: the first call returned a stress of 0.0 against 221.37.
Rule (B20 RULES.md R9): a CALL line that is only a name, naming a lifted helper,
is renamed to NAME_OTI like any other call. Canaries: a name that is NOT a
lifted helper keeps its name and the leak check still refuses the file; a call
with arguments on its own line is unchanged.
"""
import re
from pathlib import Path

from _b20_support import transform_text, failed_checks
from umat_oti.transform.source_transform import _rewrite_lifted_helper_call

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
      EMOD = PROPS(1)
      CALL UPDATE_STRESS  ! ITERATIVE UPDATE
     1 (STRESS,DSTRAN,EMOD,NTENS)
      DO I=1,NTENS
        DO J=1,NTENS
          DDSDDE(I,J)=0.D0
        END DO
        DDSDDE(I,I)=EMOD
      END DO
      RETURN
      END
"""
HELPER = """      SUBROUTINE UPDATE_STRESS(STRESS,DSTRAN,EMOD,NTENS)
      IMPLICIT REAL*8 (A-H,O-Z)
      DIMENSION STRESS(NTENS),DSTRAN(NTENS)
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+EMOD*DSTRAN(I)*(1.D0+DSTRAN(1)**2)
      END DO
      RETURN
      END
"""


def test_a_bare_call_line_is_renamed_to_the_lifted_callee():
    assert _rewrite_lifted_helper_call("      CALL UPDATE_STRESS  ", {"UPDATE_STRESS"}, {}) == \
        "      CALL UPDATE_STRESS_OTI  "


def test_canary_a_name_that_is_not_a_lifted_helper_is_left_alone():
    assert _rewrite_lifted_helper_call("      CALL SOMETHING_ELSE", {"UPDATE_STRESS"}, {}) == \
        "      CALL SOMETHING_ELSE"


def test_a_call_with_its_arguments_on_one_line_is_unchanged_by_the_rule():
    assert _rewrite_lifted_helper_call("      CALL UPDATE_STRESS(A, B)", {"UPDATE_STRESS"}, {}) == \
        "      CALL UPDATE_STRESS_OTI(A, B)"


def test_the_whole_transform_calls_the_lifted_helper(tmp_path):
    report = transform_text(tmp_path, HEAD + HELPER, ".for")
    assert report["transform_success"], failed_checks(report)
    emitted = Path(report["transformed_source"]).read_text()
    assert re.search(r"CALL UPDATE_STRESS_OTI\s+! ITERATIVE UPDATE", emitted)


def test_canary_an_unlifted_callee_split_the_same_way_is_still_refused(tmp_path):
    """UPDATE_STRESS defined nowhere, hypercomplex actuals on the continuation line."""
    unlifted = HEAD.replace(
        "      CALL UPDATE_STRESS  ! ITERATIVE UPDATE",
        "      DO I=1,NTENS\n        STRESS(I)=STRESS(I)+EMOD*DSTRAN(I)*(1.D0+DSTRAN(1)**2)\n      END DO\n"
        "      CALL REPORT_STRESS  ! DIAGNOSTIC HOOK")
    unlifted = unlifted.replace("(STRESS,DSTRAN,EMOD,NTENS)", "(STRESS,DSTRAN,NTENS)")
    report = transform_text(tmp_path, unlifted, ".for")
    assert not report["transform_success"]
    text = " ".join(str(b) for b in report["blockers"]) + " ".join(
        name for name, ok in (report.get("semantic_checks") or {}).items() if ok is False)
    assert "REPORT_STRESS" in text or "no_oti_argument_reaches_an_untransformed_call" in text
