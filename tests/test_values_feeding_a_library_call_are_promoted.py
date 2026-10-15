"""A value that reaches the stress only through a library call is on the stress path.

``FACTOR = 1 + ALPHA*(EPS(1)**2 + ...)`` scaled a compliance matrix S that was
then inverted with ``CALL DGESV(NTENS, 1, S, 6, IPIV, B, 6, INFO)``. The
dependency scan had no edge through DGESV (the file does not define it; the
transform supplies its body later), so FACTOR was not on the stress path: S was
promoted at the call, FACTOR was emitted as ``FACTOR = REAL(...)``, the stress
stayed right and every derivative through FACTOR was lost (the Abaqus gate
called it derivative_truncated). The scan now reads the supplied bodies for
their effect like an author's helper.

Each variant is transformed, built, and its tangent compared with central
differences of the original; the converted source must keep no REAL() cast of
a seed-carrying value.
"""
from __future__ import annotations

import ctypes as C
import json
import shutil
import subprocess
import sys

import numpy as np
import pytest

from test_library_routines import HEADER, _original_library, _transformed_library, call_umat

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")

DECLARE = """      DIMENSION S(6,6), B(6), EPS(6), D(6)
      INTEGER IPIV(6), INFO
      E = PROPS(1)
      XNU = 0.3D0
      ALPHA = 4000.0D0
      DO I = 1, NTENS
        EPS(I) = STRAN(I) + DSTRAN(I)
      END DO
"""

FACTOR_EXPRESSION = """      FACTOR = 1.0D0 + ALPHA*(EPS(1)**2 + EPS(2)**2 + EPS(3)**2
     1       + EPS(4)**2 + EPS(5)**2 + EPS(6)**2)
"""

FACTOR_LOOP = """      FACTOR = 1.0D0
      DO I = 1, NTENS
        FACTOR = FACTOR + ALPHA*EPS(I)*EPS(I)
      END DO
"""


def _compliance(scale: str) -> str:
    return f"""      DO I = 1, 6
        DO J = 1, 6
          S(I,J) = 0.0D0
        END DO
      END DO
      DO I = 1, 3
        DO J = 1, 3
          S(I,J) = -XNU/E*{scale}
        END DO
        S(I,I) = {scale}/E
        S(I+3,I+3) = 2.0D0*(1.0D0+XNU)/E*{scale}
      END DO
"""


SOLVE_AND_FINISH = """      CALL DGESV(NTENS, 1, S, 6, IPIV, B, 6, INFO)
      DO I = 1, NTENS
        STRESS(I) = B(I)
      END DO
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = E
      END DO
      RETURN
      END
"""

RHS_FROM_EPS = """      DO I = 1, NTENS
        B(I) = EPS(I)
      END DO
"""

VARIANTS = {
    # the original pattern: a scalar built from the strain scales the matrix
    "scalar_into_matrix": DECLARE + FACTOR_EXPRESSION + _compliance("FACTOR") + RHS_FROM_EPS
    + SOLVE_AND_FINISH,
    # the same scalar accumulated in a loop
    "accumulated_scalar_into_matrix": DECLARE + FACTOR_LOOP + _compliance("FACTOR") + RHS_FROM_EPS
    + SOLVE_AND_FINISH,
    # through an intermediate array
    "scalar_through_an_array": DECLARE + FACTOR_EXPRESSION + """      DO I = 1, 6
        D(I) = FACTOR*(1.0D0 + 0.1D0*I)
      END DO
""" + _compliance("D(I)") + RHS_FROM_EPS + SOLVE_AND_FINISH,
    # as the right-hand side, the matrix constant
    "scalar_into_the_right_hand_side": DECLARE + FACTOR_EXPRESSION + _compliance("1.0D0") + """      DO I = 1, NTENS
        B(I) = EPS(I)/FACTOR
      END DO
""" + SOLVE_AND_FINISH,
    # through an author's helper that builds the matrix
    "scalar_through_a_helper": (DECLARE + FACTOR_EXPRESSION
                                + "      CALL BUILDS(FACTOR, E, XNU, S)\n" + RHS_FROM_EPS + SOLVE_AND_FINISH
                                + """      SUBROUTINE BUILDS(F, E, XNU, S)
      IMPLICIT REAL*8 (A-H,O-Z)
      DIMENSION S(6,6)
""" + _compliance("F") + """      RETURN
      END
"""),
}


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_a_value_feeding_a_library_call_is_promoted_and_its_derivative_kept(tmp_path, name):
    umat = HEADER + VARIANTS[name]
    src = tmp_path / "src" / f"{name}.f"
    src.parent.mkdir(parents=True)
    src.write_text(umat)
    out = tmp_path / "out"
    done = subprocess.run([sys.executable, "-m", "umat_oti.cli", "jacobian", str(src), "--ntens", "6",
                           "--out", str(out)], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout[-3000:]
    report = json.loads((out / "transform_report.json").read_text())
    assert "FACTOR" in report["promoted_variables"], report["promoted_variables"]
    from umat_oti.abaqus.truncation import analyse
    truncation = analyse(next(out.glob(f"{name}_oti.f")).read_text())
    assert not truncation.drops_a_derivative, truncation.as_dict()
    transformed = C.CDLL(str(_transformed_library(out)))
    original = C.CDLL(str(_original_library(tmp_path, umat, name)))
    props = [200000.0]
    dstran = np.array([1.5e-2, 3e-3, 3e-3, 2e-3, -1e-3, 1e-3])
    stress, tangent = call_umat(transformed, props, dstran)
    np.testing.assert_allclose(stress, call_umat(original, props, dstran)[0], rtol=1e-13)
    h = 1e-8
    fd = np.zeros((6, 6))
    for j in range(6):
        e = np.zeros(6)
        e[j] = h
        fd[:, j] = (call_umat(original, props, dstran + e)[0] - call_umat(original, props, dstran - e)[0]) / (2 * h)
    np.testing.assert_allclose(tangent, fd, rtol=2e-6, atol=2e-6 * abs(fd).max())
