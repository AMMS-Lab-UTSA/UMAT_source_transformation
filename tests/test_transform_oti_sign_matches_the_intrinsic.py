"""The OTI SIGN agrees with the intrinsic SIGN bit for bit, signed zeros and NaNs included.

oti_sign_oo/or/ro decided the sign with ``B < 0``, which is false for -0.0 and
for a NaN with its sign bit set, while gfortran's SIGN(A, -0.0) is -|A|; and
the magnitude came from ABS of the OTI value, so SIGN(-0.0, B) kept -0.0. The
sign is now the intrinsic's own decision, SIGN(1, B), and the real part is the
intrinsic's value. Checked here against the intrinsic over A, B in
{+-2.5, +-0.0, +-NaN} for all three argument kinds, real part bitwise, and the
derivative part as d|A| with the intrinsic's sign.
"""
import shutil
import subprocess

import pytest

from test_transform_a_value_at_a_hypercomplex_dummy_is_passed_as_one import HEAD
from _transform_vs_original import transform

PROGRAM = """program signs
  use otim6n1, OTI_E1 => E1
  use oti_intrinsics
  use, intrinsic :: ieee_arithmetic
  implicit none
  real(8) :: v(6), a, b, ref, got, d
  type(ONUMM6N1) :: x, y, r
  integer :: i, j, bad
  v(1) = 2.5d0; v(2) = -2.5d0; v(3) = 0.0d0; v(4) = -0.0d0
  v(5) = ieee_value(1.0d0, ieee_quiet_nan); v(6) = -v(5)
  bad = 0
  do i = 1, 6
    do j = 1, 6
      a = v(i); b = v(j)
      ref = sign(a, b)
      x = 3.0d0*OTI_E1
      x%R = a
      y = 5.0d0*OTI_E1
      y%R = b
      r = sign(x, y)
      if (transfer(r%R, 0_8) /= transfer(ref, 0_8)) bad = bad + 1
      r = sign(x, b)
      if (transfer(r%R, 0_8) /= transfer(ref, 0_8)) bad = bad + 1
      got = sign(a, y)
      if (transfer(got, 0_8) /= transfer(ref, 0_8)) bad = bad + 1
      if (abs(a) > 1.0d0) then
        d = sign(1.0d0, a)*sign(1.0d0, b)*3.0d0
        r = sign(x, y)
        if (r%E1 /= d) bad = bad + 1
      end if
    end do
  end do
  print *, bad
end program signs
"""


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_oti_sign_agrees_with_the_intrinsic_on_signed_zeros_and_nans(tmp_path):
    summary, code = transform(tmp_path, HEAD % {"first": "g*2.0d0"}, ".f90")
    assert code == 0, summary
    out = tmp_path / "out"
    (out / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    subprocess.run(["bash", "compile_hint.sh"], cwd=out, check=True, capture_output=True, text=True)
    (out / "signs.f90").write_text(PROGRAM)
    subprocess.run(["gfortran", "-I.", "signs.f90", "oti_intrinsics.o", "otim6n1.o",
                    "master_parameters.o", "real_utils.o", "-o", "signs"],
                   cwd=out, check=True, capture_output=True, text=True)
    bad = subprocess.run(["./signs"], cwd=out, check=True, capture_output=True, text=True).stdout.split()
    assert bad == ["0"]
