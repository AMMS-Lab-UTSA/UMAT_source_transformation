"""Principal stretches by Cardano's formula in complex OTI arithmetic.

The eigenvalues of a symmetric C = F^T F are the roots of
lambda^3 - I1 lambda^2 + I2 lambda - I3. Cardano's formula reaches three REAL
roots only through complex intermediates (casus irreducibilis: the
discriminant is negative, so SQRT of it is imaginary and the cube roots are
complex), which is how the corpus's ``cs_cubic_roots`` computes them. Here the
same algorithm runs on the complex OTI type with C's six independent
components seeded as six OTI directions, and is checked against a real
eigen-solver:

* values: the roots' real parts against ``numpy.linalg.eigvalsh``, imaginary
  parts ~ 0;
* first derivatives: d lambda_k / d C_ij = v_k,i v_k,j (doubled for an
  off-diagonal pair perturbed together), the analytical result for distinct
  eigenvalues, with v_k the unit eigenvectors from numpy;
* principal stretches s_k = SQRT(lambda_k) and ds_k = d lambda_k / (2 s_k).
"""
from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from umat_oti.oti.complex_oti import generate_complex_oti_module
from umat_oti.oti.module_generator import generate_otilib_module

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")

PROGRAM = """
subroutine cs_cubic_roots(a, b, c, d, r1, r2, r3)
  ! Transcribed from the corpus (tengzhang48/abaqus_ufl, generated tensor_ops),
  ! with DOUBLE COMPLEX replaced by the complex OTI type -- what the transform does.
  use otim6n1
  use oti_complex
  implicit none
  type({z}), intent(in) :: a, b, c, d
  type({z}), intent(out) :: r1, r2, r3
  type({z}) :: p, q, Delta, sqrt_Delta, u, v, shift
  type({z}) :: t1, t2, t3, half, third, two, three, nine, twentyseven
  half  = DCMPLX(0.5d0, 0.0d0)
  third = DCMPLX(1.0d0/3.0d0, 0.0d0)
  two   = DCMPLX(2.0d0, 0.0d0)
  three = DCMPLX(3.0d0, 0.0d0)
  nine  = DCMPLX(9.0d0, 0.0d0)
  twentyseven = DCMPLX(27.0d0, 0.0d0)
  p = (three*a*c - b*b) / (three*a*a)
  q = (two*b**3 - nine*a*b*c + twentyseven*a*a*d) / (twentyseven*a**3)
  Delta = (q/two)**2 + (p/three)**3
  sqrt_Delta = SQRT(Delta)
  u = (-q/two + sqrt_Delta)**third
  IF (REAL(ABS(u)) .GT. 1.0d-30) THEN
    v = -p / (three*u)
  ELSE
    v = (-q/two - sqrt_Delta)**third
  END IF
  t1 = u + v
  t2 = -half*(u+v) + DCMPLX(0.0d0, DSQRT(3.0d0)/2.0d0)*(u-v)
  t3 = -half*(u+v) - DCMPLX(0.0d0, DSQRT(3.0d0)/2.0d0)*(u-v)
  shift = b / (three*a)
  r1 = t1 - shift
  r2 = t2 - shift
  r3 = t3 - shift
end subroutine cs_cubic_roots

program cardano
  use otim6n1
  use oti_complex
  implicit none
  type({t}) :: C(3,3), I1, I2, I3, stretch
  type({z}) :: a, b, cc, d, r(3)
  real(8) :: c0(6)
  integer :: k, n
  read(*,*) c0
  ! C11, C22, C33, C12, C13, C23 seeded as directions 1..6 (symmetric pairs together)
  C(1,1) = c0(1) + E1; C(2,2) = c0(2) + E2; C(3,3) = c0(3) + E3
  C(1,2) = c0(4) + E4; C(2,1) = C(1,2)
  C(1,3) = c0(5) + E5; C(3,1) = C(1,3)
  C(2,3) = c0(6) + E6; C(3,2) = C(2,3)
  I1 = C(1,1) + C(2,2) + C(3,3)
  I2 = C(1,1)*C(2,2) + C(2,2)*C(3,3) + C(1,1)*C(3,3) - C(1,2)**2 - C(1,3)**2 - C(2,3)**2
  I3 = C(1,1)*(C(2,2)*C(3,3) - C(2,3)*C(3,2)) - C(1,2)*(C(2,1)*C(3,3) - C(2,3)*C(3,1)) &
     + C(1,3)*(C(2,1)*C(3,2) - C(2,2)*C(3,1))
  a = DCMPLX(1.0d0, 0.0d0)
  b = DCMPLX(-I1, 0.0d0)
  cc = DCMPLX(I2, 0.0d0)
  d = DCMPLX(-I3, 0.0d0)
  call cs_cubic_roots(a, b, cc, d, r(1), r(2), r(3))
  do k = 1, 3
    stretch = SQRT(DBLE(r(k)))
    write(*,'(30ES26.17)') REAL(r(k)%RE), (GETIM(r(k)%RE, n), n=1,6), &
         REAL(r(k)%IM), (GETIM(r(k)%IM, n), n=1,6), REAL(stretch), (GETIM(stretch, n), n=1,6)
  end do
end program cardano
"""

#: Deformation gradients with well-separated principal stretches (Cardano's
#: conditioning degrades as two eigenvalues approach each other).
GRADIENTS = [
    np.array([[1.30, 0.20, 0.05], [0.10, 0.85, -0.15], [0.02, 0.12, 1.05]]),
    np.array([[0.70, -0.30, 0.10], [0.25, 1.40, 0.05], [-0.10, 0.20, 0.95]]),
    np.array([[1.10, 0.45, -0.20], [0.00, 0.90, 0.30], [0.15, 0.00, 1.60]]),
]


@pytest.fixture(scope="module")
def cardano(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("complex_oti_cardano")
    module = generate_otilib_module(output_dir=tmp, ntens=6, order=1)
    (tmp / "oti_complex.f90").write_text(
        generate_complex_oti_module(module.module_name, module.type_name))
    (tmp / "cardano.f90").write_text(PROGRAM.format(z="Z" + module.type_name, t=module.type_name))
    flags = ["-ffree-form", "-ffree-line-length-none", "-O0"]
    for unit in ("master_parameters.f90", "real_utils.f90", f"{module.module_name}.f90",
                 "oti_complex.f90", "cardano.f90"):
        done = subprocess.run(["gfortran", *flags, "-c", unit], cwd=tmp, capture_output=True, text=True)
        assert done.returncode == 0, f"{unit}:\n{done.stderr[-3000:]}"
    done = subprocess.run(["gfortran", *sorted(p.name for p in tmp.glob("*.o")), "-o", "cardano"],
                          cwd=tmp, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-3000:]

    def run(c_matrix):
        c0 = [c_matrix[0, 0], c_matrix[1, 1], c_matrix[2, 2], c_matrix[0, 1], c_matrix[0, 2], c_matrix[1, 2]]
        out = subprocess.run([str(tmp / "cardano")], input=" ".join(repr(float(v)) for v in c0) + "\n",
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        return np.array([[float(v) for v in line.split()] for line in out.stdout.strip().splitlines()])
    return run


def _seed_matrices():
    """The six symmetric perturbations the program seeds, in its order."""
    seeds = []
    for (i, j) in ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2)):
        e = np.zeros((3, 3))
        e[i, j] = e[j, i] = 1.0
        seeds.append(e)
    return seeds


@pytest.mark.parametrize("index", range(len(GRADIENTS)))
def test_cardano_eigenvalues_and_derivatives_match_a_real_eigensolver(cardano, index):
    F = GRADIENTS[index]
    C = F.T @ F
    rows = cardano(C)
    lam_ref, vectors = np.linalg.eigh(C)
    order = np.argsort(rows[:, 0])
    rows = rows[order]
    scale = np.abs(lam_ref).max()
    # values: real parts are the eigenvalues, imaginary parts vanish
    np.testing.assert_allclose(rows[:, 0], lam_ref, rtol=1e-12, atol=1e-13 * scale)
    np.testing.assert_allclose(rows[:, 7], 0.0, atol=1e-12 * scale)
    # first derivatives against the analytical v^T E v
    seeds = _seed_matrices()
    for k in range(3):
        v = vectors[:, k]
        expected = np.array([v @ e @ v for e in seeds])
        np.testing.assert_allclose(rows[k, 1:7], expected, rtol=1e-11, atol=1e-12)
        # the imaginary part stays zero to first order as well
        np.testing.assert_allclose(rows[k, 8:14], 0.0, atol=1e-11)
        # principal stretch and its derivative
        stretch = np.sqrt(lam_ref[k])
        assert rows[k, 14] == pytest.approx(stretch, rel=1e-12)
        np.testing.assert_allclose(rows[k, 15:21], expected / (2.0 * stretch), rtol=1e-11, atol=1e-12)


def test_cardano_derivatives_match_finite_differences_of_the_eigensolver(cardano):
    """An independent second reference: central FD of numpy's eigvalsh."""
    F = GRADIENTS[0]
    C = F.T @ F
    rows = cardano(C)[np.argsort(cardano(C)[:, 0])]
    h = 1e-6
    for n, e in enumerate(_seed_matrices()):
        fd = (np.linalg.eigvalsh(C + h * e) - np.linalg.eigvalsh(C - h * e)) / (2 * h)
        np.testing.assert_allclose(rows[:, 1 + n], fd, rtol=1e-8, atol=1e-9)


def test_the_discriminant_is_negative_so_the_complex_path_is_exercised():
    """Three distinct real roots always mean casus irreducibilis: Delta < 0."""
    for F in GRADIENTS:
        C = F.T @ F
        i1, i3 = np.trace(C), np.linalg.det(C)
        i2 = 0.5 * (i1 ** 2 - np.trace(C @ C))
        p = (3 * i2 - i1 ** 2) / 3
        q = (-2 * i1 ** 3 + 9 * i1 * i2 - 27 * i3) / 27
        assert (q / 2) ** 2 + (p / 3) ** 3 < 0
