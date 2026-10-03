"""A REAL statement that reads the seed into a shadowed variable is refused.

``G = PROPS(1)*(1.0D0 + DSTRAN(2))`` reaches the stress only through
``CALL SCALE(2.0D0*G, ...)``. The region classifier's dependency edge for a
call takes the first identifier of each actual, and ``2.0D0*G`` has none, so
the statement was left REAL ahead of the seed block, G_OTI was filled from G
with no derivative, and the transform returned a stress that agrees with the
author's bit for bit beside a tangent missing dG/dDSTRAN (DDSDDE(1,2) 1000.0
against a finite-difference 1040.8). The classifier is not changed here; the
emitted text is checked (``no_seed_read_into_a_real_copy_of_a_shadowed_name``)
so the construct is refused by name instead of emitted wrong.

The same routine with the actual written ``G*2.0D0`` transforms and agrees
(tests/test_transform_a_value_at_a_hypercomplex_dummy_is_passed_as_one.py).
"""
from _transform_vs_original import transform

from test_transform_a_value_at_a_hypercomplex_dummy_is_passed_as_one import HEAD


def test_a_seed_read_left_real_ahead_of_the_seed_block_is_refused(tmp_path):
    summary, code = transform(tmp_path, HEAD % {"first": "2.0d0*g"}, ".f90")
    assert code != 0
    assert summary["semantic_checks"]["no_seed_read_into_a_real_copy_of_a_shadowed_name"] is False
