"""Two-argument OTI functions at order 2 (F2EVAL): pure second-order terms.

x**y with x = 2 + e1, y = 3 + e2 has Taylor coefficients (stored value = derivative / multiplicity!):
    e1e1 : y(y-1) x^(y-2) / 2 = 6        e1e2 : x^(y-1)(1 + y ln x) = 12.3178
    e2e2 : x^y ln(x)^2 / 2   = 1.9218
The generated F2EVAL once divided every second-order term by 1 (stub get_deriv_factor
returned 1.0), doubling the e1e1 and e2e2 coefficients.
"""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import pytest

from umat_oti.oti.module_generator import generate_otilib_module

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran is required")

PROGRAM = """program t
  use otim2n2
  implicit none
  type(onumm2n2) :: x, y, z
  x = 2.0_dp + e1
  y = 3.0_dp + e2
  z = x**y
  print '(3ES24.15)', getim(z,3), getim(z,4), getim(z,5)
end program
"""
EXPECTED = (3 * 2 * 2 / 2.0, 2.0 ** 2 * (1 + 3 * math.log(2.0)), 2.0 ** 3 * math.log(2.0) ** 2 / 2)


def _run(directory: Path, *, plant_old_divisor: bool) -> tuple[float, float, float]:
    generate_otilib_module(output_dir=directory, ntens=2, order=2)
    module = directory / "otim2n2.f90"
    text = module.read_text()
    if plant_old_divisor:
        assert "COEF = DER2_0 / 2.0_DP" in text and "COEF = DER2_2 / 2.0_DP" in text
        text = text.replace("COEF = DER2_0 / 2.0_DP", "COEF = DER2_0 / 1.0_DP").replace(
            "COEF = DER2_2 / 2.0_DP", "COEF = DER2_2 / 1.0_DP")
        module.write_text(text)
    flags = ["gfortran", "-std=legacy", "-ffree-line-length-none"]
    for name in ("master_parameters.f90", "real_utils.f90", "otim2n2.f90"):
        subprocess.run(flags + ["-c", name], cwd=directory, check=True, capture_output=True)
    (directory / "t.f90").write_text(PROGRAM)
    subprocess.run(flags + ["t.f90", "master_parameters.o", "real_utils.o", "otim2n2.o", "-o", "t"],
                   cwd=directory, check=True, capture_output=True)
    out = subprocess.run([str(directory / "t")], cwd=directory, check=True, capture_output=True, text=True).stdout
    return tuple(float(v) for v in out.split())


def test_pow_oo_second_order_coefficients(tmp_path: Path):
    got = _run(tmp_path, plant_old_divisor=False)
    assert got == pytest.approx(EXPECTED, rel=1e-13)


def test_canary_old_divisor_is_detected(tmp_path: Path):
    """Planted error: with the old divisor the same check must fail on e1e1 and e2e2 (x2), not on e1e2."""
    got = _run(tmp_path, plant_old_divisor=True)
    assert got[0] == pytest.approx(2 * EXPECTED[0], rel=1e-13)
    assert got[2] == pytest.approx(2 * EXPECTED[2], rel=1e-13)
    assert got[1] == pytest.approx(EXPECTED[1], rel=1e-13)
    assert got != pytest.approx(EXPECTED, rel=1e-6)
