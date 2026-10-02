"""What the source computes in binary32 stays binary32 in the transformed routine.

Curie-G (B2 growth diagnosis) traced 24-28 growth rows whose transformed
primal drifted from the original by 1e7-1e8 ulpK to two constructs:

* B-W: a variable declared ``REAL`` (binary32) is shadowed by a double OTI
  value, so the binary32 rounding of every store vanished;
* B-L: a literal-only subexpression such as ``(1.0+X)**(-5.0/3.0)`` was
  rewritten with each literal widened (``-5.0D0/3.0D0``), so the quotient was
  formed in double instead of binary32.

Behavioural: a small UMAT with both constructs is transformed (tangent-only
contract), and over a three-increment history the transformed routine's STRESS
and STATEV must equal the ORIGINAL's -- compiled on its own from the same text,
entry renamed UMATORIG -- to the last bit; DDSDDE must match a central
difference of the original at three step sizes. A control asserts the
original really is binary32-sensitive here (the double evaluation differs),
so the bitwise agreement is not vacuous.
"""
import json
import shutil
import subprocess

import pytest

SOURCE = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
{declaration}
      REAL PIH
      EMOD=PROPS(1)
      PIH=3.1415927
      GROW=1.0+0.37*STATEV(1)
C     SweetMelon: 9.0/40.0*PIH is a binary32 product inside a double expression.
      ANG=9.0/40.0*PIH*(-2.0+STATEV(1))
      SCALE=1.0+DSTRAN(1)*0.3
      DO K=1,NTENS
        STRESS(K)=STRESS(K)+EMOD*DSTRAN(K)*SCALE*GROW*COS(ANG)
     1    *(1.0+DSTRAN(2))**(-5.0/3.0)
      END DO
      STATEV(1)=STATEV(1)+DSTRAN(1)*GROW+DSTRAN(2)*(GROW*0.3-1.0)
C     Cereus: a binary32 SQRT the transform guards with MAX(REAL(.),1.0D-30).
     1  +DSTRAN(3)*Sqrt(2.0)*Sqrt(GROW+0.7)
      DO K=1,NTENS
        DO L=1,NTENS
          DDSDDE(K,L)=0.D0
        END DO
      END DO
      RETURN
      END
"""

DRIVER = """program check
implicit none
real(8) :: stress(6), statev(1), ddsdde(6,6), dstran(6), props(1), stran(6)
real(8) :: s0(6), x0(1), sp(6), sm(6), xp(1), xm(1), dd(6,6), h
real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3,3), dfgrd0(3,3), dfgrd1(3,3)
real(8) :: sse, spd, scd, rpl, drpldt, dtime, temp, dtemp, pnewdt, celent, ddsddt(6), drplde(6)
real(8) :: inc_strain(6, 3)
character(len=80) :: cmname
integer :: inc, j, s, k
props = (/ 210.0d3 /)
inc_strain(:,1) = (/ 1.3d-3, -0.4d-3, 0.2d-3, 0.7d-3, 0.1d-3, -0.3d-3 /)
inc_strain(:,2) = (/ 0.9d-3, 0.5d-3, -0.6d-3, 0.2d-3, 0.3d-3, 0.4d-3 /)
inc_strain(:,3) = (/ -0.2d-3, 1.1d-3, 0.3d-3, -0.5d-3, 0.6d-3, 0.2d-3 /)
stress = 0; statev = 0.05d0; stran = 0
s0 = 0; x0 = 0.05d0
time = 0; dtime = 1; temp = 0; dtemp = 0; predef = 0; dpred = 0; coords = 0
drot = 0; dfgrd0 = 0; dfgrd1 = 0; celent = 1; pnewdt = 1; cmname = 'MAT'
do inc = 1, 3
  dstran = inc_strain(:, inc)
  ddsdde = 0
  call umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
            stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 1, &
            props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, inc)
  ! the reference from the same incoming state, then FD of it
  do j = 1, 6
    do s = 5, 7
      h = 10.0d0**(-s)
      sp = s0; xp = x0; dstran = inc_strain(:, inc); dstran(j) = dstran(j) + h
      call orig(sp, xp, dstran, inc)
      sm = s0; xm = x0; dstran = inc_strain(:, inc); dstran(j) = dstran(j) - h
      call orig(sm, xm, dstran, inc)
      write(*, '(A,I0,1X,I0,1X,I0,6ES25.16)') 'FD ', inc, j, s, (sp - sm)/(2*h)
    end do
  end do
  dstran = inc_strain(:, inc)
  call orig(s0, x0, dstran, inc)
  write(*, '(A,I0,7ES25.16)') 'OTI ', inc, stress, statev
  write(*, '(A,I0,7ES25.16)') 'ORIG ', inc, s0, x0
  write(*, '(A,I0,7Z17)') 'OTIBITS ', inc, stress, statev
  write(*, '(A,I0,7Z17)') 'ORIGBITS ', inc, s0, x0
  do k = 1, 6
    write(*, '(A,I0,1X,I0,6ES25.16)') 'DDSDDE ', inc, k, ddsdde(k, :)
  end do
end do
contains
  subroutine orig(sout, xout, de, kinc)
    real(8), intent(inout) :: sout(6), xout(1)
    real(8), intent(in) :: de(6)
    integer, intent(in) :: kinc
    dd = 0
    call umatorig(sout, xout, dd, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                  stran, de, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 1, &
                  props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, kinc)
  end subroutine orig
end program
"""


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
@pytest.mark.parametrize("declaration", [
    # SCALE depends on DSTRAN: binary32 there makes the original a staircase
    # in the strain, which no finite difference resolves -- so this variant
    # checks the primal bitwise and leaves the tangent to the next one.
    "      REAL SCALE, GROW",
    # Only the state-driven GROW is binary32; the strain path is double, so
    # the tangent is checked against finite differences of the original.
    "      REAL GROW\n      DOUBLE PRECISION SCALE",
])
def test_binary32_stores_and_literal_folds_reproduce_the_original_bitwise(tmp_path, declaration):
    from umat_oti.services.transformation import run_transformation

    text = SOURCE.format(declaration=declaration)
    source = tmp_path / "material.for"
    source.write_text(text)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    raw = {"schema_version": "1.1", "source": str(source), "entry_routine": "UMAT", "ntens": 6,
           "derivatives": [{"target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1}],
           "material_point_driver": {"dstran_per_increment": None, "nstatv": None}}
    (tmp_path / "contract.json").write_text(json.dumps(raw))
    output = tmp_path / "out"
    summary, code = run_transformation(tmp_path / "contract.json", output)
    assert code == 0, summary
    shutil.copy(tmp_path / "ABA_PARAM.INC", output / "ABA_PARAM.INC")
    emitted = next(output.glob("*_oti.for")).read_text()
    assert "%R = REAL(REAL(" in emitted                      # B-W: rounding emitted
    assert "-1.6666666269302368D0" in emitted               # B-L: binary32 fold
    assert "OTI_R4(" in emitted                              # B-W: binary32 operation
    subprocess.run([str(output / "compile_hint.sh")], check=True, capture_output=True,
                   text=True, cwd=output)
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(tmp_path / "ABA_PARAM.INC", reference / "ABA_PARAM.INC")
    (reference / "material_reference.for").write_text(
        text.replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(", 1))
    subprocess.run(["gfortran", "-O0", "-std=legacy", f"-I{reference}", "-c",
                    "material_reference.for", "-o", "reference.o"],
                   check=True, capture_output=True, text=True, cwd=reference)
    (tmp_path / "driver.f90").write_text(DRIVER)
    objects = [str(p) for p in output.glob("*.o")]
    subprocess.run(["gfortran", "-ffree-line-length-none", "driver.f90", *objects,
                    str(reference / "reference.o"), "-o", "check"],
                   check=True, capture_output=True, text=True, cwd=tmp_path)
    lines = subprocess.run([str(tmp_path / "check")], check=True, capture_output=True,
                           text=True, cwd=tmp_path).stdout.splitlines()
    bits = {}
    for row in lines:
        if row.startswith(("OTIBITS", "ORIGBITS")):
            label, inc, *words = row.split()
            bits[(label, int(inc))] = words
    for inc in (1, 2, 3):
        assert bits[("OTIBITS", inc)] == bits[("ORIGBITS", inc)], inc
    if "REAL SCALE" in declaration:
        return
    fd: dict = {}
    for row in lines:
        if row.startswith("FD "):
            _, inc, j, s, *values = row.split()
            fd.setdefault((int(inc), int(j)), {})[int(s)] = [float(v) for v in values]
    tangent = {}
    for row in lines:
        if row.startswith("DDSDDE "):
            _, inc, k, *values = row.split()
            tangent[(int(inc), int(k))] = [float(v) for v in values]
    for (inc, j), steps in fd.items():
        column = [tangent[(inc, k)][j - 1] for k in range(1, 7)]
        scale = max(abs(v) for v in steps[6])
        # FD-only plateau: the three steps agree with each other first.
        assert max(abs(a - b) for a, b in zip(steps[5], steps[6])) <= 1e-6 * scale
        assert max(abs(a - b) for a, b in zip(steps[6], steps[7])) <= 1e-5 * scale
        for got, ref in zip(column, steps[6]):
            assert abs(got - ref) <= 1e-6 * scale + 1e-9, (inc, j, got, ref)


def test_the_original_is_binary32_sensitive_here():
    """Control: evaluated in double, this source gives a different number.

    (1+x)**(-5/3) with the exponent formed in binary32 versus in double
    differs in the 8th digit, and GROW stored in binary32 versus double in
    the 8th as well -- so bitwise agreement above is a real constraint.
    """
    import numpy as np

    x = 0.5e-3
    single_exponent = float(np.float32(-5.0) / np.float32(3.0))
    assert (1.0 + x) ** single_exponent != (1.0 + x) ** (-5.0 / 3.0)
    grow = 1.0 + 0.37 * 0.05
    assert float(np.float32(grow)) != grow


def test_the_folder_respects_fortran_precedence_and_kinds():
    from umat_oti.transform.binary32 import fold_binary32_constants as fold

    # Left-associative: A*1.0/200 is (A*1.0)/200, nothing literal-only to fold.
    assert fold("      Z = A_OTI*1.0/200 + B") == "      Z = A_OTI*1.0/200 + B"
    # 1.0/200 at the head of a product is folded in binary32.
    assert "0.004999999888241291D0" in fold("      Z = 1.0/200*A_OTI + B")
    # Double literals and integer-only subexpressions are left alone.
    assert fold("      Q = 2.0D0/3.0D0*X + 1/2*Y + 1") == "      Q = 2.0D0/3.0D0*X + 1/2*Y + 1"
    # A CALL argument keeps the kind the source gave it.
    assert fold("      CALL FOO(1.0/3.0, X)") == "      CALL FOO(1.0/3.0, X)"
    # The comparison literal is untouched (its binary32 value is what the
    # caller's per-literal conversion keeps).
    assert fold("      IF ((TIME(2)+DTIME) .LE. 2.2) X = 1") == "      IF ((TIME(2)+DTIME) .LE. 2.2) X = 1"
    # An intrinsic of literals is folded correctly rounded in binary32.
    assert "1.7320507764816284D0" in fold("      S = SQRT(3.0)*A_OTI + 2")


PS_REFERENCE = """program reference
implicit none
real(8) :: stress(6), statev(1), ddsdde(6,6), dstran(6), props(1), stran(6)
real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3,3), dfgrd0(3,3), dfgrd1(3,3)
real(8) :: sse, spd, scd, rpl, drpldt, dtime, temp, dtemp, pnewdt, celent, ddsddt(6), drplde(6)
character(len=80) :: cmname
integer :: inc
props = (/ 210.0d3 /)
dstran = (/ 1.3d-3, -0.4d-3, 0.2d-3, 0.7d-3, 0.1d-3, -0.3d-3 /)
stress = 0; statev = 0; stran = 0; time = 0; dtime = 1; temp = 293.15d0; dtemp = 0
predef = 0; dpred = 0; coords = 0; drot = 0; dfgrd0 = 0; dfgrd1 = 0; celent = 1
pnewdt = 1; cmname = 'MATERIAL_OTI'
do inc = 1, 3
  ddsdde = 0
  call umatorig(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 1, &
                props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, inc)
  write(*, '(7ES24.15E3)') stress, statev
  stran = stran + dstran
  time = time + dtime
end do
end program
"""


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_the_lifted_build_keeps_binary32_too(tmp_path):
    """The PROPS-seeding lifter (the build parameter sensitivities come from)."""
    from umat_oti.transform.parameter_sensitivity_transform import (
        GenericPSContract, compile_generic_ps, run_generic_ps,
        transform_umat_for_parameter_sensitivity)

    text = SOURCE.format(declaration="      REAL SCALE, GROW")
    source = tmp_path / "material.for"
    source.write_text(text)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    contract = GenericPSContract(
        name="binary32", umat_source_path=source, parameters=(("EMOD", 1),),
        parameter_values=(210.0e3,), state_variables=(("S1", 1),), ntens=6, nstatv=1,
        ndi=3, nshr=3, dstran_per_increment=(1.3e-3, -0.4e-3, 0.2e-3, 0.7e-3, 0.1e-3, -0.3e-3),
        n_increments=3)
    layout = transform_umat_for_parameter_sensitivity(contract=contract, output_dir=tmp_path / "ps")
    lifted = layout.lifted_umat.read_text()
    assert "%R = REAL(REAL(" in lifted
    run = run_generic_ps(compile_generic_ps(layout))
    assert run.returncode == 0, run.stderr
    rows = [line.split(",") for line in run.primal_csv.read_text().splitlines()[1:]]
    lifted_values = [[float(v) for v in row[2:]] for row in rows]
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(tmp_path / "ABA_PARAM.INC", reference / "ABA_PARAM.INC")
    (reference / "orig.for").write_text(text.replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(", 1))
    (reference / "driver.f90").write_text(PS_REFERENCE)
    subprocess.run(["gfortran", "-O0", "-std=legacy", "-ffree-line-length-none", f"-I{reference}",
                    "orig.for", "driver.f90", "-o", "ref"], check=True, capture_output=True,
                   text=True, cwd=reference)
    expected = [[float(v) for v in line.split()] for line in subprocess.run(
        [str(reference / "ref")], check=True, capture_output=True, text=True).stdout.splitlines()]
    assert len(expected) == len(lifted_values) == 3
    for got_row, ref_row in zip(lifted_values, expected):
        for got, ref in zip(got_row, ref_row):
            # Printed to 16 significant digits; a binary32 store or fold
            # missed shows up at the 8th.
            assert abs(got - ref) <= 4e-15 * max(1.0, abs(ref)), (got, ref)
