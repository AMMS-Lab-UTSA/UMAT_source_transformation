"""An integer divided by an integer stays an integer division in a lifted helper.

``4/DTHREE`` with DTHREE an INTEGER PARAMETER is 1 in the source. The lifter
promotes bare integer literals next to an operator (an OTI operand has no
operator taking a default INTEGER in otim6n1), and wrote ``4.0D0/DTHREE`` =
1.333: primal 1.6e-2, DDSDDE 3 % off the author's routine (Vera B5 toy a5x).
A division both of whose operands are integer keeps its literals as written;
oti_intrinsics supplies the OTI-with-INTEGER operators the result then meets.

Behavioural: primal bit-identical to the author's routine (own object), DDSDDE
against central differences of it (see _transform_vs_original).
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
      INTEGER DTHREE
      PARAMETER (DTHREE=3)
      DIMENSION DE(N),S(N),D(N,N)
      DO I=1,N
        S(I)=S(I)+E*(2.D0*DE(I)+DE(I)*DE(I)*1.D2*(4/DTHREE))
     1   +E*DE(I)*((N+1)/2)*1.D-1+E*DE(I)*DE(I)*(7/2*1.D1)
        DO J=1,N
          D(I,J)=0.D0
        END DO
        D(I,I)=E*2.D0
      END DO
      RETURN
      END
"""

RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("CALL HSTR(", "CALL HSTRORIG("),
           ("SUBROUTINE HSTR(", "SUBROUTINE HSTRORIG(")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_an_integer_quotient_in_a_lifted_helper_is_still_an_integer(tmp_path):
    check_against_original(tmp_path, UMAT, ".for", RENAMES, ["1000.0d0"])
