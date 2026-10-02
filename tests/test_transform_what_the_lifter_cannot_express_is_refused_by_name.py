"""A statement function in an internal procedure, and ENTRY in a helper, are refused by name.

Both used to report a successful transform whose output did not build (Vera B5
T3): a statement function inside a lifted internal procedure -- including one
whose dummy or name is a host constant -- came out as an assignment to an
undeclared array, and a helper with ENTRY had its alternate entry point defined
twice. Now each is refused, naming the procedure and what to change. A
statement function in an ordinary lifted helper is unaffected (control).
"""
import shutil

import pytest

from _transform_vs_original import check_against_original, transform  # noqa: I001

CALLER = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
"""


def helper(expr, internal="", pre="", entry=""):
    return CALLER + f"""      SUBROUTINE HSTR(E,DE,S,D,N)
      INCLUDE 'ABA_PARAM.INC'
      PARAMETER (ONE=1.D0, TWO=2.D0)
      DIMENSION DE(N),S(N),D(N,N)
{pre}      DO I=1,N
        S(I)=S(I)+{expr}
        DO J=1,N
          D(I,J)=0.D0
        END DO
        D(I,I)=E*2.D0
      END DO
      RETURN
{entry}""" + (f"      CONTAINS\n{internal}\n" if internal else "") + "      END\n"


ENTRY = "      ENTRY HSTRB(E,DE,S,D,N)\n      S(1)=ONE\n      RETURN\n"
REFUSED = {
    "sf_dummy_named_like_a_host_constant": (
        helper("E*F(DE(I))", "      FUNCTION F(X)\n      SQ(ONE)=ONE*ONE*1.D2\n"
               "      F = TWO*X*ONE + SQ(X)\n      END FUNCTION"), ("F", "SQ")),
    "sf_named_like_a_host_constant": (
        helper("E*F(DE(I))", "      FUNCTION F(X)\n      TWO(Y)=3.D0*Y\n"
               "      F = TWO(X) + ONE*X*X*1.D2\n      END FUNCTION"), ("F", "TWO")),
    "entry_in_a_helper": (helper("E*(TWO*DE(I)+ONE*DE(I)**2*1.D2)", entry=ENTRY), ("HSTR", "HSTRB")),
    "entry_in_a_host": (helper("E*F(DE(I))", "      FUNCTION F(X)\n      F = TWO*X + ONE*X*X*1.D2\n"
                                "      END FUNCTION", entry=ENTRY), ("HSTR", "HSTRB")),
}


@pytest.mark.parametrize("toy", sorted(REFUSED))
def test_it_is_refused_with_the_names(tmp_path, toy):
    from umat_oti.transform.helper_lifting import HelperLiftingError

    text, names = REFUSED[toy]
    with pytest.raises(HelperLiftingError) as refusal:
        transform(tmp_path, text, ".for")
    assert all(name in str(refusal.value) for name in names)


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_statement_function_in_an_ordinary_helper_still_transforms(tmp_path):
    text = helper("E*(2.D0*DE(I)+SQ(DE(I)))", pre="      SQ(Y)=Y*Y*0.7D2\n")
    check_against_original(tmp_path, text, ".for", [
        ("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("), ("CALL HSTR(", "CALL HSTRORIG("),
        ("SUBROUTINE HSTR(", "SUBROUTINE HSTRORIG(")], ["1000.0d0"])
