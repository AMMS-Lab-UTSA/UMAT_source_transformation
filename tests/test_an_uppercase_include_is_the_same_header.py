"""``#INCLUDE <SMAASPUSERSUBROUTINES.HDR>`` is not a broken source.

``victorlefevre/UMAT_Lefevre_Sozio_Lopez-Pamies`` writes that at its own lines
848 and 1233. Abaqus 2021 ships the file as ``SMAAspUserSubroutines.hdr`` and
carries no uppercase variant anywhere in the installation, so on a
case-sensitive filesystem ``-fpp`` cannot resolve it, the build fails before
Abaqus writes a .dat or a .msg or an .odb, and pass9 recorded the entry as
``original_job_failed`` -- which reads as a verdict on the author's science.

Measured through Abaqus's own compile line, ``abaqus make library=``:

    without the shim   klp.f(848):  #error: can't find include file: SMAASPU...
                       klp.f(1233): #error: can't find include file: SMAASPU...
                       Abaqus Error: Problem during compilation
    with the shim      no errors, klp-std.o produced

The source is identical in both runs. What changed is the directory the
compiler was allowed to look in, and the shipped ``-I`` paths are still there
and still searched first for anything they hold.

This also records why the Fortran ``INCLUDE 'ABA_PARAM.INC'`` in 54 verified
entries never had this problem: the ``INCLUDE`` statement and the preprocessor
``#include`` are resolved by different machinery, and only one of them cares.
"""
import os
import subprocess
from pathlib import Path

import pytest

from umat_oti.abaqus import include_shim, runner


def test_every_shipped_header_answers_to_its_uppercase_name(tmp_path):
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "SMAAspUserSubroutines.hdr").write_text("      integer x\n")
    (shipped / "aba_param.inc").write_text("      implicit real*8(a-h,o-z)\n")

    shim = include_shim.build(tmp_path / "work", roots=(str(shipped),))
    for name in ("SMAAspUserSubroutines.hdr", "SMAASPUSERSUBROUTINES.HDR",
                 "aba_param.inc", "ABA_PARAM.INC"):
        assert (shim / name).is_symlink(), name
    # each link resolves to the shipped file itself, not to a copy that could
    # drift from what Abaqus actually compiles against.
    assert (shim / "SMAASPUSERSUBROUTINES.HDR").resolve() == \
        (shipped / "SMAAspUserSubroutines.hdr").resolve()
    assert (shim / "ABA_PARAM.INC").read_text() == \
        (shipped / "aba_param.inc").read_text()


def test_a_name_that_is_already_lowercase_only_gets_one_link(tmp_path):
    """``ABA_PARAM.INC`` upper-cased is itself; linking it twice would raise."""
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "ABA_PARAM.INC").write_text("x\n")
    shim = include_shim.build(tmp_path / "work", roots=(str(shipped),))
    assert sorted(p.name for p in shim.iterdir()) == ["ABA_PARAM.INC"]


def test_the_first_directory_wins_a_name_the_second_repeats(tmp_path):
    """Abaqus lists two include directories and they share filenames. The
    shipped ``-I`` order decides which one wins; the shim must not invert it."""
    first, second = tmp_path / "one", tmp_path / "two"
    for d in (first, second):
        d.mkdir()
    (first / "shared.hdr").write_text("first\n")
    (second / "shared.hdr").write_text("second\n")
    shim = include_shim.build(tmp_path / "work",
                              roots=(str(first), str(second)))
    assert (shim / "shared.hdr").read_text() == "first\n"
    assert (shim / "SHARED.HDR").read_text() == "first\n"


def test_no_shipped_headers_means_no_flag_rather_than_an_empty_directory(tmp_path):
    """Pointing the compiler at an empty directory would change which of two
    identically named headers wins. Finding nothing must change nothing."""
    assert include_shim.build(tmp_path / "work",
                              roots=(str(tmp_path / "absent"),)) is None
    assert include_shim.install(tmp_path / "work",
                                roots=(str(tmp_path / "absent"),)) is None
    assert not (tmp_path / "work" / include_shim.ENVIRONMENT_FILE).exists()


def test_the_environment_file_keeps_the_shipped_flags_and_leaves_P_last(tmp_path):
    """``%P`` is the source file and ifort wants it last. The shipped ``-I``
    directories are kept, so nothing that resolved before stops resolving."""
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "SMAAspUserSubroutines.hdr").write_text("x\n")
    shim = include_shim.install(tmp_path / "work", roots=(str(shipped),))
    text = (tmp_path / "work" / include_shim.ENVIRONMENT_FILE).read_text()

    namespace = {"compile_fortran": ["ifort", "-c", "-fpp", "-I%I", "%P"]}
    exec(compile(text, "abaqus_v6.env", "exec"), namespace)
    got = namespace["compile_fortran"]
    assert got[-1] == "%P"
    assert "-I%I" in got
    assert f"-I{shim.resolve()}" in got
    assert got.index(f"-I{shim.resolve()}") == len(got) - 2


def test_a_callers_own_environment_file_is_added_to_and_not_replaced(tmp_path):
    """It may carry settings of its own, and trading a silent build difference
    for another silent build difference is not a fix."""
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "SMAAspUserSubroutines.hdr").write_text("x\n")
    work = tmp_path / "work"
    work.mkdir()
    where = work / include_shim.ENVIRONMENT_FILE
    where.write_text("cpus = 4\n")

    include_shim.install(work, roots=(str(shipped),))
    text = where.read_text()
    assert text.startswith("cpus = 4\n")

    # and installing twice does not append the same flag twice
    include_shim.install(work, roots=(str(shipped),))
    assert where.read_text().count("include_any_case") == text.count("include_any_case")


def test_running_a_job_installs_the_shim_before_abaqus_compiles(tmp_path, monkeypatch):
    """The wiring, not the module: a run that supplies user source must leave
    the environment file behind, or the shim helps nothing that actually runs."""
    shipped = tmp_path / "shipped"
    shipped.mkdir()
    (shipped / "SMAAspUserSubroutines.hdr").write_text("x\n")
    monkeypatch.setenv("UMAT_OTI_ABAQUS_HEADERS", str(shipped))

    seen = {}

    def _no_abaqus(command, **kwargs):
        seen["command"] = command
        raise OSError("no abaqus here")

    monkeypatch.setattr(runner.subprocess, "run", _no_abaqus)
    source = tmp_path / "u.f"
    source.write_text("      SUBROUTINE UMAT\n      END\n")
    work = tmp_path / "work"
    runner.run_job(work, "j", "*HEADING\n", user_source=source)

    assert (work / include_shim.ENVIRONMENT_FILE).exists()
    assert (work / include_shim.SHIM_DIRECTORY
            / "SMAASPUSERSUBROUTINES.HDR").is_symlink()


@pytest.mark.abaqus
def test_the_file_that_failed_compiles_unmodified_through_abaqus(tmp_path):
    """The measurement itself, against Abaqus's own compile line."""
    cache = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                 or Path.home() / "softwarex_work" / "discovery_cache")
    source = (cache / "victorlefevre__UMAT_Lefevre_Sozio_Lopez-Pamies"
              / "Examples" / "C3D8H" / "UT kappa_mu=1" / "UMAT_KLP_RK5_hybrid.f")
    if not source.exists():
        pytest.skip(f"{source} is not on this machine")
    if runner.abaqus_command() is None:
        pytest.skip("no abaqus on this machine")

    text = source.read_text(errors="replace")
    assert "#INCLUDE <SMAASPUSERSUBROUTINES.HDR>" in text

    def _compile(where):
        (where / "klp.f").write_text(text)
        finished = subprocess.run(
            [runner.abaqus_command(), "make", "library=klp.f"],
            cwd=str(where), capture_output=True, text=True, timeout=600)
        return finished.stdout + finished.stderr

    bare = tmp_path / "bare"
    bare.mkdir()
    before = _compile(bare)
    assert "can't find include file" in before

    shimmed = tmp_path / "shimmed"
    shimmed.mkdir()
    include_shim.install(shimmed)
    after = _compile(shimmed)
    assert "can't find include file" not in after
    assert "Problem during compilation" not in after
    assert list(shimmed.glob("klp*.o")), after[-2000:]
