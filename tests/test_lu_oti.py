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
from umat_oti.transform.lu_definitions import DGETRF_DEFINITION, DGETRS_DEFINITION
from umat_oti.transform.parameter_sensitivity_transform import _emit_intrinsic_extensions


def test_character_literals_are_not_promoted_in_conditions():
    from umat_oti.transform.helper_lifting import _wrap_condition_with_real_tokens

    line = "IF (TRANS.NE.'T' .AND. LABEL.NE.'C)(' .AND. VALUE.GT.0) INFO=1"
    expected = "IF (TRANS.NE.'T' .AND. LABEL.NE.'C)(' .AND. REAL(VALUE).GT.0) INFO=1"
    assert _wrap_condition_with_real_tokens(line, {"T", "C", "VALUE"}) == expected


@pytest.mark.parametrize("header,expected", [
    ("0 -1 0 0 N 1 1", -1), ("0 0 -1 0 N 1 1", -2), ("0 0 0 0 N 0 1", -4),
    ("2 0 0 0 X 1 1", -1), ("2 0 -1 0 N 1 1", -2), ("2 0 0 -1 N 1 1", -3),
    ("2 0 0 0 N 0 1", -5), ("2 0 0 0 N 1 0", -8),
])
def test_invalid_arguments(lu_solver, header, expected):
    run = subprocess.run([str(lu_solver)], input=header+"\n", capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert int(run.stdout.strip()) == expected


@pytest.mark.parametrize("matrix,expected", [(np.array([[0.,0.],[0.,1.]]), 1),
                                            (np.array([[1.,2.],[2.,4.]]), 2)])
def test_singular_factorization_reports_first_zero_pivot(lu_solver, matrix, expected):
    rhs = np.ones((2,1))
    output = run_lu(lu_solver, matrix, rhs, [matrix*0]*2, [rhs*0]*2)
    assert output[0] == expected


def test_singular_solve_is_refused(lu_solver):
    factors = np.diag([1.,0.])
    rhs = np.ones((2,1))
    output = run_lu(lu_solver, factors, rhs, [factors*0]*2, [rhs*0]*2, mode=2)
    np.testing.assert_array_equal(output, [2])


@pytest.mark.parametrize("shape", [(0,0), (0,3), (3,0)])
def test_empty_factorization(lu_solver, shape):
    matrix = np.empty(shape)
    rhs = np.empty((shape[1],0))
    output = run_lu(lu_solver, matrix, rhs, [matrix,matrix], [rhs,rhs], mode=0)
    np.testing.assert_array_equal(output, [0])


@pytest.mark.parametrize("trans", ["N", "T"])
def test_zero_primal_rhs_keeps_derivatives(lu_solver, trans):
    matrix = np.array([[0.,2.],[3.,1.]])
    rhs = np.zeros((2,2))
    seeds = [np.eye(2), np.array([[1.,2.],[3.,4.]])]
    output = run_lu(lu_solver, matrix, rhs, [matrix*0]*2, seeds, trans=trans)
    assert output[0] == output[15] == 0
    actual = output[16:].reshape(2,2,3).transpose(1,0,2)
    np.testing.assert_array_equal(actual[:,:,0], rhs)
    for direction, seed in enumerate(seeds, start=1):
        expected = np.linalg.solve(matrix if trans == "N" else matrix.T, seed)
        np.testing.assert_allclose(actual[:,:,direction], expected, atol=2e-12)


@pytest.mark.parametrize("scale", [1e-200, 1e200])
@pytest.mark.parametrize("trans", ["N", "T"])
def test_scaled_systems(lu_solver, scale, trans):
    base = np.array([[1.,2.],[3.,1.]])
    rhs_base = np.array([[2.],[-1.]])
    matrix, rhs = base*scale, rhs_base*scale
    output = run_lu(lu_solver, matrix, rhs, [matrix*.1, matrix*0], [rhs*0, rhs*.2], trans=trans)
    assert output[0] == output[15] == 0
    actual = output[16:].reshape(2,3)
    expected = np.linalg.solve(base if trans == "N" else base.T, rhs_base)[:,0]
    np.testing.assert_allclose(actual, np.column_stack([expected, -.1*expected, .2*expected]), atol=2e-12)


SYNTHETIC_UMAT = """subroutine umat(stress,dstran,ddsdde,ntens)
implicit none
integer :: ntens
real(8) :: stress(ntens),dstran(ntens),ddsdde(ntens,ntens)
call solve_update(stress,dstran,ntens)
ddsdde = 0.0d0
end subroutine umat
subroutine solve_update(stress,dstran,ntens)
implicit none
integer :: ntens,info,pivots(3),row
real(8) :: stress(ntens),dstran(ntens),matrix(3,3),rhs(3,2)
matrix(1,1)=1.0d0+dstran(1)
matrix(2,1)=3.0d0
matrix(3,1)=0.5d0
matrix(1,2)=2.0d0
matrix(2,2)=5.0d0+dstran(2)
matrix(3,2)=-0.3d0
matrix(1,3)=0.2d0
matrix(2,3)=-0.4d0
matrix(3,3)=4.0d0+dstran(3)
rhs(1,1)=1.0d0+dstran(4)
rhs(2,1)=2.0d0+dstran(5)
rhs(3,1)=3.0d0+dstran(6)
rhs(1,2)=2.0d0
rhs(2,2)=-1.0d0
rhs(3,2)=0.5d0
call dgetrf(3,3,matrix,3,pivots,info)
if(info.ne.0) stop 1
call dgetrs('N',3,2,matrix,3,pivots,rhs,3,info)
if(info.ne.0) stop 2
do row=1,3
stress(row)=rhs(row,1)
stress(row+3)=rhs(row,2)
end do
end subroutine solve_update
"""


def response(increment):
    matrix = np.array([[1.,2.,.2],[3.,5.,-.4],[.5,-.3,4.]]) + np.diag(increment[:3])
    rhs = np.column_stack([np.array([1.,2.,3.])+increment[3:], [2.,-1.,.5]])
    return np.linalg.solve(matrix, rhs).ravel(order="F")


@pytest.mark.parametrize("form", ["free", "fixed"])
def test_jacobian_workflow_supplies_and_executes_lu(tmp_path, form):
    from umat_oti.transform.source_transform import _wrap_fixed_form_source
    from umat_oti.services.jacobian_request import run_jacobian_transform

    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    source = tmp_path / ("lu_umat.f90" if form == "free" else "lu_umat.for")
    text = SYNTHETIC_UMAT
    if form == "fixed":
        text = _wrap_fixed_form_source("\n".join("      " + line for line in text.splitlines()) + "\n")
    source.write_text(text, encoding="ascii")
    output = tmp_path / "out"
    result = run_jacobian_transform(source, output, ntens=6, compile_generated=True, discover_dependencies=True)
    assert result.succeeded, result.report
    driver = output / "verify_lu.f90"
    driver.write_text("""program verify_lu
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
end program verify_lu
""", encoding="ascii")
    executable = output / "verify_lu"
    files = (output / "compile_order.txt").read_text().splitlines()
    built = subprocess.run(["gfortran", "-ffree-line-length-none", "-ffixed-line-length-none",
                            *files, driver.name, "-o", str(executable)], cwd=output, text=True, capture_output=True)
    assert built.returncode == 0, built.stdout + built.stderr
    strain = np.array([.1,-.2,.05,.13,-.07,.18])
    run = subprocess.run([str(executable)], input=" ".join(map(str,strain))+"\n", text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    actual = np.fromstring(run.stdout, sep=" ")
    step = 1e-6
    expected = np.column_stack([(response(strain+direction*step)-response(strain-direction*step))/(2*step)
                                for direction in np.eye(6)])
    np.testing.assert_allclose(actual[:6], response(strain), atol=2e-12)
    np.testing.assert_allclose(actual[6:].reshape(6,6), expected, atol=2e-8, rtol=2e-8)


def test_parameter_sensitivity_workflow_supplies_lu(tmp_path):
    from umat_oti.transform.parameter_sensitivity_transform import (
        GenericPSContract, compile_generic_ps, run_generic_ps, transform_umat_for_parameter_sensitivity,
    )
    from umat_oti.transform.source_transform import _wrap_fixed_form_source

    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    public = Path(__file__).resolve().parents[1] / "UMATs/UMATs/generic_ps/elastic_props.f"
    prefix = public.read_text().split("      E    = PROPS(1)", 1)[0]
    helper = "subroutine solve_update(" + SYNTHETIC_UMAT.split("subroutine solve_update(", 1)[1]
    helper = _wrap_fixed_form_source("\n".join("      " + line for line in helper.splitlines()) + "\n")
    source = tmp_path / "lu_parameters.for"
    source.write_text(prefix + "      CALL SOLVE_UPDATE(STRESS,PROPS,NTENS)\n      END\n" + helper)
    parameters = np.array([.1,-.2,.05,.13,-.07,.18])
    contract = GenericPSContract(
        name="lu", umat_source_path=source,
        parameters=tuple((f"PAR{index}",index) for index in range(1,7)),
        parameter_values=tuple(parameters), state_variables=(), ntens=6, nstatv=1, ndi=3, nshr=3,
        dstran_per_increment=(0.,)*6, n_increments=1,
    )
    layout = transform_umat_for_parameter_sensitivity(contract=contract, output_dir=tmp_path / "ps")
    assert {"DGETRF", "DGETRS"} <= set(layout.umat_and_helpers)
    run = run_generic_ps(compile_generic_ps(layout))
    assert run.returncode == 0, run.stderr
    with run.dsigma_csv.open() as stream:
        rows = list(csv.reader(stream))[1:]
    actual = np.array([[float(value) for value in row[3:]] for row in rows])
    step = 1e-6
    expected = np.column_stack([(response(parameters+direction*step)-response(parameters-direction*step))/(2*step)
                                for direction in np.eye(6)])
    np.testing.assert_allclose(actual, expected, atol=2e-8, rtol=2e-8)


@pytest.mark.parametrize("name", ["DGETRF", "DGETRS"])
def test_user_supplied_lu_is_not_replaced(tmp_path, name):
    from umat_oti.transform.abaqus_utility_definitions import supply_reachable_definitions

    source = tmp_path / "custom.f90"
    text = f"subroutine outer()\ncall {name}()\nend\nsubroutine {name}()\nend\n"
    source.write_text(text, encoding="ascii")
    parsed, supplied = supply_reachable_definitions(parse_fortran_file(source), ["OUTER"])
    assert supplied == ()
    assert parsed.text == text


def test_unverified_higher_order_fallback_is_refused(tmp_path):
    from umat_oti.services.jacobian_request import run_jacobian_transform

    source = tmp_path / "higher_order.f90"
    source.write_text(SYNTHETIC_UMAT, encoding="ascii")
    run = run_jacobian_transform(source, tmp_path / "out", ntens=6, order=2)
    assert not run.succeeded
    assert any("DGETRF/DGETRS" in message and "order=1" in message for message in run.report["blockers"])


def test_multiple_sequential_pivots(lu_solver):
    matrix = np.array([[0.,2.,1.],[0.,1.,3.],[4.,1.,0.]])
    rhs = np.eye(3)
    output = run_lu(lu_solver, matrix, rhs, [matrix*0]*2, [rhs*0]*2)
    assert output[0] == output[31] == 0
    np.testing.assert_array_equal(output[1:4], [3,3,3])
    actual = output[32:].reshape(3,3,3).transpose(1,0,2)
    np.testing.assert_allclose(actual[:,:,0], np.linalg.inv(matrix), atol=2e-12)


def test_zero_right_hand_sides(lu_solver):
    matrix = np.eye(3)
    rhs = np.empty((3,0))
    output = run_lu(lu_solver, matrix, rhs, [matrix*0]*2, [rhs,rhs])
    assert len(output) == 32
    assert output[0] == output[-1] == 0


DRIVER = """
program check_lu
use lu_backend
use otim2n1
implicit none
integer :: mode,rows,cols,nrhs,lda,ldb,info,row,col
integer, allocatable :: pivots(:)
character :: trans
type(ONUMM2N1), allocatable :: matrix(:,:),rhs(:,:)
read(*,*) mode,rows,cols,nrhs,trans,lda,ldb
allocate(matrix(max(1,rows,lda),max(1,cols)))
allocate(rhs(max(1,cols,ldb),max(1,nrhs)),pivots(max(1,rows,cols)))
matrix = -777.0d0
rhs = -888.0d0
do row=1,size(pivots)
pivots(row)=row
end do
do col=1,cols
do row=1,rows
read(*,*) matrix(row,col)%r,matrix(row,col)%e1,matrix(row,col)%e2
end do
end do
do col=1,nrhs
do row=1,cols
read(*,*) rhs(row,col)%r,rhs(row,col)%e1,rhs(row,col)%e2
end do
end do
if(mode /= 2) then
call dgetrf_oti(rows,cols,matrix,lda,pivots,info)
write(*,*) info
if(info < 0) stop
write(*,*) pivots(1:min(rows,cols))
do col=1,cols
do row=1,rows
write(*,'(3ES27.17E3)') matrix(row,col)%r,matrix(row,col)%e1,matrix(row,col)%e2
end do
end do
if(info /= 0 .or. mode == 0) stop
end if
call dgetrs_oti(trans,cols,nrhs,matrix,lda,pivots,rhs,ldb,info)
write(*,*) info
if(info /= 0) stop
do col=1,nrhs
do row=1,cols
write(*,'(3ES27.17E3)') rhs(row,col)%r,rhs(row,col)%e1,rhs(row,col)%e2
end do
end do
if(any(matrix(rows+1:,:)%r /= -777.0d0)) stop 8
if(any(rhs(cols+1:,:)%r /= -888.0d0)) stop 9
end program check_lu
"""


@pytest.fixture(scope="module")
def lu_solver(tmp_path_factory):
    compiler = shutil.which("gfortran")
    if compiler is None:
        pytest.skip("gfortran required")
    output = tmp_path_factory.mktemp("lu_oti")
    module = generate_otilib_module(output_dir=output, ntens=2)
    source = output / "lu.for"
    source.write_text(DGETRF_DEFINITION + DGETRS_DEFINITION, encoding="ascii")
    lifted = lift_helper_set_source(parse_fortran_file(source), ["DGETRF", "DGETRS"],
                                    module_name=module.module_name, type_name=module.type_name)
    (output / "oti_intrinsics.f90").write_text(
        _emit_intrinsic_extensions(module.module_name, module.type_name), encoding="ascii")
    (output / "lu.f90").write_text("module lu_backend\ncontains\n" + wrap_free_form(lifted.source) +
                                   "end module lu_backend\n", encoding="ascii")
    (output / "driver.f90").write_text(DRIVER, encoding="ascii")
    executable = output / "check_lu"
    built = subprocess.run([compiler, "-O0", "-fcheck=all", "-ffpe-trap=invalid,zero,overflow",
                            "-ffree-line-length-none", module.master_parameters_path.name,
                            module.real_utils_path.name, module.module_path.name,
                            "oti_intrinsics.f90", "lu.f90", "driver.f90", "-o", str(executable)],
                           cwd=output, capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    return executable


def run_lu(executable, matrix, rhs, matrix_seeds, rhs_seeds, *, mode=1, trans="N", lda=None, ldb=None):
    rows, cols = matrix.shape
    nrhs = rhs.shape[1]
    lda = max(1, rows)+2 if lda is None else lda
    ldb = max(1, cols)+3 if ldb is None else ldb
    lines = [f"{mode} {rows} {cols} {nrhs} {trans} {lda} {ldb}"]
    for primal, seeds in ((matrix, matrix_seeds), (rhs, rhs_seeds)):
        for col in range(primal.shape[1]):
            for row in range(primal.shape[0]):
                lines.append(" ".join(f"{array[row,col]:.17e}" for array in (primal, *seeds)))
    run = subprocess.run([str(executable)], input="\n".join(lines)+"\n", capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return np.fromstring(run.stdout, sep=" ")


@pytest.mark.parametrize("trans", ["N", "T", "C", "n", "t", "c"])
@pytest.mark.parametrize("count,nrhs", [(1,1), (3,1), (6,3)])
def test_solve_and_two_derivative_directions(lu_solver, trans, count, nrhs):
    random = np.random.default_rng(900+count)
    matrix = random.normal(size=(count,count)) + np.eye(count)*count
    matrix = matrix[::-1].copy()
    rhs = random.normal(size=(count,nrhs))
    matrix_seeds = [random.normal(size=matrix.shape)*.1 for _ in range(2)]
    rhs_seeds = [random.normal(size=rhs.shape)*.2 for _ in range(2)]
    output = run_lu(lu_solver, matrix, rhs, matrix_seeds, rhs_seeds, trans=trans)
    assert output[0] == 0
    offset = 1 + count + 3*count*count
    assert output[offset] == 0
    actual = output[offset+1:].reshape(nrhs,count,3).transpose(1,0,2)
    operated = matrix if trans.upper() == "N" else matrix.T
    expected = np.linalg.solve(operated, rhs)
    np.testing.assert_allclose(actual[:,:,0], expected, atol=2e-12, rtol=2e-12)
    for direction in range(2):
        perturbation = matrix_seeds[direction] if trans.upper() == "N" else matrix_seeds[direction].T
        derivative = np.linalg.solve(operated, rhs_seeds[direction] - perturbation @ expected)
        np.testing.assert_allclose(actual[:,:,direction+1], derivative, atol=3e-12, rtol=3e-11)
        step = 1e-5
        finite_difference = (np.linalg.solve(operated+step*perturbation, rhs+step*rhs_seeds[direction]) -
                             np.linalg.solve(operated-step*perturbation, rhs-step*rhs_seeds[direction]))/(2*step)
        np.testing.assert_allclose(actual[:,:,direction+1], finite_difference, atol=3e-10, rtol=3e-8)


@pytest.mark.parametrize("shape", [(5,3), (3,5), (3,3)])
def test_rectangular_factorization_and_derivatives(lu_solver, shape):
    random = np.random.default_rng(77)
    matrix = random.normal(size=shape)
    seeds = [random.normal(size=shape)*.1 for _ in range(2)]
    rhs = np.empty((shape[1],0))
    output = run_lu(lu_solver, matrix, rhs, seeds, [rhs,rhs], mode=0)
    assert output[0] == 0
    rank = min(shape)
    pivots = output[1:1+rank].astype(int)-1
    factors = output[1+rank:].reshape(shape[1],shape[0],3).transpose(1,0,2)
    permuted = np.stack([matrix,*seeds], axis=2)
    for row, pivot in enumerate(pivots):
        permuted[[row,pivot]] = permuted[[pivot,row]]
    lower = np.tril(factors[:,:rank,0], -1) + np.eye(shape[0],rank)
    upper = np.triu(factors[:rank,:,0])
    np.testing.assert_allclose(lower @ upper, permuted[:,:,0], atol=2e-12)
    for direction in (1,2):
        derivative = np.tril(factors[:,:rank,direction], -1) @ upper + lower @ np.triu(factors[:rank,:,direction])
        np.testing.assert_allclose(derivative, permuted[:,:,direction], atol=2e-12)