"""B17 G2c: an END closing a host subroutine after CONTAINS is not an implicit main program.

NN_UMAT_Vahid.f holds `contains` + an internal function; its END, then the host's END.
The remover counted open subprograms with a flag, so the internal function's END cleared
it and the host's END was commented out as an "implicit main program": the driver then
failed with a syntax error and the row was recorded as an init probe that could not be
built. A depth counter closes each unit once. A stray END after every unit is closed is
still removed (the planted error).
"""
from umat_oti.abaqus.replay import without_the_authors_program

HOST = """      subroutine host(a)
      real*8 a
      a = det(a)
      return
      contains
      real*8 function det(c)
        real*8 c
        det = c
      end
      end
"""


def test_the_host_end_after_an_internal_procedure_is_kept():
    out, removed = without_the_authors_program(HOST, "fixed")
    assert removed == ()
    assert out == HOST


def test_a_stray_end_after_every_unit_is_closed_is_still_removed():
    out, removed = without_the_authors_program(HOST + "      end\n", "fixed")
    assert removed == ("(implicit main program)",)
    assert out.rstrip().splitlines()[-1].startswith("C     OTIS-REMOVED")
    assert out.startswith(HOST)
