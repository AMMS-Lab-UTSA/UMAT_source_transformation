"""What a job directory has to be given before Abaqus compiles the UMAT in it.

The transform rewrites every INCLUDE it resolved to the output-relative path
``dependencies/<name>`` and writes the files there. A Fortran compiler opens a
relative INCLUDE from the directory of the file carrying it, so that reference
resolves for as long as the emitted source sits beside that directory -- and
stops the moment a COPY of it is compiled somewhere else. ``abaqus job=...
user=...`` is exactly that copy.

Measured on the store at fingerprint 650a66ab55825346: 238 of 238 entries carry
a ``dependencies/`` tree and 394 of their emitted include lines name a path
inside it, and the corpus verifier staged none of them. Every one of those jobs
died at

    transformed_user.f(15): error #5102:
        Cannot open include file 'dependencies/ABA_PARAM.INC'

before Abaqus reached its input processor. The type errors reported after it --
``#6549``/``#6355`` on a promoted ``*_OTI`` variable -- are that failure's
consequence, not a second defect: with the header gone the untransformed
scalars beside the promoted one lose ``IMPLICIT REAL*8(A-H,O-Z)``, so no
specific ``operator(**)`` in ``otim6n1`` matches and the compiler names the OTI
operand. Staging the tree alone removes both.

The header itself should never have been in the tree: it is the solver's, and
``dependency_bundle`` now leaves every ``INCLUDE 'aba_param.inc'`` (any case)
unrewritten for the job's include path to resolve. Staging the tree remains
necessary for the includes an author ships, which is what these tests pin.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

from umat_oti.abaqus.support import (
    DEPENDENCY_DIRECTORY, SupportBuild, build_support, compile_order,
    install_support, stage_dependencies)

pytestmark = pytest.mark.regression


def _transform_output(directory: Path, *, units=("m.f90",),
                      include: str = "dependencies/decls.inc") -> Path:
    """A directory shaped like one the transform wrote."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / DEPENDENCY_DIRECTORY).mkdir(exist_ok=True)
    (directory / DEPENDENCY_DIRECTORY / "decls.inc").write_text(
        "      IMPLICIT REAL*8(A-H,O-Z)\n", encoding="utf-8")
    for name in units:
        (directory / name).write_text("      END\n", encoding="utf-8")
    (directory / "u_oti.for").write_text(
        f"      SUBROUTINE U()\n      INCLUDE '{include}'\n      END\n",
        encoding="utf-8")
    (directory / "compile_order.txt").write_text(
        "".join(f"{name}\n" for name in units) + "u_oti.for\n", encoding="utf-8")
    return directory


def test_installing_the_support_also_stages_the_dependency_tree(tmp_path):
    """The environment file alone leaves the compile unable to open its include."""
    output = _transform_output(tmp_path / "out")
    job = tmp_path / "job"
    build = SupportBuild(objects=(job / "m.o",), include_dir=job, ok=True,
                         transform_dir=output)

    assert install_support(build, job) == job / "abaqus_v6.env"

    staged = job / DEPENDENCY_DIRECTORY / "decls.inc"
    assert staged.is_file(), "the job cannot open dependencies/decls.inc"
    assert staged.read_text() == (output / DEPENDENCY_DIRECTORY / "decls.inc").read_text()


def test_the_build_remembers_which_transform_its_units_came_from(tmp_path):
    """Read off the units, so a caller that already has them needs no change."""
    output = _transform_output(tmp_path / "out")
    units = compile_order(output, exclude=output / "u_oti.for")

    build = build_support(units, tmp_path / "job", abaqus="no-such-abaqus")

    assert not build.ok                       # nothing was compiled, on purpose
    assert build.transform_dir == output      # and it still says where from
    assert build.as_dict()["transform_dir"] == str(output)


def test_a_unit_staged_under_dependencies_still_names_its_transform(tmp_path):
    """A declared module source is compiled from inside ``dependencies/``."""
    output = tmp_path / "out"
    (output / DEPENDENCY_DIRECTORY).mkdir(parents=True)
    (output / DEPENDENCY_DIRECTORY / "flags.f90").write_text(
        "module flags\nend module flags\n", encoding="utf-8")
    (output / "compile_order.txt").write_text(
        "dependencies/flags.f90\n", encoding="utf-8")

    units = compile_order(output)

    assert [unit.name for unit in units] == ["flags.f90"]
    assert build_support(units, tmp_path / "job",
                         abaqus="no-such-abaqus").transform_dir == output


def test_a_failed_support_build_installs_nothing(tmp_path):
    """No environment file and no staging: the job is not going to run."""
    output = _transform_output(tmp_path / "out")
    job = tmp_path / "job"

    assert install_support(SupportBuild(reason="did not compile",
                                        transform_dir=output), job) is None
    assert not (job / DEPENDENCY_DIRECTORY).exists()


def test_staging_over_itself_neither_recurses_nor_fails(tmp_path):
    """The job directory IS the transform output in the single-directory path."""
    output = _transform_output(tmp_path / "out")

    assert stage_dependencies(output, output) == output / DEPENDENCY_DIRECTORY
    assert sorted(p.name for p in (output / DEPENDENCY_DIRECTORY).iterdir()) == [
        "decls.inc"]


def test_a_transform_without_dependencies_stages_nothing(tmp_path):
    """Most of the store predates the bundle; staging must not invent a directory."""
    output = tmp_path / "out"
    output.mkdir()

    assert stage_dependencies(output, tmp_path / "job") is None
    assert stage_dependencies(None, tmp_path / "job") is None
    assert not (tmp_path / "job" / DEPENDENCY_DIRECTORY).exists()


def test_staging_replaces_a_stale_copy_left_by_an_earlier_rung(tmp_path):
    """A job directory is reused; a stale include would be compiled in silence."""
    output = _transform_output(tmp_path / "out")
    job = tmp_path / "job"
    (job / DEPENDENCY_DIRECTORY).mkdir(parents=True)
    (job / DEPENDENCY_DIRECTORY / "decls.inc").write_text("stale\n", encoding="utf-8")

    stage_dependencies(output, job)

    assert (job / DEPENDENCY_DIRECTORY / "decls.inc").read_text() != "stale\n"


@pytest.mark.fortran
@pytest.mark.slow
def test_the_emitted_entry_source_compiles_in_a_staged_job_directory(tmp_path):
    """The whole defect, end to end: transform a UMAT, then build it as a job does.

    The job directory holds a COPY of the entry source under the name the
    harness gives it, and whatever ``install_support`` puts there. The Abaqus
    parameter header is reached through an include path, which is where a real
    job finds it -- never beside the source.
    """
    from umat_oti.corpus.cli import _write_aba_param_stub
    from umat_oti.services.jacobian_request import run_jacobian_transform

    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "umat.for"
    source.write_text(
        "      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,\n"
        "     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,\n"
        "     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,\n"
        "     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)\n"
        "      INCLUDE 'ABA_PARAM.INC'\n"
        "      INCLUDE 'material.inc'\n"
        "      CHARACTER*80 CMNAME\n"
        "      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),\n"
        "     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),\n"
        "     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),\n"
        "     3 DFGRD0(3,3),DFGRD1(3,3)\n"
        "      EMOD=PROPS(1)*SCALE\n"
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
    # An include the author ships beside the source: the bundler stages it
    # and rewrites the reference to dependencies/material.inc. The stub the
    # harness drops beside a staged source is there too, and must NOT be
    # staged: the solver's header is reached on its include path.
    (inputs / "material.inc").write_text(
        "      PARAMETER (SCALE=1.0D0)\n", encoding="utf-8")
    _write_aba_param_stub(inputs)

    output = tmp_path / "out"
    run = run_jacobian_transform(source, output, ntens=6)
    assert run.succeeded, run.report
    entry = Path(run.transformed_source)
    emitted = entry.read_text()
    assert "INCLUDE 'dependencies/material.inc'" in emitted, (
        "this test is only about a transform whose includes were rewritten")
    assert "DEPENDENCIES/ABA_PARAM" not in emitted.upper(), (
        "the solver's header is never rewritten into the artefact")

    # A job directory: the entry source under the harness's name, the support
    # units compiled there, and whatever install_support brings.
    job = tmp_path / "job"
    job.mkdir()
    units = compile_order(output, exclude=entry)
    shutil.copy2(entry, job / "transformed_user.f")
    build = SupportBuild(objects=(), include_dir=job, ok=True, transform_dir=output)
    install_support(build, job)

    headers = tmp_path / "headers"
    headers.mkdir()
    _write_aba_param_stub(headers)
    for unit in units:
        built = subprocess.run(
            ["gfortran", "-c", "-ffree-form", "-ffree-line-length-none",
             f"-I{headers}", str(unit), "-J", str(job), "-o",
             str(job / f"{unit.stem}.o")],
            cwd=job, capture_output=True, text=True)
        assert built.returncode == 0, built.stderr

    built = subprocess.run(
        ["gfortran", "-c", "-ffixed-form", "-ffixed-line-length-none",
         f"-I{headers}", f"-I{job}", "transformed_user.f",
         "-J", str(job), "-o", str(job / "transformed_user.o")],
        cwd=job, capture_output=True, text=True)

    assert built.returncode == 0, built.stdout + built.stderr
    assert "Cannot open include file" not in built.stderr
    assert (job / "transformed_user.o").is_file()
