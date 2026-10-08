"""SUM(array, DIM=d) over hypercomplex arrays: a linear reduction, so exact.

vCANN reduces rank 3 to 6 arrays with ``sum(x, dim=3)`` and
``sum(sum(y, dim=4), dim=3)``. A sum is linear: the derivative of the sum is the
sum of the derivatives. Rule (B20 RULES.md R7): oti_intrinsics declares
SUM(ARRAY, DIM) for ranks 2..6 only for a file that uses SUM(..., DIM=...); the
refusal stays for MASK= and for a positional second argument. Canaries: the
reduction axis is checked on non-cubic arrays (a wrong axis changes the shape or
the values), and SUM with a mask is still refused by the blocker scan.
"""
import shutil
import subprocess

import pytest

from umat_oti.oti.module_generator import generate_otilib_module
from umat_oti.transform.parameter_sensitivity_transform import _emit_intrinsic_extensions
from umat_oti.transform.source_transform import _unsupported_intrinsic_blockers

DRIVER = """program check
  use otim2n1
  use oti_intrinsics
  implicit none
  type(onumm2n1) :: a(2,3,4), s3(2,3), s2(2,4), t(2)
  integer :: i, j, k
  do k = 1, 4
    do j = 1, 3
      do i = 1, 2
        a(i,j,k) = real(i + 10*j + 100*k, 8)
        a(i,j,k)%e1 = real(i, 8)
        a(i,j,k)%e2 = real(k*j, 8)
      end do
    end do
  end do
  s3 = sum(a, dim=3)
  s2 = sum(a, dim=2)
  t = sum(sum(a, dim=3), dim=2)
  write (*, '(A,I0,1X,I0)') 'SHAPE3 ', size(s3,1), size(s3,2)
  write (*, '(A,I0,1X,I0)') 'SHAPE2 ', size(s2,1), size(s2,2)
  write (*, '(A,3ES24.15E3)') 'S3 ', s3(2,3)%r, s3(2,3)%e1, s3(2,3)%e2
  write (*, '(A,3ES24.15E3)') 'S2 ', s2(1,4)%r, s2(1,4)%e1, s2(1,4)%e2
  write (*, '(A,3ES24.15E3)') 'T ', t(2)%r, t(2)%e1, t(2)%e2
end program check
"""


@pytest.fixture(scope="module")
def output(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required")
    out = tmp_path_factory.mktemp("sum_dim")
    module = generate_otilib_module(output_dir=out, ntens=2)
    (out / "oti_intrinsics.f90").write_text(
        _emit_intrinsic_extensions(module.module_name, module.type_name, sum_dim=True), encoding="ascii")
    (out / "driver.f90").write_text(DRIVER, encoding="ascii")
    done = subprocess.run([compiler, "-O0", "-ffree-line-length-none", module.master_parameters_path.name,
                           module.real_utils_path.name, module.module_path.name, "oti_intrinsics.f90",
                           "driver.f90", "-o", "check"], cwd=out, text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr
    run = subprocess.run([str(out / "check")], text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    return {line.split()[0]: [float(v) for v in line.split()[1:]] for line in run.stdout.splitlines()}


def test_the_reduction_axis_and_the_shape_are_right(output):
    assert output["SHAPE3"] == [2.0, 3.0]          # dim=3 removes the extent 4
    assert output["SHAPE2"] == [2.0, 4.0]          # dim=2 removes the extent 3


def test_values_and_derivatives_are_the_sums(output):
    i, j, k_all, j_all = 2, 3, range(1, 5), range(1, 4)
    assert output["S3"] == pytest.approx([sum(i + 10 * j + 100 * k for k in k_all),
                                          float(i) * 4, float(sum(k * j for k in k_all))])
    i, k = 1, 4
    assert output["S2"] == pytest.approx([sum(i + 10 * j + 100 * k for j in j_all),
                                          float(i) * 3, float(sum(k * j for j in j_all))])
    # sum over dim 3 then dim 2 of element i=2: all 12 (j,k) pairs
    total = sum(2 + 10 * j + 100 * k for j in j_all for k in k_all)
    assert output["T"] == pytest.approx([total, 2.0 * 12, float(sum(k * j for j in j_all for k in k_all))])


def test_the_generic_is_absent_unless_asked_for():
    assert "oti_sum_d3" not in _emit_intrinsic_extensions("otim2n1", "ONUMM2N1")
    assert "oti_sum_d3" in _emit_intrinsic_extensions("otim2n1", "ONUMM2N1", sum_dim=True)


def _blockers(statement):
    source = f"      X = {statement}\n"
    return _unsupported_intrinsic_blockers(source, {"seed": set(), "promote": {"A"}},
                                           [{"start_line": 1, "end_line": 1}])


def test_a_keyword_dim_is_accepted_and_canary_a_mask_is_still_refused():
    assert _blockers("SUM(A, DIM=3)") == []
    assert _blockers("SUM(SUM(A, DIM=4), DIM=3)") == []
    assert _blockers("SUM(A, MASK=A.GT.0.D0)")
    assert _blockers("SUM(A, 3)")
