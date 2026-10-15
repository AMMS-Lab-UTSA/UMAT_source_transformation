"""Two small generalisations met on a plasticity UMAT with a Newton loop.

1. A LOGICAL assigned from a comparison of a differentiated value ("ELASTIC = (PHI_OTI .LE. TOL)") is
   left as it is; wrapping it in REAL(...) does not compile.
2. A UMAT that declares JSTEP(4) (the Abaqus 2021 interface) gets a 4-array from the provider wrappers.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.transform.source_transform import _is_logical_expression, _wrap_real_assignment_rhs  # noqa: E402


def test_a_comparison_is_logical_and_a_numeric_expression_is_not():
    assert _is_logical_expression("(PHI_OTI .LE. TOL)")
    assert _is_logical_expression("PHI_OTI .GT. 0.0D0 .AND. F_OTI < 1.0D0")
    assert not _is_logical_expression("MERGE(A_OTI, B, X .GT. Y)")
    assert not _is_logical_expression("(Q_OTI/SY0)**2 + 1.0D0")


def test_the_logical_assignment_is_not_wrapped_and_a_real_one_still_is():
    assert _wrap_real_assignment_rhs("      ELASTIC = (PHI_OTI .LE. TOL)") == "      ELASTIC = (PHI_OTI .LE. TOL)"
    assert "REAL(" in _wrap_real_assignment_rhs("      X = Q_OTI*2.0D0")


def test_the_wrappers_pass_a_four_array_when_asked():
    from umat_oti.provider import emit
    text = (",1,1,1,1,1,INCREMENT)\n" "NOEL,NPT,1,1,KSTEP,KINC)\n")
    original = emit._emit_wrappers
    try:
        emit._emit_wrappers = lambda *a, **k: text
        out = emit.emit_wrappers(None, ntens=6, nprops=1, nstatev=1, parameters=(("A", 1),), path_dependent=True,
                                 jstep_array=True)
        assert "(/1,1,0,0/),INCREMENT)" in out and "(/KSTEP,1,0,0/),KINC)" in out
        assert emit.emit_wrappers(None, ntens=6, nprops=1, nstatev=1, parameters=(("A", 1),),
                                  path_dependent=True) == text
    finally:
        emit._emit_wrappers = original
