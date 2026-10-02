"""The inserted STRESS/DDSDDE extractions run on every path, and nothing overwrites them.

Two defects from Vera's B1 review, both of which passed every semantic check:

* czmHealing.f: both extractions were emitted inside the ELSE of
  ``IF (Da0.LE.0.99999)``, so an undamaged material point returned STRESS = 0
  and DDSDDE = 0. The checks asked whether an extraction exists and after
  which line -- never under which condition.
* umat_neohooke.f90: ``forall(i=1:ntens,j=1:ntens,j<i) ddsdde(i,j) =
  ddsdde(j,i)`` after the extraction overwrote the lower triangle of the
  (unsymmetric) OTI tangent; the FORALL was not on the list of DDSDDE writes.

Behavioural: the czmHealing shape -- a stress update, an old-tangent IF/ELSE,
then a trailing IF/ELSE on a state flag in which the last state writes sit --
is transformed and run on BOTH branches against the ORIGINAL compiled
separately: STRESS bitwise, DDSDDE against central differences of the
original. The FORALL shape must be refused by name, not emitted.
"""
import json
import shutil
import subprocess

import pytest

BRANCHED = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      EMOD=PROPS(1)
      DA0=STATEV(1)
      DMG=1.D0-DA0
      DO K=1,NTENS
        STRESS(K)=STRESS(K)+DMG*EMOD*DSTRAN(K)*(1.D0+DSTRAN(1)**2)
      END DO
      IF (DSTRAN(1).GT.0.D0) THEN
        DO K=1,NTENS
          DDSDDE(K,K)=DMG*EMOD
        END DO
      ELSE
        DO K=1,NTENS
          DDSDDE(K,K)=EMOD
        END DO
      ENDIF
      STATEV(3)=STRESS(1)
      IF (DA0.LE.0.99999D0) THEN
        STATEV(2)=STATEV(2)+STRESS(1)*DSTRAN(1)
      ELSE
        STATEV(2)=0.D0
      ENDIF
      RETURN
      END
"""

DRIVER = """program check
implicit none
real(8) :: stress(6), statev(3), ddsdde(6,6), dstran(6), props(1), stran(6)
real(8) :: s0(6), x0(3), sp(6), sm(6), xp(3), xm(3), dd(6,6), h, da0
real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3,3), dfgrd0(3,3), dfgrd1(3,3)
real(8) :: sse, spd, scd, rpl, drpldt, dtime, temp, dtemp, pnewdt, celent, ddsddt(6), drplde(6)
character(len=80) :: cmname
integer :: j, s, k, branch
props = (/ 1000.0d0 /)
time = 0; dtime = 1; temp = 0; dtemp = 0; predef = 0; dpred = 0; coords = 0
drot = 0; dfgrd0 = 0; dfgrd1 = 0; celent = 1; pnewdt = 1; cmname = 'MAT'; stran = 0
do branch = 1, 2
  da0 = merge(0.3d0, 1.0d0, branch == 1)
  dstran = (/ 2.0d-3, -1.0d-3, 0.5d-3, 0.3d-3, -0.2d-3, 0.1d-3 /)
  stress = 1.0d0; statev = (/ da0, 0.0d0, 0.0d0 /); ddsdde = 0
  call umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
            stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 3, &
            props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, 1)
  s0 = 1.0d0; x0 = (/ da0, 0.0d0, 0.0d0 /)
  call orig(s0, x0, dstran)
  write(*, '(A,I0,9Z17)') 'OTIBITS ', branch, stress, statev
  write(*, '(A,I0,9Z17)') 'ORIGBITS ', branch, s0, x0
  do k = 1, 6
    write(*, '(A,I0,1X,I0,6ES25.16)') 'DDSDDE ', branch, k, ddsdde(k, :)
  end do
  do j = 1, 6
    do s = 4, 6
      h = 10.0d0**(-s)
      sp = 1.0d0; xp = (/ da0, 0.0d0, 0.0d0 /); dstran(j) = dstran(j) + h
      call orig(sp, xp, dstran)
      dstran(j) = dstran(j) - 2*h
      sm = 1.0d0; xm = (/ da0, 0.0d0, 0.0d0 /)
      call orig(sm, xm, dstran)
      dstran(j) = dstran(j) + h
      write(*, '(A,I0,1X,I0,1X,I0,6ES25.16)') 'FD ', branch, j, s, (sp - sm)/(2*h)
    end do
  end do
end do
contains
  subroutine orig(sout, xout, de)
    real(8), intent(inout) :: sout(6), xout(3)
    real(8), intent(in) :: de(6)
    dd = 0
    call umatorig(sout, xout, dd, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                  stran, de, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 3, &
                  props, 1, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, 1, 1)
  end subroutine orig
end program
"""


def _transform(tmp_path, text):
    from umat_oti.services.transformation import run_transformation

    source = tmp_path / "material.for"
    source.write_text(text)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    raw = {"schema_version": "1.1", "source": str(source), "entry_routine": "UMAT", "ntens": 6,
           "derivatives": [{"target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1}],
           "material_point_driver": {"dstran_per_increment": None, "nstatv": None}}
    (tmp_path / "contract.json").write_text(json.dumps(raw))
    return run_transformation(tmp_path / "contract.json", tmp_path / "out")


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_both_branches_return_the_originals_stress_and_its_tangent(tmp_path):
    summary, code = _transform(tmp_path, BRANCHED)
    assert code == 0, summary
    output = tmp_path / "out"
    shutil.copy(tmp_path / "ABA_PARAM.INC", output / "ABA_PARAM.INC")
    subprocess.run([str(output / "compile_hint.sh")], check=True, capture_output=True,
                   text=True, cwd=output)
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(tmp_path / "ABA_PARAM.INC", reference / "ABA_PARAM.INC")
    (reference / "orig.for").write_text(BRANCHED.replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(", 1))
    subprocess.run(["gfortran", "-O0", "-std=legacy", f"-I{reference}", "-c", "orig.for", "-o", "orig.o"],
                   check=True, capture_output=True, text=True, cwd=reference)
    (tmp_path / "driver.f90").write_text(DRIVER)
    subprocess.run(["gfortran", "-ffree-line-length-none", "driver.f90",
                    *[str(p) for p in output.glob("*.o")], str(reference / "orig.o"), "-o", "check"],
                   check=True, capture_output=True, text=True, cwd=tmp_path)
    lines = subprocess.run([str(tmp_path / "check")], check=True, capture_output=True,
                           text=True, cwd=tmp_path).stdout.splitlines()
    bits = {(row.split()[0], int(row.split()[1])): row.split()[2:]
            for row in lines if row.startswith(("OTIBITS", "ORIGBITS"))}
    tangent = {(int(r.split()[1]), int(r.split()[2])): [float(v) for v in r.split()[3:]]
               for r in lines if r.startswith("DDSDDE ")}
    fd: dict = {}
    for row in lines:
        if row.startswith("FD "):
            _, branch, j, s, *values = row.split()
            fd.setdefault((int(branch), int(j)), {})[int(s)] = [float(v) for v in values]
    for branch in (1, 2):
        assert bits[("OTIBITS", branch)] == bits[("ORIGBITS", branch)], branch
        for j in range(1, 7):
            steps = fd[(branch, j)]
            scale = max(1.0, max(abs(v) for v in steps[5]))
            assert max(abs(a - b) for a, b in zip(steps[4], steps[5])) <= 1e-6 * scale
            for k in range(6):
                got, ref = tangent[(branch, k + 1)][j - 1], steps[6][k]
                assert abs(got - ref) <= 1e-7 * scale, (branch, k + 1, j, got, ref)


def test_the_extraction_is_never_left_inside_a_branch(tmp_path):
    """The emitted file itself: both markers sit outside every block."""
    from umat_oti.transform.control_blocks import block_spans, enclosing_blocks

    summary, code = _transform(tmp_path, BRANCHED)
    assert code == 0, summary
    emitted = next((tmp_path / "out").glob("*_oti.for")).read_text().splitlines()
    blocks = block_spans(emitted, "fixed", (1, len(emitted)))
    markers = [n for n, line in enumerate(emitted, start=1)
               if "Copy real-valued OTIS outputs" in line or "OTIS DDSDDE extraction" in line]
    assert markers
    assert not any(enclosing_blocks(blocks, n) for n in markers)


FORALL = BRANCHED.replace(
    "      RETURN\n",
    "      FORALL (I=1:NTENS, J=1:NTENS, J.LT.I) DDSDDE(I,J)=DDSDDE(J,I)\n      RETURN\n")


WHERE = BRANCHED.replace(
    "      RETURN\n",
    "      WHERE (DDSDDE.LT.0.D0) DDSDDE=0.D0\n      RETURN\n")


@pytest.mark.parametrize("source, keyword", [(FORALL, "FORALL"), (WHERE, "WHERE")],
                         ids=["forall", "where"])
def test_a_masked_write_to_ddsdde_after_the_update_is_seen(tmp_path, source, keyword):
    """matmodlab umat_neohooke (Vera Q1): a FORALL/WHERE write after the extraction
    would overwrite the OTI tangent; it is refused, naming the statement."""
    summary, code = _transform(tmp_path, source)
    # Only the diagnostics: the whole summary holds tmp_path, whose name
    # contains the keyword and once made this assertion vacuous.
    text = json.dumps(summary.get("blockers", []) + summary.get("warnings", []))
    assert code != 0
    assert keyword in text.upper() and "DDSDDE" in text


def test_hoisting_moves_an_insertion_out_of_every_enclosing_block():
    from umat_oti.transform.control_blocks import hoisted_insertion_line

    lines = ["      SUBROUTINE X", "      IF (A.GT.0) THEN", "        B=1", "      ELSE",
             "        DO I=1,3", "          B=B+1", "        END DO", "      ENDIF", "      END"]
    assert hoisted_insertion_line(lines, "fixed", (1, 9), 6) == (8, "")
    assert hoisted_insertion_line(lines, "fixed", (1, 9), 8) == (8, "")
    with_return = lines[:6] + ["          RETURN"] + lines[6:]
    line, problem = hoisted_insertion_line(with_return, "fixed", (1, 10), 3)
    assert line == 3 and "leaves the routine" in problem
