"""A value that is only printed is not used by the model.

no_ddsdde_read_after_disabled_assignment refuses a file in which a live
statement still reads DDSDDE after a write to it was disabled. A PRINT of
DDSDDE (JuliaFEM's gurson_porous_plasticity prints the tangent) only
displays the array; counting it as a read refused a source whose model never
uses the old tangent. Rule (B20 notes R2): PRINT statements are not reads
(WRITE is not included: its unit may be an internal file read back). Planted errors: a genuine read stays a read -- on the right-hand side of
an assignment, in a branch condition, and in an IF whose body is a PRINT.
"""
import pytest

from umat_oti.transform.source_transform import _statement_reads


@pytest.mark.parametrize("statement", [
    "      PRINT *, DDSDDE",
    "      PRINT '(6E12.4)', (DDSDDE(1,J), J=1,6)",
    "  100 PRINT *, 'D11 = ', DDSDDE(1,1)",
])
def test_a_displayed_tangent_is_not_a_read(statement):
    assert not _statement_reads(statement, "DDSDDE")


@pytest.mark.parametrize("statement", [
    "      X = DDSDDE(1,1)*2.D0",
    "      STRESS(I) = STRESS(I) + DDSDDE(I,J)*DSTRAN(J)",
    "      IF (DDSDDE(1,1).GT.0.D0) PRINT *, 'positive'",
    "      WRITE(7,*) 'DDSDDE=', DDSDDE(1,1)",       # WRITE may go to an internal file: still a read
])
def test_canary_a_genuine_read_is_still_a_read(statement):
    assert _statement_reads(statement, "DDSDDE")
