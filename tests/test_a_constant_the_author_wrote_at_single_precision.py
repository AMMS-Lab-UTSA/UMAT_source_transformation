"""Two primal_disagreed entries, two root causes, neither of them round-off.

``abuganza/UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_strain.f`` reports a
worst stress difference of 1.4294492700071145e-06, bit-identical to pass9. The
author writes

    sigmaiso(i) = sigmabar(i) - (1./3.)*tr_sigmabar      i = 1, 2, 3

and assigns the shear components without the term. ``1./3.`` is a quotient of
two DEFAULT REAL literals, so Fortran evaluates it in single precision and
widens the result: 0.3333333432674408, not 0.33333333333333331.
``ABA_PARAM.INC``'s ``IMPLICIT REAL*8`` cannot help -- implicit typing types
variables, never literal constants -- and Abaqus does not build user
subroutines with ``-r8``. The transform emits ``(1.0D0/3.0D0)``, so the
promoted constant lands as ONE COMMON ADDITIVE OFFSET on exactly the three
normal stresses. The transformed build is the accurate one.

``Jeff97/.../From-2D-to-2D-Axe.for`` is a different animal. From the recorded
entry state both builds return all six stresses to the last bit, and DDSDDE
differing by 6.95e-07 of its scale. The deck's ENU is 0.4995, so
``D1 = SIX*(ONE-TWO*ENU)/EMOD`` cancels to 0.001/EMOD and the volumetric
penalty ``2/D1`` is 3.0e+08. Abaqus steers Newton with DDSDDE, so the builds
converge to different displacement fields and every later record is compared
at inputs they no longer share.

Neither entry is a reason to widen a tolerance, and the tests below exist to
stop that being the conclusion drawn from them.
"""
import json
import math
import os
import pathlib

import pytest

from umat_oti.abaqus.primal_signature import (CONFIRMED, DIAGNOSED_ENTRIES,
                                              REDUCED_PRECISION_INPUT,
                                              ROUND_OFF_GROWTH,
                                              first_call_difference,
                                              inexact_single_precision_literals)

DAMAGE = "d08cead8f57af10c6eb7e138"
AXE = "d6c1a1095875c2d4007280d6"


def _work(key):
    root = pathlib.Path(
        os.environ.get("UMAT_OTI_CORPUS_RUN")
        or pathlib.Path.home() / "softwarex_work" / "corpus_run")
    where = root / "pass10" / "work" / key
    if not where.is_dir():
        pytest.skip(f"no pass10 work directory at {where}")
    return where


def _history(key, which):
    return json.loads((_work(key) / which / f"{which}_history.json").read_text())


def test_a_quotient_of_default_real_literals_is_single_precision():
    """1/3 and 2/3 are not representable; 1/2 and 3/4 are, in both
    precisions, so reporting them would be noise."""
    found = inexact_single_precision_literals(
        "x = a -(1./3.)*b + (2./3.)*c + (1./2.)*d + (3./4.)*e")
    assert found == ["1./3.", "2./3."]


def test_an_already_double_literal_is_not_reported():
    """(1.0D0/3.0D0) is what the transform emits. Reporting the repaired
    form as the defect would invert the finding."""
    assert inexact_single_precision_literals("y = (1.0D0/3.0D0)*t") == []


def test_the_single_precision_third_differs_where_the_damage_entry_differs():
    """9.93e-09 relative is the whole mechanism, so it is worth pinning."""
    single = float(__import__("struct").unpack(
        "f", __import__("struct").pack("f", 1.0 / 3.0))[0])
    assert abs(single - 1.0 / 3.0) / (1.0 / 3.0) == pytest.approx(2.98e-08,
                                                                 rel=0.1)


def test_a_first_call_difference_cannot_be_the_path():
    """Agreement at the first call with disagreement later is a different
    finding from disagreement at the first call, and the two must not be
    reported as one."""
    assert first_call_difference([{"STRESS": [1.0, 2.0]}],
                                 [{"STRESS": [1.0, 2.0]}]) == 0.0
    assert first_call_difference([{"STRESS": [1.0]}],
                                 [{"STRESS": [1.25]}]) == 0.25
    assert math.isinf(first_call_difference([{"STRESS": [float("nan")]}],
                                            [{"STRESS": [1.0]}]))
    assert first_call_difference([], []) == 0.0


def test_both_entries_are_recorded_with_a_reproduction_and_a_cause():
    """A diagnosis without a control is a note somebody wrote once."""
    by_source = {d.source.split("/")[-1]: d for d in DIAGNOSED_ENTRIES}
    damage = by_source["UMAT_Tissue_2d_plane_strain.f"]
    axe = by_source["From-2D-to-2D-Axe.for"]
    assert damage.hypothesis == REDUCED_PRECISION_INPUT
    assert axe.hypothesis == ROUND_OFF_GROWTH
    for entry in (damage, axe):
        assert entry.confirmation_status == CONFIRMED
        assert entry.reproduction.held_fixed and entry.reproduction.varied
        assert entry.reproduction.observed and entry.reproduction.repeatable
    # The damage entry must never be filed as round-off: its own model moves
    # 16000 times LESS than the difference when perturbed by one ulp.
    assert "not round-off" in damage.root_cause or \
           "not round-off" in damage.reproduction.observed
    # The Axe entry is round-off amplified, and saying so must not become a
    # licence to widen the tolerance.
    assert "NOT a reason to widen a tolerance" in axe.reproduction.observed


@pytest.mark.integration
def test_the_damage_entry_carries_the_literal_and_differs_at_the_first_call():
    """Source text and history agree on the shape of the finding."""
    original = (_work(DAMAGE) / "original" / "original_user.f").read_text()
    assert "(1./3.)" in original
    transformed = (_work(DAMAGE) / "transformed"
                   / "transformed_user.f").read_text()
    assert "(1.0D0/3.0D0)" in transformed
    assert inexact_single_precision_literals(original)
    # The offset is common to the three normal stresses and absent from the
    # shear, which is what one promoted constant in the deviatoric projection
    # predicts and what an accumulated path difference does not.
    o = _history(DAMAGE, "original")[0]["STRESS"]
    t = _history(DAMAGE, "transformed")[0]["STRESS"]
    offsets = [abs(x - y) for x, y in zip(o, t)]
    assert offsets[0] == pytest.approx(offsets[1], rel=1e-6)
    assert offsets[0] == pytest.approx(offsets[2], rel=1e-6)
    assert offsets[3] < offsets[0] * 1e-4


@pytest.mark.integration
def test_the_axe_entry_is_compared_at_inputs_the_builds_no_longer_share():
    """Its records are correctly aligned -- same element, point, increment and
    time throughout -- and the inputs at those records still differ, which is
    what makes the reported number a statement about the path."""
    o = _history(AXE, "original")
    t = _history(AXE, "transformed")
    assert len(o) == len(t)
    for a, b in zip(o, t):
        assert (a["element"], a["point"], a["step"], a["increment"],
                a["time"]) == (b["element"], b["point"], b["step"],
                               b["increment"], b["time"])
    assert o[0]["entry"]["DSTRAN"] != t[0]["entry"]["DSTRAN"]
