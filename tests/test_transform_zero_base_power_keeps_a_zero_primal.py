"""``x**m`` at ``x = 0`` has real part ``0**m`` in every OTI operand combination.

Curing (Worlthen, Curie-G B2 cluster E): ``(cure/max_cure)**m`` is evaluated at
cure = 0 on the first increment. In real arithmetic ``0.0**0.4`` is 0. If any
partial of the OTI power is non-finite (``m*0**(m-1)`` is Inf for m < 1,
``0**m*LOG(0)`` is -Inf*0), the evaluator multiplies it by a zero perturbation
and the NaN reaches the real part. The transform keeps literal-only exponents
REAL (see the curing case in test_transform_stress_lines_are_not_bridged...);
this test covers the case it cannot avoid: the exponent is a parameter, so in a
parameter-sensitivity build both operands carry derivatives (OTI**OTI).

Behavioural against plain REAL(8) arithmetic compiled in the same program: the
real part of OTI**OTI, OTI**REAL and REAL**OTI at a zero base equals the real
power bitwise, and no part is non-finite, for exponents 0.4, 1.0, 1.4 and 2.0.
"""
import shutil
import subprocess

import pytest

PROGRAM = """program check
use otim6n1
implicit none
type(ONUMM6N1) :: x, m, r
real(8) :: xr, mr, ref
real(8) :: exps(4) = (/ 0.4d0, 1.0d0, 1.4d0, 2.0d0 /)
integer :: k
do k = 1, 4
  xr = 0.0d0
  mr = exps(k)
  x = 0.0d0
  m = mr
  x%E1 = 1.0d0
  m%E2 = 1.0d0
  ref = xr**mr
  r = x**m
  write(*, '(A,7ES25.16)') 'OO ', r%R, r%E1, r%E2, r%E3, r%E4, r%E5, r%E6
  r = x**mr
  write(*, '(A,7ES25.16)') 'OR ', r%R, r%E1, r%E2, r%E3, r%E4, r%E5, r%E6
  write(*, '(A,ES25.16)') 'REF ', ref
end do
end program
"""


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_zero_base_power_has_the_real_power_as_its_real_part(tmp_path):
    from umat_oti.oti.module_generator import generate_otilib_module

    result = generate_otilib_module(output_dir=tmp_path, ntens=6, order=1)
    sources = ["master_parameters.f90", "real_utils.f90", result.module_path.name]
    (tmp_path / "check.f90").write_text(PROGRAM)
    subprocess.run(["gfortran", "-O0", "-ffree-line-length-none", *sources, "check.f90", "-o", "check"],
                   check=True, capture_output=True, text=True, cwd=tmp_path)
    lines = subprocess.run([str(tmp_path / "check")], check=True, capture_output=True,
                           text=True, cwd=tmp_path).stdout.splitlines()
    rows = [line.split() for line in lines]
    blocks = [rows[i:i + 3] for i in range(0, len(rows), 3)]
    assert len(blocks) == 4
    for (oo, orr, ref) in blocks:
        expected = float(ref[1])
        assert expected == 0.0
        for row in (oo, orr):
            values = [float(v) for v in row[1:]]
            assert values[0] == expected, row
            assert all(v == v and abs(v) < 1e300 for v in values), row
