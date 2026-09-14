"""An INTERFACE block declares a procedure; it does not define one.

``parse_subroutines`` had no idea INTERFACE blocks existed. An interface body
is written with the same words as a definition --

    interface
        pure subroutine MohrCoulombStressReturn(Sigma, nsigma, ...)
            ...declarations only...
        end subroutine MohrCoulombStressReturn
    end interface

-- and that ``end subroutine`` closed whatever program unit was open. Where the
interface block sits in a UMAT's own declaration section, which is where
Fortran requires it, the unit it closed was the UMAT. On
``baw-de__poroMechanicalFoam/.../MohrCoulombAbaqus.for`` -- 1694 lines, a
Mohr-Coulomb return mapping -- UMAT was recorded as spanning lines 1-141 when
its body runs to 245. The stress update at line 230 and the tangent store at
229 both sit past 141, were discarded for lying outside the routine, and the
transform refused with four missing anchors: missing_stress_update_region,
missing_stress_update_regions, missing_real_output_extraction_point,
missing_ddsdde_extraction_point. Four true statements, none of them the reason.

The second half of the same gap: the definitions in that file are written
``pure subroutine NAME(...)``, and the header pattern admitted no prefix, so
none of the fourteen routines below UMAT was parsed either.

Both stores are whole-array -- ``DDSDDE = Depc``, ``STRESS = SigC``, no
subscript -- so a reader looking for an indexed assignment finds nothing in
that file and concludes the anchor locator cannot see whole-array writes. It
can; ``ASSIGNMENT_RE`` has always matched both spellings. What it could not see
was any line past 141.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.fortran.parser import (  # noqa: E402
    interface_declared_procedures, logical_lines_from_text, parse_subroutines,
    parse_function_subprograms)

pytestmark = pytest.mark.unit


FIXED_UMAT_WITH_AN_INTERFACE_BLOCK = """      subroutine UMAT(STRESS,STATEV,DDSDDE,DSTRAN,NTENS)
      implicit none
      integer NTENS
      real(8) STRESS(NTENS), STATEV(1), DDSDDE(NTENS,NTENS)
      real(8) DSTRAN(NTENS), SigC(NTENS), Depc(NTENS,NTENS)
      interface
          pure subroutine Kernel(Sigma, nsigma, Sigma_up, Dep)
              integer, intent(in) :: nsigma
              real(8), intent(in) :: Sigma(nsigma)
              real(8), intent(out) :: Sigma_up(nsigma), Dep(nsigma,nsigma)
          end subroutine Kernel
      end interface
      call Kernel(STRESS, NTENS, SigC, Depc)
      DDSDDE = Depc
      STRESS = SigC
      end subroutine UMAT

      pure subroutine Kernel(Sigma, nsigma, Sigma_up, Dep)
      integer, intent(in) :: nsigma
      real(8), intent(in) :: Sigma(nsigma)
      real(8), intent(out) :: Sigma_up(nsigma), Dep(nsigma,nsigma)
      Sigma_up = Sigma
      Dep = 0.0d0
      end subroutine Kernel
"""


def _routines(text, form="free"):
    return {routine.upper_name: (routine.lines[0].line_numbers[0],
                                 routine.lines[-1].line_numbers[-1])
            for routine in parse_subroutines(logical_lines_from_text(text, form))}


def test_the_umat_span_reaches_its_own_end_and_not_the_interface_bodys():
    routines = _routines(FIXED_UMAT_WITH_AN_INTERFACE_BLOCK)
    start, end = routines["UMAT"]
    body = FIXED_UMAT_WITH_AN_INTERFACE_BLOCK.splitlines()
    assert body[start - 1].strip().lower().startswith("subroutine umat")
    assert body[end - 1].strip().lower() == "end subroutine umat"
    # Both whole-array stores are inside the span. That is the whole point.
    for needle in ("DDSDDE = Depc", "STRESS = SigC"):
        line = next(i for i, text in enumerate(body, start=1) if needle in text)
        assert start <= line <= end, f"{needle} fell outside the UMAT span"


def test_a_prefixed_definition_is_still_a_definition():
    routines = _routines(FIXED_UMAT_WITH_AN_INTERFACE_BLOCK)
    assert "KERNEL" in routines, "pure subroutine Kernel was not parsed"
    start, end = routines["KERNEL"]
    assert end > start


def test_the_interface_body_does_not_become_a_second_routine():
    lines = logical_lines_from_text(FIXED_UMAT_WITH_AN_INTERFACE_BLOCK, "free")
    spans = [(r.upper_name, r.lines[0].line_numbers[0]) for r in parse_subroutines(lines)]
    assert [name for name, _ in spans] == ["UMAT", "KERNEL"], spans


def test_an_interface_declared_procedure_is_still_known_to_be_a_procedure():
    """Skipping the body must not lose the fact that the NAME is callable.

    The submodule idiom is where this bites: the interface body is the only
    place the signature appears, because the implementation is written
    ``module procedure convert_array_to_tensor`` with no argument list. Losing
    the name made ``Convert_array_to_tensor(stress, 1.0_DP)`` read as a
    subscript, and the transform refused sanisand's merged source with
    "promoted variable CONVERT_ARRAY_TO_TENSOR is indexed in a stress region
    but has no confirmed shape".
    """
    submodule = """module tensor_mod
      interface
        module function Convert_array_to_tensor(array, scalar) result(tensor)
          real(8), intent(in) :: array(6), scalar
          real(8) :: tensor(3,3)
        end function Convert_array_to_tensor
      end interface
      end module tensor_mod
"""
    names = interface_declared_procedures(logical_lines_from_text(submodule, "free"))
    assert "CONVERT_ARRAY_TO_TENSOR" in names
    # ...and it is not offered to the lifter as something with a body here.
    defined = {f.upper_name for f in
               parse_function_subprograms(logical_lines_from_text(submodule, "free"))}
    assert "CONVERT_ARRAY_TO_TENSOR" not in defined


def test_a_module_procedure_line_names_a_procedure_too():
    text = """module m
      interface swap
        module procedure swap_i, swap_r
      end interface swap
      end module m
"""
    names = interface_declared_procedures(logical_lines_from_text(text, "free"))
    assert {"SWAP_I", "SWAP_R"} <= names


def test_an_argument_less_header_is_not_invented_from_a_mangled_end_line():
    """``  end subroutine umat`` read by fixed-form columns is ``subroutine umat``.

    Four sahmotaman sources are free-form Fortran in a file named ``.for``.
    Read by column, ``  end subroutine umat`` loses its first six characters
    and the remainder is a bare ``subroutine umat`` -- indistinguishable from a
    legal argument-less header. Accepting that spelling reported a UMAT whose
    body was one line long, and the refusal that followed named a cause that
    was not there. The pattern keeps the argument list required.
    """
    mangled = "  end subroutine umat\n"
    assert not parse_subroutines(logical_lines_from_text(mangled, "fixed"))
