"""A seed handed over on the continuation line of a CALL is consumed.

A UMAT that delegates to its material routine often writes the call over two
lines, and the strain increment lands on the second one:

          CALL UMAT_MODEL(DDSDDE, STRESS, STATEV,
         1DSTRAN, PROPS, KINC, NTENS, NSTATV, NPROPS)

The semantic check ``stress_path_consumes_the_seed`` searched the stress path
line by line, and a continuation line has neither ``=`` nor ``CALL``, so the
seed was never seen to be read: six corpus sources (davidmorinNTNU V_UMAT and
five toruinaba/manforge models, free and fixed form) were refused for a zero
tangent they would not have produced. In fixed form the column-6 mark is also
glued to the first name (``1DSTRAN_OTI``), which hid it from a word-boundary
search even once the line was joined.

Behavioural: the transformed delegating UMAT is compiled and run beside the
AUTHOR's routine (renamed UMATORIG, its own object). STRESS and STATEV must
agree bit for bit, and DDSDDE (d STRESS / d DSTRAN at fixed incoming STRESS and
STATEV, one increment -- the local tangent) must match a central difference of
the original at steps 1e-4..1e-6 (converged between 1e-5 and 1e-6).

The check is not weakened: a continued call that does NOT pass the seed is
still refused.
"""
import json
import shutil
import subprocess

import pytest

_MODEL_FIXED = """      SUBROUTINE UMAT_MODEL(DDSDDE,STRESS,STATEV,DSTRAN,PROPS,KINC,
     +                      NTENS,NSTATV,NPROPS)
      IMPLICIT NONE
      INTEGER NTENS,NSTATV,NPROPS,KINC,K
      REAL*8 STRESS(NTENS),STATEV(NSTATV),DSTRAN(NTENS),PROPS(NPROPS)
      REAL*8 DDSDDE(NTENS,NTENS),EMOD,HARD
      EMOD=PROPS(1)
      HARD=1.D0/(1.D0+STATEV(1))
      DO K=1,NTENS
        STRESS(K)=STRESS(K)+HARD*EMOD*DSTRAN(K)*(1.D0+DSTRAN(1)**2)
      END DO
      STATEV(1)=STATEV(1)+ABS(DSTRAN(1))
      DO K=1,NTENS
        DDSDDE(K,K)=EMOD
      END DO
      RETURN
      END
"""

_HEADER = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
"""

#: The davidmorinNTNU shape: the seed is the first name of the continuation.
FIXED_WRAPPER = _HEADER + """      call UMAT_MODEL(DDSDDE, STRESS, STATEV,
     1DSTRAN, PROPS, KINC, NTENS, NSTATV, NPROPS)
      RETURN
      END
""" + _MODEL_FIXED

FREE_WRAPPER = """subroutine umat_model(ddsdde, stress, statev, dstran, props, kinc, ntens, nstatv, nprops)
  implicit none
  integer, intent(in) :: ntens, nstatv, nprops, kinc
  double precision, intent(inout) :: stress(ntens), statev(nstatv)
  double precision, intent(in) :: dstran(ntens), props(nprops)
  double precision, intent(out) :: ddsdde(ntens, ntens)
  double precision :: emod, hard
  integer :: k
  emod = props(1)
  hard = 1.0d0/(1.0d0 + statev(1))
  do k = 1, ntens
    stress(k) = stress(k) + hard*emod*dstran(k)*(1.0d0 + dstran(1)**2)
  end do
  statev(1) = statev(1) + abs(dstran(1))
  ddsdde = 0.0d0
end subroutine umat_model

subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, &
                ndi, nshr, ntens, nstatv, props, nprops, coords, drot, pnewdt, &
                celent, dfgrd0, dfgrd1, noel, npt, layer, kspt, kstep, kinc)
  implicit none
  character(len=80) :: cmname
  integer :: ndi, nshr, ntens, nstatv, nprops, noel, npt, layer, kspt, kstep, kinc
  double precision :: stress(ntens), statev(nstatv), ddsdde(ntens, ntens), sse, spd, scd, rpl
  double precision :: ddsddt(ntens), drplde(ntens), drpldt, stran(ntens), dstran(ntens)
  double precision :: time(2), dtime, temp, dtemp, predef(1), dpred(1), props(nprops)
  double precision :: coords(3), drot(3, 3), pnewdt, celent, dfgrd0(3, 3), dfgrd1(3, 3)
  call umat_model(ddsdde, stress, statev, &
                  dstran, props, kinc, ntens, nstatv, nprops)
end subroutine umat
"""

#: Same continued call, but the material routine is handed STRAN, not the
#: seeded DSTRAN: nothing on the stress path reads the seed, and the refusal
#: has to survive the joining of continuation lines.
FIXED_WITHOUT_SEED = FIXED_WRAPPER.replace("     1DSTRAN, PROPS,", "     1STRAN, PROPS,")

DRIVER = """program check
implicit none
real(8) :: stress(6), statev(1), ddsdde(6,6), dstran(6), props(1), stran(6)
real(8) :: s0(6), x0(1), sp(6), sm(6), xp(1), xm(1), dd(6,6), h
real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3,3), dfgrd0(3,3), dfgrd1(3,3)
real(8) :: sse, spd, scd, rpl, drpldt, dtime, temp, dtemp, pnewdt, celent, ddsddt(6), drplde(6)
character(len=80) :: cmname
integer :: j, s
props = (/ 1000.0d0 /)
time = 0; dtime = 1; temp = 0; dtemp = 0; predef = 0; dpred = 0; coords = 0
drot = 0; dfgrd0 = 0; dfgrd1 = 0; celent = 1; pnewdt = 1; cmname = 'MAT'; stran = 0
dstran = (/ 2.0d-2, -1.0d-2, 0.5d-2, 0.3d-2, -0.2d-2, 0.1d-2 /)
stress = 1.0d0; statev = 0.4d0; ddsdde = 0
call umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
          stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 1, &
          props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, 1)
s0 = 1.0d0; x0 = 0.4d0
call orig(s0, x0, dstran)
write(*, '(A,7Z17)') 'OTIBITS ', stress, statev
write(*, '(A,7Z17)') 'ORIGBITS ', s0, x0
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
    real(8), intent(inout) :: sout(6), xout(1)
    real(8), intent(in) :: de(6)
    dd = 0
    call umatorig(sout, xout, dd, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                  stran, de, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 1, &
                  props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, 1)
  end subroutine orig
end program
"""


def _transform(tmp_path, text, suffix):
    from umat_oti.services.transformation import run_transformation

    source = tmp_path / f"material{suffix}"
    source.write_text(text)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    raw = {"schema_version": "1.1", "source": str(source), "entry_routine": "UMAT", "ntens": 6,
           "derivatives": [{"target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1}],
           "material_point_driver": {"dstran_per_increment": None, "nstatv": None}}
    (tmp_path / "contract.json").write_text(json.dumps(raw))
    return run_transformation(tmp_path / "contract.json", tmp_path / "out")


def _original_object(tmp_path, text, suffix):
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(tmp_path / "ABA_PARAM.INC", reference / "ABA_PARAM.INC")
    renamed = text.replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(", 1) \
        .replace("subroutine umat(", "subroutine umatorig(", 1) \
        .replace("end subroutine umat\n", "end subroutine umatorig\n") \
        .replace("UMAT_MODEL", "UMAT_MODEL_ORIG").replace("umat_model", "umat_model_orig")
    (reference / f"orig{suffix}").write_text(renamed)
    subprocess.run(["gfortran", "-O0", "-std=legacy", f"-I{reference}", "-c", f"orig{suffix}",
                    "-o", "orig.o"], check=True, capture_output=True, text=True, cwd=reference)
    return reference / "orig.o"


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
@pytest.mark.parametrize("text,suffix", [(FIXED_WRAPPER, ".for"), (FREE_WRAPPER, ".f90")],
                         ids=["fixed-form-column-6", "free-form-ampersand"])
def test_a_seed_on_the_continuation_line_reaches_the_tangent(tmp_path, text, suffix):
    summary, code = _transform(tmp_path, text, suffix)
    assert code == 0, summary
    output = tmp_path / "out"
    shutil.copy(tmp_path / "ABA_PARAM.INC", output / "ABA_PARAM.INC")
    subprocess.run([str(output / "compile_hint.sh")], check=True, capture_output=True,
                   text=True, cwd=output)
    original = _original_object(tmp_path, text, suffix)
    (tmp_path / "driver.f90").write_text(DRIVER)
    subprocess.run(["gfortran", "-ffree-line-length-none", "driver.f90",
                    *[str(p) for p in output.glob("*.o")], str(original), "-o", "check"],
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
    assert nonzero >= 6  # the comparison is against a tangent, not against zeros


def test_a_continued_call_that_does_not_pass_the_seed_is_still_refused(tmp_path):
    summary, code = _transform(tmp_path, FIXED_WITHOUT_SEED, ".for")
    assert code != 0
    assert "stress_path_consumes_the_seed" in json.dumps(summary)


def test_the_continuation_mark_is_not_glued_to_the_seed():
    from umat_oti.transform.source_transform import _seed_consuming_stress_lines, _with_continuations

    fixed = [(10, "      call M_OTI(DDSDDE_OTI, STRESS_OTI,"), (11, "     1DSTRAN_OTI, NTENS)"),
             (12, "      X = 1")]
    joined = _with_continuations(fixed[:1], fixed, "fixed")
    assert _seed_consuming_stress_lines(joined, {"DSTRAN"}) == [10]
    free = [(3, "  call m_oti(stress_oti, &  ! trailing comment"), (4, "    & dstran_oti)")]
    assert _seed_consuming_stress_lines(_with_continuations(free[:1], free, "free"), {"DSTRAN"}) == [3]
    # A following statement is not a continuation: column 6 blank / no "&".
    assert _seed_consuming_stress_lines(
        _with_continuations(fixed[2:], fixed + [(13, "      Y = DSTRAN_OTI(1)")], "fixed"),
        {"DSTRAN"}) == []
