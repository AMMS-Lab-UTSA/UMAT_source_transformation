"""The solver's parameter header is the solver's: never staged, never rewritten.

Between pass16 (fingerprint dbe9f928191e1d43) and pass17 (650a66ab55825346)
the dependency bundler began resolving ``INCLUDE 'ABA_PARAM.INC'`` against the
gfortran stub the corpus driver drops beside a staged source, copying the stub
into ``dependencies/`` and rewriting the include to
``dependencies/ABA_PARAM.INC``. In an Abaqus job directory that path does not
exist, and 141 of 234 verification rows ended at

    transformed_user.f(10): error #5102:
        Cannot open include file 'dependencies/ABA_PARAM.INC'

-- including 31 rows that had been ``verified`` in pass16. Staging the stub
into the job would also have been wrong: it is not Abaqus's header (it lacks
``parameter (nprecd=2)``).

These tests are behavioural: the emitted source compiles in a directory that
holds only what a job holds, with the header reached on an include path.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from transform_all import (
    HARNESS_ERROR,
    JOB_LAYOUT,
    WorkItem,
    job_layout_compile,
    strip_build_byproducts,
    transform_one,
)

from umat_oti.transform.dependency_bundle import (
    bundle_sources,
    is_runtime_header,
)

pytestmark = pytest.mark.regression

UMAT = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      EMOD=PROPS(1)
      DO K1=1,NTENS
        STRESS(K1)=STRESS(K1)+EMOD*DSTRAN(K1)
      END DO
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=0.D0
        END DO
        DDSDDE(K1,K1)=EMOD
      END DO
      RETURN
      END
"""


def _stub(directory: Path) -> None:
    from umat_oti.corpus.cli import _write_aba_param_stub
    _write_aba_param_stub(directory)


@pytest.mark.parametrize("name", ["ABA_PARAM.INC", "aba_param.inc",
                                  "Aba_Param.Inc", "sub/aba_param.inc"])
def test_every_spelling_of_the_header_is_the_runtime_header(name):
    assert is_runtime_header(name)


def test_an_authors_include_is_not_the_runtime_header():
    assert not is_runtime_header("aba_param_local.inc")
    assert not is_runtime_header("material.inc")


def test_the_bundler_leaves_the_header_where_the_solver_puts_it(tmp_path):
    """A stub beside the source is not a dependency of the source."""
    inputs = tmp_path / "in"
    inputs.mkdir()
    (inputs / "umat.for").write_text(
        UMAT.replace("      CHARACTER*80 CMNAME\n",
                     "      INCLUDE 'material.inc'\n      CHARACTER*80 CMNAME\n"),
        encoding="utf-8")
    (inputs / "material.inc").write_text("      PARAMETER (S=1.0D0)\n",
                                         encoding="utf-8")
    _stub(inputs)
    out = tmp_path / "out"

    staged, manifest = bundle_sources([inputs / "umat.for"], out)

    names = sorted(p.name for p in (out / "dependencies").iterdir())
    assert names == ["material.inc", "umat.for"]
    text = staged[(inputs / "umat.for").resolve()].read_text()
    assert "INCLUDE 'ABA_PARAM.INC'" in text
    assert "INCLUDE 'dependencies/material.inc'" in text
    import json
    record = json.loads(manifest.read_text())
    assert [r["include"] for r in record["runtime_includes"]] == ["ABA_PARAM.INC"]
    assert record["source_includes_complete"] is True


@pytest.mark.fortran
@pytest.mark.slow
def test_the_stored_entry_compiles_in_a_bare_job_directory(tmp_path):
    """End to end through transform_all: what is stored builds where a job builds.

    The job directory gets a COPY of the entry source and the support units,
    and NOT the transform's dependencies tree -- the pass17 verifier staged
    none, and a source with no author includes must not need one. The header
    is on -I only.
    """
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "umat.for"
    source.write_text(UMAT, encoding="utf-8")
    _stub(inputs)
    item = WorkItem(source_id="fixture__plain/umat.for", path=source,
                    sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    ntens=6)

    result = transform_one(item, tmp_path / "work")

    assert result.ok, result.reason
    assert result.metadata["compiled"] is True, result.metadata["compile_error"]
    assert result.metadata["compile_layout"] == JOB_LAYOUT
    out = Path(result.out_dir)
    # Nothing compiler-specific and no stub is left in what gets stored.
    leftovers = [p.name for p in out.rglob("*")
                 if p.suffix in (".o", ".mod") or p.name.lower() == "aba_param.inc"]
    assert leftovers == []

    job, headers = tmp_path / "job", tmp_path / "headers"
    job.mkdir()
    headers.mkdir()
    _stub(headers)
    units = [line.strip() for line in
             (out / "compile_order.txt").read_text().splitlines() if line.strip()]
    entry = Path(result.entry_source)
    for unit in units:
        if (out / unit).resolve() == entry.resolve():
            continue
        built = subprocess.run(
            ["gfortran", "-c", "-ffree-form", "-ffree-line-length-none",
             str(out / unit), "-J", str(job), "-o", str(job / (Path(unit).stem + ".o"))],
            cwd=job, capture_output=True, text=True)
        assert built.returncode == 0, built.stderr
    shutil.copy2(entry, job / "transformed_user.f")
    built = subprocess.run(
        ["gfortran", "-c", "-ffixed-form", "-ffixed-line-length-none",
         f"-I{headers}", f"-I{job}", "transformed_user.f", "-J", str(job),
         "-o", str(job / "transformed_user.o")],
        cwd=job, capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    assert not (job / "dependencies").exists()


def test_an_authors_own_header_copy_is_not_stripped(tmp_path):
    """Only the driver's stub is a by-product; a file with other text is not."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "aba_param.inc").write_text("      implicit real*8(a-h,o-z)\n"
                                       "      parameter (nprecd=2)\n")
    _stub(tmp_path)
    shutil.copy2(tmp_path / "ABA_PARAM.INC", out / "ABA_PARAM.INC")
    (out / "m.mod").write_text("x")
    (out / "dependencies").mkdir()
    (out / "dependencies" / "u.o").write_text("x")
    (out / "u.f90").write_text("end\n")

    removed = strip_build_byproducts(out)

    assert sorted(removed) == ["ABA_PARAM.INC", "dependencies/u.o", "m.mod"]
    assert (out / "aba_param.inc").is_file()
    assert (out / "u.f90").is_file()


@pytest.mark.fortran
def test_a_relative_work_directory_still_builds(tmp_path, monkeypatch):
    """The check used to run its script by a path relative to the wrong cwd."""
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    out = tmp_path / "out"
    out.mkdir()
    (out / "u.for").write_text("      SUBROUTINE U(X)\n      INCLUDE 'ABA_PARAM.INC'\n"
                               "      X=X+1.D0\n      END\n")
    (out / "compile_order.txt").write_text("u.for\n")
    script = out / "compile_hint.sh"
    script.write_text('#!/usr/bin/env bash\nset -e\ncd -- "$(dirname -- "$0")"\n'
                      'gfortran -c -ffixed-form -I. -I"$OBJDIR" u.for -o "$OBJDIR/u.o"\n')
    script.chmod(0o755)
    monkeypatch.chdir(tmp_path)

    result = job_layout_compile(out, Path("work"))

    assert result["status"] == "compiled", result.get("stderr")


def test_a_build_that_could_not_start_is_not_a_compile_failure(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "u.for").write_text("      END\n")
    (out / "compile_order.txt").write_text("u.for\n")
    (out / "compile_hint.sh").write_text("#!/nonexistent/interpreter\n")

    result = job_layout_compile(out, tmp_path / "work")

    assert result["status"] == HARNESS_ERROR
