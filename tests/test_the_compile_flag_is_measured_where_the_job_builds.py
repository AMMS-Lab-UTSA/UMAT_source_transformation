"""Where ``compiled: true`` was measured, and why the place is the claim.

``transform_all`` used to record ``compiled`` from the transform's own
``--compile`` check, which runs inside the output directory. Everything the
transform wrote is to hand there: the contract, the reports, the ABA_PARAM.INC
stub it dropped for gfortran, and the ``dependencies/`` tree whose files the
emitted INCLUDEs name. A job directory holds a copy of the entry source, the
units in ``compile_order.txt``, and the Abaqus header on an include path.

Those are different file sets and they gave different answers. At fingerprint
650a66ab55825346 all 238 stored entries were recorded ``compiled: true`` while
the emitted source could not open ``dependencies/ABA_PARAM.INC`` in the
directory a job compiles it in. The flag was true of a directory nobody
builds in.

So the check moved to the job's file set, and the flag now says which layout
it was measured in. These tests pin the disagreement itself: a source that can
only be built because a file happens to sit in the output directory is not
recorded as compiling.
"""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from transform_all import (                                       # noqa: E402
    JOB_LAYOUT, WorkItem, compiled_cleanly, job_layout_compile, transform_one)

pytestmark = pytest.mark.regression


HINT = """#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
OBJDIR=${OBJDIR:-.}
mkdir -p -- "$OBJDIR"
gfortran -c -ffixed-form -ffixed-line-length-none -I. -I"$OBJDIR" "u_oti.for" \
  -J"$OBJDIR" -o "$OBJDIR/transformed_umat.o"
"""


def _output_directory(directory: Path, include: str) -> Path:
    """A transform output whose one generated unit includes ``include``."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "dependencies").mkdir(exist_ok=True)
    (directory / "dependencies" / "decls.inc").write_text(
        "      IMPLICIT REAL*8(A-H,O-Z)\n", encoding="utf-8")
    # Present in the output directory, and in no job directory: the transform
    # dropped it there for its own check.
    (directory / "scratch_only.inc").write_text(
        "      IMPLICIT REAL*8(A-H,O-Z)\n", encoding="utf-8")
    (directory / "u_oti.for").write_text(
        f"      SUBROUTINE U(X)\n      INCLUDE '{include}'\n"
        "      X=X+1.D0\n      RETURN\n      END\n", encoding="utf-8")
    (directory / "compile_order.txt").write_text("u_oti.for\n", encoding="utf-8")
    script = directory / "compile_hint.sh"
    script.write_text(HINT, encoding="utf-8")
    script.chmod(0o755)
    return directory


def _builds_in_place(directory: Path) -> bool:
    """What the old instrument asked: does it build in the output directory?"""
    done = subprocess.run([str(directory / "compile_hint.sh")], cwd=directory,
                          capture_output=True, text=True)
    return done.returncode == 0


@pytest.mark.fortran
def test_a_unit_that_only_builds_in_the_output_directory_is_not_recorded_compiled(tmp_path):
    """The disagreement, made into an assertion in both directions."""
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    output = _output_directory(tmp_path / "out", include="scratch_only.inc")

    assert _builds_in_place(output), (
        "the fixture is only meaningful if the old check would have passed it")

    result = job_layout_compile(output, tmp_path / "work")

    assert result["layout"] == JOB_LAYOUT
    assert result["status"] == "compile_failed"
    assert not compiled_cleanly({"compilation": result})
    assert "scratch_only.inc" in result["stderr"]


@pytest.mark.fortran
def test_an_include_the_transform_staged_is_carried_into_the_job_layout(tmp_path):
    """The other direction: ``dependencies/`` is part of the artefact, so it goes."""
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    output = _output_directory(tmp_path / "out", include="dependencies/decls.inc")

    result = job_layout_compile(output, tmp_path / "work")

    assert result["status"] == "compiled", result.get("stderr")
    assert compiled_cleanly({"compilation": result})
    staged = Path(result["directory"])
    assert (staged / "dependencies" / "decls.inc").is_file()
    # And nothing else from the output directory: the check is only honest
    # while the file set it builds over is the file set a job is given.
    assert sorted(path.name for path in staged.iterdir()) == [
        "compile_hint.sh", "dependencies", "u_oti.for"]


@pytest.mark.fortran
def test_the_header_is_reached_by_include_path_not_by_sitting_beside_the_source(tmp_path):
    """A job is given ABA_PARAM.INC with ``-I``; so is this check."""
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    output = _output_directory(tmp_path / "out", include="ABA_PARAM.INC")
    from umat_oti.corpus.cli import _write_aba_param_stub
    _write_aba_param_stub(output)

    result = job_layout_compile(output, tmp_path / "work")

    assert result["status"] == "compiled", result.get("stderr")
    staged = Path(result["directory"])
    assert not (staged / "ABA_PARAM.INC").exists(), (
        "the header must not be in the directory the source is compiled in")


def test_a_transform_with_nothing_to_build_is_not_recorded_as_having_built(tmp_path):
    """A check that could not run is not a check that passed."""
    empty = tmp_path / "out"
    empty.mkdir()

    result = job_layout_compile(empty, tmp_path / "work")

    assert result["status"] == "no_build_script"
    assert not compiled_cleanly({"compilation": result})


def test_a_compile_order_naming_a_file_that_is_not_there_fails_the_check(tmp_path):
    """The job would be given a file set with a hole in it; say so, do not build."""
    output = _output_directory(tmp_path / "out", include="dependencies/decls.inc")
    (output / "compile_order.txt").write_text("gone.f90\nu_oti.for\n", encoding="utf-8")

    result = job_layout_compile(output, tmp_path / "work")

    assert result["status"] == "unit_missing"
    assert "gone.f90" in result["stderr"]
    assert not compiled_cleanly({"compilation": result})


@pytest.mark.fortran
@pytest.mark.slow
def test_the_stored_flag_says_which_layout_it_was_measured_in(tmp_path):
    """End to end: the recorded metadata carries the job-layout answer."""
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    from umat_oti.corpus.cli import _write_aba_param_stub

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "umat.for"
    source.write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,\n"
        "     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,\n"
        "     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,\n"
        "     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)\n"
        "      INCLUDE 'ABA_PARAM.INC'\n"
        "      CHARACTER*80 CMNAME\n"
        "      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),\n"
        "     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),\n"
        "     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),\n"
        "     3 DFGRD0(3,3),DFGRD1(3,3)\n"
        "      EMOD=PROPS(1)\n"
        "      DO K1=1,NTENS\n"
        "        STRESS(K1)=STRESS(K1)+EMOD*DSTRAN(K1)\n"
        "      END DO\n"
        "      DO K1=1,NTENS\n"
        "        DO K2=1,NTENS\n"
        "          DDSDDE(K1,K2)=0.D0\n"
        "        END DO\n"
        "        DDSDDE(K1,K1)=EMOD\n"
        "      END DO\n"
        "      RETURN\n"
        "      END\n", encoding="utf-8")
    _write_aba_param_stub(inputs)

    item = WorkItem(source_id="fixture__tiny/umat.for", path=source,
                    sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    ntens=6)
    result = transform_one(item, tmp_path / "work")

    assert result.ok, result.reason
    metadata = result.metadata or {}
    assert metadata["compile_layout"] == JOB_LAYOUT, (
        "the flag a reader takes for 'this builds' must name the layout it "
        "was measured in")
    assert metadata["compiled"] is True, metadata.get("compile_error")
    # Kept beside it so a future divergence between the two is in the data.
    assert "compiled_in_output_dir" in metadata
