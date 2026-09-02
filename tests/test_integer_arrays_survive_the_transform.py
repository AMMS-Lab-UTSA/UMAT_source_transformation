"""End to end: a DIMENSION-declared integer array is not promoted.

The unit rule lives in `test_an_array_is_typed_by_the_same_rule`. This runs the
transform itself, because the rule was correct in one place and absent in two
others, and each absence was enough on its own to promote the array.

The shape of the fixture is the shape of the failure it is drawn from: an
integer array declared by DIMENSION alone, written from a real-valued PROPS
through NINT, read on the stress path, and handed to a helper that declares the
same argument INTEGER.
"""
from pathlib import Path

from umat_oti.core.roles import suggest_variable_roles
from umat_oti.fortran.scanner import analyze_fortran_source

FIXTURE = '''      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      IMPLICIT REAL*8 (A-H,O-Z)
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
C     Declared by DIMENSION alone: a shape, and no type. I is outside
C     A-H and O-Z, so these are arrays of INTEGER.
      DIMENSION IDIRN(3), SCALED(3)
      DO K1=1,3
         IDIRN(K1)=NINT(PROPS(K1))
      END DO
      CALL SCALEBY (IDIRN, SCALED)
      DO K1=1,NTENS
         STRESS(K1)=STRESS(K1)+PROPS(4)*DSTRAN(K1)*SCALED(1)
      END DO
      RETURN
      END

      SUBROUTINE SCALEBY (IDIRN, SCALED)
      IMPLICIT REAL*8 (A-H,O-Z)
      DIMENSION IDIRN(3), SCALED(3)
      RMOD=SQRT(FLOAT(IDIRN(1)**2+IDIRN(2)**2+IDIRN(3)**2))
      DO K1=1,3
         SCALED(K1)=IDIRN(K1)/RMOD
      END DO
      RETURN
      END
'''


def test_the_integer_array_is_kept_real(tmp_path):
    source = tmp_path / "u.for"
    source.write_text(FIXTURE, encoding="utf-8")
    rows = suggest_variable_roles(analyze_fortran_source(source), FIXTURE)
    roles = {str(row["variable name"]).upper(): row["user-selected OTIS role"]
             for row in rows}
    assert roles.get("IDIRN") == "Keep real", roles.get("IDIRN")


def test_the_real_array_beside_it_is_untouched(tmp_path):
    """The rule is about the first letter, not about being DIMENSION-declared."""
    source = tmp_path / "u.for"
    source.write_text(FIXTURE, encoding="utf-8")
    rows = suggest_variable_roles(analyze_fortran_source(source), FIXTURE)
    roles = {str(row["variable name"]).upper(): row["user-selected OTIS role"]
             for row in rows}
    assert roles.get("SCALED") != "Keep real", roles.get("SCALED")


def test_the_rule_needs_the_source_and_says_nothing_without_it(tmp_path):
    """Guessing the implicit rule would be worse than not applying it.

    A source declaring `IMPLICIT REAL*8 (A-Z)` has no implicit integers at
    all, so a caller that cannot supply the text gets no ruling rather than a
    wrong one -- which is why the compact-config loader not passing it made
    the rule silently inert.
    """
    source = tmp_path / "u.for"
    source.write_text(FIXTURE, encoding="utf-8")
    rows = suggest_variable_roles(analyze_fortran_source(source))
    roles = {str(row["variable name"]).upper(): row["user-selected OTIS role"]
             for row in rows}
    assert roles.get("IDIRN") != "Keep real"
