"""Binary32 rule 'widened': OTI equals the derivative of the widened original.

Jeff97 Wrinkle (pass21 254a65c2) holds G11 = (x3^2 + s x4^2)/MMOD and
G22 = (x4^2 + s x3^2)/MMOD in binary32, with G11 + G22 = 1 + s exactly. The
determinant's derivative depends on G11' = -G22'. Under B-W (rule 'author')
MMOD's real part is rounded and its derivative is not, which breaks that
identity at the 1e-7 level. Where the derivative is itself a cancellation of
that size, OTI then equals neither the author's function nor the double
idealisation: there it gave 9.05 against 0.435 (Vera pre22 addendum, B32-3).

Rule 'widened' rounds none of those variables. The lifted build is then the OTI
form of precision.widen()'s control, and its derivative must equal a central
FD of that control compiled in double. Rule 'author' stays the default, and
its generated code is unchanged.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from umat_oti.abaqus.precision import PrecisionFinding, narrow_declarations, widen
from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract,
    transform_umat_for_parameter_sensitivity,
)

_TOY = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATEV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATEV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      REAL MMOD, G11, G22
      MMOD = STATEV(1)*STATEV(1) + STATEV(2)*STATEV(2)
      G11 = (STATEV(1)*STATEV(1) + 1.02D0*STATEV(2)*STATEV(2))/MMOD
      G22 = (STATEV(2)*STATEV(2) + 1.02D0*STATEV(1)*STATEV(1))/MMOD
      DET = G11*G22
      DO K1 = 1, NTENS
        STRESS(K1) = PROPS(1)*(DFGRD1(1,1)/DET - 1.D0)
        DO K2 = 1, NTENS
          DDSDDE(K1, K2) = 0.D0
        END DO
      END DO
      RETURN
      END
"""

_X = (-0.9840244987895895, -0.00413465055066736)
_PROPS = 1.5e8
_F11 = 1.00002


def _lift(tmp_path: Path, rule: str):
    source = tmp_path / "toy.for"
    source.write_text(_TOY, encoding="utf-8")
    contract = GenericPSContract(
        name="toy", umat_source_path=source, parameters=(("E", 1),), parameter_values=(_PROPS,),
        state_variables=(("A", 1), ("B", 2)), ntens=1, nstatv=2, ndi=1, nshr=0,
        dstran_per_increment=(0.0,), n_increments=1, static_props=(_PROPS,))
    return transform_umat_for_parameter_sensitivity(
        contract=contract, output_dir=tmp_path / rule, extra_directions=1, binary32=rule)


def _oti_derivatives(layout) -> tuple[float, float]:
    """d STRESS(1) / d STATEV(1), d STATEV(2) from the lifted build."""
    work, mod, typ = layout.root, layout.module_name, layout.type_name
    driver = f"""program d
  use {mod}
  use umat_oti_lifted_mod
  implicit none
  type({typ}) :: s(1), x(2), dd(1,1), sc(5), v1(1), t(2), p(1), c(3), m3(3,3), f0(3,3), f1(3,3), pd(1)
  character(len=80) :: cm
  integer :: i, j
  call zero(s); call zero(x); call zero(sc); call zero(v1); call zero(t); call zero(p); call zero(c); call zero(pd)
  do i = 1, 3
    call zero(m3(:, i)); call zero(f0(:, i)); call zero(f1(:, i))
    m3(i, i)%R = 1d0; f0(i, i)%R = 1d0; f1(i, i)%R = 1d0
  end do
  dd(1,1)%R = 0d0; dd(1,1)%E1 = 0d0; dd(1,1)%E2 = 0d0
  f1(1, 1)%R = {_F11!r}d0
  x(1)%R = {_X[0]!r}d0; x(2)%R = {_X[1]!r}d0; x(1)%E1 = 1d0; x(2)%E2 = 1d0
  p(1)%R = {_PROPS!r}d0
  cm = 'X'
  call umat_oti(s, x, dd, sc(1), sc(2), sc(3), sc(4), v1, v1, sc(5), v1, v1, t, sc(1), sc(2), sc(3), &
      pd, pd, cm, 1, 0, 1, 2, p, 1, c, m3, sc(4), sc(5), f0, f1, 1, 1, 1, 1, 1, 1)
  print '(2es26.17)', s(1)%E1, s(1)%E2
contains
  subroutine zero(a)
    type({typ}) :: a(:)
    a%R = 0d0; a%E1 = 0d0; a%E2 = 0d0
  end subroutine
end program
"""
    (work / "d.f90").write_text(driver, encoding="utf-8")
    objects = ["master_parameters.o", "real_utils.o", f"{mod}.o", "oti_intrinsics.o", "umat_oti_lifted.o"]
    subprocess.run(["make", "-s", "FC=gfortran", *objects], cwd=work, check=True, capture_output=True)
    subprocess.run(["gfortran", "-ffree-line-length-none", "-o", "d", "d.f90", *objects],
                   cwd=work, check=True, capture_output=True)
    out = subprocess.run(["./d"], cwd=work, check=True, capture_output=True, text=True).stdout
    a, b = (float(v.replace("D", "E")) for v in out.split())
    return a, b


def _control_fd(tmp_path: Path, names) -> tuple[float, float]:
    """Central FD of the ORIGINAL with exactly ``names`` widened, in double.

    h = 1e-3 relative: dSTRESS/dG is about PROPS(1) = 1.5e8, so a smaller step
    is round-off (1e-6 is off by 0.2%); at 1e-3 the truncation error is 5e-7.
    """
    narrow = narrow_declarations(_TOY, names)
    widened_text, changes = widen(_TOY, PrecisionFinding(
        promoted=tuple(names), narrow=narrow, widened=tuple(sorted(n.upper() for n in names))))
    assert changes, "the control must widen the binary32 declaration"
    work = tmp_path / "control"
    work.mkdir()
    (work / "ABA_PARAM.INC").write_text("      IMPLICIT REAL*8(A-H,O-Z)\n", encoding="utf-8")
    (work / "control.for").write_text(widened_text, encoding="utf-8")
    (work / "fd.f90").write_text(f"""program fd
  implicit none
  real(8) :: x(2), xp(2), xm(2), h, d(2)
  integer :: k
  x = [{_X[0]!r}d0, {_X[1]!r}d0]
  do k = 1, 2
    h = 1d-3 * abs(x(k))
    xp = x; xm = x; xp(k) = x(k) + h; xm(k) = x(k) - h
    d(k) = (s(xp) - s(xm)) / (2d0 * h)
  end do
  print '(2es26.17)', d
contains
  real(8) function s(xin)
    real(8), intent(in) :: xin(2)
    real(8) :: st(1), xs(2), dd(1,1), sc(5), v1(1), t(2), p(1), c(3), m3(3,3), f0(3,3), f1(3,3), pd(1)
    character(len=80) :: cm
    integer :: i
    st = 0; xs = xin; sc = 0; v1 = 0; t = 0; c = 0; pd = 0; m3 = 0; dd = 0
    do i = 1, 3; m3(i, i) = 1d0; end do
    f0 = m3; f1 = m3; f1(1, 1) = {_F11!r}d0; p(1) = {_PROPS!r}d0; cm = 'X'
    call umat(st, xs, dd, sc(1), sc(2), sc(3), sc(4), v1, v1, sc(5), v1, v1, t, sc(1), sc(2), sc(3), &
        pd, pd, cm, 1, 0, 1, 2, p, 1, c, m3, sc(4), sc(5), f0, f1, 1, 1, 1, 1, 1, 1)
    s = st(1)
  end function
end program
""", encoding="utf-8")
    subprocess.run(["gfortran", "-O0", "-I.", "-o", "fd", "fd.f90", "control.for"],
                   cwd=work, check=True, capture_output=True)
    out = subprocess.run(["./fd"], cwd=work, check=True, capture_output=True, text=True).stdout
    a, b = (float(v.replace("D", "E")) for v in out.split())
    return a, b


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_widened_oti_equals_the_fd_of_the_widened_original(tmp_path):
    widened = _lift(tmp_path, "widened")
    listed = [row["name"].upper() for row in widened.binary32_stores["stores"]]
    assert set(listed) == {"MMOD", "G11", "G22"}
    assert widened.binary32_stores["binary32_rule"] == "widened"
    assert "%R = REAL(REAL(" not in widened.lifted_umat.read_text(encoding="utf-8")
    oti = _oti_derivatives(widened)
    fd = _control_fd(tmp_path, listed)
    for got, want in zip(oti, fd):
        assert abs(got - want) <= 1e-5 * max(abs(want), 1.0), (oti, fd)


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_the_author_rule_is_the_default_and_differs_where_the_derivative_cancels(tmp_path):
    author = _lift(tmp_path, "author")
    source = tmp_path / "toy.for"
    default = transform_umat_for_parameter_sensitivity(
        contract=GenericPSContract(
            name="toy", umat_source_path=source, parameters=(("E", 1),), parameter_values=(_PROPS,),
            state_variables=(("A", 1), ("B", 2)), ntens=1, nstatv=2, ndi=1, nshr=0,
            dstran_per_increment=(0.0,), n_increments=1, static_props=(_PROPS,)),
        output_dir=tmp_path / "default", extra_directions=1)
    assert default.lifted_umat.read_bytes() == author.lifted_umat.read_bytes()
    assert author.binary32_stores["binary32_rule"] == "author"
    oti = _oti_derivatives(author)
    fd = _control_fd(tmp_path, [row["name"] for row in author.binary32_stores["stores"]])
    # d/dSTATEV(1) is the cancellation: B-W's value is not the idealisation's.
    assert abs(oti[0] - fd[0]) > 0.1 * abs(fd[0]), (oti, fd)
