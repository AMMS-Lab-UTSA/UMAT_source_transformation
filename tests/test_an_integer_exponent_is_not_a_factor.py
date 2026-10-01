"""``X_OTI**2`` is a power, and the two was being read as a multiplication.

The emitter promotes a bare integer that multiplies or divides a hypercomplex
term, because the OTI type has no operator against a default INTEGER. The
pattern it used for the operand-after-the-operator case, ``([*/])\\s*(\\d+)``,
matches the SECOND asterisk of ``**`` as well, so every integer exponent in a
promoted expression came out as a real one: ``Y_OTI**2`` was emitted as
``Y_OTI**2.0D0`` and ``Y_OTI*A**2`` -- where A is the author's own REAL -- as
``Y_OTI*A**2.0D0``.

The promotion is not needed there. The generated algebra declares
``OPERATOR(**)`` for (OTI, INTEGER(4)) and (OTI, INTEGER(8)) as well as for
(OTI, REAL), and for (INTEGER, OTI); an integer exponent resolves and carries
the same derivative. What the rewrite does instead is replace an exact
repeated multiplication by a call to the real power, on an operand the
transform never looked at -- ``A`` above is not promoted and is not even
necessarily positive. Fortran's ``A**2`` is defined for every real A; its
``A**2.0D0`` is defined only for A >= 0, and what glibc does with a negative
base and an integral real exponent is not something this transform should be
relying on.

The emitter and the post-check ``integer_literals_normalized_in_oti_expressions``
share the two patterns deliberately, so that the check cannot refuse a file the
emitter wrote correctly. Both are asserted here for the same reason.
"""
import pytest

from umat_oti.transform.source_transform import (
    _integer_literals_normalized_in_oti_expressions,
    _normalize_numeric_literals_in_oti_expression)


@pytest.mark.unit
def test_an_integer_exponent_of_a_shadow_keeps_its_integer_kind():
    assert (_normalize_numeric_literals_in_oti_expression("      X_OTI = Y_OTI**2")
            == "      X_OTI = Y_OTI**2")


@pytest.mark.unit
def test_an_integer_exponent_of_the_authors_own_real_is_left_alone():
    """``A`` is not promoted and may be negative; ``A**2.0D0`` is not ``A**2``."""
    assert (_normalize_numeric_literals_in_oti_expression("      X_OTI = Y_OTI*A**2")
            == "      X_OTI = Y_OTI*A**2")


@pytest.mark.unit
def test_a_bare_integer_factor_is_still_promoted():
    """The reason the rewrite exists has not been taken away with it."""
    assert (_normalize_numeric_literals_in_oti_expression("      X_OTI = 2*Y_OTI")
            == "      X_OTI = 2.0D0*Y_OTI")
    assert (_normalize_numeric_literals_in_oti_expression("      X_OTI = Y_OTI*2")
            == "      X_OTI = Y_OTI*2.0D0")
    assert (_normalize_numeric_literals_in_oti_expression("      X_OTI = Y_OTI/2")
            == "      X_OTI = Y_OTI/2.0D0")


@pytest.mark.unit
def test_a_factor_beside_a_power_is_promoted_and_the_exponent_is_not():
    assert (_normalize_numeric_literals_in_oti_expression(
        "      X_OTI = Y_OTI**3 + 2*Z_OTI")
        == "      X_OTI = Y_OTI**3 + 2.0D0*Z_OTI")


@pytest.mark.unit
def test_the_post_check_accepts_the_integer_exponent_the_emitter_leaves():
    """Emitter and check read the same expression the same way, or a correct
    file is refused for a defect that is not in it."""
    assert _integer_literals_normalized_in_oti_expressions(
        "      X_OTI = Y_OTI**2\n", "fixed")
    assert _integer_literals_normalized_in_oti_expressions(
        "      X_OTI = Y_OTI*A**2\n", "fixed")


@pytest.mark.unit
def test_the_post_check_still_refuses_a_bare_integer_factor():
    assert not _integer_literals_normalized_in_oti_expressions(
        "      X_OTI = 2*Y_OTI\n", "fixed")
    assert not _integer_literals_normalized_in_oti_expressions(
        "      X_OTI = Y_OTI*2\n", "fixed")
