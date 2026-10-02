"""A DATA-initialised name changed only inside a lifted helper carries over calls.

``DATA XI/1.D0/`` handed to a lifted helper that increments it: the shadow is
SAVEd beside XI, and was re-copied from the never-updated real XI at every
entry, so the carried value was lost (Vera, B2 review item 4, toy t4c: call 2
STRESS 0.200 against the original's 0.210). The DATA value is now copied once,
on the first call, behind a SAVEd flag; on later calls the carried value
enters as incoming state, its derivative parts from the previous increment
dropped (local tangent: incoming state held fixed).

Behavioural, two calls in one process, against the ORIGINAL compiled on its own
(fresh process per FD evaluation, so the reference's DATA state is exact).
"""
from test_transform_a_value_set_before_the_seed_block_reaches_its_shadow import (
    DIRECTION, HEADER, TANGENT, assert_matches_the_original, build_original,
    build_transformed, needs_gfortran, transform)

SOURCE = HEADER + """      DIMENSION XI(1)
      DATA XI/1.D0/
      E=PROPS(1)
      CALL UPD(XI,DSTRAN,PROPS(1),STRESS,NTENS)
""" + TANGENT + """
      SUBROUTINE UPD(X,D,E,S,N)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION X(1),D(N),S(N)
      DO I=1,N
        S(I)=S(I)+E*X(1)*D(I)*(1.D0+1.D2*D(I))
      END DO
      X(1)=X(1)+1.D2*D(1)
      RETURN
      END
"""


@needs_gfortran
def test_the_helper_s_change_to_a_data_value_reaches_the_next_call(tmp_path):
    code, summary, output, source = transform(tmp_path, SOURCE)
    assert code == 0, summary
    original = build_original(tmp_path, source)
    transformed = build_transformed(output)
    increments = [[1e-3 * v for v in DIRECTION]] * 3
    assert_matches_the_original(original, transformed, [100.0, 0.3, 1.0], [0.0], increments)
