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
    assert "  802 IF (REAL(IFLAG_OTI).EQ.1) THEN" in lines
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
