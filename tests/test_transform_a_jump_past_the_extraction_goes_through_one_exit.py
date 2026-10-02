"""A jump out of the hoisted-over block reaches the extraction through one exit.

The extractions are hoisted to the end of the outermost block enclosing their
insertion point. ``IF (..) GOTO 200`` inside that block, to a label after it,
skipped the hoisted copy-out and DDSDDE altogether (Vera, B2 review item 2,
toy t2d: primal relative error 1.0, DDSDDE 0 against FD ~100). Any jump --
unconditional, computed GO TO, arithmetic IF -- from at or before the
insertion point to a label after it now gives the routine one exit
(RETURN -> GO TO 99999) where the extractions run.

Behavioural, against the ORIGINAL compiled on its own (harness in
test_transform_a_value_set_before_the_seed_block_reaches_its_shadow).
"""
import pytest

from test_transform_a_value_set_before_the_seed_block_reaches_its_shadow import (
    DIRECTION, HEADER, assert_matches_the_original, build_original, build_transformed,
    needs_gfortran, transform)


def body(jump: str) -> str:
    return HEADER + """      E=PROPS(1)
      IF (STATEV(2).GT.0.5D0) THEN
        DO I=1,NTENS
          STRESS(I)=STRESS(I)+E*DSTRAN(I)*(1.D0+1.D3*DSTRAN(I)**2)
        END DO
        DO I=1,NTENS
          DO J=1,NTENS
            DDSDDE(I,J)=0.D0
          END DO
          DDSDDE(I,I)=E
        END DO
""" + jump + """
        STRESS(1)=STRESS(1)+E*DSTRAN(2)
      ELSE
        DO I=1,NTENS
          STRESS(I)=STRESS(I)+2.D0*E*DSTRAN(I)
        END DO
        DO I=1,NTENS
          DO J=1,NTENS
            DDSDDE(I,J)=0.D0
          END DO
          DDSDDE(I,I)=2.D0*E
        END DO
      END IF
      SSE=1.D0
  200 CONTINUE
      RETURN
      END
"""


JUMPS = {
    "goto": "        IF (PROPS(3).GT.0.D0) GOTO 200",
    "computed_goto": "        K=1\n        IF (PROPS(3).LT.0.D0) K=2\n        GO TO (200,210), K\n  210   CONTINUE",
    "arithmetic_if": "        IF (PROPS(3)) 210,210,200\n  210   CONTINUE",
}


@needs_gfortran
@pytest.mark.parametrize("kind", sorted(JUMPS))
@pytest.mark.parametrize("taken", [True, False], ids=["jump_taken", "jump_not_taken"])
def test_the_extraction_runs_whether_or_not_the_jump_is_taken(tmp_path, kind, taken):
    code, summary, output, source = transform(tmp_path, body(JUMPS[kind]))
    assert code == 0, summary
    text = (output / "material_oti.for").read_text()
    assert "GO TO 99999" in text.upper()
    original = build_original(tmp_path, source)
    transformed = build_transformed(output)
    increments = [[1e-3 * v for v in DIRECTION]] * 2
    assert_matches_the_original(original, transformed, [100.0, 0.3, 1.0 if taken else -1.0],
                                [0.0, 1.0], increments)


def test_jump_targets_are_read_from_every_jump_form():
    from umat_oti.transform.control_blocks import _jump_targets

    assert _jump_targets("IF (X.GT.0) GOTO 200") == {"200"}
    assert _jump_targets("GO TO (10, 20,30), K") == {"10", "20", "30"}
    assert _jump_targets("IF (X-1.D0) 10,20,30") == {"10", "20", "30"}
    assert _jump_targets("GO TO N, (10,20)") == {"10", "20"}
    assert _jump_targets("GO TO N") is None
    assert _jump_targets("READ(5,*,END=40) X") == {"40"}
    assert _jump_targets("IF (X.GT.0) THEN") == set()
    assert _jump_targets("X = Y") == set()
