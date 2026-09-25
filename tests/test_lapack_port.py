from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from umat_oti.oti.lapack_port import _filter_overloaded_intrinsics, _preserve_scale_derivatives, port_reference
from umat_oti.oti import lapack_port


REFERENCE = Path(__file__).resolve().parents[1] / "out" / "lapack_reference_v3.12.1"
KERNELS = ["DAXPY", "DCOPY", "DDOT", "DSCAL", "DSWAP"]

DRIVER = """
program verify_blas
  use otim2n1
  implicit none
  type(ONUMM2N1) :: values_x(20), values_y(20), scale, answer
  type(ONUMM2N1), external :: ddot_oti
  real(8), external :: ddot
  real(8) :: alpha, step, real_x(20), real_y(20), real_alpha, real_answer
  integer :: operation, count, stride_x, stride_y, position, direction, side
  read(*,*) operation, count, stride_x, stride_y, alpha
  scale = alpha
  scale%e1 = 0.4d0
  scale%e2 = -0.3d0
  do position = 1, 20
    values_x(position) = real(position,8)
    values_y(position) = 2.0d0 - 0.1d0*position
    values_x(position)%e1 = 0.1d0*position
    values_x(position)%e2 = -0.2d0*position
    values_y(position)%e1 = -0.05d0*position
    values_y(position)%e2 = 0.07d0*position
  end do
  select case(operation)
  case(1)
    call daxpy_oti(count, scale, values_x, stride_x, values_y, stride_y)
  case(2)
    call dcopy_oti(count, values_x, stride_x, values_y, stride_y)
  case(3)
    answer = ddot_oti(count, values_x, stride_x, values_y, stride_y)
  case(4)
    call dscal_oti(count, scale, values_x, stride_x)
  case(5)
    call dswap_oti(count, values_x, stride_x, values_y, stride_y)
  end select
  if(operation == 3) then
    write(*,'(3ES26.17)') answer%r, answer%e1, answer%e2
  else
    do position = 1, 20
      write(*,'(3ES26.17)') values_x(position)%r, values_x(position)%e1, values_x(position)%e2
      write(*,'(3ES26.17)') values_y(position)%r, values_y(position)%e1, values_y(position)%e2
    end do
  end if
  do direction = 0, 2
    do side = -1, 1, 2
      step = side * 1.0d-5
      if(direction == 0) step = 0.0d0
      real_alpha = alpha
      if(direction == 1) real_alpha = alpha + 0.4d0*step
      if(direction == 2) real_alpha = alpha - 0.3d0*step
      do position = 1, 20
        real_x(position) = real(position,8)
        real_y(position) = 2.0d0 - 0.1d0*position
        if(direction == 1) then
          real_x(position) = real_x(position) + step*0.1d0*position
          real_y(position) = real_y(position) - step*0.05d0*position
        else if(direction == 2) then
          real_x(position) = real_x(position) - step*0.2d0*position
          real_y(position) = real_y(position) + step*0.07d0*position
        end if
      end do
      select case(operation)
      case(1)
        call daxpy(count, real_alpha, real_x, stride_x, real_y, stride_y)
      case(2)
        call dcopy(count, real_x, stride_x, real_y, stride_y)
      case(3)
        real_answer = ddot(count, real_x, stride_x, real_y, stride_y)
      case(4)
        call dscal(count, real_alpha, real_x, stride_x)
      case(5)
        call dswap(count, real_x, stride_x, real_y, stride_y)
      end select
      if(operation == 3) then
        write(*,'(ES26.17)') real_answer
      else
        do position = 1, 20
          write(*,'(ES26.17)') real_x(position)
          write(*,'(ES26.17)') real_y(position)
        end do
      end if
    end do
  end do
end program verify_blas
"""


@pytest.fixture(scope="module")
def reference_tree():
    source = Path(os.environ.get("UMAT_OTI_LAPACK_SOURCE", REFERENCE)).resolve()
    if not source.is_dir():
        pytest.skip("Public LAPACK v3.12.1 checkout absent; set UMAT_OTI_LAPACK_SOURCE")
    return source


@pytest.fixture(scope="module")
def compiled_kernels(reference_tree, tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran is required for numerical LAPACK port tests")
    output = tmp_path_factory.mktemp("lapack_port")
    report = port_reference(reference_tree, output, routines=KERNELS, compile_generated=True)
    assert report["counts"] == {"compiled_unverified": len(KERNELS)}, report
    assert report["numerically_verified"] is False
    assert report["supported_library"] is False
    assert (output / "LAPACK_LICENSE.txt").read_bytes() == (reference_tree / "LICENSE").read_bytes()
    driver = output / "verify_blas.f90"
    driver.write_text(DRIVER, encoding="ascii")
    executable = output / "verify_blas"
    built = subprocess.run(
        [compiler, "-ffree-line-length-none", "-fcheck=all", str(driver),
         *[str(path) for path in output.glob("*.o")],
         *[str(reference_tree / "BLAS" / "SRC" / f"{name.lower()}.f") for name in KERNELS],
         "-o", str(executable)], cwd=output, capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    return executable


@pytest.mark.fortran
@pytest.mark.integration
@pytest.mark.parametrize("operation", range(1, 6), ids=KERNELS)
def test_blas_values_and_two_derivative_directions(compiled_kernels, operation):
    for count in (0, 1, 3, 7):
        for stride_x, stride_y in ((1, 1), (2, 1), (-1, 2), (-2, -1)):
            for alpha in (0.0, 1.0, 2.5):
                result = subprocess.run([str(compiled_kernels)],
                                        input=f"{operation} {count} {stride_x} {stride_y} {alpha}\n",
                                        capture_output=True, text=True)
                case = (KERNELS[operation - 1], count, stride_x, stride_y, alpha)
                assert result.returncode == 0, (case, result.stderr)
                values = np.fromstring(result.stdout, sep=" ")
                size = 1 if operation == 3 else 40
                actual = values[:3 * size].reshape(size, 3)
                reference = values[3 * size:].reshape(3, 2, size)
                expected = np.column_stack((reference[0, 0],
                                            (reference[1, 1] - reference[1, 0]) / 2.0e-5,
                                            (reference[2, 1] - reference[2, 0]) / 2.0e-5))
                np.testing.assert_allclose(actual, expected, rtol=2e-8, atol=2e-8, err_msg=str(case))


def test_report_does_not_claim_compilation_is_library_support(compiled_kernels):
    report = json.loads((compiled_kernels.parent / "port_report.json").read_text())
    assert report["supported_library"] is False
    assert all(row["numerically_verified"] is False for row in report["routines"].values())
    assert report["scanned_file_count"] > 0
    assert "SRC/la_constants.f90" in report["files_without_indexed_routines"]
    assert "GNU Fortran" in report["compiler_version"]


def test_missing_reference_license_is_refused(tmp_path):
    with pytest.raises(ValueError, match="LICENSE"):
        port_reference(tmp_path / "reference", tmp_path / "output")


def test_output_cannot_be_in_reference_tree(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        port_reference(tmp_path, tmp_path / "generated")


def test_intrinsic_filter_preserves_unrelated_declarations():
  source, changes = _filter_overloaded_intrinsics(
    "    INTRINSIC MAX, MOD, SQRT\n    intrinsic :: MIN\n    answer = sqrt(value)\n",
    {"MAX", "MIN", "SQRT"})
  assert source == "    intrinsic :: MOD\n    answer = sqrt(value)\n"
  assert len(changes) == 3


def test_scale_rewrite_refuses_changed_source():
  with pytest.raises(ValueError, match="not found exactly once"):
    _preserve_scale_derivatives("DAXPY", "subroutine daxpy_oti()\nend\n")


@pytest.mark.fortran
@pytest.mark.integration
def test_lapack_intrinsic_declarations_no_longer_block_compilation(reference_tree, tmp_path):
  if shutil.which("gfortran") is None:
    pytest.skip("gfortran required")
  report = port_reference(reference_tree, tmp_path, routines=["DGEMM", "DGETRF", "DGETRS", "DSPEVD"],
              compile_generated=True)
  assert report["counts"] == {"compiled_unverified": 4}, report
  assert report["supported_library"] is False


@pytest.mark.parametrize("revision,status,message", [
  ("wrong-commit", "", "Expected Reference"),
  (lapack_port.REFERENCE_COMMIT, " M SRC/dgetrf.f", "must be clean"),
  (lapack_port.REFERENCE_COMMIT, "?? SRC/extra.f", "must be clean"),
])
def test_reference_provenance_is_enforced(tmp_path, monkeypatch, revision, status, message):
  source = tmp_path / "reference"
  for relative in ("SRC", "BLAS/SRC", "INSTALL"):
    (source / relative).mkdir(parents=True)
  (source / "LICENSE").write_text("synthetic fixture", encoding="ascii")

  def git_result(command, **kwargs):
    assert command[0] == "git"
    return subprocess.CompletedProcess(command, 0, revision if "rev-parse" in command else status, "")

  monkeypatch.setattr(lapack_port.subprocess, "run", git_result)
  with pytest.raises(ValueError, match=message):
    port_reference(source, tmp_path / "output")
  assert not (tmp_path / "output").exists()