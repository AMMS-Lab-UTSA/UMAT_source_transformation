"""A routine defined on a tab-led fixed-form line in a companion file is found.

ifort and gfortran read a tab in the label field as "statement starts in
column 7". The dependency resolver did column arithmetic on the raw line, so
``\\tsubroutine inv3x3(A,invA,det)`` had an 'o' in column 6 and was skipped as
a continuation line: every module procedure of the OXFORD-UMAT crystal
plasticity code (Shi2oon/DIC2ABAQUS, five corpus copies) is written that way,
and the companion search reported INV3X3 and INITIALIZE_ORIENTATIONS missing
from the very files that define them. The resolver now expands such a tab
before reading the columns, as the parser already does.

Behavioural: the UMAT calls a helper published beside it on tab-led lines; the
transform resolves it through the published-companion retry, and the result is
built and run against the author's two files compiled separately (primal
bitwise, DDSDDE against central differences at three step sizes).
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _transform_vs_original import DRIVER

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

UMAT = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      CALL KSOFT(STRESS,DSTRAN,PROPS(1),NTENS)
      STATEV(1)=STATEV(1)+STRESS(1)
      DO K=1,NTENS
        DO L=1,NTENS
          DDSDDE(K,L)=0.D0
        END DO
        DDSDDE(K,K)=PROPS(1)
      END DO
      RETURN
      END
"""

# Tab-led, as the OXFORD-UMAT modules are written.
HELPER = ("\tSUBROUTINE KSOFT(S,DE,E,N)\n"
          "\tINCLUDE 'ABA_PARAM.INC'\n"
          "\tDIMENSION S(N),DE(N)\n"
          "\tDO K=1,N\n"
          "\t  S(K)=S(K)+E*DE(K)*(1.D0+10.D0*DE(K)*DE(K))\n"
          "\t1   +0.3D0*E*DE(MOD(K,N)+1)\n"
          "\tEND DO\n"
          "\tRETURN\n"
          "\tEND\n")


def test_the_resolver_reads_a_tab_led_definition(tmp_path):
    from umat_oti.transform.dependency_resolution import _definitions_in

    path = tmp_path / "ksoft.for"
    path.write_text(HELPER)
    assert [d.name for d in _definitions_in(path)] == ["KSOFT"]


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
def test_a_umat_whose_helper_is_tab_led_in_a_sibling_file_transforms_and_agrees(tmp_path, monkeypatch):
    import transform_all as ta

    cache = tmp_path / "cache"
    models = cache / "owner__repo" / "models"
    models.mkdir(parents=True)
    (models / "umat.for").write_text(UMAT)
    (models / "ksoft.for").write_text(HELPER)
    monkeypatch.setattr(ta, "DEFAULT_CACHE", cache)
    item = ta.WorkItem(source_id="owner__repo/models/umat.for", path=models / "umat.for",
                       sha256="x", ntens=6, stage="transformed")
    work = tmp_path / "work"
    result = ta.transform_one(item, work)
    assert result.ok, result.reason
    assert result.metadata["published_companions"]["used_root"].endswith("models")

    stub = "      implicit real*8(a-h,o-z)\n"
    out = work / "out"
    (out / "ABA_PARAM.INC").write_text(stub)
    subprocess.run(["bash", "compile_hint.sh"], cwd=out, check=True, capture_output=True, text=True)
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "ABA_PARAM.INC").write_text(stub)
    original = UMAT.replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(") + HELPER.replace("KSOFT", "KSOFTORIG")
    original = original.replace("CALL KSOFT(", "CALL KSOFTORIG(")
    (reference / "orig.for").write_text(original)
    subprocess.run(["gfortran", "-O0", "-std=legacy", "-c", "orig.for", "-o", "orig.o"],
                   cwd=reference, check=True, capture_output=True, text=True)
    (tmp_path / "driver.f90").write_text(DRIVER % {"nprops": 1, "props": "1000.0d0"})
    subprocess.run(["gfortran", "-ffree-line-length-none", "driver.f90",
                    *[str(p) for p in out.glob("*.o")], str(reference / "orig.o"), "-o", "check"],
                   cwd=tmp_path, check=True, capture_output=True, text=True)
    lines = subprocess.run([str(tmp_path / "check")], cwd=tmp_path, check=True,
                           capture_output=True, text=True).stdout.splitlines()
    bits = {row.split()[0]: row.split()[1:] for row in lines if row.startswith(("OTIBITS", "ORIGBITS"))}
    assert bits["OTIBITS"] == bits["ORIGBITS"]
    tangent = {int(r.split()[1]): [float(v) for v in r.split()[2:]] for r in lines if r.startswith("DDSDDE ")}
    fd: dict = {}
    for row in lines:
        if row.startswith("FD "):
            _, j, s, *values = row.split()
            fd.setdefault(int(j), {})[int(s)] = [float(v) for v in values]
    for j in range(1, 7):
        scale = max(1.0, max(abs(v) for v in fd[j][5]))
        assert max(abs(a - b) for a, b in zip(fd[j][5], fd[j][6])) <= 1e-6 * scale
        for k in range(6):
            assert abs(tangent[k + 1][j - 1] - fd[j][6][k]) <= 1e-6 * scale, (k + 1, j)


MODULE_UMAT = """subroutine umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
                stran, dstran, time, dtime, temp, dtemp, predef, dpred, cmname, &
                ndi, nshr, ntens, nstatv, props, nprops, coords, drot, pnewdt, &
                celent, dfgrd0, dfgrd1, noel, npt, layer, kspt, kstep, kinc)
  use state_mod, only: hist
  implicit none
  character(len=80) :: cmname
  integer :: ndi, nshr, ntens, nstatv, nprops, noel, npt, layer, kspt, kstep, kinc
  real(8) :: stress(ntens), statev(nstatv), ddsdde(ntens, ntens), sse, spd, scd, rpl
  real(8) :: ddsddt(ntens), drplde(ntens), drpldt, stran(ntens), dstran(ntens)
  real(8) :: time(2), dtime, temp, dtemp, predef(1), dpred(1), props(nprops)
  real(8) :: coords(3), drot(3, 3), pnewdt, celent, dfgrd0(3, 3), dfgrd1(3, 3)
  integer :: i
  do i = 1, ntens
    stress(i) = stress(i) + props(1)*dstran(i) + hist(noel)*dstran(i)**2
  end do
  hist(noel) = hist(noel) + stress(1)
  ddsdde = 0.0d0
end subroutine umat
"""

STATE_MODULE = """module state_mod
  implicit none
  real(8), public :: hist(100)
end module state_mod
"""


def test_state_kept_in_a_module_variable_is_refused_by_name(tmp_path, monkeypatch):
    """The OXFORD-UMAT closure now resolves; what stops it is state in module variables."""
    import transform_all as ta

    cache = tmp_path / "cache"
    models = cache / "owner__repo" / "models"
    models.mkdir(parents=True)
    (models / "umat.f90").write_text(MODULE_UMAT)
    (models / "state_mod.f90").write_text(STATE_MODULE)
    monkeypatch.setattr(ta, "DEFAULT_CACHE", cache)
    item = ta.WorkItem(source_id="owner__repo/models/umat.f90", path=models / "umat.f90",
                       sha256="x", ntens=6, stage="transformed")
    result = ta.transform_one(item, tmp_path / "work")
    assert not result.ok
    assert "HIST is a variable of module STATE_MOD (state_mod.f90)" in result.reason
