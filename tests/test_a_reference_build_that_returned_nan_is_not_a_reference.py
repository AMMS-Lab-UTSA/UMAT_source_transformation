"""A NaN total cannot tell which build produced it, and it decides the meaning.

Ten of the 42 pass9 ``primal_disagreed`` entries are the HelixUp family
(``Jeff97/Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/
Examples-In-Section-3/HelixUp/*``). Read back from
``corpus_run/pass9/work/f5af2fe003be5a2cfb41273e/original/original_probe.txt``,
**72 of the ORIGINAL build's 80 converged records carry NaN in all six stress
components**, and from increment 2 onward Abaqus is handing the author's
routine a DSTRAN and a DFGRD1 that are NaN as well:

    STRESS0  nan nan nan nan nan nan
    DSTRAN   nan nan nan nan nan nan
    DFGRD1   nan nan nan nan nan nan
    STATEV0  0.178548 0.244984 0.211325 0.742217 ...

The job's own ``original.sta`` ends ``THE ANALYSIS HAS COMPLETED
SUCCESSFULLY`` over the ten increments requested, the record carries
``complete_finite_verification_run: true``, and ``original.completed`` is
``true`` with no reasons. The global solution went to NaN on our generated
single-element body-force deck and Abaqus did not say so.

Whatever that is, it is not a measurement of a transform. The total
``non_finite_components`` alone could not say it, because it does not say whose
NaN it is.
"""
import math

import pytest

from umat_oti.abaqus.compare import compare_primal

pytestmark = pytest.mark.unit


def _history(stress, state=(1.0,)):
    return [{"step": 1, "element": 1, "point": 1, "increment": 1, "time": 0.0,
             "STRESS": list(stress), "STATEV": list(state)}]


def test_a_nan_from_the_original_build_is_counted_as_the_originals():
    result = compare_primal(_history([float("nan")] * 6),
                            _history([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))
    assert result.non_finite_original == 6
    assert result.non_finite_transformed == 0
    assert not result.agrees


def test_a_nan_from_the_transformed_build_is_counted_as_the_transformeds():
    """simplified_curing.for: the transformed build returns NaN in all six
    stress components on the first call, from finite identical inputs."""
    result = compare_primal(_history([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
                            _history([float("nan")] * 6))
    assert result.non_finite_original == 0
    assert result.non_finite_transformed == 6


def test_the_reason_names_the_original_when_the_reference_went_non_finite():
    """"nothing about this pair is established" is true and not enough: an
    entry whose reference is NaN is not a disagreement about the transform,
    and ten entries were filed as though it were."""
    result = compare_primal(_history([float("nan")] * 6), _history([1.0] * 6))
    assert "the ORIGINAL build's" in result.reason
    assert "cannot carry a claim about the transform" in result.reason


def test_the_reason_does_not_blame_the_original_when_only_the_transform_failed():
    result = compare_primal(_history([1.0] * 6), _history([float("nan")] * 6))
    assert "ORIGINAL build's" not in result.reason
    assert "nothing about this pair is established" in result.reason


def test_both_builds_returning_nan_is_still_the_originals_problem_too():
    result = compare_primal(_history([float("nan")] * 6),
                            _history([float("nan")] * 6))
    assert result.non_finite_original == 6
    assert result.non_finite_transformed == 6
    assert math.isinf(result.worst_stress_relative)


def test_the_counts_survive_serialisation():
    result = compare_primal(_history([float("nan")] * 6), _history([1.0] * 6))
    row = result.as_dict()
    assert row["non_finite_original"] == 6
    assert row["non_finite_transformed"] == 0
