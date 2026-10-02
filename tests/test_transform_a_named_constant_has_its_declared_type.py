"""A named constant in a lifted helper has the type the source gives it.

The lifter typed each PARAMETER from the form of its value: an integer literal
made an INTEGER constant. ``REAL(8) :: THREE`` then ``PARAMETER (THREE=3)``,
and ``PARAMETER (TWO=2)`` under ABA_PARAM.INC's IMPLICIT REAL*8, both came out
``integer, parameter``, so ``1/THREE`` was an integer division (0) where the
source divides reals -- a wrong value that compiles. The type is now the
declaration's, else the routine's IMPLICIT rule; ``INTEGER N`` with
``PARAMETER (N=2*3)`` is an integer however its value is written.

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
%(constants)s
      DIMENSION DE(N),S(N),D(N,N)
      DO I=1,N
        S(I)=S(I)+E*(2.D0*DE(I)+DE(I)*DE(I)*7.D1*(1/%(name)s))
     1   +E*DE(I)*(%(count)s/4)
        DO J=1,N
          D(I,J)=0.D0
        END DO
        D(I,I)=E*2.D0
      END DO
      RETURN
      END
"""

#: Declared REAL(8), an integer-literal value; and an INTEGER whose value is
#: an expression (it used to be written real(8)).
DECLARED = {"constants": "      REAL(8) :: THREE\n      INTEGER KCOUNT\n"
                         "      PARAMETER (THREE=3, KCOUNT=2*3)",
            "name": "THREE", "count": "KCOUNT"}
#: Typed by IMPLICIT REAL*8 alone.
IMPLICIT = {"constants": "      PARAMETER (TWO=2, KCOUNT=6)", "name": "TWO", "count": "KCOUNT"}

RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("CALL HSTR(", "CALL HSTRORIG("),
           ("SUBROUTINE HSTR(", "SUBROUTINE HSTRORIG(")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
@pytest.mark.parametrize("toy", [DECLARED, IMPLICIT], ids=["declared_real", "implicit_real"])
def test_a_named_constant_keeps_the_type_the_source_gives_it(tmp_path, toy):
    check_against_original(tmp_path, UMAT % toy, ".for", RENAMES, ["1000.0d0"])
