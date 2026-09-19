"""Two transformer defects the slide-8 benchmark reproduction exposed (2026-09-18).

1. A labelled IF whose condition reads a promoted variable, ``  802 IF
   (IFLAG.EQ.1) THEN``, was rebuilt from its statement segment and re-prefixed
   with the line's leading blanks only: the label its GOTO targets was dropped
   and the statement began inside the label field, so the combined user file of
   UMAT_PCL, PCLI, PCLI_R and PCLK did not compile in Abaqus.
2. A source that keeps the elastic stiffness in DDSDDE and forms the predictor
   stress from it had the inputs of those DDSDDE writes (ELAM, EBULK3) classed
   "feeds only the old tangent" and their assignments skipped, while the kept
   predictor block still read them: the transformed UMAT_VPDCL and UMAT_NKH_1.02
   returned a stress that differed from the original's by a hydrostatic offset.

Both are checked on the committed benchmark contracts, the second against the
ORIGINAL source compiled separately and replayed along the same strain path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

from umat_oti.cli_json import run_config_transform
from umat_oti.validation.parameter_sensitivity_validation import (
    ABA_PARAM, build_original_driver, driver_source, replay,
)

REPO = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.regression, pytest.mark.fortran]


def _transform(name: str, out: Path) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        summary, code = run_config_transform(REPO / "benchmarks" / f"{name}.json", out)
    assert code == 0 and summary["transform_success"], summary.get("blockers")
    return summary


@pytest.mark.parametrize("name", ["UMAT_PCL", "UMAT_PCLK"])
def test_a_labelled_promoted_branch_keeps_its_label_and_compiles(name, tmp_path):
    if not shutil.which("gfortran"):
        pytest.fail("gfortran is required for this regression")
    summary = _transform(name, tmp_path / "t")
    lines = Path(summary["transformed_source"]).read_text().splitlines()
    # IFLAG is an INTEGER (implicit I-N) and is no longer promoted, so the
    # branch keeps its original text; the label must survive either way. The
    # rewrite of a labelled branch whose condition does read a promoted value
    # is pinned by test_a_labelled_branch_on_a_promoted_real_keeps_its_label.
    assert "  802 IF (IFLAG.EQ.1) THEN" in lines
    combined = next((tmp_path / "t").glob("*_oti_combined.f90"))
    for include in ("aba_param.inc", "ABA_PARAM.INC"):
        (tmp_path / "t" / include).write_text(ABA_PARAM)
    compiled = subprocess.run(["gfortran", "-fsyntax-only", "-ffree-line-length-none", "-I", ".",
                               combined.name], cwd=tmp_path / "t", capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr[-2000:]


@pytest.mark.parametrize("name,props1", [("UMAT_VPDCL", 1.0), ("UMAT_NKH_1.02", 0.0)])
def test_predictor_inputs_stay_live_and_the_primal_matches_the_original(name, props1, tmp_path):
    if not shutil.which("gfortran"):
        pytest.fail("gfortran is required for this regression")
    summary = _transform(name, tmp_path / "t")
    text = Path(summary["transformed_source"]).read_text()
    assert "OTIS-SKIP: ELAM=(EBULK3-EG2)/THREE" not in text
    source = REPO / "UMATs" / "UMATs" / "ICP" / f"{name}.for"
    ntens, nstatv, nprops = 4, 48, 24
    # the paired-validation probe (unit constants); NKH takes PROPS(1)=0 so the
    # temperature comes from TEMP, because with PROPS(1)=1 it reads DTHTA unset
    props = [props1] + [1.0] * (nprops - 1)
    path = [[7.5e-4, -3.0e-4, 0.0, 0.0]] * 4
    original = replay(build_original_driver(source, tmp_path / "original", ntens=ntens,
                                            nstatv=nstatv, nprops=nprops),
                      props, path, ntens=ntens, nstatv=nstatv)
    work = tmp_path / "transformed"
    work.mkdir()
    for include in ("aba_param.inc", "ABA_PARAM.INC"):
        (work / include).write_text(ABA_PARAM)
    (work / "driver.f90").write_text(driver_source(ntens=ntens, nstatv=nstatv, nprops=nprops))
    combined = next((tmp_path / "t").glob("*_oti_combined.f90"))
    subprocess.run(["gfortran", "-O0", "-ffree-line-length-none", "-I", str(work), "-c", str(combined),
                    "-o", "umat.o"], cwd=work, check=True, capture_output=True, text=True)
    subprocess.run(["gfortran", "driver.f90", "umat.o", "-o", "driver"], cwd=work, check=True,
                   capture_output=True, text=True)
    transformed = replay(work / "driver", props, path, ntens=ntens, nstatv=nstatv)
    scale = max(abs(v) for row in original.stress for v in row)
    worst = max(abs(a - b) for ra, rb in zip(original.stress, transformed.stress) for a, b in zip(ra, rb))
    assert worst <= 1e-12 * scale, (worst, scale)


LABELLED_BRANCH_UMAT = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      EMOD = PROPS(1)
      SEFF = STRESS(1) + EMOD*DSTRAN(1)
      IF (DSTRAN(1) .LT. 0.D0) GOTO 802
      SEFF = 1.01D0*SEFF
  802 IF (SEFF .GT. PROPS(2)) THEN
        SEFF = PROPS(2) + 0.1D0*(SEFF - PROPS(2))
      END IF
      STRESS(1) = SEFF
      DO K1 = 2, NTENS
        STRESS(K1) = STRESS(K1) + EMOD*DSTRAN(K1)
      END DO
      DDSDDE(1,1) = EMOD
      RETURN
      END
"""


def test_a_labelled_branch_on_a_promoted_real_keeps_its_label(tmp_path):
    """The case the label fix was written for, on a value that IS promoted.

    SEFF is REAL and on the stress path, so the condition of the branch the
    GOTO targets reads its shadow and the statement is rebuilt; label 802 has
    to stay in columns 1-5 or the GOTO has no target and the file does not
    compile.
    """
    if not shutil.which("gfortran"):
        pytest.fail("gfortran is required for this regression")
    from umat_oti.app.engine import _build_contract
    from umat_oti.corpus.cli import _write_aba_param_stub
    from umat_oti.services.transformation import TransformationOptions, run_transformation
    work = tmp_path / "work"
    work.mkdir()
    source = work / "labelled.for"
    source.write_text(LABELLED_BRANCH_UMAT)
    _write_aba_param_stub(work)
    config, _finite = _build_contract("labelled", "auto", "STRESS", "DDSDDE", 6, 1, source)
    (work / "contract.json").write_text(json.dumps(config))
    out = work / "out"
    out.mkdir()
    _write_aba_param_stub(out)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        report, _code = run_transformation(work / "contract.json", out,
                                           TransformationOptions(compile_generated=True))
    assert report.get("transform_success"), report.get("blockers")
    lines = Path(report["transformed_source"]).read_text().splitlines()
    labelled = [line for line in lines if line[:5].strip() == "802"]
    assert labelled and "SEFF_OTI" in labelled[0], labelled
    assert (report.get("compilation") or {}).get("status") == "compiled", \
        str((report.get("compilation") or {}).get("stderr"))[-2000:]

