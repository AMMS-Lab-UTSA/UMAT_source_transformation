"""Vera B10 conditions on include staging (Gauss).

A. A quad replay stages each INCLUDE promoted as its source is; a linked
   double-precision include would make the quad reference mixed-precision.
B. An absolute or ``..`` INCLUDE is refused, not staged; every staged file
   carries the sha256 of the author's file and of what was staged.
"""
import hashlib
import shutil
from pathlib import Path

import pytest

from umat_oti.abaqus import include_shim
from umat_oti.corpus_features.drivers import quadify

pytestmark = pytest.mark.unit


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_absolute_and_parent_includes_are_refused(tmp_path):
    author = tmp_path / "repo" / "src"
    author.mkdir(parents=True)
    (tmp_path / "repo" / "up.inc").write_text("      U = 1\n")
    (tmp_path / "abs.inc").write_text("      A = 1\n")
    shim = tmp_path / "shim"
    shim.mkdir()
    text = (f"      INCLUDE '{tmp_path / 'abs.inc'}'\n"
            "      INCLUDE '../up.inc'\n")
    staged = include_shim.stage_includes(text, [author], shim)
    assert [s["found"] for s in staged] == [False, False]
    assert all(s["refused"] for s in staged)
    assert "absolute" in staged[0]["reason"] and ".." in staged[1]["reason"]
    assert list(shim.iterdir()) == []


def test_a_staged_include_records_its_sha256_and_its_own_includes(tmp_path):
    author = tmp_path / "a"
    author.mkdir()
    outer = "      INCLUDE 'inner.inc'\n      REAL*8 X\n"
    (author / "outer.inc").write_text(outer)
    (author / "inner.inc").write_text("      REAL*8 Y\n")
    shim = tmp_path / "s"
    shim.mkdir()
    staged = include_shim.stage_includes("      INCLUDE 'outer.inc'\n", [author], shim)
    by = {s["include"]: s for s in staged}
    assert set(by) == {"outer.inc", "inner.inc"}
    assert by["outer.inc"]["sha256"] == _sha(outer) == by["outer.inc"]["staged_sha256"]
    assert by["outer.inc"]["staged_as"] == "link"
    assert (shim / "inner.inc").is_file()


def test_the_abaqus_header_beside_a_source_is_never_linked(tmp_path):
    author = tmp_path / "a"
    author.mkdir()
    (author / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    shim = tmp_path / "s"
    shim.mkdir()
    assert include_shim.stage_includes("      INCLUDE 'ABA_PARAM.INC'\n", [author], shim) == []
    assert not (shim / "ABA_PARAM.INC").exists()


def test_a_converted_include_is_a_promoted_copy_not_a_link(tmp_path):
    author = tmp_path / "a"
    author.mkdir()
    original = "      DOUBLE PRECISION E\n      PARAMETER (E=2.1D5)\n"
    (author / "PARAM_UMAT.INC").write_text(original)
    shim = tmp_path / "s"
    shim.mkdir()
    (record,) = include_shim.stage_includes("      INCLUDE 'PARAM_UMAT.INC'\n", [author], shim,
                                            convert=quadify, conversion="quadify")
    staged = shim / "PARAM_UMAT.INC"
    assert not staged.is_symlink()
    assert staged.read_text() == quadify(original) != original
    assert record["staged_as"] == "converted copy"
    assert record["sha256"] == _sha(original)
    assert record["staged_sha256"] == _sha(quadify(original))
    assert (author / "PARAM_UMAT.INC").read_text() == original      # author's file untouched


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_the_quad_replay_compiles_the_promoted_include(tmp_path):
    from umat_oti.abaqus.replay import build_replay
    author = tmp_path / "repo"
    author.mkdir()
    (author / "model.inc").write_text("      DOUBLE PRECISION EMOD\n      PARAMETER (EMOD=1.0D3)\n")
    source = author / "umat.f"
    source.write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,\n"
        "     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,\n"
        "     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,\n"
        "     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)\n"
        "      INCLUDE 'ABA_PARAM.INC'\n"
        "      INCLUDE 'model.inc'\n"
        "      CHARACTER*80 CMNAME\n"
        "      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS)\n"
        "      DIMENSION DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS)\n"
        "      DIMENSION DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1)\n"
        "      DIMENSION PROPS(NPROPS),COORDS(3),DROT(3,3)\n"
        "      DIMENSION DFGRD0(3,3),DFGRD1(3,3)\n"
        "      DO I=1,NTENS\n"
        "        STRESS(I)=STRESS(I)+EMOD*DSTRAN(I)\n"
        "        DDSDDE(I,I)=EMOD\n"
        "      END DO\n"
        "      RETURN\n"
        "      END\n")
    build = build_replay(source, tmp_path / "quad", quad=True)
    assert build.ok, build.reason + build.log
    (record,) = build.includes
    assert record["staged_as"] == "converted copy"
    assert "REAL*16" in (tmp_path / "quad" / "model.inc").read_text().upper() \
        or "REAL(16)" in (tmp_path / "quad" / "model.inc").read_text().upper()
    double = build_replay(source, tmp_path / "double")
    assert double.ok and double.includes[0]["staged_as"] == "link"
