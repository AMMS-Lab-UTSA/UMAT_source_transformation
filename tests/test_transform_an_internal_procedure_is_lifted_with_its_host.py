"""A helper with internal procedures (CONTAINS) is lifted, and they come with it.

GuGuaTT__STEEL-3dPointClouds (two rate-independent plasticity sources) delegate
from UMAT to UMAT2, which CONTAINS ``pure function dotprod6(A, B) result(C)``.
The lifter read the internal function's specification statements as the
host's: UMAT2_OTI declared A(6), B(6) and C beside its own scalar A and did not
compile. Each internal procedure was also lifted on its own as an EXTERNAL
copy, which (a) lost the host's named constant TWO it reads by host
association -- an uninitialised local in the copy, a wrong stress that compiles
-- and (b) left a call with an assumed-shape dummy without the explicit
interface it needs.

Now the host is lifted without its CONTAINS section, each internal procedure is
lifted with its host's named constants declared in it, and the lifted copies
are put back after CONTAINS in the lifted host. An internal procedure that
reads a host VARIABLE is refused with the name, because carrying a variable is
not the same program.

Behavioural: primal bit-identical to the author's routine (own object), DDSDDE
against central differences of it (see _transform_vs_original).
"""
import shutil

import pytest

from _transform_vs_original import check_against_original, transform  # noqa: I001

HEADER = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      CALL MODEL(STRESS,STATEV,DDSDDE,DSTRAN,PROPS,NTENS,NSTATV,
     1 NPROPS)
      RETURN
      END
"""

#: The host has a scalar A; the internal function's dummies are A(6), B(6).
#: DOT6 reads the host's named constant TWO; SCALE takes an assumed-shape P(:).
MODEL = """      SUBROUTINE MODEL(STRESS,STATEV,DDSDDE,DSTRAN,PROPS,NTENS,NSTATV,
     1 NPROPS)
      IMPLICIT REAL*8 (A-H,O-Z)
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DSTRAN(NTENS),PROPS(NPROPS)
      REAL(8), PARAMETER :: TWO = 2.0D0
      EMOD = PROPS(1)
      A = DOT6(DSTRAN, DSTRAN)
      DO K=1,NTENS
        STRESS(K)=STRESS(K)+EMOD*DSTRAN(K)*(1.D0+%(coupling)s)
     1   +SCALE(PROPS(1:NPROPS))*DSTRAN(K)*A
      END DO
      STATEV(1)=STATEV(1)+A
      DO K=1,NTENS
        DDSDDE(K,K)=EMOD
      END DO
      RETURN
      CONTAINS
      PURE FUNCTION DOT6(A, B) RESULT(C)
      REAL(8), INTENT(IN) :: A(6), B(6)
      REAL(8) :: C
      INTEGER :: I
      C = 0.0D0
      DO I = 1, 3
        C = C + A(I)*B(I)
      END DO
      DO I = 4, 6
        C = C + TWO*(A(I)*B(I))
      END DO
      END FUNCTION
      FUNCTION SCALE(P) RESULT(S)
      REAL(8), INTENT(IN) :: P(:)
      REAL(8) :: S
      S = 0.1D0*P(SIZE(P))%(host_read)s
      END FUNCTION
      END
"""

RENAMES = [("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("CALL MODEL(", "CALL MODELORIG("),
           ("SUBROUTINE MODEL(", "SUBROUTINE MODELORIG(")]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_the_internal_procedures_come_with_their_host_and_its_constants(tmp_path):
    text = HEADER + MODEL % {"coupling": "A", "host_read": ""}
    output = check_against_original(tmp_path, text, ".for", RENAMES, ["1000.0d0", "3.0d0"])
    helpers = (output / "umat_oti_helpers.f90").read_text().lower()
    assert "contains" in helpers  # back inside their host, with its interface


def test_an_internal_procedure_that_reads_a_host_variable_is_refused(tmp_path):
    from umat_oti.transform.helper_lifting import HelperLiftingError

    text = HEADER + MODEL % {"coupling": "A", "host_read": "*EMOD"}
    with pytest.raises(HelperLiftingError) as refusal:
        transform(tmp_path, text, ".for")
    message = str(refusal.value)
    assert "SCALE" in message and "EMOD" in message and "TWO" not in message
