"""A shadow whose real variable was given its value BEFORE the seed block is copied in.

The seed block zeroes every shadow and is inserted at the first stress-path
statement; statements above it stay real. A name assigned up there and read on
the stress path through its shadow was therefore read as zero (Vera, B2 review
item 1): czmHealing.f's ``SMALL_K=1.D-8`` became SMALL_K_OTI = 0 (shear stress
621.7506 against 621.75060622; at the damaged state 2.7e-8 against 6.2e4), and
``E=PROPS(1)`` handed to a lifted helper returned STRESS = 0 (toy t4a).

Behavioural. The ORIGINAL is compiled on its own from the author's text into
its own executable; every evaluation is a fresh process, so SAVE/DATA state of
the reference is restored exactly. STRESS/STATEV are compared bitwise, DDSDDE
against central differences of the original at three step sizes (local
tangent: incoming state of the increment held fixed). The harness here is
shared with the other B2d review tests.
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

DRIVER = """program drv
implicit none
integer :: ntens, nstatv, nprops, ncall, k, i, jstep(4)
real(8), allocatable :: stress(:), statev(:), ddsdde(:,:), props(:), dstran(:,:), stran(:)
real(8), allocatable :: ddsddt(:), drplde(:)
real(8) :: time(2), predef(1), dpred(1), coords(3), drot(3,3), dfgrd0(3,3), dfgrd1(3,3)
real(8) :: sse, spd, scd, rpl, drpldt, dtime, temp, dtemp, pnewdt, celent
character(len=80) :: cmname
read(*,*) ntens, nstatv, nprops, ncall, temp
allocate(stress(ntens), statev(nstatv), ddsdde(ntens,ntens), props(nprops), dstran(ntens,ncall), &
         stran(ntens), ddsddt(ntens), drplde(ntens))
read(*,*) props
read(*,*) statev
do k = 1, ncall
  read(*,*) dstran(:,k)
end do
stress = 0; stran = 0; time = 0; dtime = 1; dtemp = 0; predef = 0; dpred = 0; coords = 0
drot = 0; dfgrd0 = 0; dfgrd1 = 0; celent = 1; cmname = 'MAT'; jstep = 1
do i = 1, 3
  drot(i,i) = 1; dfgrd0(i,i) = 1; dfgrd1(i,i) = 1
end do
sse = 0; spd = 0; scd = 0; rpl = 0; drpldt = 0; ddsddt = 0; drplde = 0
do k = 1, ncall
  ddsdde = 0; pnewdt = 1
  call umat(stress, statev, ddsdde, sse, spd, scd, rpl, ddsddt, drplde, drpldt, &
            stran, dstran(:,k), time, dtime, temp, dtemp, predef, dpred, cmname, 3, 3, ntens, nstatv, &
            props, nprops, coords, drot, pnewdt, celent, dfgrd0, dfgrd1, 1, 1, 1, 1, jstep, k)
  write(*,'(A,I0,*(1X,Z16))') 'BITS ', k, stress, statev
  write(*,'(A,I0,*(1X,ES25.16))') 'S ', k, stress
  do i = 1, ntens
    write(*,'(A,I0,1X,I0,*(1X,ES25.16))') 'D ', k, i, ddsdde(i,:)
  end do
  stran = stran + dstran(:,k)
  time = time + dtime
end do
end program
"""
STUB = "      implicit real*8(a-h,o-z)\n      parameter (nprecd=2)\n"
HEADER = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,JSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3),JSTEP(4)
"""
DIRECTION = (1.0, -0.3, -0.3, 0.4, 0.2, -0.1)

needs_gfortran = pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")


def transform(work: Path, source_text: str, name: str = "material.for"):
    """Transform ``source_text``; returns (code, summary, output dir, source path)."""
    from umat_oti.services.transformation import run_transformation

    work.mkdir(parents=True, exist_ok=True)
    source = work / name
    source.write_text(source_text)
    (work / "ABA_PARAM.INC").write_text(STUB)
    raw = {"schema_version": "1.1", "source": str(source), "entry_routine": "UMAT", "ntens": 6,
           "derivatives": [{"target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1}],
           "material_point_driver": {"dstran_per_increment": None, "nstatv": None}}
    (work / "contract.json").write_text(json.dumps(raw))
    output = work / "out"
    summary, code = run_transformation(work / "contract.json", output)
    return code, summary, output, source


def _link(directory: Path, objects: list[str]) -> Path:
    (directory / "drv.f90").write_text(DRIVER)
    subprocess.run(["gfortran", "-O0", "-ffree-line-length-none", "drv.f90", *objects, "-o", "drv"],
                   check=True, capture_output=True, text=True, cwd=directory)
    return directory / "drv"


def build_original(work: Path, source: Path) -> Path:
    """The author's text, compiled on its own into its own executable."""
    directory = work / "original"
    directory.mkdir(exist_ok=True)
    (directory / "ABA_PARAM.INC").write_text(STUB)
    (directory / "aba_param.inc").write_text(STUB)
    subprocess.run(["gfortran", "-O0", "-std=legacy", "-ffixed-line-length-none", f"-I{directory}",
                    "-c", str(source), "-o", "original.o"],
                   check=True, capture_output=True, text=True, cwd=directory)
    return _link(directory, ["original.o"])


def build_transformed(output: Path) -> Path:
    for name in ("ABA_PARAM.INC", "aba_param.inc"):
        (output / name).write_text(STUB)
    subprocess.run(["bash", str(output / "compile_hint.sh")], check=True, capture_output=True,
                   text=True, cwd=output)
    objects = sorted(str(p) for p in output.glob("*.o"))
    return _link(output, objects)


def run(executable: Path, props, statev, increments, temp=0.0, ntens=6):
    """STRESS bits, STRESS and DDSDDE after each call of one fresh process."""
    text = (f"{ntens} {len(statev)} {len(props)} {len(increments)} {temp!r}\n"
            + " ".join(repr(float(v)) for v in props) + "\n"
            + " ".join(repr(float(v)) for v in statev) + "\n"
            + "".join(" ".join(repr(float(v)) for v in d) + "\n" for d in increments))
    lines = subprocess.run([str(executable)], input=text, check=True, capture_output=True,
                           text=True, cwd=executable.parent, timeout=120).stdout.splitlines()
    bits = {int(r.split()[1]): r.split()[2:] for r in lines if r.startswith("BITS ")}
    stress = {int(r.split()[1]): [float(v) for v in r.split()[2:]] for r in lines if r.startswith("S ")}
    tangent: dict = {}
    for row in lines:
        if row.startswith("D "):
            _, call, i, *values = row.split()
            tangent.setdefault(int(call), {})[int(i)] = [float(v) for v in values]
    return bits, stress, tangent


def assert_matches_the_original(original: Path, transformed: Path, props, statev, increments,
                                temp=0.0, steps=(1e-6, 1e-7, 1e-8), rtol=1e-6):
    """Primal bitwise at every call; DDSDDE of every call against FD of the original."""
    o_bits, _, _ = run(original, props, statev, increments, temp)
    t_bits, _, t_tangent = run(transformed, props, statev, increments, temp)
    for call in range(1, len(increments) + 1):
        assert t_bits[call] == o_bits[call], ("primal differs", call)
        for j in range(6):
            columns = []
            for h in steps:
                plus = [list(d) for d in increments[:call]]
                minus = [list(d) for d in increments[:call]]
                plus[-1][j] += h
                minus[-1][j] -= h
                sp = run(original, props, statev, plus, temp)[1][call]
                sm = run(original, props, statev, minus, temp)[1][call]
                columns.append([(a - b) / (2 * h) for a, b in zip(sp, sm)])
            scale = max(1.0, max(abs(v) for v in columns[1]))
            assert max(abs(a - b) for a, b in zip(columns[1], columns[2])) <= 1e-5 * scale, \
                ("FD did not converge", call, j)
            for i in range(6):
                assert abs(t_tangent[call][i + 1][j] - columns[1][i]) <= rtol * scale, \
                    (call, i + 1, j + 1, t_tangent[call][i + 1][j], columns[1][i])


HELPER = """
      SUBROUTINE UPD(X,D,E,S,N)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION X(1),D(N),S(N)
      DO I=1,N
        S(I)=S(I)+E*X(1)*D(I)*(1.D0+1.D2*D(I))
      END DO
      RETURN
      END
"""
TANGENT = """      DO I=1,NTENS
        DO J=1,NTENS
          DDSDDE(I,J)=0.D0
        END DO
        DDSDDE(I,I)=E
      END DO
      RETURN
      END
"""
#: Toy t4a: E=PROPS(1) is assigned above the first stress-path statement and
#: reaches the stress only through a lifted helper's argument.
PROPS_TO_HELPER = HEADER + """      DIMENSION XI(1)
      DATA XI/1.D0/
      E=PROPS(1)
      CALL UPD(XI,DSTRAN,E,STRESS,NTENS)
""" + TANGENT + HELPER
#: czmHealing.f's shape: a residual-stiffness constant assigned in the
#: preamble and read in the stress update.
RESIDUAL_CONSTANT = HEADER + """      E=PROPS(1)
      SMALL_K=1.D-2
      DAMAGE=STATEV(1)
      F=(1.D0-DAMAGE)**2+SMALL_K
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+F*E*DSTRAN(I)*(1.D0+1.D2*DSTRAN(I))
      END DO
""" + TANGENT
#: The Curing source's shape: a value derived in the preamble (C12INF from
#: two properties), behind a logical IF as well.
DERIVED_IN_THE_PREAMBLE = HEADER + """      E=PROPS(1)
      C12INF=PROPS(2)*PROPS(1)
      IF (PROPS(3).GT.0.D0) C12INF=C12INF*2.D0
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+E*DSTRAN(I)+C12INF*DSTRAN(I)**2
      END DO
""" + TANGENT


@needs_gfortran
@pytest.mark.parametrize("name,text,statev", [
    ("props_to_helper", PROPS_TO_HELPER, [0.0]),
    ("residual_constant", RESIDUAL_CONSTANT, [1.0]),
    ("derived_in_the_preamble", DERIVED_IN_THE_PREAMBLE, [0.0]),
], ids=["props_to_helper", "residual_constant", "derived_in_the_preamble"])
def test_a_value_assigned_before_the_seed_block_reaches_the_stress(tmp_path, name, text, statev):
    code, summary, output, source = transform(tmp_path / name, text)
    assert code == 0, summary
    original = build_original(tmp_path / name, source)
    transformed = build_transformed(output)
    increments = [[1e-3 * v for v in DIRECTION]] * 2
    assert_matches_the_original(original, transformed, [100.0, 0.3, 1.0], statev, increments)


CZM = Path("/home/ammslab3/softwarex_work/discovery_cache/lucassalmon83860-bit__thesis-benchmark-cases"
           "/Benchmarks/Fuel_pellet_quarter/czmHealing.f")


@needs_gfortran
@pytest.mark.skipif(not CZM.exists(), reason="corpus source czmHealing.f not in the discovery cache")
def test_czm_healing_keeps_its_residual_stiffness_at_the_damaged_state(tmp_path):
    """czmHealing.f at DSTRAN 1e-3 (fully damaged after one increment), 1000 K.

    Primal only: the damaged-state DDSDDE is not claimed (it disagrees with
    converged FD of the original by up to 17% of the damaged column maximum,
    a regime where (1-Da)^2 ~ 1e-21; open). At TEMP = 0 K the original divides
    by zero in its Arrhenius factor and the OTI derivative parts become NaN;
    the temperature here is physical.
    """
    code, summary, output, source = transform(tmp_path, CZM.read_text(errors="replace"), "czmHealing.f")
    assert code == 0, summary
    original = build_original(tmp_path, source)
    transformed = build_transformed(output)
    props = [4.92219e+16, 4.92219e+16, 2.072502e+16, 0.0, 1000.0, 2000.0, 3.25, 0.8, 45000.0, 2.0, 0.1]
    increments = [[1e-3 * v for v in (1.0, 0.3, -0.2, 0.1, 0.05, -0.05)]] * 2
    o_bits, o_stress, _ = run(original, props, [0.0] * 20, increments, temp=1000.0)
    t_bits, t_stress, t_tangent = run(transformed, props, [0.0] * 20, increments, temp=1000.0)
    # STRESS bitwise. Two STATEV slots of the original hold a denormal left
    # over from an uninitialised local (6.6e-320); the shadows start at zero.
    for call in (1, 2):
        assert t_bits[call][:6] == o_bits[call][:6], call
        for o_hex, t_hex in zip(o_bits[call][6:], t_bits[call][6:]):
            o_value, t_value = (struct.unpack(">d", bytes.fromhex(h.rjust(16, "0")))[0]
                                for h in (o_hex, t_hex))
            assert o_hex == t_hex or abs(o_value - t_value) < 1e-300
    assert abs(o_stress[1][1] - 6.2175060e4) < 1.0     # the residual shear stiffness is live
    assert all(v == v for row in t_tangent[2].values() for v in row)   # no NaN
