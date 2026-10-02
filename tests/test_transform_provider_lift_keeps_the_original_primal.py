"""The provider's lifted UMAT reproduces the ORIGINAL's stress to round-off.

Noether (B2, finding 2) found providers built from the working tree off the
original by 1.1e-8 (abaci), 5.9e-7 (Sina CompresibleNeoHookean) and 9.3e-7
(keisuke biofilm visco), with Newton failing at increment 1. Cause: for a
14-minute window the lifter's binary32 rule typed each routine from its
INCLUDE-expanded text, in which ABA_PARAM.INC's IMPLICIT REAL*8 had been left
out, so every implicitly typed local was rounded to binary32 at every store.
The routine is now typed from its text as written (routine_typing resolves the
INCLUDE itself).

Behavioural, on the corpus source that moved most (Sina-Taghizadeh's
CompresibleNeoHookean.for, from the acquisition cache; skipped where the cache
is absent): the lift ``umat_oti.provider.build`` uses
(transform_umat_for_parameter_sensitivity) drives three finite-strain
increments through its generated driver, and the ORIGINAL -- the author's file,
UMAT renamed, compiled on its own -- is driven through the same increments by a
plain REAL*8 driver. Stresses must agree to 4e-15 relative (the driver prints 16
digits); a binary32 store anywhere shows up at the 8th. A second case does the
same for a synthetic IMPLICIT-REAL*8 routine so the guard runs without the cache.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

CACHE = Path("/home/ammslab3/softwarex_work/discovery_cache")
SINA = CACHE / "Sina-Taghizadeh__UMAT_Hyperelastic/CompresibleNeoHookean.for"

SYNTHETIC = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      C10=PROPS(1)
      D1=PROPS(2)
      DET=DFGRD1(1,1)*DFGRD1(2,2)*DFGRD1(3,3)-DFGRD1(1,2)*DFGRD1(2,1)
     1 *DFGRD1(3,3)
      SCALE=DET**(-1.D0/3.D0)
      DO K=1,NDI
        STRESS(K)=2.D0*C10*SCALE*SCALE*DFGRD1(K,K)**2/DET+2.D0/D1*(DET-1.D0)
      END DO
      DO K=NDI+1,NTENS
        STRESS(K)=2.D0*C10/DET*DFGRD1(1,2)*SCALE
      END DO
      RETURN
      END
"""

REFERENCE = """program reference
implicit none
real(8) :: stress(6), statev(8), ddsdde(6,6), dstran(6), props(2), stran(6)
real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3,3), dfgrd0(3,3), dfgrd1(3,3), inc_f(3,3)
real(8) :: sse, spd, scd, rpl, drpldt, dtime, temp, dtemp, pnewdt, celent, ddsddt(6), drplde(6)
character(len=80) :: cmname
integer :: inc, i, kstep(4)
props = (/ {p1}d0, {p2}d0 /)
stress = 0; statev = 0; stran = 0; dstran = 0; time = 0; dtime = 1; temp = 293.15d0; dtemp = 0
predef = 0; dpred = 0; coords = 0; drot = 0; celent = 1; pnewdt = 1; cmname = 'MATERIAL_OTI'
dfgrd0 = 0; dfgrd1 = 0
do i = 1, 3
  drot(i,i) = 1; dfgrd0(i,i) = 1; dfgrd1(i,i) = 1
end do
inc_f = reshape((/ {f} /), (/ 3, 3 /), order=(/ 2, 1 /))
kstep = 0; kstep(1) = 1
do inc = 1, 3
  dfgrd0 = dfgrd1
  dfgrd1 = dfgrd1 + inc_f
  ddsdde = 0
  call umatorig(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, 6, 8, &
                props, 2, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, {kstep}, inc)
  write(*, '(6ES24.15E3)') stress
  time = time + dtime
end do
end program
"""

F_INC = (0.02, 0.004, 0.0, 0.001, -0.01, 0.0, 0.0, 0.0, -0.005)


def _compare(tmp_path: Path, source_text: str, suffix: str, kstep_array: bool):
    from umat_oti.transform.parameter_sensitivity_transform import (
        GenericPSContract, compile_generic_ps, run_generic_ps,
        transform_umat_for_parameter_sensitivity)

    source = tmp_path / ("material" + suffix)
    source.write_text(source_text)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    props = (1.7, 0.08)
    contract = GenericPSContract(
        name="provider_primal", umat_source_path=source, parameters=(("C10", 1), ("D1", 2)),
        parameter_values=props, state_variables=(), ntens=6, nstatv=8, ndi=3, nshr=3,
        dstran_per_increment=(0.0,) * 6, n_increments=3, static_props=props,
        deformation_gradient_increment=F_INC)
    layout = transform_umat_for_parameter_sensitivity(contract=contract, output_dir=tmp_path / "ps")
    assert "%R = REAL(REAL(" not in layout.lifted_umat.read_text()
    run = run_generic_ps(compile_generic_ps(layout))
    assert run.returncode == 0, run.stderr
    lifted = [[float(v) for v in line.split(",")[2:8]]
              for line in run.primal_csv.read_text().splitlines()[1:]]
    reference = tmp_path / "reference"
    reference.mkdir()
    shutil.copy(tmp_path / "ABA_PARAM.INC", reference / "ABA_PARAM.INC")
    (reference / ("orig" + suffix)).write_text(
        source_text.replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(", 1))
    (reference / "driver.f90").write_text(REFERENCE.format(
        p1=props[0], p2=props[1], f=", ".join(f"{v}d0" for v in F_INC),
        kstep="kstep" if kstep_array else "kstep(1)"))
    subprocess.run(["gfortran", "-O0", "-std=legacy", "-ffixed-line-length-none", "-c", "orig" + suffix],
                   check=True, capture_output=True, text=True, cwd=reference)
    subprocess.run(["gfortran", "-ffree-line-length-none", "driver.f90", "orig.o", "-o", "ref"],
                   check=True, capture_output=True, text=True, cwd=reference)
    expected = [[float(v) for v in line.split()] for line in subprocess.run(
        [str(reference / "ref")], check=True, capture_output=True, text=True).stdout.splitlines()]
    assert len(lifted) == len(expected) == 3
    worst = max(abs(a - b) / max(1.0, abs(b)) for got, ref in zip(lifted, expected) for a, b in zip(got, ref))
    assert worst <= 4e-15, worst


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_an_implicit_real8_routine_lifts_without_binary32_rounding(tmp_path):
    _compare(tmp_path, SYNTHETIC, ".for", kstep_array=False)


@pytest.mark.skipif(shutil.which("gfortran") is None or not SINA.is_file(),
                    reason="gfortran and the acquisition cache required")
def test_sina_compressible_neo_hookean_lift_matches_the_original(tmp_path):
    _compare(tmp_path, SINA.read_text(errors="replace"), ".for", kstep_array=True)
