"""An internal procedure's implicitly typed names follow its host's IMPLICIT rules.

An internal procedure without an IMPLICIT statement of its own types its names
by its host's rules -- here ABA_PARAM.INC's IMPLICIT REAL*8 (A-H,O-Z). The
lifted copy was typed from its own text alone, so its implicitly typed dummy,
local and result read as default REAL, and every store to them was rounded to
binary32 (OTI_R4): primal 2e-8..7e-8 off the author's routine (Vera B5 toys
a1_chain, a3_implicit_dummy). Behavioural: primal bit-identical to the author's
routine (own object), DDSDDE against central differences of it.
"""
import shutil

import pytest

from _transform_vs_original import check_against_original  # noqa: I001

UMAT = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,JSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3),JSTEP(4)
      E=PROPS(1)
      CALL HSTR(E,DSTRAN,STRESS,DDSDDE,NTENS)
      RETURN
      END
      SUBROUTINE HSTR(E,DE,S,D,N)
      INCLUDE 'ABA_PARAM.INC'
%(constants)s
      DIMENSION DE(N),S(N),D(N,N)
      DO I=1,N
        S(I)=S(I)+E*F(DE(I))
        DO J=1,N
          D(I,J)=0.D0
        END DO
        D(I,I)=E*2.D0
      END DO
      RETURN
      CONTAINS
%(function)s
      END FUNCTION
      END
"""

#: Vera's a1_chain: a chain of host constants, an implicit dummy and result.
CHAIN = {"constants": "      PARAMETER (ONE=1.D0)\n      PARAMETER (TWO=2.D0*ONE, HALF=ONE/TWO)",
         "function": "      FUNCTION F(X)\n      F = TWO*X + HALF*X*X*1.1D3"}
#: Vera's a3_implicit_dummy: an implicit local as well.
IMPLICIT_LOCAL = {"constants": "      PARAMETER (TWO=2.D0)",
                  "function": "      FUNCTION F(Y)\n      Z = Y*Y\n      F = TWO*Y + Z*0.7D2"}

RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("CALL HSTR(", "CALL HSTRORIG("),
           ("SUBROUTINE HSTR(", "SUBROUTINE HSTRORIG(")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
@pytest.mark.parametrize("toy", [CHAIN, IMPLICIT_LOCAL], ids=["a1_chain", "a3_implicit_local"])
def test_an_internal_procedure_is_double_precision_where_its_host_is(tmp_path, toy):
    output = check_against_original(tmp_path, UMAT % toy, ".for", RENAMES, ["1000.0d0"])
    assert "oti_r4" not in (output / "umat_oti_helpers.f90").read_text().lower()
