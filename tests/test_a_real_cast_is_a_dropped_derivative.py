"""``REAL(x)`` takes the value and throws the derivatives away.

That is exactly right at the end, where the real stress has to go back into
Abaqus's array. Anywhere the result is used again it is exactly wrong: from
that assignment on the quantity behaves like a constant, so the stress is
still right and every derivative computed through it is short by whatever it
contributed.

Measured on ``UMAT_Tissue_2d_plane_strain.f``, whose converted source contains
``detF2d = REAL(+DFGRD1_OTI(1,1)*DFGRD1_OTI(2,2) - ...)`` and then divides the
stress by it. The primal history agrees with the original to the last bit and
the tangent comes back nearly diagonal and three orders of magnitude small,
FLAT across all six step sizes of the finite difference -- which is not what a
convergence failure looks like, and is exactly what a different function looks
like. 33 of 253 stored transforms do this.

Not every cast is one. ``GSHEAR = REAL(PROPS_OTI(1)/2/(1+PROPS_OTI(2)))``
discards derivatives that were never there, because PROPS carries no seed when
the tangent is what is being computed. 105 casts in the same store are of that
kind and none is reported.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.truncation import analyse  # noqa: E402

SEEDED = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)
      TYPE(ONUMM6N1) :: DFGRD1_OTI(3,3), STRESS_OTI(6), PROPS_OTI(4)
      DFGRD1_OTI(1,1) = DFGRD1_OTI(1,1) + OTI_E1
      DFGRD1_OTI(2,2) = DFGRD1_OTI(2,2) + OTI_E2
      DFGRD1_OTI(1,2) = DFGRD1_OTI(1,2) + 0.5D0*OTI_E4
"""

WRITEBACK = """\
      DO OTI_I = 1, NTENS
         STRESS(OTI_I) = REAL(STRESS_OTI(OTI_I))
      END DO
      RETURN
      END
"""


def test_a_cast_of_a_seeded_expression_that_is_used_again_is_reported():
    text = (SEEDED
            + "      detf = REAL(DFGRD1_OTI(1,1)*DFGRD1_OTI(2,2))\n"
              "      STRESS_OTI(1) = STRESS_OTI(1) / detf\n"
            + WRITEBACK)
    found = analyse(text)
    assert found.drops_a_derivative
    assert found.truncations[0].target == "DETF"
    assert "DFGRD1_OTI" in found.truncations[0].depends_on
    assert "behaves like a constant" in found.reason()


def test_the_writeback_is_not_a_defect():
    """Taking the real part of STRESS_OTI is the point of the whole thing."""
    text = SEEDED + "      STRESS_OTI(1) = DFGRD1_OTI(1,1)\n" + WRITEBACK
    assert not analyse(text).drops_a_derivative


def test_a_cast_of_something_that_carries_no_seed_is_not_a_defect():
    text = (SEEDED
            + "      GSHEAR = REAL(PROPS_OTI(1)/2.0D0/(1.0D0+PROPS_OTI(2)))\n"
              "      STRESS_OTI(1) = STRESS_OTI(1) * GSHEAR\n"
            + WRITEBACK)
    found = analyse(text)
    assert not found.drops_a_derivative
    assert found.harmless >= 1


def test_a_cast_that_is_never_read_again_is_not_a_defect():
    """A value taken out of the hypercomplex domain and printed is a
    diagnostic, not a dropped derivative."""
    text = (SEEDED
            + "      DEBUGV = REAL(DFGRD1_OTI(1,1))\n"
            + WRITEBACK)
    assert not analyse(text).drops_a_derivative


def test_the_taint_follows_a_chain_of_assignments():
    text = (SEEDED
            + "      FBAR_OTI = DFGRD1_OTI(1,1) * 2.0D0\n"
              "      CBAR_OTI = FBAR_OTI * FBAR_OTI\n"
              "      scale = REAL(CBAR_OTI)\n"
              "      STRESS_OTI(1) = STRESS_OTI(1) * scale\n"
            + WRITEBACK)
    found = analyse(text)
    assert found.drops_a_derivative
    assert found.truncations[0].target == "SCALE"


def test_a_source_with_no_seed_reports_nothing():
    found = analyse("      SUBROUTINE UMAT(S)\n      RETURN\n      END\n")
    assert not found.drops_a_derivative
    assert found.seeded == ()
    assert "no assignment" in found.reason()


def test_the_seeded_variables_are_named():
    found = analyse(SEEDED + WRITEBACK)
    assert found.seeded == ("DFGRD1_OTI",)
