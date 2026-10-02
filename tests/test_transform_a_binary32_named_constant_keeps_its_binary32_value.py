"""A named constant declared REAL (binary32) keeps its binary32 value when lifted.

``REAL C; PARAMETER (C=1.D0/3.D0)`` is 1/3 rounded to binary32 in the source.
The lifter emitted ``real(8), parameter :: C = 1.D0/3.D0`` -- the double value
-- and the primal moved by 4.3e-9 (7.1e-10 for ``C=0.1D0``), also when the
constant was carried into an internal procedure (Vera B5 T3 v_*). Now the
constant holds the binary32 value exactly (an OTI operator takes REAL(8), so
it stays real(8)), and an operation between two binary32 operands is rounded
as the source's is.

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
        S(I)=S(I)+%(expr)s
        DO J=1,N
          D(I,J)=0.D0
        END DO
        D(I,I)=E*2.D0
      END DO
      RETURN
%(internal)s      END
"""
TOYS = {
    "real_default_expr": ("      REAL C5\n      PARAMETER (C5=1.D0/3.D0)", "E*(2.D0*DE(I)+C5*DE(I)**2*1.3D3)", ""),
    "real_default_literal": ("      REAL C5\n      PARAMETER (C5=0.1D0)", "E*(2.D0*DE(I)+C5*DE(I)**2*1.3D3)", ""),
    "real_star4": ("      REAL*4 C5\n      PARAMETER (C5=1.D0/3.D0)", "E*(2.D0*DE(I)+C5*DE(I)**2*1.3D3)", ""),
    "real4_attributed": ("      REAL(4), PARAMETER :: C4=0.1", "E*(2.D0*DE(I)+C4*DE(I)**2*1.3D3)", ""),
    "real4_expr": ("      REAL(4) C4\n      PARAMETER (C4=1.D0/3.D0)", "E*(2.D0*DE(I)+C4*DE(I)**2*1.3D3)", ""),
    "binary32_product": ("      REAL C5, C6\n      PARAMETER (C5=1.D0/3.D0, C6=0.7D0)",
                         "E*(2.D0*DE(I)+C5*C6*DE(I)**2*1.3D3)", ""),
    "carried_into_internal": ("      REAL C5\n      PARAMETER (C5=1.D0/3.D0)", "E*F(DE(I))",
                              "      CONTAINS\n      FUNCTION F(X)\n      F = 2.D0*X + C5*X*X*1.3D3\n"
                              "      END FUNCTION\n"),
}
RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("CALL HSTR(", "CALL HSTRORIG("),
           ("SUBROUTINE HSTR(", "SUBROUTINE HSTRORIG(")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
@pytest.mark.parametrize("toy", sorted(TOYS))
def test_a_binary32_named_constant_keeps_its_binary32_value(tmp_path, toy):
    constants, expr, internal = TOYS[toy]
    text = UMAT % {"constants": constants, "expr": expr, "internal": internal}
    check_against_original(tmp_path, text, ".for", RENAMES, ["1000.0d0"])
