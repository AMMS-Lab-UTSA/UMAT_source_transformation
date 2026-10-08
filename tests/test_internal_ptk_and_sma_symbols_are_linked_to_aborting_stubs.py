"""B20 rule H3: Abaqus-internal PTK / SMA symbols are linked to stubs that give them no semantics.

Worlthen ``array_with_two_pixel_z.for`` holds UEPACTIVATIONSETUP / UEPACTIVATIONVOL (PTK toolpath) and a UMAT
that assigns ``ptrb=SMAFloatArrayAccess(1)`` and never reads the pointee. The replay driver did not link.
A stub never invents a result: a SUBROUTINE or FUNCTION that is entered stops the run with status 8; the
two ``*ArrayAccess`` functions return the null address, so a pointee read crashes.
"""
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")

HEAD = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      INTEGER*8 PTRB
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
"""
BODY = """      DO I=1,NTENS
        STRESS(I) = STRESS(I) + PROPS(1)*DSTRAN(I)
        DO J=1,NTENS
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      STATEV(1) = STATEV(1) + 1.D0
      RETURN
      END
"""
#: only linked: the UMAT takes an address it never uses; a PTK routine sits in a routine nobody calls here
DEAD = HEAD + "      PTRB = SMAFLOATARRAYACCESS(1)\n" + BODY + """      SUBROUTINE UEPACTIVATIONSETUP(LOP)
      CALL PTKSETMESHANDEVENTSERIES(LOP)
      CALL GETPARAMETERTABLE(LOP)
      RETURN
      END
"""
#: PLANTED ERROR: the UMAT path itself enters an Abaqus-internal routine
ENTERED = HEAD + "      CALL PTKCOMPUTE(NOEL)\n" + BODY


def _check(tmp_path, text, monkeypatch):
    import umat_oti.abaqus.replay as R
    import verify_store_in_abaqus as V
    real = R.build_history_replay

    def no_ifort(source, work_dir, **kw):
        if kw.get("compiler") == "ifort":
            b = R.HistoryBuild(label=kw["label"], compiler="ifort", flags=())
            b.reason = "ifort is not on PATH"
            return b
        return real(source, work_dir, **kw)
    monkeypatch.setattr(R, "build_history_replay", no_ifort)
    source = tmp_path / "original_probed.for"
    source.write_text(text)
    include = tmp_path / "inc"
    include.mkdir()
    for name in ("aba_param.inc", "ABA_PARAM.INC"):
        (include / name).write_text("      implicit real*8(a-h,o-z)\n")
    entry = {"NTENS": 6, "NSTATV": 1, "NPROPS": 1, "NDI": 3, "NSHR": 3,
             "DTIME": [1.0], "TIME": [0.0, 0.0], "STRESS0": [0.0] * 6,
             "STATEV0": [0.0], "STRAN": [0.0] * 6, "DSTRAN": [1e-3] * 6,
             "PROPS": [10.0], "COORDS": [0.0, 0.0, 0.0, 1.0], "NOEL": 1}
    return V.init_variant_check(source, [entry, entry], tmp_path / "work", ntens=6,
                                include_dirs=[include])


def test_symbols_that_are_only_linked_let_the_replay_complete(tmp_path, monkeypatch):
    check = _check(tmp_path, DEAD, monkeypatch)
    assert check["established"], check
    assert not (check["undefined"]["STRESS"] or check["undefined"]["DDSDDE"])


def test_a_stubbed_routine_that_is_entered_stops_the_run_with_status_8(tmp_path, monkeypatch):
    check = _check(tmp_path, ENTERED, monkeypatch)
    assert not check["established"], check
    assert "did not replay" in check["reason"] or "stopped" in check["reason"]
    assert check["zero"]["returncode"] == 8 and "PTKCOMPUTE" in check["zero"]["tail"]


def test_a_source_that_defines_its_own_array_access_gets_no_second_definition(tmp_path, monkeypatch):
    own = DEAD.replace("      INTEGER*8 PTRB\n", "      INTEGER*8 PTRB, SMAFLOATARRAYACCESS\n") + """      FUNCTION SMAFLOATARRAYACCESS(ID)
      INTEGER*8 SMAFLOATARRAYACCESS
      SMAFLOATARRAYACCESS = 0
      RETURN
      END
"""
    check = _check(tmp_path, own, monkeypatch)
    assert check["established"], check
