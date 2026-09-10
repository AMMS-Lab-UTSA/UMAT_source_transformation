"""Free form is not a dialect of fixed form.

A continuation marked in column 6 is a syntax error in free form, and a
statement beginning in column 1 is a label field in fixed form. The probe was
written in fixed form and appended to whatever it was given, so every free-form
source in the corpus produced a file ifort rejected -- and a job whose compile
aborts writes no ``.sta``, no ``.msg`` and no ``.odb``, which the ladder read as
"the ORIGINAL did not run".

Fifty-five of the corpus's 391 sources are free form. Before this, not one of
them had ever reached Abaqus: every one sat at ``acquired``, ``transformed`` or
``not_a_umat``, and none had a result about its model.

These tests compile both forms with a real compiler, so a probe that parses in
Python but not in Fortran cannot pass them.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.probe import (PROBE_SOURCE, entry_call,  # noqa: E402
                                   free_form, instrument, probe_call)

pytestmark = pytest.mark.fortran

FREE_UMAT = """\
subroutine umat(stress, statev, ddsdde, sse, spd, scd, &
                rpl, ddsddt, drplde, drpldt, &
                stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, &
                ndi, nshr, ntens, nstatv, props, nprops, coords, drot, pnewdt, &
                celent, dfgrd0, dfgrd1, noel, npt, layer, kspt, kstep, kinc)
  implicit none
  character(len=80) :: cmname
  integer :: ndi, nshr, ntens, nstatv, nprops, noel, npt, layer, kspt
  integer :: kstep, kinc
  double precision :: stress(ntens), statev(nstatv), ddsdde(ntens, ntens)
  double precision :: sse, spd, scd, rpl, drpldt, dtime, temp, dtemp, pnewdt
  double precision :: celent
  double precision :: ddsddt(ntens), drplde(ntens), stran(ntens), dstran(ntens)
  double precision :: time(2), predef(1), dpred(1), props(nprops), coords(3)
  double precision :: drot(3, 3), dfgrd0(3, 3), dfgrd1(3, 3)
  integer :: i
  ! a comment that starts indented, which the column-1 rule missed
  do i = 1, ntens
    stress(i) = stress(i) + props(1) * dstran(i)
  end do
  return
end subroutine umat
"""


def gfortran():
    found = shutil.which("gfortran")
    if found is None:
        pytest.skip("gfortran is not on PATH")
    return found


def compiles(path: Path, work: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [gfortran(), "-c", "-ffixed-line-length-132", "-ffree-line-length-none",
         "-std=legacy", "-w", str(path), "-o", str(work / "unit.o"),
         f"-J{work}"],
        capture_output=True, text=True, cwd=str(work))


def test_the_fixed_form_probe_compiles(tmp_path):
    unit = tmp_path / "probe.f"
    unit.write_text(PROBE_SOURCE, encoding="utf-8")
    done = compiles(unit, tmp_path)
    assert done.returncode == 0, done.stderr


def test_the_free_form_probe_compiles(tmp_path):
    unit = tmp_path / "probe.f90"
    unit.write_text(free_form(PROBE_SOURCE), encoding="utf-8")
    done = compiles(unit, tmp_path)
    assert done.returncode == 0, done.stderr


def test_a_free_form_umat_with_the_probe_compiles(tmp_path):
    """The whole point: instrumenting a free-form source produces free-form
    Fortran that a compiler accepts."""
    text, instrumented = instrument(FREE_UMAT, "original", form="free")
    assert instrumented, "the probe found no call site in a free-form routine"
    unit = tmp_path / "umat.f90"
    unit.write_text(text, encoding="utf-8")
    done = compiles(unit, tmp_path)
    assert done.returncode == 0, done.stderr


def test_the_same_source_as_fixed_form_does_not_compile(tmp_path):
    """The failure this fixes, demonstrated rather than described."""
    text, instrumented = instrument(FREE_UMAT, "original", form="fixed")
    assert instrumented
    unit = tmp_path / "umat.f"
    unit.write_text(text, encoding="utf-8")
    assert compiles(unit, tmp_path).returncode != 0


def test_the_free_form_calls_carry_no_column_six_marker():
    for text in (probe_call("t", indent="  ", form="free"),
                 entry_call("t", indent="  ", form="free")):
        lines = text.splitlines()
        assert len(lines) > 1
        for line in lines[:-1]:
            assert line.rstrip().endswith("&"), line
        for line in lines[1:]:
            assert not line.startswith("     1"), line


def test_the_fixed_form_calls_keep_their_column_six_marker():
    for text in (probe_call("t"), entry_call("t")):
        for line in text.splitlines()[1:]:
            assert len(line) > 5 and line[5] not in " \t", line
            assert not line[:5].strip(), line
