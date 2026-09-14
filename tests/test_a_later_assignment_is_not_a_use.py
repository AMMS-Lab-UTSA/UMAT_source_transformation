"""Writing to a name again is not reading it, and the difference was a verdict.

``umat_oti.abaqus.truncation`` reports a REAL() cast as a dropped derivative
only when the result is "used again"; a value taken out of the hypercomplex
domain and never read is a diagnostic print, not a defect. The test for "used
again" asked whether the target's name appears in any later line -- and the
name on the left of a later assignment appears in it.

The contradiction that names the bug: an array filled element by element
reports every element but the last, because each is followed by another
assignment to the same array and the last is not. Nothing about the last
element is different.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus import truncation  # noqa: E402


#: The shape the corpus produces: a seed, a run of casts filling one array,
#: and no reader. Modelled on the converted
#: abuganza/BayesianCalibrationSkinGrowth Iso_Example.f, whose b(1)..b(6) are
#: read only by the old tangent block -- which the transform comments out.
FILLED_AND_NEVER_READ = """\
      DFGRD1_OTI(1,1) = DFGRD1_OTI(1,1) + OTI_E1
      b(1) = REAL(DFGRD1_OTI(1,1)*DFGRD1_OTI(1,1))
      b(2) = REAL(DFGRD1_OTI(2,1)*DFGRD1_OTI(2,1))
      b(3) = REAL(DFGRD1_OTI(3,1)*DFGRD1_OTI(3,1))
C     OTIS-SKIP: cg_ij(1) = mu*(b(1)-xn(1)*xn(1))
      STRESS(1) = REAL(DFGRD1_OTI(1,1))
"""

FILLED_AND_THEN_READ = """\
      DFGRD1_OTI(1,1) = DFGRD1_OTI(1,1) + OTI_E1
      b(1) = REAL(DFGRD1_OTI(1,1)*DFGRD1_OTI(1,1))
      b(2) = REAL(DFGRD1_OTI(2,1)*DFGRD1_OTI(2,1))
      STRESS_OTI(1) = STRESS_OTI(1) + b(1) + b(2)
"""


def test_a_run_of_casts_with_no_reader_reports_nothing():
    """Before: 2 of the 3 reported, the last one not. After: none of them.

    The same count, from the same rule, on the whole corpus: five converted
    sources reported six truncations each and now report none. Their only
    consumer is a line the transform has commented out, so there is no
    derivative to drop.
    """
    finding = truncation.analyse(FILLED_AND_NEVER_READ)
    assert [t.target for t in finding.truncations] == []
    assert finding.harmless == 3


def test_a_cast_whose_result_is_read_is_still_reported():
    """The check has to keep failing what it was written for.

    b(1) and b(2) are both read by the stress update below them, so both are
    defects and both are named -- the fix narrows "used" to "read", it does
    not narrow it to "never".
    """
    finding = truncation.analyse(FILLED_AND_THEN_READ)
    assert sorted({t.target for t in finding.truncations}) == ["B"]
    assert len(finding.truncations) == 2


def test_a_subscript_on_the_left_is_read():
    """``A(I) = X`` reads I and X and writes A.

    The index is a read even though it stands to the left of the ``=``, so a
    cast whose result is only ever used as a subscript is still a defect.
    """
    source = """\
      DSTRAN_OTI(1) = DSTRAN_OTI(1) + OTI_E1
      IDX = REAL(DSTRAN_OTI(1))
      TABLE(IDX) = 1.0D0
"""
    finding = truncation.analyse(source)
    assert [t.target for t in finding.truncations] == ["IDX"]
