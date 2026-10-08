"""B17 rule G2d: a poisoned build stopped by the author's own check is undefined_in_original.

A guard on an uninitialised value (ISNAN, a plain STOP, XIT) that ends the poisoned replay
while the zero build completes is a use of the undefined value; a trap, a signal, a driver
limit or a stop that completes every call establishes nothing.
"""
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from umat_oti.abaqus.replay import stopped_by_the_authors_check

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))


def run(rc=0, calls=5, ok=False, tail=""):
    return SimpleNamespace(ok=ok, returncode=rc, calls=[{}] * calls, tail=tail)


def test_a_plain_stop_an_xit_and_an_abqerr_are_the_authors():
    assert stopped_by_the_authors_check(run(0), 140)
    assert stopped_by_the_authors_check(run(3), 140)
    assert stopped_by_the_authors_check(run(5), 140)
    # gfortran's trailing note about flags is not a trap
    assert stopped_by_the_authors_check(run(0, tail="Note: The following floating-point "
                                           "exceptions are signalling: IEEE_INVALID_FLAG"), 140)


def test_a_planted_ieee_trap_a_signal_and_a_driver_limit_establish_nothing():
    assert not stopped_by_the_authors_check(run(-8), 140)                    # SIGFPE
    assert not stopped_by_the_authors_check(
        run(1, tail="forrtl: error (65): floating invalid"), 140)
    assert not stopped_by_the_authors_check(
        run(2, tail="Program received signal SIGFPE: Floating-point exception"), 140)
    assert not stopped_by_the_authors_check(
        run(2, tail="Fortran runtime error: End of record"), 140)
    for status in (4, 6, 7):
        assert not stopped_by_the_authors_check(run(status), 140)


def test_a_stop_that_completes_every_call_or_a_clean_run_is_not_a_stop():
    assert not stopped_by_the_authors_check(run(0, calls=140), 140)
    assert not stopped_by_the_authors_check(run(0, calls=140, ok=True), 140)


HEAD = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      DO I=1,NTENS
        STRESS(I) = STRESS(I) + PROPS(1)*DSTRAN(I)
        DO J=1,NTENS
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
"""
#: PLANTED ERROR: UNSET is never assigned; the author's NaN guard stops on it.
GUARDED = HEAD + """      R2 = UNSET*UNSET - UNSET*UNSET
      IF (ISNAN(R2)) THEN
        STOP
      END IF
      STATEV(1) = STATEV(1) + 1.D0
      RETURN
      END
"""
CLEAN = HEAD + """      STATEV(1) = STATEV(1) + 1.D0
      RETURN
      END
"""


def _check(tmp_path, text):
    import verify_store_in_abaqus as V
    source = tmp_path / "original_probed.for"
    source.write_text(text)
    include = tmp_path / "inc"
    include.mkdir()
    for name in ("aba_param.inc", "ABA_PARAM.INC"):
        (include / name).write_text("      implicit real*8(a-h,o-z)\n")
    entries = [{"NTENS": 6, "NSTATV": 1, "NPROPS": 1, "NDI": 3, "NSHR": 3,
                "DTIME": [1.0], "TIME": [0.0, 0.0], "STRESS0": [0.0] * 6,
                "STATEV0": [0.0], "STRAN": [0.0] * 6, "DSTRAN": [1e-3] * 6,
                "PROPS": [10.0], "COORDS": [0.0, 0.0, 0.0, 1.0]}] * 4
    return V.init_variant_check(source, entries, tmp_path / "work", ntens=6,
                                include_dirs=[include])


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_a_planted_author_isnan_guard_on_an_uninitialised_value_is_flagged(tmp_path, monkeypatch):
    # gfortran set only (ifort may be absent in CI): the probe falls back to it.
    import umat_oti.abaqus.replay as R
    real = R.build_history_replay

    def no_ifort(source, work_dir, **kw):
        if kw.get("compiler") == "ifort":
            b = R.HistoryBuild(label=kw["label"], compiler="ifort", flags=())
            b.reason = "ifort is not on PATH"
            return b
        return real(source, work_dir, **kw)
    monkeypatch.setattr(R, "build_history_replay", no_ifort)
    check = _check(tmp_path, GUARDED)
    assert check["established"], check
    assert check["undefined"]["STRESS"] == [1, 2, 3, 4, 5, 6], check["undefined"]
    assert check["author_guard_stops"][0]["variant"] in ("snan", "inf")


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_a_clean_source_with_the_same_structure_is_not_flagged(tmp_path):
    check = _check(tmp_path, CLEAN)
    assert check["established"], check
    assert not (check["undefined"]["STRESS"] or check["undefined"]["DDSDDE"])
    assert "author_guard_stops" not in check
