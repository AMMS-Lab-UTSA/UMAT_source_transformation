"""Per build: does the object compiled WITHOUT -assume norealloc_lhs reference
for_realloc_lhs (Vera B10)? The flag changes code only where it does."""
import shutil
from pathlib import Path

import pytest

from umat_oti.abaqus import realloc_probe

pytestmark = pytest.mark.unit

ENV = """\
import os
fortCmd = "ifort"
abaHomeInc = "/x"
compile_fortran = [fortCmd,
                   '-V',
                   '-c', '-fpp','-fPIC',   # comment, with 'quoted' text
                   #'-init=zero',
                   '-fp-model', 'precise',
                   '-WB', '-I%I', '-I'+abaHomeInc, '%P']
compile_cpp = ['g++', '-c']
"""

ALLOCATING = """\
      SUBROUTINE GROW(N, S)
      INTEGER N
      DOUBLE PRECISION S
      DOUBLE PRECISION, ALLOCATABLE :: A(:)
      A = [(DBLE(I), I = 1, N)]
      S = SUM(A)
      END
"""

PLAIN = """\
      SUBROUTINE PLAIN(N, S)
      INTEGER N
      DOUBLE PRECISION S
      S = DBLE(N)
      END
"""


def test_the_shipped_flags_are_read_without_compiler_source_or_includes(tmp_path):
    env = tmp_path / "site.env"
    env.write_text(ENV)
    assert realloc_probe.shipped_compile_flags(env) == [
        "-fpp", "-fPIC", "-fp-model", "precise", "-WB"]
    assert realloc_probe.shipped_compile_flags(tmp_path / "missing.env") is None


@pytest.mark.skipif(shutil.which("ifort") is None
                    or not Path(realloc_probe.SITE_ENV).is_file(),
                    reason="needs ifort and the Abaqus site environment")
def test_an_allocatable_assignment_is_what_references_the_symbol(tmp_path):
    grow = tmp_path / "grow.f"
    grow.write_text(ALLOCATING)
    plain = tmp_path / "plain.f"
    plain.write_text(PLAIN)
    yes = realloc_probe.probe(grow, tmp_path / "a")
    no = realloc_probe.probe(plain, tmp_path / "b")
    assert yes["references_for_realloc_lhs"] is True, yes
    assert no["references_for_realloc_lhs"] is False, no
    assert "norealloc_lhs" not in " ".join(yes["command"])
    assert len(yes["object_sha256"]) == 64
