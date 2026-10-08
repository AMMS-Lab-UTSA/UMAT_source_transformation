"""A free-form file called .for defines routines, and ``#include "x"`` is an include.

sahmotaman's TMM-FE sources are free form in a ``.for`` file and pull their
routines in with ``#include 'plasticity_subroutine.f90'``. Read as fixed form
the file "defines nothing"; and the include was invisible to the resolver.
Planted-error canary: a genuinely fixed-form .for file is still read as fixed.
"""
from umat_oti.transform import dependency_resolution as dr

FREE_FOR = """! free form in a .for file
  subroutine umat(a, b)
    real(8) :: a, b
    call helper(a)
  end subroutine umat
"""

FIXED_FOR = """C fixed form
      SUBROUTINE UMAT(A, B)
      REAL*8 A, B
      CALL HELPER(A)
      END
"""


def test_a_free_form_for_file_defines_its_routine(tmp_path):
    path = tmp_path / "u.for"
    path.write_text(FREE_FOR)
    assert [d.name for d in dr._definitions_in(path)] == ["UMAT"]
    assert dr._definitions_in(path)[0].fixed_form is False


def test_canary_a_fixed_form_for_file_is_still_fixed(tmp_path):
    path = tmp_path / "u.for"
    path.write_text(FIXED_FOR)
    assert [d.name for d in dr._definitions_in(path)] == ["UMAT"]
    assert dr._definitions_in(path)[0].fixed_form is True


def test_a_quoted_cpp_include_names_a_file_to_resolve(tmp_path):
    path = tmp_path / "u.for"
    path.write_text("#include 'helper.f90'\n" + FREE_FOR)
    (tmp_path / "helper.f90").write_text("subroutine helper(a)\n real(8) :: a\nend subroutine helper\n")
    assert dr._include_targets(path) == ["helper.f90"]
    graph = dr.resolve_closure(path, entry="UMAT", roots=[tmp_path])
    assert "HELPER" in graph.resolved
    assert "helper.f90" in dr.combined_source(graph) or "HELPER" in dr.combined_source(graph)


def test_canary_a_system_include_is_not_a_local_include(tmp_path):
    path = tmp_path / "u.for"
    path.write_text("#include <mpif.h>\n" + FREE_FOR)
    assert dr._include_targets(path) == []
