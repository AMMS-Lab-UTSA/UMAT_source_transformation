"""A UMAT that runs off its END has an exit as well.

keisuke58 umat_biofilm_visco, tengzhang48 template_umat and neo_hookean_umat end
without a RETURN. The probe placed its exit call before the last RETURN only,
found none, and the run recorded zero transformed records ("the probe found no
call site"; the tangent gate never ran). Rule (B20 RULES.md R10): with no RETURN
the exit call goes before the routine's closing END or END SUBROUTINE. Canaries:
a routine with a RETURN keeps the call before the LAST RETURN (an early RETURN
is a path that did not converge), and a text with no UMAT is still reported as
having no call site.
"""
import pytest

from umat_oti.abaqus.probe import FIXED, FREE, instrument

FIXED_NO_RETURN = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),TIME(2),
     2 PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+PROPS(1)*DSTRAN(I)
      END DO
%(CLOSE)s"""

FREE_NO_RETURN = """subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
    stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, ndi, nshr, ntens, nstatv, &
    props, nprops, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, noel, npt, layer, kspt, kstep, kinc)
  implicit none
  character(len=80) :: cmname
  integer :: ndi, nshr, ntens, nstatv, nprops, noel, npt, layer, kspt, kstep, kinc, i
  real(8) :: stress(ntens), statev(nstatv), ddsdde(ntens,ntens), sse, spd, scd, rpl, ddsddt(ntens)
  real(8) :: drplde(ntens), drpldt, stran(ntens), dstran(ntens), time(2), dtime, temp, dtemp
  real(8) :: predef(1), dpred(1), props(nprops), coords(3), drot(3,3), pnewdt, celent
  real(8) :: dfgrd0(3,3), dfgrd1(3,3)
  do i = 1, ntens
    stress(i) = stress(i) + props(1)*dstran(i)
  end do
%(CLOSE)s"""


def _statements_after_the_exit_call(text):
    """The non-blank lines after the exit call that are not part of the call itself."""
    lines = text.splitlines()
    call = next(i for i, l in enumerate(lines) if "CALL OTIS_PROBE(" in l)
    rest = lines[call + 1:]
    # the call is a few continuation lines; stop at the first line that is not one
    index = 0
    while index < len(rest) and (rest[index].strip() == "" or
                                 (len(rest[index]) > 5 and rest[index][5] not in " \t"
                                  and rest[index][:5].strip() == "")
                                 or rest[index].rstrip().endswith("&") or lines[call + index].rstrip().endswith("&")):
        index += 1
    return [l.strip().lower() for l in rest[index:] if l.strip()]


@pytest.mark.parametrize("closing", ["      END\n", "      END SUBROUTINE UMAT\n"])
def test_a_fixed_form_umat_without_return_gets_its_exit_call(closing):
    text, ok = instrument(FIXED_NO_RETURN % {"CLOSE": closing}, "orig", form=FIXED)
    assert ok
    assert "CALL OTIS_PROBE(" in text and "CALL OTIS_PROBE_IN(" in text
    assert _statements_after_the_exit_call(text)[0].startswith("end")


@pytest.mark.parametrize("closing", ["end subroutine umat\n", "end\n"])
def test_a_free_form_umat_without_return_gets_its_exit_call(closing):
    text, ok = instrument(FREE_NO_RETURN % {"CLOSE": closing}, "orig", form=FREE)
    assert ok
    assert _statements_after_the_exit_call(text)[0].startswith("end")


def test_canary_a_routine_with_a_return_keeps_the_call_before_the_last_return():
    body = FIXED_NO_RETURN % {"CLOSE": "      RETURN\n      END\n"}
    text, ok = instrument(body, "orig", form=FIXED)
    assert ok
    assert _statements_after_the_exit_call(text)[0] == "return"


def test_canary_a_text_without_the_entry_routine_has_no_call_site():
    text, ok = instrument("      SUBROUTINE OTHER(A)\n      A = 1.D0\n      END\n", "orig")
    assert not ok
