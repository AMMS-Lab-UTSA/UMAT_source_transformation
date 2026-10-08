"""A UMAT may own a variable called MAX; the emitted SQRT guard must not call it.

The transform guards SQRT against a round-off negative argument with
``MAX(REAL(x), 1.0D-30)``. mholla's umat_ortho_stretch declares a variable MAX,
so in that scope the emitted call would index the author's variable, and the
transform refused the source. Rule (B20 RULES.md R5): when the author declares
MAX, the guard is spelled without a call, (x + c + |x - c|)/2, and the generic
import is renamed so the author's variable is untouched. Canary: a source that
uses the intrinsic keeps the call form.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from _b20_support import transform_text, failed_checks

HEAD = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      REAL*8 EMOD, S2, PEAK
%(DECL)s      EMOD = PROPS(1)
%(INIT)s      DO I=1,NTENS
        IF (ABS(DSTRAN(I)).GT.PEAK) PEAK = ABS(DSTRAN(I))
      END DO
      S2 = SQRT(EMOD*(DSTRAN(1)**2+DSTRAN(2)**2) + 1.D-3)
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+EMOD*DSTRAN(I)*(1.D0+S2*PEAK)
      END DO
      DO I=1,NTENS
        DO J=1,NTENS
          DDSDDE(I,J)=0.D0
        END DO
        DDSDDE(I,I)=EMOD
      END DO
      RETURN
      END
"""
def _owns_max():
    text = HEAD % {"DECL": "", "INIT": "      PEAK = 0.D0\n"}
    return re.sub(r"\bPEAK\b", "MAX", text)


def _uses_the_intrinsic():
    text = HEAD % {"DECL": "", "INIT": "      PEAK = 0.D0\n"}
    return text.replace("S2*PEAK", "S2*MAX(PEAK,1.D0)")


def test_the_guard_is_written_without_a_call_when_the_author_owns_max(tmp_path):
    report = transform_text(tmp_path, _owns_max(), ".for")
    assert report["transform_success"], failed_checks(report)
    emitted = Path(report["transformed_source"]).read_text()
    assert "0.5D0*(REAL(" in emitted and "+ ABS(REAL(" in emitted
    assert not re.search(r"MAX\s*\(\s*REAL\(", emitted)
    if shutil.which("gfortran"):
        shutil.copy(tmp_path / "ABA_PARAM.INC", tmp_path / "out" / "ABA_PARAM.INC")
        done = subprocess.run([str(tmp_path / "out" / "compile_hint.sh")], cwd=tmp_path / "out",
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr[-800:]


def test_canary_a_source_that_uses_the_intrinsic_keeps_the_call_form(tmp_path):
    report = transform_text(tmp_path, _uses_the_intrinsic(), ".for")
    assert report["transform_success"], failed_checks(report)
    emitted = Path(report["transformed_source"]).read_text()
    assert re.search(r"MAX\s*\(\s*REAL\(", emitted)
