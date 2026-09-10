"""Eight corpus sources are free-form Fortran in a file named ``.f`` or ``.for``.

``RafalMichalczyk__PavementDesign/Subroutines/umat_gmaxwell.for`` opens with
``subroutine umat(stress,... &`` in column 1. Compiled as fixed form -- which is
what the suffix said -- ifort rejects line 1 with "Illegal character in
statement label field", the compile aborts before the analysis starts, and the
job leaves no ``.sta``, no ``.msg`` and no ``.odb``. The ladder read that as
the ORIGINAL failing to run.

So the form is declared first, measured second and named last, and the measure
only wins when it is unambiguous and repeated. 336 of the 391 sources are
genuinely fixed form; a rule that rescued eight at their expense would be a bad
trade, and the last test here is the one that would catch it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.fortran.normalize import (detect_source_form,  # noqa: E402
                                        form_evidence)

FREE_IN_A_DOT_FOR = """\
subroutine umat(stress,statev,ddsdde,sse,spd,scd, &
    rpl,ddsddt,drplde,drpldt,stran,dstran, &
    time,dtime,temp,dtemp,predef,dpred,materl,ndi,nshr,ntens, &
    nstatv,props,nprops,coords,drot,pnewdt,celent, &
    dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc)
  implicit none
  return
end subroutine
"""

FIXED = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP)
      INCLUDE 'ABA_PARAM.INC'
      RETURN
      END
"""

TAB_INDENTED_FREE = (
    "Subroutine UMAT(STRESS, STATEV, DDSDDE, SSE, SPD, SCD, RPL, &\r\n"
    "\t\t\t\tDRPLDT, STRAN, DSTRAN, TIME, DTIME)\r\n"
    "\t\t\t  SUM_rate = 0.0d0\r\n"
    "\t\t\t  IErateI = 1.0d0\r\n"
    "\t\t\t  return\r\n"
    "End Subroutine\r\n")


def test_a_free_form_source_named_dot_for_is_read_as_free():
    assert detect_source_form(Path("umat_gmaxwell.for"), FREE_IN_A_DOT_FOR) == "free"


def test_a_fixed_form_source_stays_fixed():
    assert detect_source_form(Path("umat.for"), FIXED) == "fixed"
    assert detect_source_form(Path("umat.f"), FIXED) == "fixed"


def test_a_tab_indented_statement_is_not_a_continuation_marker():
    """A tab in the first six columns makes column counting meaningless: ifort
    treats it as "the statement starts here", which is neither a label field
    nor a marker. Counting such lines as fixed-form evidence read 34 tab-
    indented statements in UMAT_SSMCWStrainRates_Zambrano.for as continuations
    and outvoted the 608 lines that could only be free form."""
    evidence = form_evidence(TAB_INDENTED_FREE)
    assert evidence["fixed"] == 0, evidence
    assert evidence["free"] >= 2
    assert detect_source_form(Path("x.for"), TAB_INDENTED_FREE) == "free"


def test_a_declared_form_outranks_everything():
    assert detect_source_form(Path("x.f90"), "!DIR$ FIXEDFORM\n" + FIXED) == "fixed"
    assert detect_source_form(Path("x.for"), "!DEC$ FREEFORM\n" + FREE_IN_A_DOT_FOR) == "free"


def test_one_ambiguous_line_does_not_outrank_the_suffix():
    """Two independent lines saying the same thing is not a typo; one is."""
    nearly = FIXED + "     &\n"
    assert detect_source_form(Path("x.for"), nearly) == "fixed"


def test_every_cached_fixed_form_source_is_still_read_as_fixed():
    """The trade this rule must not make, measured on the corpus itself."""
    cache = Path(__file__).resolve().parents[2] / "discovery_cache"
    if not cache.is_dir():
        import pytest
        pytest.skip("the corpus cache is not on this machine")
    fixed_form_markers = 0
    for source in sorted(cache.rglob("*.for"))[:400]:
        text = source.read_text(errors="replace")
        evidence = form_evidence(text)
        if evidence["fixed"] >= 5 and evidence["free"] == 0:
            fixed_form_markers += 1
            assert detect_source_form(source, text) == "fixed", source
    assert fixed_form_markers > 20, "the corpus scan found almost nothing"
