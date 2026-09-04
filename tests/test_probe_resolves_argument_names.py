"""The probe must call an argument what the routine calls it.

The Abaqus UMAT interface is positional. Position 23 is the state-variable
count; the manual spells it NSTATV and half this corpus spells it NSTATEV.
A probe that names NSTATV inside a routine declaring NSTATEV names something
the routine never declared -- and under ABA_PARAM.INC that is an implicitly
typed INTEGER with no value, so ``(STATEV(I),I=1,NSTATV)`` walks off the end
of the array. Abaqus dies with a segmentation fault inside the formatted
WRITE, in a stack whose top frame is otis_probe_in, and the row is recorded
as a failure of somebody's UMAT.

Measured over the 251 sources of one gate run: 125 spell it NSTATEV, and 157
rename at least one interface argument.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.probe import (UMAT_INTERFACE, argument_order,  # noqa: E402
                                   entry_call, probe_call, resolved_arguments)

FIXED = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATEV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      RETURN
      END
"""

FREE = """subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, &
     ddsddt, drplde, drpldt, stran, dstran, time, dtime, temp, dtemp, &
     predef, dpred, cmname, ndi, nshr, ntens, nstatv, props, nprops, &
     coords, drot, pnewdt, celent, dfgrd0, dfgrd1, noel, npt, layer, &
     kspt, kstep, kinc)
end subroutine
"""


def _lines(text):
    return text.splitlines(keepends=True)


# ---- reading the interface ----------------------------------------------
def test_a_fixed_form_signature_is_read_in_order():
    order = argument_order(_lines(FIXED), 0)
    assert len(order) == len(UMAT_INTERFACE)
    assert order[0] == "STRESS" and order[-1] == "KINC"
    assert order[22] == "NSTATEV"


def test_a_free_form_signature_is_read_in_order():
    """Reading a `&`-continued line as fixed form drops six characters,
    turning COORDS into OORDS and PREDEF into REDEF: every argument after it
    keeps its position while losing its name."""
    order = argument_order(_lines(FREE), 0)
    assert len(order) == len(UMAT_INTERFACE)
    assert "COORDS" in order and "OORDS" not in order
    assert "PREDEF" in order and "REDEF" not in order
    assert order[22] == "NSTATV"


def test_the_continuation_marker_is_not_read_as_an_argument():
    """A fixed-form continuation carries a mark in column 6. Counting it
    shifts every later position by one, which is worse than not resolving."""
    assert "1" not in argument_order(_lines(FIXED), 0)
    assert "2" not in argument_order(_lines(FIXED), 0)


# ---- resolution ----------------------------------------------------------
def test_the_source_s_own_spelling_wins():
    assert resolved_arguments(_lines(FIXED), 0)["NSTATV"] == "NSTATEV"


def test_a_canonical_source_resolves_to_itself():
    names = resolved_arguments(_lines(FREE), 0)
    assert names["NSTATV"] == "NSTATV" and names["COORDS"] == "COORDS"


def test_an_unparsed_opener_falls_back_rather_than_guessing():
    """A short list means the opener was not parsed. Resolving positionally
    against it would map arguments to the wrong names; the canonical
    spellings are what the probe used before and are the safe fallback."""
    names = resolved_arguments(_lines("      SUBROUTINE UMAT(A,B,C)\n"), 0)
    assert names == {name: name for name in UMAT_INTERFACE}


# ---- what the emitted call says -----------------------------------------
def test_the_entry_call_uses_the_resolved_names():
    call = entry_call("T", names=resolved_arguments(_lines(FIXED), 0))
    assert "NSTATEV" in call
    assert ",NSTATV," not in call


def test_the_exit_call_uses_them_too():
    call = probe_call("T", names=resolved_arguments(_lines(FIXED), 0))
    assert "NSTATEV" in call and ",NSTATV," not in call


def test_no_names_keeps_the_canonical_spellings():
    """Callers that pass nothing must behave exactly as before."""
    assert "NSTATV" in entry_call("T")
    assert "NSTATV" in probe_call("T")


def test_the_continuation_marker_stays_in_column_six():
    for call in (entry_call("T"), probe_call("T")):
        for line in call.splitlines()[1:]:
            assert line[:5] == "     " and line[5:6].strip()
