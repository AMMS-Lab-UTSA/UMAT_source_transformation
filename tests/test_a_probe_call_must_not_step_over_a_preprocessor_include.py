"""Abaqus compiles user subroutines with -fpp, so a source may carry #include.

``Worlthen/array_with_two_pixel_z.for`` pulls in Abaqus's own public header
between the Fortran INCLUDE and the type declarations::

          INCLUDE 'ABA_PARAM.INC'
    #include <SMAAspUserSubroutines.hdr>
    C
          CHARACTER*80 CMNAME

``_is_executable_line`` says a ``#include`` runs, because it begins with none
of the keywords that declare. So the probe call was inserted above it, which
put the header's INTERFACE blocks and every declaration after them into the
executable section. Recompiled here with the exact flags from
``corpus_run/pass9/work/284fb12379dea8b621d13b6e/original/original.com``, the
pass9 file fails with eleven copies of

    error #6236: A specification statement cannot appear in the executable
    section

Abaqus stopped before writing a .dat, .msg or .odb -- the run left no record of
any kind -- and the entry was recorded as ``original_job_failed``: the author's
code blamed for where this module put a line.
"""
import pytest

from umat_oti.abaqus.probe import _first_executable, _routine_span, instrument

pytestmark = pytest.mark.unit

WITH_DIRECTIVE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
C
      INCLUDE 'ABA_PARAM.INC'
#include <SMAAspUserSubroutines.hdr>
C
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV)
      STRESS(1) = 0.D0
      RETURN
      END
"""


def _line(text, index):
    return text.splitlines()[index]


def test_the_first_executable_line_is_below_the_preprocessor_directive():
    lines = WITH_DIRECTIVE.splitlines()
    start, end = _routine_span(lines, "UMAT")
    where = _first_executable(lines, start, end)
    assert lines[where].strip() == "STRESS(1) = 0.D0"


def test_a_directive_is_not_an_executable_statement():
    lines = WITH_DIRECTIVE.splitlines()
    start, end = _routine_span(lines, "UMAT")
    where = _first_executable(lines, start, end)
    assert not lines[where].lstrip().startswith("#")


def test_the_instrumented_source_keeps_every_declaration_above_its_first_call():
    """The probe call has to land after the header and after CHARACTER and
    DIMENSION, or the file is not a Fortran program unit any more."""
    text, changed = instrument(WITH_DIRECTIVE, "original")
    assert changed
    lines = text.splitlines()
    call = next(i for i, line in enumerate(lines)
                if "OTIS_PROBE_IN" in line and not line.lstrip().startswith("C"))
    above = "\n".join(lines[:call])
    assert "#include <SMAAspUserSubroutines.hdr>" in above
    assert "CHARACTER*80 CMNAME" in above
    assert "DIMENSION STRESS(NTENS)" in above


@pytest.mark.fortran
def test_the_instrumented_source_compiles_where_the_pass9_one_did_not():
    """Compiled with the pass9 flags, the instrumented file returns 0 and the
    pass9 artefact returns 1 with eleven #6236 errors."""
    import os
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    ifort = shutil.which("ifort")
    if ifort is None:
        pytest.skip("no ifort on PATH")
    source = Path("/home/ammslab3/softwarex_work/discovery_cache/"
                  "Worlthen__20220314-abqus-simulation/abaqus/original/"
                  "array_with_two_pixel_z.for")
    include = Path("/usr/SIMULIA/EstProducts/2021/SMAUsubs/PublicInterfaces")
    if not source.exists() or not include.exists():
        pytest.skip("the corpus source or the Abaqus headers are not here")
    text, _ = instrument(source.read_text(errors="replace"), "original")
    with tempfile.TemporaryDirectory() as work:
        shim = Path(work) / "inc"
        shim.mkdir()
        for header in include.iterdir():
            (shim / header.name).symlink_to(header)
            (shim / header.name.upper()).symlink_to(header)
        target = Path(work) / "probed.f"
        target.write_text(text)
        finished = subprocess.run(
            [ifort, "-c", "-fpp", "-fPIC", "-extend-source", "-DABQ_LNX86_64",
             "-DABQ_FORTRAN", "-auto", "-pc64", "-fp-model", "precise",
             f"-I{shim}", "-o", str(Path(work) / "probed.o"), str(target)],
            capture_output=True, text=True, cwd=work)
        assert finished.returncode == 0, finished.stdout + finished.stderr
        assert "6236" not in finished.stdout + finished.stderr
