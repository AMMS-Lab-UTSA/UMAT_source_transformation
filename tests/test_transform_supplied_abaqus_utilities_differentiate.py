"""The supplied SPRINC/SPRIND/SINV/DGESV/DGETRI bodies: values and derivatives.

A UMAT that calls a solver utility publishes no body for it, so the lifter
refused it ("Helper lifting requires source definitions for ['SPRINC']": five
D2 sources in damage, growth and hyperelasticity, plus LAPACK DGESV/DGETRI in
five plasticity/damage sources). The bodies are now supplied
(``abaqus_utility_definitions``) and lifted like an author's helper. These
tests check them against references independent of that code:

* values and first derivatives of SPRINC/SPRIND against numpy's LAPACK
  eigensolver (``eigh``) and the analytical eigenvalue derivative
  ``dlambda_k = n_k . dS . n_k`` (distinct eigenvalues), in every Voigt layout
  Abaqus uses (NDI/NSHR = 3/3, 3/1, 2/1) and both LSTR conventions;
* SINV against the closed forms tr(sigma)/3 and sqrt(3/2 s:s) and their
  analytical derivatives;
* DGESV/DGETRI against numpy.linalg.solve/inv and dx = A^-1 (db - dA x),
  d(A^-1) = -A^-1 dA A^-1.

The bodies are compiled twice from the same text -- lifted to the OTI type,
and as plain REAL*8 Fortran -- and both builds must agree with numpy.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from umat_oti.fortran.parser import parse_fortran_file
from umat_oti.oti.module_generator import generate_otilib_module
from umat_oti.transform.abaqus_utility_definitions import (
    UTILITY_DEFINITIONS, available_definitions, definition_text)
from umat_oti.transform.helper_lifting import lift_helper_set_source, wrap_free_form
from umat_oti.transform.parameter_sensitivity_transform import _emit_intrinsic_extensions

ABA_PARAM = "      implicit real*8(a-h,o-z)\n      parameter (nprecd=2)\n"

OTI_DRIVER = """
program check_utilities
  use utility_backend
  use otim2n1
  implicit none
  character(len=8) :: what
  integer :: ndi, nshr, lstr, k, i, n, nrhs, info
  type(ONUMM2N1) :: s(6), ps(3), an(3,3), sinv1, sinv2
  type(ONUMM2N1), allocatable :: a(:,:), b(:,:), work(:)
  integer, allocatable :: ipiv(:)
  read(*,*) what
  if (what == 'SPRIND' .or. what == 'SPRINC' .or. what == 'SINV') then
    read(*,*) ndi, nshr, lstr
    do k = 1, ndi + nshr
      read(*,*) s(k)%r, s(k)%e1, s(k)%e2
    end do
    if (what == 'SPRIND') then
      call sprind_oti(s, ps, an, lstr, ndi, nshr)
    else if (what == 'SPRINC') then
      call sprinc_oti(s, ps, lstr, ndi, nshr)
      an = 0.0d0
    else
      call sinv_oti(s, sinv1, sinv2, ndi, nshr)
      write(*,'(3ES27.17E3)') sinv1%r, sinv1%e1, sinv1%e2
      write(*,'(3ES27.17E3)') sinv2%r, sinv2%e1, sinv2%e2
      stop
    end if
    do k = 1, 3
      write(*,'(3ES27.17E3)') ps(k)%r, ps(k)%e1, ps(k)%e2
    end do
    do k = 1, 3
      do i = 1, 3
        write(*,'(3ES27.17E3)') an(k,i)%r, an(k,i)%e1, an(k,i)%e2
      end do
    end do
  else
    read(*,*) n, nrhs
    allocate(a(n,n), b(n,max(nrhs,1)), ipiv(n), work(n))
    do i = 1, n
      do k = 1, n
        read(*,*) a(i,k)%r, a(i,k)%e1, a(i,k)%e2
      end do
    end do
    do i = 1, n
      do k = 1, nrhs
        read(*,*) b(i,k)%r, b(i,k)%e1, b(i,k)%e2
      end do
    end do
    if (what == 'DGESV') then
      call dgesv_oti(n, nrhs, a, n, ipiv, b, n, info)
      write(*,*) info
      do i = 1, n
        do k = 1, nrhs
          write(*,'(3ES27.17E3)') b(i,k)%r, b(i,k)%e1, b(i,k)%e2
        end do
      end do
    else
      call dgetrf_oti(n, n, a, n, ipiv, info)
      call dgetri_oti(n, a, n, ipiv, work, n, info)
      write(*,*) info
      do i = 1, n
        do k = 1, n
          write(*,'(3ES27.17E3)') a(i,k)%r, a(i,k)%e1, a(i,k)%e2
        end do
      end do
    end if
  end if
end program check_utilities
"""

REAL_DRIVER = """
program check_real
  implicit none
  integer :: ndi, nshr, lstr, k, i
  double precision :: s(6), ps(3), an(3,3)
  read(*,*) ndi, nshr, lstr
  do k = 1, ndi + nshr
    read(*,*) s(k)
  end do
  call sprind(s, ps, an, lstr, ndi, nshr)
  do k = 1, 3
    write(*,'(ES27.17E3)') ps(k)
  end do
  do k = 1, 3
    do i = 1, 3
      write(*,'(ES27.17E3)') an(k,i)
    end do
  end do
end program check_real
"""

NAMES = ["SPRIND", "SPRINC", "SINV", "DGESV", "DGETRI"]


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required")
    output = tmp_path_factory.mktemp("abaqus_utilities")
    (output / "ABA_PARAM.INC").write_text(ABA_PARAM)
    module = generate_otilib_module(output_dir=output, ntens=2)
    source = output / "utilities.for"
    source.write_text(definition_text(NAMES), encoding="ascii")
    names = list(available_definitions(NAMES))
    lifted = lift_helper_set_source(parse_fortran_file(source), names,
                                    module_name=module.module_name, type_name=module.type_name)
    (output / "oti_intrinsics.f90").write_text(
        _emit_intrinsic_extensions(module.module_name, module.type_name), encoding="ascii")
    (output / "utility_backend.f90").write_text(
        "module utility_backend\ncontains\n" + wrap_free_form(lifted.source)
        + "end module utility_backend\n", encoding="ascii")
    (output / "driver.f90").write_text(OTI_DRIVER, encoding="ascii")
    oti = output / "check_oti"
    result = subprocess.run(
        [compiler, "-O0", "-fcheck=all", "-ffree-line-length-none",
         module.master_parameters_path.name, module.real_utils_path.name, module.module_path.name,
         "oti_intrinsics.f90", "utility_backend.f90", "driver.f90", "-o", str(oti)],
        cwd=output, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    (output / "real_driver.f90").write_text(REAL_DRIVER, encoding="ascii")
    real = output / "check_real"
    result = subprocess.run([compiler, "-O0", "-std=legacy", "-fcheck=all", f"-I{output}",
                             str(source), "real_driver.f90", "-o", str(real)],
                            cwd=output, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return oti, real


def _voigt(tensor: np.ndarray, ndi: int, nshr: int, lstr: int) -> np.ndarray:
    factor = 2.0 if lstr == 2 else 1.0
    direct = [tensor[i, i] for i in range(ndi)]
    shears = [tensor[0, 1], tensor[0, 2], tensor[1, 2]][:nshr]
    return np.array(direct + [factor * value for value in shears])


def _tensor_of_layout(rng, ndi: int, nshr: int) -> np.ndarray:
    tensor = rng.normal(size=(3, 3))
    tensor = tensor + tensor.T
    if ndi < 3:
        tensor[2, :] = tensor[:, 2] = 0.0
    if nshr < 3:
        tensor[0, 2] = tensor[2, 0] = tensor[1, 2] = tensor[2, 1] = 0.0
    return tensor


def _run(executable: Path, text: str) -> np.ndarray:
    result = subprocess.run([str(executable)], input=text, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return np.array([float(v) for v in result.stdout.split()])


def _spectral_input(what, ndi, nshr, lstr, values, seeds):
    lines = [what, f"{ndi} {nshr} {lstr}"]
    for k in range(ndi + nshr):
        lines.append(f"{values[k]:.17e} {seeds[0][k]:.17e} {seeds[1][k]:.17e}")
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("ndi,nshr", [(3, 3), (3, 1), (2, 1)])
@pytest.mark.parametrize("lstr", [1, 2])
def test_principal_values_directions_and_their_derivatives(builds, ndi, nshr, lstr):
    oti, real = builds
    rng = np.random.default_rng(100 * ndi + 10 * nshr + lstr)
    tensor = _tensor_of_layout(rng, ndi, nshr)
    dirs = [_tensor_of_layout(rng, ndi, nshr) for _ in range(2)]
    values = _voigt(tensor, ndi, nshr, lstr)
    seeds = [_voigt(d, ndi, nshr, lstr) for d in dirs]
    out = _run(oti, _spectral_input("SPRIND", ndi, nshr, lstr, values, seeds)).reshape(-1, 3)
    principal, directions = out[:3], out[3:].reshape(3, 3, 3)
    reference, vectors = np.linalg.eigh(tensor)              # ascending
    np.testing.assert_allclose(principal[:, 0], reference, rtol=1e-12, atol=1e-12)
    for k in range(3):
        vector = directions[k, :, 0]                          # AN(K,1..3)
        np.testing.assert_allclose(tensor @ vector, reference[k] * vector, atol=1e-11)
        assert abs(np.dot(vector, vectors[:, k])) == pytest.approx(1.0, abs=1e-11)
        for direction, d in enumerate(dirs, start=1):
            # dlambda_k = n_k . dS . n_k, for distinct eigenvalues.
            assert principal[k, direction] == pytest.approx(vectors[:, k] @ d @ vectors[:, k],
                                                            rel=1e-10, abs=1e-12)
    # The same text compiled as plain REAL*8 gives the same values.
    plain = _run(real, _spectral_input("", ndi, nshr, lstr, values, seeds).split("\n", 1)[1])
    np.testing.assert_allclose(plain[:3], principal[:, 0], rtol=1e-14, atol=1e-14)


def test_sprinc_returns_the_values_sprind_returns(builds):
    oti, _ = builds
    rng = np.random.default_rng(7)
    tensor = _tensor_of_layout(rng, 3, 3)
    seeds = [_voigt(_tensor_of_layout(rng, 3, 3), 3, 3, 1) for _ in range(2)]
    values = _voigt(tensor, 3, 3, 1)
    both = _run(oti, _spectral_input("SPRIND", 3, 3, 1, values, seeds)).reshape(-1, 3)[:3]
    only = _run(oti, _spectral_input("SPRINC", 3, 3, 1, values, seeds)).reshape(-1, 3)[:3]
    np.testing.assert_array_equal(both, only)


def test_a_repeated_pair_keeps_the_sum_of_its_derivatives(builds):
    """Uniaxial tension: two principal values are equal (here both zero).

    Each member of the pair has no derivative of its own; their sum does, and
    the averaged pair carries exactly half of it each.
    """
    oti, _ = builds
    tensor = np.diag([2.0, 0.0, 0.0])
    d = np.array([[0.1, 0.3, 0.0], [0.3, 0.5, 0.2], [0.0, 0.2, -0.1]])
    values = _voigt(tensor, 3, 3, 1)
    seeds = [_voigt(d, 3, 3, 1), _voigt(np.zeros((3, 3)), 3, 3, 1)]
    out = _run(oti, _spectral_input("SPRINC", 3, 3, 1, values, seeds)).reshape(-1, 3)[:3]
    np.testing.assert_allclose(out[:, 0], [0.0, 0.0, 2.0], atol=1e-12)
    pair_trace_rate = d[1, 1] + d[2, 2]                      # trace of the pair block
    np.testing.assert_allclose(out[:2, 1], [pair_trace_rate / 2] * 2, atol=1e-12)
    assert out[2, 1] == pytest.approx(d[0, 0], abs=1e-12)


@pytest.mark.parametrize("ndi,nshr", [(3, 3), (3, 1), (2, 1)])
def test_sinv_is_the_mean_and_mises_stress_with_their_derivatives(builds, ndi, nshr):
    oti, _ = builds
    rng = np.random.default_rng(31 + ndi + nshr)
    tensor = _tensor_of_layout(rng, ndi, nshr)
    dirs = [_tensor_of_layout(rng, ndi, nshr) for _ in range(2)]
    out = _run(oti, _spectral_input("SINV", ndi, nshr, 1, _voigt(tensor, ndi, nshr, 1),
                                     [_voigt(d, ndi, nshr, 1) for d in dirs])).reshape(2, 3)
    mean = np.trace(tensor) / 3.0
    deviator = tensor - mean * np.eye(3)
    mises = np.sqrt(1.5 * np.sum(deviator * deviator))
    assert out[0, 0] == pytest.approx(mean, rel=1e-13, abs=1e-13)
    assert out[1, 0] == pytest.approx(mises, rel=1e-13)
    for k, d in enumerate(dirs, start=1):
        assert out[0, k] == pytest.approx(np.trace(d) / 3.0, rel=1e-12, abs=1e-13)
        # d(mises) = 3/2 s:ds / mises
        ds = d - np.trace(d) / 3.0 * np.eye(3)
        assert out[1, k] == pytest.approx(1.5 * np.sum(deviator * ds) / mises, rel=1e-11)


def _matrix_input(what, a, da, b=None, db=None):
    n = len(a)
    nrhs = 0 if b is None else b.shape[1]
    lines = [what, f"{n} {nrhs}"]
    for i in range(n):
        for k in range(n):
            lines.append(f"{a[i, k]:.17e} {da[0][i, k]:.17e} {da[1][i, k]:.17e}")
    for i in range(n):
        for k in range(nrhs):
            lines.append(f"{b[i, k]:.17e} {db[0][i, k]:.17e} {db[1][i, k]:.17e}")
    return "\n".join(lines) + "\n"


def test_dgesv_solves_and_differentiates(builds):
    oti, _ = builds
    rng = np.random.default_rng(5)
    a = rng.normal(size=(4, 4)) + 4 * np.eye(4)
    b = rng.normal(size=(4, 2))
    da = [rng.normal(size=(4, 4)) for _ in range(2)]
    db = [rng.normal(size=(4, 2)) for _ in range(2)]
    out = _run(oti, _matrix_input("DGESV", a, da, b, db))
    assert int(out[0]) == 0
    x = out[1:].reshape(4, 2, 3)
    expected = np.linalg.solve(a, b)
    np.testing.assert_allclose(x[:, :, 0], expected, rtol=1e-12, atol=1e-12)
    for k in range(2):
        rate = np.linalg.solve(a, db[k] - da[k] @ expected)
        np.testing.assert_allclose(x[:, :, k + 1], rate, rtol=1e-10, atol=1e-11)


def test_dgetri_inverts_and_differentiates(builds):
    oti, _ = builds
    rng = np.random.default_rng(9)
    a = rng.normal(size=(3, 3)) + 3 * np.eye(3)
    da = [rng.normal(size=(3, 3)) for _ in range(2)]
    out = _run(oti, _matrix_input("DGETRI", a, da))
    assert int(out[0]) == 0
    inverse = out[1:].reshape(3, 3, 3)
    expected = np.linalg.inv(a)
    np.testing.assert_allclose(inverse[:, :, 0], expected, rtol=1e-12, atol=1e-12)
    for k in range(2):
        np.testing.assert_allclose(inverse[:, :, k + 1], -expected @ da[k] @ expected,
                                   rtol=1e-10, atol=1e-11)


def test_supplying_a_routine_supplies_what_it_calls():
    assert set(available_definitions(["SPRINC"])) == {"SPRINC", "SPRIND", "DSPEVD"}
    assert set(available_definitions(["DGESV"])) == {"DGESV", "DGETRF", "DGETRS"}
    assert set(available_definitions(["DGETRI"])) == {"DGETRI", "DGETRS"}
    # No statement labels: the free-form conversion drops columns 1-5.
    import re
    for name, text in UTILITY_DEFINITIONS.items():
        assert not [line for line in text.splitlines() if re.match(r"^\s{0,4}\d+\s", line)], name


def test_the_emitted_file_keeps_calling_the_solvers_own_routine():
    """The supplied REAL body must not replace the solver's in the job."""
    from umat_oti.transform.abaqus_utility_definitions import strip_supplied_solver_bodies

    text = ("      SUBROUTINE UMAT\n      CALL SPRINC_OTI(A,B,1,3,3)\n      END\n"
            + definition_text(["SPRINC"]))
    stripped = strip_supplied_solver_bodies(text, ["SPRINC", "SPRIND", "DSPEVD"])
    assert "SUBROUTINE SPRINC(" not in stripped and "SUBROUTINE SPRIND(" not in stripped
    assert "SUBROUTINE DSPEVD(" in stripped        # a library routine, not the solver's
    assert "CALL SPRINC_OTI" in stripped
