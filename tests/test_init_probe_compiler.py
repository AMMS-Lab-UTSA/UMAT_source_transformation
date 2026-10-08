"""B17 rule G2a: the D-12 init probe is built the way the solver builds the original.

The primary probe is ifort with the Abaqus flags and -init=zero/huge/minus_huge;
the gfortran set is the secondary and decides only where the primary could not be
built or run. A source that really reads an uninitialised variable must still be
flagged, under either compiler, and a clean source must not be.
"""
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

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
"""
CLEAN = HEAD + """      DO I=1,NTENS
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
#: PLANTED ERROR: UNSET is never assigned and reaches STRESS(1) and DDSDDE(1,1).
UNINIT = HEAD + """      DO I=1,NTENS
        STRESS(I) = STRESS(I) + PROPS(1)*DSTRAN(I)
        DO J=1,NTENS
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      STRESS(1) = STRESS(1) + UNSET
      DDSDDE(1,1) = DDSDDE(1,1) + UNSET
      STATEV(1) = STATEV(1) + 1.D0
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
    entry = {"NTENS": 6, "NSTATV": 1, "NPROPS": 1, "NDI": 3, "NSHR": 3,
             "DTIME": [1.0], "TIME": [0.0, 0.0], "STRESS0": [0.0] * 6,
             "STATEV0": [0.0], "STRAN": [0.0] * 6, "DSTRAN": [1e-3] * 6,
             "PROPS": [10.0], "COORDS": [0.0, 0.0, 0.0, 1.0]}
    return V.init_variant_check(source, [entry, entry], tmp_path / "work", ntens=6,
                                include_dirs=[include])


needs_ifort = pytest.mark.skipif(shutil.which("ifort") is None, reason="needs ifort")
needs_gfortran = pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")


@needs_ifort
def test_the_primary_probe_is_the_solvers_compiler_and_flags_a_real_uninitialised_read(tmp_path):
    check = _check(tmp_path, UNINIT)
    assert check["established"], check
    assert check["decided_by"] == "ifort"
    assert "ifort" in check["pair"]
    assert check["undefined"]["STRESS"] == [1]
    assert 1 in check["undefined"]["DDSDDE"]


@needs_ifort
@needs_gfortran
def test_a_clean_source_is_not_flagged_and_the_two_probes_agree(tmp_path):
    check = _check(tmp_path, CLEAN)
    assert check["established"], check
    assert check["decided_by"] == "ifort"
    assert not (check["undefined"]["STRESS"] or check["undefined"]["DDSDDE"]
                or check["undefined"]["STATEV"])
    assert check["probe_agreement"]["agree"]
    assert check["secondary"]["established"]


@needs_ifort
@needs_gfortran
def test_the_secondary_probe_agrees_on_the_planted_error(tmp_path):
    check = _check(tmp_path, UNINIT)
    assert check["probe_agreement"]["agree"]
    assert check["secondary"]["undefined"]["STRESS"] == [1]


@needs_gfortran
def test_where_the_primary_cannot_be_built_the_gfortran_set_decides(tmp_path, monkeypatch):
    import umat_oti.abaqus.replay as R
    real = R.build_history_replay

    def no_ifort(source, work_dir, **kw):
        if kw.get("compiler") == "ifort":
            b = R.HistoryBuild(label=kw["label"], compiler="ifort", flags=())
            b.reason = "ifort is not on PATH"
            return b
        return real(source, work_dir, **kw)
    monkeypatch.setattr(R, "build_history_replay", no_ifort)
    check = _check(tmp_path, UNINIT)
    assert check["established"], check
    assert check["decided_by"] == "gfortran"
    assert "ifort is not on PATH" in check["primary_failure"]
    assert check["undefined"]["STRESS"] == [1]
