"""An internal procedure sees each host named constant it does not hide itself.

The lifted internal procedure is given its host's named constants, which it saw
by host association. They used to be carried per source STATEMENT: a DOTPROD6
that declared a local THREE dropped the whole of the host's
``PARAMETER(TOL=..., ONE=..., TWO=..., THREE=..., ...)``, TWO with it, and the
lifted copy multiplied by an uninitialised local TWO (UVCmultiaxial with
``REAL(8) :: THREE`` added; Vera B5: stress 4-6 %, DDSDDE 43 % off). They are
carried per NAME now: only the hidden name is left out, and a carried value
defined through a hidden name is refused.

Behavioural: primal bit-identical to the author's routine (own object), DDSDDE
against central differences of it (see _transform_vs_original). The UMAT is
the host in the first test (its internal procedure is lifted on its own), a
lifted helper in the second (the internal procedure goes back inside it).
"""
import shutil

import pytest

from _transform_vs_original import check_against_original, transform  # noqa: I001

UMAT_HOST = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      INTEGER :: N_BASIC
      REAL(8) :: TOL, ONE, TWO, THREE
      PARAMETER(TOL=1.0D-10,
     1N_BASIC=7, ONE=1.0D0, TWO=2.0D0,
     2THREE=3.0D0)
      EMOD = PROPS(1)
      AA = DOTPROD6(DSTRAN, DSTRAN)
      DO K=1,NTENS
        STRESS(K)=STRESS(K)+EMOD*DSTRAN(K)*(ONE+AA*PROPS(2)*THREE)
      END DO
      STATEV(1)=STATEV(1)+AA
      DO K=1,NTENS
        DDSDDE(K,K)=EMOD
      END DO
      RETURN
      CONTAINS
      pure function dotprod6(A, B) result(C)
      REAL(8), intent(in) :: A(6), B(6)
      REAL(8)             :: C
      INTEGER             :: i
      REAL(8)             :: THREE
      C = 0.0D0
      DO i = 1, 3
        C = C + A(i) * B(i)
      END DO
      DO i = 4, 6
        C = C + TWO * (A(i) * B(i))
      END DO
      end function
      END
"""

HELPER_HOST = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      E=PROPS(1)
      CALL HSTR(E,DSTRAN,STRESS,DDSDDE,NTENS)
      RETURN
      END
      SUBROUTINE HSTR(E,DE,S,D,N)
      INCLUDE 'ABA_PARAM.INC'
      PARAMETER (ONE=1.D0, TWO=%(two)s)
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
      FUNCTION F(X)
      REAL(8) :: ONE
      ONE = 5.D0
      F = TWO*X + ONE*X*X
      END FUNCTION
      END
"""

UMAT_RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(")]
HELPER_RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("CALL HSTR(", "CALL HSTRORIG("),
                  ("SUBROUTINE HSTR(", "SUBROUTINE HSTRORIG(")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_umat_host_constant_survives_a_local_named_like_its_neighbour(tmp_path):
    output = check_against_original(tmp_path, UMAT_HOST, ".for", UMAT_RENAMES,
                                    ["1000.0d0", "50.0d0"])
    lifted = (output / "umat_oti_helpers.f90").read_text().lower()
    assert "parameter :: two" in lifted and "parameter :: three" not in lifted


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_lifted_host_constant_survives_a_local_named_like_its_neighbour(tmp_path):
    check_against_original(tmp_path, HELPER_HOST % {"two": "2.D0"}, ".for", HELPER_RENAMES,
                           ["1000.0d0"])


def test_a_carried_constant_defined_through_a_hidden_name_is_refused(tmp_path):
    from umat_oti.transform.helper_lifting import HelperLiftingError

    with pytest.raises(HelperLiftingError) as refusal:
        transform(tmp_path, HELPER_HOST % {"two": "2.D0*ONE"}, ".for")
    message = str(refusal.value)
    assert "TWO" in message and "ONE" in message and "F" in message
