"""Shared check for behavioural transform tests: transform a toy UMAT, build it
and the AUTHOR's routine (renamed, its own object), run both through one
increment from a non-trivial state, and compare.

Quantity: DDSDDE = d STRESS / d DSTRAN at fixed incoming STRESS and STATEV, one
increment (the local tangent). Reference: central differences of the ORIGINAL
at h = 1e-4, 1e-5, 1e-6 (converged between the last two).
"""
import json
import shutil
import subprocess

DRIVER = """program check
implicit none
real(8) :: stress(6), statev(2), ddsdde(6,6), dstran(6), props(%(nprops)d), stran(6)
real(8) :: s0(6), x0(2), sp(6), sm(6), xp(2), xm(2), dd(6,6), h
real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3,3), dfgrd0(3,3), dfgrd1(3,3)
real(8) :: sse, spd, scd, rpl, drpldt, dtime, temp, dtemp, pnewdt, celent, ddsddt(6), drplde(6)
character(len=80) :: cmname
integer :: j, s
props = (/ %(props)s /)
time = 0; dtime = 1; temp = 0; dtemp = 0; predef = 0; dpred = 0; coords = 0
drot = 0; dfgrd0 = 0; dfgrd1 = 0; celent = 1; pnewdt = 1; cmname = 'MAT'; stran = 0
dstran = (/ 2.0d-2, -1.0d-2, 0.5d-2, 0.3d-2, -0.2d-2, 0.1d-2 /)
stress = 1.0d0; statev = 0.4d0; ddsdde = 0
call umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
          stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 2, &
          props, %(nprops)d, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, 1)
s0 = 1.0d0; x0 = 0.4d0
call orig(s0, x0, dstran)
write(*, '(A,8Z17)') 'OTIBITS ', stress, statev
write(*, '(A,8Z17)') 'ORIGBITS ', s0, x0
do j = 1, 6
  write(*, '(A,I0,6ES25.16)') 'DDSDDE ', j, ddsdde(j, :)
end do
do j = 1, 6
  do s = 4, 6
    h = 10.0d0**(-s)
    sp = 1.0d0; xp = 0.4d0; dstran(j) = dstran(j) + h
    call orig(sp, xp, dstran)
    dstran(j) = dstran(j) - 2*h
    sm = 1.0d0; xm = 0.4d0
    call orig(sm, xm, dstran)
    dstran(j) = dstran(j) + h
    write(*, '(A,I0,1X,I0,6ES25.16)') 'FD ', j, s, (sp - sm)/(2*h)
  end do
end do
contains
  subroutine orig(sout, xout, de)
    real(8), intent(inout) :: sout(6), xout(2)
    real(8), intent(in) :: de(6)
    dd = 0
    call umatorig(sout, xout, dd, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                  stran, de, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 2, &
                  props, %(nprops)d, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, 1)
  end subroutine orig
end program
"""


def transform(tmp_path, text, suffix):
    from umat_oti.services.transformation import run_transformation

    source = tmp_path / f"material{suffix}"
    source.write_text(text)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    raw = {"schema_version": "1.1", "source": str(source), "entry_routine": "UMAT", "ntens": 6,
           "derivatives": [{"target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1}],
           "material_point_driver": {"dstran_per_increment": None, "nstatv": None}}
    (tmp_path / "contract.json").write_text(json.dumps(raw))
    return run_transformation(tmp_path / "contract.json", tmp_path / "out")


def check_against_original(tmp_path, text, suffix, renames, props):
    """Transform, build, run; assert bitwise primal and DDSDDE == FD of the original.

    ``props`` are Fortran literals ("1000.0d0"); ``renames`` turn the author's
    routine names into the reference's (UMAT -> UMATORIG, helpers likewise).
    """
    summary, code = transform(tmp_path, text, suffix)
    assert code == 0, json.dumps(summary)[:3000]
    output = tmp_path / "out"
    shutil.copy(tmp_path / "ABA_PARAM.INC", output / "ABA_PARAM.INC")
    subprocess.run([str(output / "compile_hint.sh")], check=True, capture_output=True,
                   text=True, cwd=output)
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(tmp_path / "ABA_PARAM.INC", reference / "ABA_PARAM.INC")
    renamed = text
    for old, new in renames:
        renamed = renamed.replace(old, new)
    (reference / f"orig{suffix}").write_text(renamed)
    subprocess.run(["gfortran", "-O0", "-std=legacy", "-ffixed-line-length-none", "-ffree-line-length-none",
                    f"-I{reference}", "-c", f"orig{suffix}",
                    "-o", "orig.o", f"-J{reference}"], check=True, capture_output=True, text=True,
                   cwd=reference)
    (tmp_path / "driver.f90").write_text(DRIVER % {"nprops": len(props), "props": ", ".join(props)})
    subprocess.run(["gfortran", "-ffree-line-length-none", "driver.f90",
                    *[str(p) for p in output.glob("*.o")], str(reference / "orig.o"), "-o", "check"],
                   check=True, capture_output=True, text=True, cwd=tmp_path)
    lines = subprocess.run([str(tmp_path / "check")], check=True, capture_output=True,
                           text=True, cwd=tmp_path).stdout.splitlines()
    bits = {row.split()[0]: row.split()[1:] for row in lines if row.startswith(("OTIBITS", "ORIGBITS"))}
    assert bits["OTIBITS"] == bits["ORIGBITS"]
    tangent = {int(r.split()[1]): [float(v) for v in r.split()[2:]]
               for r in lines if r.startswith("DDSDDE ")}
    fd: dict = {}
    for row in lines:
        if row.startswith("FD "):
            _, j, s, *values = row.split()
            fd.setdefault(int(j), {})[int(s)] = [float(v) for v in values]
    nonzero = 0
    for j in range(1, 7):
        steps = fd[j]
        scale = max(1.0, max(abs(v) for v in steps[5]))
        assert max(abs(a - b) for a, b in zip(steps[5], steps[6])) <= 1e-6 * scale
        for k in range(6):
            got, ref = tangent[k + 1][j - 1], steps[6][k]
            assert abs(got - ref) <= 1e-6 * scale, (k + 1, j, got, ref)
            nonzero += abs(ref) > 1.0
    assert nonzero >= 6
    return output
