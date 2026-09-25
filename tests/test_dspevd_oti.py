from __future__ import annotations

import shutil
import subprocess
import csv
from pathlib import Path

import numpy as np
import pytest

from umat_oti.fortran.parser import parse_fortran_file
from umat_oti.oti.module_generator import generate_otilib_module
from umat_oti.transform.helper_lifting import lift_helper_set_source, wrap_free_form
from umat_oti.transform.parameter_sensitivity_transform import _emit_intrinsic_extensions
from umat_oti.transform.spectral_definitions import DSPEVD_DEFINITION


@pytest.mark.parametrize("scale", [1e-200, 1e-100, 1e100, 1e200])
def test_scaled_matrices(eigensolver, scale):
    base = np.array([[2., .3, -.2], [.3, 4., .1], [-.2, .1, 7.]])
    seed = np.array([[.2, .1, .3], [.1, -.3, .2], [.3, .2, .4]])
    info, output = run_solver(eigensolver, base*scale, [base*scale*.1, seed*scale])
    assert info == 0
    values = output[2:11].reshape(3,3)/scale
    vectors = output[11:].reshape(3,3,3).transpose(1,0,2)
    np.testing.assert_allclose(values[:,0], np.linalg.eigvalsh(base), rtol=2e-12)
    np.testing.assert_allclose(values[:,1], values[:,0]*.1, atol=2e-12)
    np.testing.assert_allclose(vectors[:,:,1], 0, atol=2e-12)
    residual = (seed @ vectors[:,:,0] + base @ vectors[:,:,2] -
                vectors[:,:,2]*values[:,0] - vectors[:,:,0]*values[:,2])
    np.testing.assert_allclose(residual, 0, atol=3e-11)


def test_equal_diagonal_nonzero_offdiagonal(eigensolver):
    matrix = np.array([[2., .5], [.5, 2.]])
    seeds = [np.diag([1., -1.]), np.array([[0., 1.], [1., 0.]])]
    info, output = run_solver(eigensolver, matrix, seeds)
    assert info == 0
    values = output[2:8].reshape(2,3)
    np.testing.assert_allclose(values, [[1.5, 0., -1.], [2.5, 0., 1.]], atol=2e-12)


def test_an_offdiagonal_too_small_to_square_does_not_become_a_nan(eigensolver):
    """This matrix returned NaN, and reported INFO = 0 doing it.

    Not constructed by hand -- found by scoring the routine against LAPACK
    over 600 symmetric matrices, and kept verbatim because the failure needs
    the sweeps to land on an exact state. They drive the two close diagonals
    to precisely equal, so GAP becomes zero, leaving an off-diagonal around
    1D-184. Squaring that underflows: OFFVAL*OFFVAL is exactly zero below
    about 1.5D-154, so SQRT(GAP*GAP + 4*OFFVAL*OFFVAL) returned zero and
    TANGENT divided 2*OFFVAL by it.

    The NaN escaped the convergence test as well, because every comparison
    against NaN is false: RESIDUAL .GT. tol was false, so the routine
    returned success. Both halves are checked -- finite, and right.

    Not an exotic state for a solid: it is a momentarily isotropic stress,
    which for uniaxial loading is every increment.
    """
    matrix = np.array([
        [-1.18554211097012649e+03, -1.04170182032070464e+01, 6.34020653095463089e+01],
        [-1.04170182032070464e+01, -1.19249445973601451e+03, -4.56816667416518811e+01],
        [6.34020653095463089e+01, -4.56816667416518811e+01, -9.21963429293859008e+02]])
    expected = np.linalg.eigvalsh(matrix)               # gap 4.5e-13 on 1200
    seeds = [np.zeros((3, 3)), np.zeros((3, 3))]
    info, output = run_solver(eigensolver, matrix, seeds)
    assert info == 0, "reported INFO = %d" % info
    values = output[2:2 + 3 * 3].reshape(3, 3)[:, 0]
    assert np.all(np.isfinite(values)), "returned %s" % values
    np.testing.assert_allclose(sorted(values), sorted(expected), atol=1e-9)


def test_a_diagonal_matrix_still_has_eigenvector_derivatives(eigensolver):
    """The off-diagonal carries the whole sensitivity when the real part is 0.

    Guarding the underflow above by skipping rotations with a negligible
    OFFVAL passes every eigenvalue check and silently returns eigenvector
    derivatives of zero: for a diagonal matrix the real off-diagonal IS zero,
    and the perturbation the derivative is taken along lives entirely in the
    imaginary part. Scaling the root instead of dropping the term is what
    keeps this nonzero.
    """
    matrix = np.diag([3.0, 5.0])
    seeds = [np.array([[0.0, 1.0], [1.0, 0.0]]), np.zeros((2, 2))]
    info, output = run_solver(eigensolver, matrix, seeds)
    assert info == 0
    vectors = output[2 + 2 * 3:].reshape(2, 2, 3)
    # dV/ds for a symmetric off-diagonal seed on diag(3, 5): the rotation
    # rate is 1/(5-3), so the sensitivity is +/- 0.5 on the off-diagonal.
    np.testing.assert_allclose(np.abs(vectors[:, :, 1]),
                               [[0.0, 0.5], [0.5, 0.0]], atol=1e-9)


def test_parameter_sensitivity_path_supplies_dspevd(tmp_path):
    from umat_oti.transform.parameter_sensitivity_transform import (
        GenericPSContract, compile_generic_ps, run_generic_ps, transform_umat_for_parameter_sensitivity,
    )
    from umat_oti.transform.source_transform import _wrap_fixed_form_source

    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    public = Path(__file__).resolve().parents[1] / "UMATs/UMATs/generic_ps/elastic_props.f"
    prefix = public.read_text().split("      E    = PROPS(1)", 1)[0]
    helper = "subroutine eigen_update(" + SYNTHETIC_UMAT.split("subroutine eigen_update(", 1)[1]
    helper = _wrap_fixed_form_source("\n".join("      " + line for line in helper.splitlines()) + "\n")
    source = tmp_path / "spectral_parameters.for"
    source.write_text(prefix + "      CALL EIGEN_UPDATE(STRESS,PROPS,NTENS)\n      END\n" + helper)
    contract = GenericPSContract(
        name="spectral", umat_source_path=source,
        parameters=tuple((f"PAR{index}", index) for index in range(1,7)),
        parameter_values=(.1, -.2, .05, .13, -.07, .18), state_variables=(),
        ntens=6, nstatv=1, ndi=3, nshr=3, dstran_per_increment=(0.,)*6, n_increments=1,
    )
    layout = transform_umat_for_parameter_sensitivity(contract=contract, output_dir=tmp_path / "ps")
    assert "DSPEVD" in layout.umat_and_helpers
    run = run_generic_ps(compile_generic_ps(layout))
    assert run.returncode == 0, run.stderr
    with run.dsigma_csv.open() as stream:
        rows = list(csv.reader(stream))[1:]
    derivatives = np.array([[float(value) for value in row[3:]] for row in rows])
    matrix = np.array([[1.1, .13, -.07], [.13, 2.8, .18], [-.07, .18, 5.05]])
    _, vectors = np.linalg.eigh(matrix)
    expected = np.column_stack((vectors[0]**2, vectors[1]**2, vectors[2]**2,
                                2*vectors[0]*vectors[1], 2*vectors[0]*vectors[2], 2*vectors[1]*vectors[2]))
    np.testing.assert_allclose(derivatives[:3], expected, atol=2e-10, rtol=2e-9)


def test_higher_order_dspevd_is_not_silently_certified(tmp_path):
    from umat_oti.services.jacobian_request import run_jacobian_transform

    source = tmp_path / "higher_order.f90"
    source.write_text(SYNTHETIC_UMAT, encoding="ascii")
    result = run_jacobian_transform(source, tmp_path / "out", ntens=6, order=2)
    assert not result.succeeded
    assert any("DSPEVD" in message and "order=1" in message for message in result.report["blockers"])


def test_user_supplied_dspevd_is_preserved(tmp_path):
    from umat_oti.transform.abaqus_utility_definitions import supply_reachable_definitions

    source = tmp_path / "custom.f90"
    text = "subroutine outer()\ncall dspevd()\nend\nsubroutine dspevd()\nend\n"
    source.write_text(text, encoding="ascii")
    parsed, supplied = supply_reachable_definitions(parse_fortran_file(source), ["OUTER"])
    assert supplied == ()
    assert parsed.text == text


def test_negative_dimension(eigensolver):
    run = subprocess.run([str(eigensolver)], input="-1 V U 1 1 1\n", text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    assert int(run.stdout.strip()) == -3


DRIVER = """
program check_dspevd
  use spectral_backend
  use otim2n1
  implicit none
  integer :: count, leading, lwork, liwork, info, position, row, col
  integer, allocatable :: iwork(:)
  character :: jobz, uplo
  type(ONUMM2N1), allocatable :: packed(:), values(:), vectors(:,:), work(:)
  read(*,*) count, jobz, uplo, leading, lwork, liwork
  allocate(packed(max(1,count*(count+1)/2)),values(max(1,count)))
  allocate(vectors(max(1,leading),max(1,count)),work(max(1,lwork)))
  allocate(iwork(max(1,liwork)))
  vectors = -999.0d0
  do position = 1,max(0,count*(count+1)/2)
    read(*,*) packed(position)%r, packed(position)%e1, packed(position)%e2
  end do
  call dspevd_oti(jobz,uplo,count,packed,values,vectors,leading, &
                  work,lwork,iwork,liwork,info)
  write(*,*) info
  if(info /= 0) stop
  write(*,*) work(1)%r,iwork(1)
  if(lwork == -1 .or. liwork == -1) stop
  do col = 1,count
    write(*,'(3ES27.17E3)') values(col)%r,values(col)%e1,values(col)%e2
  end do
  if(jobz == 'V' .or. jobz == 'v') then
    do col = 1,count
      do row = 1,count
        write(*,'(3ES27.17E3)') vectors(row,col)%r,vectors(row,col)%e1,vectors(row,col)%e2
      end do
    end do
  end if
end program check_dspevd
"""


@pytest.fixture(scope="module")
def eigensolver(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required")
    output = tmp_path_factory.mktemp("dspevd_oti")
    module = generate_otilib_module(output_dir=output, ntens=2)
    source = output / "spectral.for"
    source.write_text(DSPEVD_DEFINITION, encoding="ascii")
    lifted = lift_helper_set_source(parse_fortran_file(source), ["DSPEVD"],
                                    module_name=module.module_name, type_name=module.type_name)
    (output / "oti_intrinsics.f90").write_text(
        _emit_intrinsic_extensions(module.module_name, module.type_name), encoding="ascii")
    (output / "spectral.f90").write_text(
        "module spectral_backend\ncontains\n" + wrap_free_form(lifted.source) +
        "end module spectral_backend\n", encoding="ascii")
    (output / "driver.f90").write_text(DRIVER, encoding="ascii")
    executable = output / "check_dspevd"
    result = subprocess.run([compiler, "-O0", "-fcheck=all", "-ffpe-trap=invalid,zero,overflow",
                             "-ffree-line-length-none", module.master_parameters_path.name,
                             module.real_utils_path.name, module.module_path.name, "oti_intrinsics.f90",
                             "spectral.f90", "driver.f90", "-o", str(executable)],
                            cwd=output, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


def run_solver(executable, matrix, seeds, *, uplo="U", jobz="V", lwork=None, liwork=None, leading=None):
    count = len(matrix)
    leading = max(1, count) if leading is None else leading
    lwork = 1 + 6*count + count*count if lwork is None else lwork
    liwork = 3 + 5*count if liwork is None else liwork
    lines = [f"{count} {jobz} {uplo} {leading} {lwork} {liwork}"]
    for col in range(count):
        rows = range(col + 1) if uplo.upper() == "U" else range(col, count)
        for row in rows:
            lines.append(" ".join(f"{array[row,col]:.17e}" for array in (matrix, *seeds)))
    result = subprocess.run([str(executable)], input="\n".join(lines)+"\n", text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    values = np.fromstring(result.stdout, sep=" ")
    return int(values[0]), values[1:]


@pytest.mark.parametrize("count", [1, 2, 3, 6, 12])
@pytest.mark.parametrize("uplo", ["U", "L"])
@pytest.mark.parametrize("diagonal", [False, True])
def test_eigenpairs_and_derivatives(eigensolver, count, uplo, diagonal):
    random = np.random.default_rng(812 + count)
    matrix = np.diag(np.arange(1.0, count+1.0))
    if not diagonal:
        basis, _ = np.linalg.qr(random.normal(size=(count,count)))
        matrix = basis @ matrix @ basis.T
    seeds = []
    for _ in range(2):
        raw = random.normal(size=(count,count))
        seeds.append((raw + raw.T)*0.15)
    info, output = run_solver(eigensolver, matrix, seeds, uplo=uplo)
    assert info == 0
    values = output[2:2+3*count].reshape(count,3)
    vectors = output[2+3*count:].reshape(count,count,3).transpose(1,0,2)
    expected, _ = np.linalg.eigh(matrix)
    np.testing.assert_allclose(values[:,0], expected, rtol=2e-12, atol=2e-12)
    np.testing.assert_allclose(matrix @ vectors[:,:,0], vectors[:,:,0]*values[:,0], atol=3e-12)
    np.testing.assert_allclose(vectors[:,:,0].T @ vectors[:,:,0], np.eye(count), atol=3e-12)
    step = 1e-5
    for direction, seed in enumerate(seeds, start=1):
        high_values, high_vectors = np.linalg.eigh(matrix + step*seed)
        low_values, low_vectors = np.linalg.eigh(matrix - step*seed)
        for col in range(count):
            if np.dot(high_vectors[:,col], vectors[:,col,0]) < 0:
                high_vectors[:,col] *= -1
            if np.dot(low_vectors[:,col], vectors[:,col,0]) < 0:
                low_vectors[:,col] *= -1
        np.testing.assert_allclose(values[:,direction], (high_values-low_values)/(2*step), atol=3e-9, rtol=3e-8)
        np.testing.assert_allclose(vectors[:,:,direction], (high_vectors-low_vectors)/(2*step), atol=3e-9, rtol=3e-8)
        residual = (seed @ vectors[:,:,0] + matrix @ vectors[:,:,direction] -
                    vectors[:,:,direction]*values[:,0] - vectors[:,:,0]*values[:,direction])
        np.testing.assert_allclose(residual, 0.0, atol=3e-11)


@pytest.mark.parametrize("options,expected", [
    ({"jobz": "X"}, -1), ({"uplo": "X"}, -2), ({"leading": 1}, -7),
    ({"lwork": 1}, -9), ({"liwork": 1}, -11),
])
def test_invalid_arguments(eigensolver, options, expected):
    matrix = np.diag([1.0, 3.0, 5.0])
    info, _ = run_solver(eigensolver, matrix, [matrix*0, matrix*0], **options)
    assert info == expected


@pytest.mark.parametrize("options", [{"lwork": -1}, {"liwork": -1}, {"lwork": -1, "liwork": -1}])
def test_workspace_query(eigensolver, options):
    matrix = np.diag([1.0, 3.0, 5.0])
    info, output = run_solver(eigensolver, matrix, [matrix*0, matrix*0], **options)
    assert info == 0
    np.testing.assert_array_equal(output, [28.0, 18])


@pytest.mark.parametrize("matrix", [np.eye(3), np.zeros((3,3)), np.diag([1., 1.+1e-14, 3.])])
def test_a_repeated_cluster_is_averaged_rather_than_refused(eigensolver, matrix):
    """A repeated eigenvalue used to be refused with INFO=N+1.

    Refusing is defensible -- an individual eigenvalue of a repeated pair is
    not differentiable -- but it stops every model whose stress state is
    momentarily isotropic, which for uniaxial tension is the whole of it: two
    principal stresses are equal at every increment. What the block DOES have
    is a differentiable trace, so the cluster is averaged and returned.
    """
    info, output = run_solver(eigensolver, matrix, [np.ones_like(matrix), matrix*0])
    assert info == 0
    values = output[2:2+3*len(matrix)].reshape(len(matrix), 3)
    primal = np.linalg.eigvalsh(matrix)
    np.testing.assert_allclose(values[:, 0], primal, atol=2e-12)


def test_the_averaged_cluster_keeps_the_trace_derivative_exact(eigensolver):
    """The reason averaging is the right answer rather than a shrug.

    Perturb a degenerate pair by diag(p, r). The individual first-order
    eigenvalues are p and r, which the pair cannot carry -- but their sum is
    p + r, and each averaged member carries (p + r)/2, so any symmetric
    function of the cluster differentiates exactly.
    """
    matrix = np.diag([2.0, 2.0])
    seeds = [np.diag([1.0, 3.0]), np.zeros((2, 2))]
    info, output = run_solver(eigensolver, matrix, seeds)
    assert info == 0
    values = output[2:8].reshape(2, 3)
    np.testing.assert_allclose(values[:, 0], [2.0, 2.0], atol=2e-12)
    # each member carries the mean ...
    np.testing.assert_allclose(values[:, 1], [2.0, 2.0], atol=2e-12)
    # ... so the trace derivative, which is what a symmetric function needs,
    # is exactly p + r.
    assert abs(values[:, 1].sum() - 4.0) < 2e-12


def test_a_separated_pair_still_carries_its_own_derivatives(eigensolver):
    """The paired case: nothing is averaged when the eigenvalues are apart."""
    matrix = np.diag([2.0, 5.0])
    seeds = [np.diag([1.0, 3.0]), np.zeros((2, 2))]
    info, output = run_solver(eigensolver, matrix, seeds)
    assert info == 0
    values = output[2:8].reshape(2, 3)
    np.testing.assert_allclose(values[:, 0], [2.0, 5.0], atol=2e-12)
    np.testing.assert_allclose(values[:, 1], [1.0, 3.0], atol=2e-12)


def test_empty_and_values_only(eigensolver):
    matrix = np.empty((0,0))
    info, output = run_solver(eigensolver, matrix, [matrix, matrix])
    assert info == 0
    np.testing.assert_array_equal(output, [1, 1])
    matrix = np.array([[1., .2], [.2, 3.]])
    info, output = run_solver(eigensolver, matrix, [matrix*0, matrix*0], jobz="N", leading=1, lwork=4, liwork=1)
    assert info == 0
    np.testing.assert_allclose(output[2:].reshape(2,3)[:,0], np.linalg.eigvalsh(matrix))


SYNTHETIC_UMAT = """subroutine umat(stress,dstran,ddsdde,ntens)
implicit none
integer :: ntens
real(8) :: stress(ntens),dstran(ntens),ddsdde(ntens,ntens)
call eigen_update(stress,dstran,ntens)
ddsdde = 0.0d0
end subroutine umat
subroutine eigen_update(stress,dstran,ntens)
implicit none
integer :: ntens,info,iwork(18),component
real(8) :: stress(ntens),dstran(ntens),packed(6),values(3),vectors(3,3),work(28)
packed(1)=1.0d0+dstran(1)
packed(2)=dstran(4)
packed(3)=3.0d0+dstran(2)
packed(4)=dstran(5)
packed(5)=dstran(6)
packed(6)=5.0d0+dstran(3)
call dspevd('V','U',3,packed,values,vectors,3,work,28,iwork,18,info)
if(info.ne.0) stop 1
do component=1,3
stress(component)=values(component)
stress(component+3)=vectors(component,1)
end do
end subroutine eigen_update
"""


@pytest.mark.parametrize("form", ["free", "fixed"])
def test_transitive_dspevd_is_supplied_to_jacobian_pipeline(tmp_path, form):
    from umat_oti.transform.source_transform import _wrap_fixed_form_source
    from umat_oti.services.jacobian_request import run_jacobian_transform

    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    source = tmp_path / ("spectral_umat.f90" if form == "free" else "spectral_umat.for")
    text = SYNTHETIC_UMAT
    if form == "fixed":
        text = _wrap_fixed_form_source("\n".join("      " + line for line in text.splitlines()) + "\n")
    source.write_text(text, encoding="ascii")
    result = run_jacobian_transform(source, tmp_path / "out", ntens=6, compile_generated=True)
    assert result.succeeded, result.report
    assert any("subroutine dspevd_oti" in path.read_text().lower() for path in (tmp_path / "out").glob("*.f90"))
    output = tmp_path / "out"
    driver = output / "verify_tangent.f90"
    driver.write_text("""program verify_tangent
implicit none
real(8) :: stress(6),strain(6),tangent(6,6)
integer :: row
read(*,*) strain
stress=0.0d0
call umat(stress,strain,tangent,6)
write(*,'(6ES26.17)') stress
do row=1,6
write(*,'(6ES26.17)') tangent(row,:)
end do
end program verify_tangent
""", encoding="ascii")
    executable = output / "verify_tangent"
    files = (output / "compile_order.txt").read_text().splitlines()
    built = subprocess.run(["gfortran", "-ffree-line-length-none", "-ffixed-line-length-none",
                            *files, driver.name, "-o", str(executable)], cwd=output, text=True, capture_output=True)
    assert built.returncode == 0, built.stdout + built.stderr
    strain = np.array([.1, -.2, .05, .13, -.07, .18])
    run = subprocess.run([str(executable)], input=" ".join(map(str, strain))+"\n", text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    actual = np.fromstring(run.stdout, sep=" ")

    def response(increment):
        matrix = np.diag([1., 3., 5.]) + np.diag(increment[:3])
        matrix[0,1] = matrix[1,0] = increment[3]
        matrix[0,2] = matrix[2,0] = increment[4]
        matrix[1,2] = matrix[2,1] = increment[5]
        values, vectors = np.linalg.eigh(matrix)
        first = vectors[:,0]
        if first[np.argmax(np.abs(first))] < 0:
            first = -first
        return np.concatenate([values, first])

    step = 1e-6
    expected = np.column_stack([(response(strain + direction*step) - response(strain - direction*step))/(2*step)
                                for direction in np.eye(6)])
    np.testing.assert_allclose(actual[:6], response(strain), atol=2e-12)
    np.testing.assert_allclose(actual[6:].reshape(6,6), expected, atol=2e-9, rtol=2e-8)