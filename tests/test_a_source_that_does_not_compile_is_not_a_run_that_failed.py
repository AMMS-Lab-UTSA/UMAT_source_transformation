"""A compile that aborts and a solver that fell over look identical from outside.

Neither writes a ``.sta``, a ``.msg`` or an ``.odb``. The ladder read both as
``original_job_failed`` -- a name that says this harness could not run the
model, when for seventeen corpus entries what happened is that the author
published a file that does not build.
``mholla__growth/umats/umat_neohooke.f`` line 40 ends
``noel,npt,kstep,kinc))``.

So the compiler is asked. The UNMODIFIED source is compiled with Abaqus's own
compile line -- no probe, no widened declaration, nothing this pipeline adds --
and the answer separates three findings that were one:

* the text is rejected: ``incomplete_or_corrupt_source``, terminal, external;
* a module or an include is not there: ``external_dependency_unavailable``,
  terminal, external, and the record names what is missing;
* it compiles: the ladder's own verdict about the run stands.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from umat_oti.abaqus.companions import (modules_defined, needs,  # noqa: E402
                                        repository_files, resolve)
from umat_oti.abaqus.support import DEPENDENCY_DIAGNOSTICS  # noqa: E402

BROKEN = """\
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,
     # rpl,ddsddt,drplde,drpldt,stran,dstran,time,dtime,temp,dtemp,
     # predef,dpred,cmname,ndi,nshr,ntens,nstatv,props,nprops,coords,
     # drot,pnewdt,celent,dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc))
      include 'aba_param.inc'
      return
      end
"""

USES_A_MODULE = """\
      subroutine umat(stress)
      use Tensor
      include 'ttb/ttb_library.f'
      return
      end
"""

DEFINES_THE_MODULE = """\
       module Tensor
       implicit none
       end module Tensor
"""


def test_a_module_defined_in_the_file_is_not_a_need():
    text = DEFINES_THE_MODULE + "\n      subroutine umat(s)\n      use Tensor\n      end\n"
    assert needs(text).modules == ()


def test_a_module_is_found_by_what_a_file_declares(tmp_path):
    """Not by its name. ``Tensor`` lives in ``ttb_library.f``."""
    (tmp_path / "ttb").mkdir()
    (tmp_path / "ttb" / "ttb_library.f").write_text(DEFINES_THE_MODULE)
    entry = tmp_path / "umat.f"
    entry.write_text(USES_A_MODULE)
    found = resolve(entry, [tmp_path / "ttb" / "ttb_library.f"])
    assert found.complete, found.reason()
    assert "ttb/ttb_library.f" in found.include_files


def test_a_file_pulled_in_by_include_is_not_also_compiled(tmp_path):
    """It is compiled as part of whatever includes it. Compiling it separately
    as well defines its module twice and the link fails on every symbol."""
    (tmp_path / "ttb").mkdir()
    library = tmp_path / "ttb" / "ttb_library.f"
    library.write_text(DEFINES_THE_MODULE)
    entry = tmp_path / "umat.f"
    entry.write_text(USES_A_MODULE)
    found = resolve(entry, [library])
    assert library not in found.order


def test_a_module_nothing_declares_is_named_in_the_reason(tmp_path):
    entry = tmp_path / "umat.f"
    entry.write_text("      subroutine umat(s)\n      use SolveMatrixEquation\n      end\n")
    found = resolve(entry, [])
    assert not found.complete
    assert found.missing_modules == ("SolveMatrixEquation",)
    assert "SolveMatrixEquation" in found.reason()


def test_abaqus_own_includes_are_not_needs():
    assert needs("      INCLUDE 'ABA_PARAM.INC'\n").includes == ()
    assert needs("      include 'aba_param.inc'\n").includes == ()


def test_a_module_declaration_is_found_in_fixed_form():
    """``       module Tensor`` starts in column 8. A whole-text pattern with
    ``^...$`` and no MULTILINE matched nothing, so every module in the corpus
    looked undefined."""
    assert modules_defined(DEFINES_THE_MODULE) == ("TENSOR",)


def test_the_search_is_scoped_to_the_source_own_repository(tmp_path):
    """More than one repository in this corpus defines a module called
    ``utils``, and compiling somebody else's is worse than compiling none."""
    mine = tmp_path / "owner__mine" / "src"
    theirs = tmp_path / "owner__theirs" / "src"
    for directory in (mine, theirs):
        directory.mkdir(parents=True)
        (directory / "helpers.f90").write_text("module utils\nend module utils\n")
    entry = mine / "umat.f"
    entry.write_text("      subroutine umat(s)\n      use utils\n      end\n")
    found = repository_files(entry, tmp_path)
    assert all("owner__theirs" not in str(path) for path in found)
    assert any("owner__mine" in str(path) for path in found)


def test_the_preprocessor_spelling_counts_as_a_dependency():
    """ifort's -fpp says "can't find include file"; the compiler proper says
    "cannot open include file". Matching only the second classified nine
    well-formed sources as malformed."""
    assert "can't find include file" in DEPENDENCY_DIAGNOSTICS


@pytest.mark.fortran
def test_a_broken_source_is_reported_as_broken(tmp_path):
    from umat_oti.abaqus.support import compile_one
    if __import__("shutil").which("abaqus") is None:
        pytest.skip("abaqus is not on PATH")
    entry = tmp_path / "umat.f"
    entry.write_text(BROKEN)
    check = compile_one(entry, tmp_path / "build")
    assert not check.ok
    assert check.source_is_malformed
    assert not check.missing_dependencies
    assert any("5276" in line or "parenthes" in line.lower()
               for line in check.defects), check.defects


@pytest.mark.fortran
def test_a_source_missing_a_module_is_not_reported_as_broken(tmp_path):
    from umat_oti.abaqus.support import compile_one
    if __import__("shutil").which("abaqus") is None:
        pytest.skip("abaqus is not on PATH")
    entry = tmp_path / "umat.f90"
    entry.write_text("subroutine umat(s)\n  use SolveMatrixEquation\nend subroutine\n")
    check = compile_one(entry, tmp_path / "build", form="free")
    assert not check.ok
    assert check.missing_dependencies
    assert not check.source_is_malformed


def test_the_converted_build_is_asked_the_same_question():
    """A build that aborts leaves no .sta, no .msg error count and no .odb,
    and that reads as "the converted build did not run" whether it failed to
    compile or failed to converge. Those need different work, and the compiler
    tells them apart in seconds. The answer is ours either way -- which is why
    the original's version of this check can end in an EXTERNAL verdict and
    this one cannot."""
    tool = (Path(__file__).resolve().parents[1] / "tools"
            / "verify_store_in_abaqus.py").read_text(encoding="utf-8")
    assert "def diagnose_transformed(" in tool
    body = tool.split("def diagnose_transformed(")[1].split("\ndef ")[0]
    assert "the transform emitted Fortran the compiler will not accept" in body
    assert "INCOMPLETE_OR_CORRUPT_SOURCE" not in body, (
        "a converted source that will not compile is this project's problem, "
        "never the author's")
    assert "EXTERNAL_DEPENDENCY_UNAVAILABLE" not in body
