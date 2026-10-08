"""B20 rule H3b: the gfortran replay build does for a source what ifort -fpp does for it in the solver.

Worlthen ``array_with_two_pixel_z.for`` `#include`s Abaqus headers in single quotes and declares a Cray pointer;
gfortran's preprocessor takes neither, so the tangent replay "did not link" for all four chosen states. A source
with neither gets exactly the flags it had.
"""
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from umat_oti.abaqus.replay import build_replay, requote_cpp_includes  # noqa: E402

HEAD = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
#include 'aba_param.inc'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
"""
BODY = """      DO I=1,NTENS
        STRESS(I)=STRESS(I)+PROPS(1)*DSTRAN(I)
        DO J=1,NTENS
          DDSDDE(I,J)=0.D0
        END DO
        DDSDDE(I,I)=PROPS(1)
      END DO
      RETURN
      END
"""
CRAY = HEAD + "      real*8 b(*)\n      integer*8 ptrb\n      pointer(ptrb,b)\n" + BODY
PLAIN = HEAD + BODY


def test_flags_are_added_only_for_the_text_that_needs_them(tmp_path):
    import verify_store_in_abaqus as V
    cray = tmp_path / "cray.for"; cray.write_text(CRAY)
    plain = tmp_path / "plain.for"; plain.write_text("      SUBROUTINE UMAT\n      RETURN\n      END\n")
    both = V.replay_flags("fixed", tmp_path, cray)
    assert "-cpp" in both and "-fcray-pointer" in both
    assert V.replay_flags("fixed", tmp_path, plain) == V.replay_flags("fixed", tmp_path)   # unchanged
    assert V.replay_extension_flags(None) == ()


def test_single_quoted_include_names_are_double_quoted_and_nothing_else_changes():
    text = "      X = 1\n#include 'aba_param.inc'\n      Y = 'abc'\n"
    new, note = requote_cpp_includes(text)
    assert new == '      X = 1\n#include "aba_param.inc"\n      Y = \'abc\'\n' and "double-quoted" in note
    assert requote_cpp_includes("      X = 1\n") == ("      X = 1\n", "")


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_a_source_with_a_single_quoted_include_and_a_cray_pointer_builds(tmp_path):
    import verify_store_in_abaqus as V
    src = tmp_path / "umat.for"
    src.write_text(CRAY)
    built = build_replay(src, tmp_path / "w", name="T", flags=V.replay_flags("fixed", tmp_path / "w", src))
    assert built.ok, built.reason


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_the_same_source_without_the_flags_does_not_build(tmp_path):
    # PLANTED ERROR: the old flags (no -cpp, no -fcray-pointer) cannot build this text
    import verify_store_in_abaqus as V
    src = tmp_path / "umat.for"
    src.write_text(CRAY)
    old = V.replay_flags("fixed", tmp_path / "w")
    built = build_replay(src, tmp_path / "w", name="T", flags=old)
    assert not built.ok
