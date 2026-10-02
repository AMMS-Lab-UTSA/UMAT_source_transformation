"""A callee published beside the UMAT is lifted, not refused.

The corpus transform was given one file. LallyLab's umat_MA_local.for calls
KPOLARDECOMP from kpolarDecomp.for in the same directory, and was refused
("DFGRD1_OTI is passed to KPOLARDECOMP, which was neither lifted, inlined, nor
transformed"). tools/transform_all.py now retries such a refusal with the
source's own repository as dependency root, widening one directory at a time
up to the repository root, and records which root resolved it. These tests
build a two-file "repository" and check that the retry happens, that it is
recorded, that the job-layout build compiles, and that a callee the
repository does not publish keeps its refusal. (The lifted callee's
arithmetic is the ordinary lifter's, checked elsewhere; the corpus sources
this unblocks are checked against FD of their originals in the B2 report.)
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

UMAT = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      CALL KSOFT(STRESS,DSTRAN,PROPS(1),NTENS)
      DO K=1,NTENS
        DO L=1,NTENS
          DDSDDE(K,L)=0.D0
        END DO
        DDSDDE(K,K)=PROPS(1)
      END DO
      RETURN
      END
"""

HELPER = """      SUBROUTINE KSOFT(S,DE,E,N)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION S(N),DE(N)
      DO K=1,N
        S(K)=S(K)+E*DE(K)/(1.D0+10.D0*DE(K)**2)
      END DO
      RETURN
      END
"""


def _item(path: Path):
    import transform_all as ta

    return ta.WorkItem(source_id=f"owner__repo/models/{path.name}", path=path, sha256="x",
                       ntens=6, stage="transformed")


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_callee_in_a_sibling_file_is_resolved_and_recorded(tmp_path, monkeypatch):
    import transform_all as ta

    cache = tmp_path / "cache"
    models = cache / "owner__repo" / "models"
    models.mkdir(parents=True)
    (models / "umat.for").write_text(UMAT)
    (models / "ksoft.for").write_text(HELPER)
    monkeypatch.setattr(ta, "DEFAULT_CACHE", cache)
    result = ta.transform_one(_item(models / "umat.for"), tmp_path / "work")
    assert result.ok, result.reason
    companions = result.metadata["published_companions"]
    assert companions["used_root"].endswith("models")
    assert result.metadata["compiled"], result.metadata.get("compile_error")


def test_a_callee_nobody_publishes_keeps_its_refusal(tmp_path, monkeypatch):
    import transform_all as ta

    cache = tmp_path / "cache"
    models = cache / "owner__repo" / "models"
    models.mkdir(parents=True)
    (models / "umat.for").write_text(UMAT)
    monkeypatch.setattr(ta, "DEFAULT_CACHE", cache)
    result = ta.transform_one(_item(models / "umat.for"), tmp_path / "work")
    assert not result.ok
    assert "KSOFT" in result.reason
    attempts = result.metadata["published_companions"]["attempts"]
    assert attempts and all(not attempt["success"] for attempt in attempts)
    # The search stopped at the repository root, never above it.
    assert all("owner__repo" in attempt["root"] for attempt in attempts)
