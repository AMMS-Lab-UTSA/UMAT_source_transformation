"""Abaqus job staging (pass21 findings, Gauss).

- An INCLUDE that names a file beside the author's source (davidmorin
  V_UMAT: ``INCLUDE './UMAT_MODEL.f'``) is staged where the compiler looks.
- ``INCLUDE 'PARAM_UMAT.INC'`` opens ``param_umat.inc`` when exactly one file
  matches case-insensitively (jpsferreira), the ORIGINAL source's directory
  first; the match is recorded.
- A library that builds and cannot be loaded (``undefined symbol``) is named
  as such, not as an analysis that left no record.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus import include_shim
from umat_oti.abaqus.job_status import classify_job

pytestmark = pytest.mark.unit

SOURCE = """\
      SUBROUTINE UMAT(STRESS)
      INCLUDE './UMAT_MODEL.f'
      INCLUDE 'PARAM_UMAT.INC'
C     INCLUDE 'COMMENTED.INC'
#include "PRE.h"
      END
"""


def test_includes_are_found_exactly_or_case_insensitively(tmp_path):
    author = tmp_path / "repo" / "test"
    author.mkdir(parents=True)
    (author / "UMAT_MODEL.f").write_text("      X = 1\n")
    (author / "param_umat.inc").write_text("      Y = 2\n")
    (tmp_path / "repo" / "param_umat.inc").write_text("      Y = 99\n")   # another one
    shim = tmp_path / "job" / "include_any_case"
    shim.mkdir(parents=True)
    staged = include_shim.stage_includes(SOURCE, [author, tmp_path / "repo"], shim)
    by = {s["include"]: s for s in staged}
    assert include_shim.included_names(SOURCE) == ["./UMAT_MODEL.f", "PARAM_UMAT.INC", "PRE.h"]
    assert by["./UMAT_MODEL.f"]["match"] == "exact"
    assert (shim / "UMAT_MODEL.f").read_text() == "      X = 1\n"
    assert by["PARAM_UMAT.INC"]["match"] == "case-insensitive"
    # the ORIGINAL source's directory wins over the repository root
    assert (shim / "PARAM_UMAT.INC").read_text() == "      Y = 2\n"
    assert by["PRE.h"]["found"] is False


def test_two_case_variants_are_ambiguous_and_not_guessed(tmp_path):
    author = tmp_path / "a"
    author.mkdir()
    (author / "param.inc").write_text("1\n")
    (author / "Param.inc").write_text("2\n")
    shim = tmp_path / "s"
    shim.mkdir()
    (staged,) = include_shim.stage_includes("      INCLUDE 'PARAM.INC'\n", [author], shim)
    assert staged["found"] is False and staged["reason"] == "ambiguous"


def test_a_library_that_cannot_be_loaded_is_named(tmp_path):
    (tmp_path / "j.dat").write_text("input processed\n")
    (tmp_path / "j.msg").write_text("INCREMENT     1 STARTS\n")
    console = ("/usr/SIMULIA/.../standard: symbol lookup error: "
               "/tmp/x_123/libstandardU.so: undefined symbol: for_realloc_lhs\n")
    status = classify_job(tmp_path, "j", console=console)
    assert not status.analysis_completed
    assert any("undefined symbol for_realloc_lhs" in r for r in status.reasons)
