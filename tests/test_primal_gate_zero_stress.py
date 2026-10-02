"""A stress-free history (mholla umat_iso_morph.f: free isotropic growth,
|sigma| ~ 1e-15 on moduli ~ 1) is below the resolution of the arithmetic, not
a 100% disagreement between the builds."""
import gzip
import json
from pathlib import Path

from umat_oti.abaqus.compare import compare_primal, stiffness_scale

FIXTURES = Path(__file__).parent / "fixtures" / "primal_gate"


def case():
    with gzip.open(FIXTURES / "mholla_iso_morph.json.gz", "rt") as handle:
        return json.load(handle)


def test_without_a_stiffness_scale_rounding_reads_as_a_disagreement():
    c = case()
    result = compare_primal(c["original"], c["transformed"], tolerance=1e-10)
    assert not result.agrees
    assert result.worst_stress_relative > 1e-2


def test_with_the_stiffness_scale_the_stress_is_below_resolution_and_the_state_decides():
    c = case()
    stiffness = stiffness_scale(c["transformed"])
    assert 0.1 < stiffness < 10
    result = compare_primal(c["original"], c["transformed"], tolerance=1e-10,
                            stiffness=stiffness)
    assert result.agrees, result.reason
    assert result.stress_below_resolution > 0
    # The component that decided the old verdict is one of them.
    old = compare_primal(c["original"], c["transformed"], tolerance=1e-10)
    _, _, x, y = old.worst_stress_at
    assert max(abs(x), abs(y)) <= result.stress_resolution


def test_the_stiffness_scale_does_not_forgive_a_real_stress_difference():
    c = case()
    bumped = [dict(r, STRESS=[v + 1e-6 for v in r["STRESS"]]) for r in c["transformed"]]
    result = compare_primal(c["original"], bumped, tolerance=1e-10,
                            stiffness=stiffness_scale(c["transformed"]))
    assert not result.agrees
