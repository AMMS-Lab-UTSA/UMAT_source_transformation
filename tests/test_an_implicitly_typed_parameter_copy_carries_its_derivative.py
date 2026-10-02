"""A parameter derivative survives the two places the combined entry cut it off.

1. A parameter copied into an implicitly typed local.

``TAU0=PROPS(3)`` under ABA_PARAM.INC types TAU0 by the implicit rule, and the
scanner reports it as type "unknown". The combined in-place entry used to grow
the parameter dependence only through names *declared* real, so the copy was
emitted ``TAU0=REAL(PROPS_OTI(3))``: the primal was bit-identical and every
parameter derivative came back exactly zero (m5_cpflow, 458 of 840 rows).

Behavioural: OTI_DSIGMA_DP / OTI_DSTATEV_DP over a three-increment history are
compared with central differences of the original routine (real arithmetic,
history replayed from scratch for every perturbed run) at three step sizes.
The quantity is the TOTAL derivative along a fixed strain path: incoming
stress/state derivatives are carried between increments, DSTRAN is held fixed.

The finite-difference reference is the AUTHOR's routine, compiled on its own
from the text written below with the entry renamed UMATORIG -- not the
``umat`` the transform output links, which would make the reference depend on
the very build under test (Vera, B1 review Q7).
"""
import json
import shutil
import subprocess

import pytest

PARAMETERS = [("EMOD", 1), ("SY", 2)]
VALUES = (3.0, 0.7, 2.0)  # PROPS(3) is copied into NREP, implicitly INTEGER

STORE_BODY = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,PROPS,NTENS,NSTATV,
     1 NPROPS)
{typing}
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DSTRAN(NTENS),PROPS(NPROPS)
      EMOD=PROPS(1)
      SY=PROPS(2)
      NREP=PROPS(3)
      DO K=1,NTENS
        DO L=1,NTENS
          DDSDDE(K,L)=0.D0
        END DO
      END DO
      DO K=1,NTENS
        DDSDDE(K,K)=EMOD+SY*K
      END DO
      DDSDDE(1,2)=SY*NREP
      DO K=1,NTENS
        DS=0.D0
        DO L=1,NTENS
          DS=DS+DDSDDE(K,L)*DSTRAN(L)
        END DO
        STRESS(K)=STRESS(K)+DS+EXP(-SY)*STATEV(1)
      END DO
      STATEV(1)=STATEV(1)+EMOD*SY*DSTRAN(1)
      RETURN
      END
"""

BODY = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,PROPS,NTENS,NSTATV,
     1 NPROPS)
{typing}
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DSTRAN(NTENS),PROPS(NPROPS)
      EMOD=PROPS(1)
      SY=PROPS(2)
      NREP=PROPS(3)
      HARD=EMOD*SY/(EMOD+SY)
      DO K=1,NTENS
        STRESS(K)=STRESS(K)+HARD*DSTRAN(K)+EXP(-SY)*STATEV(1)*NREP
      END DO
      STATEV(1)=STATEV(1)+SY**2*DSTRAN(1)+EMOD*STATEV(1)*DSTRAN(2)
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
integer, parameter :: np = 2, ninc = 3
real(8) :: stress(6), statev(1), ddsdde(6,6), dstran(6), props(3), p0(3)
real(8) :: dsigma(6,np), dstate(1,np), dstate_de(1,6), df0(3,3,np), df1(3,3,np)
real(8) :: sp(6), sm(6), xp(1), xm(1), h
integer :: inc, k, s, idx(np)
idx = (/ 1, 2 /)
p0 = (/ {v1}d0, {v2}d0, {v3}d0 /)
dstran = (/ 0.01d0, -0.004d0, 0.002d0, 0.003d0, 0.d0, 0.001d0 /)
props = p0; stress = 0; statev = 0.05d0
dsigma = 0; dstate = 0; dstate_de = 0; df0 = 0; df1 = 0
do inc = 1, ninc
  ddsdde = 7.0d0
  call umat_with_sensitivities(stress, statev, ddsdde, dstran, props, 6, 1, 3, &
       dsigma, dstate, dstate_de, df0, df1)
end do
call run(1, 0.0d0, sp, xp)
write(*, '(A,7ES25.16)') 'PRIMAL_OTI ', stress, statev
write(*, '(A,7ES25.16)') 'PRIMAL_ORIGINAL ', sp, xp
do k = 1, np
  write(*, '(A,I0,7ES25.16)') 'OTI ', k, dsigma(:, k), dstate(1, k)
  do s = 4, 6
    h = 10.0d0**(-s) * abs(p0(idx(k)))
    call run(idx(k), h, sp, xp)
    call run(idx(k), -h, sm, xm)
    write(*, '(A,I0,1X,I0,7ES25.16)') 'FD ', k, s, (sp - sm)/(2*h), (xp - xm)/(2*h)
  end do
end do
contains
  subroutine run(j, dh, sout, xout)
    integer, intent(in) :: j
    real(8), intent(in) :: dh
    real(8), intent(out) :: sout(6), xout(1)
    real(8) :: pr(3), dd(6,6)
    integer :: i
    pr = p0; pr(j) = pr(j) + dh
    sout = 0; xout = 0.05d0
    do i = 1, ninc
      dd = 7.0d0
      call umatorig(sout, xout, dd, dstran, pr, 6, 1, 3)
    end do
  end subroutine run
end program
"""


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
@pytest.mark.parametrize("body", ["parameter_copy", "stiffness_store"])
@pytest.mark.parametrize("typing", ["include", "implicit_statement"])
def test_an_implicitly_typed_parameter_copy_carries_its_derivative(tmp_path, typing, body):
    from umat_oti.services.transformation import run_transformation

    line = ("      INCLUDE 'ABA_PARAM.INC'" if typing == "include"
            else "      IMPLICIT DOUBLE PRECISION (A-H,O-Z)")
    source = tmp_path / "material.for"
    source.write_text((BODY if body == "parameter_copy" else STORE_BODY).format(typing=line))
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    raw = {
        "schema_version": "1.1",
        "source": str(source), "entry_routine": "UMAT", "ntens": 6,
        "parameters": [{"name": name, "props_index": index} for name, index in PARAMETERS],
        "derivatives": [
            {"target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1},
            {"target": "DSIGMA_DP", "seed": "PROPS", "response": "STRESS", "order": 1},
            {"target": "DSTATEV_DP", "seed": "PROPS", "response": "STATEV", "order": 1},
        ],
        "material_point_driver": {"dstran_per_increment": None, "nstatv": None},
    }
    config_path = tmp_path / "contract.json"
    config_path.write_text(json.dumps(raw))
    output = tmp_path / "out"
    summary, code = run_transformation(config_path, output)
    assert code == 0, summary
    shutil.copy(tmp_path / "ABA_PARAM.INC", output / "ABA_PARAM.INC")
    subprocess.run([str(output / "compile_hint.sh")], check=True, capture_output=True,
                   text=True, cwd=output)
    driver = tmp_path / "driver.f90"
    driver.write_text(DRIVER.format(v1=VALUES[0], v2=VALUES[1], v3=VALUES[2]))
    # The reference: the author's text, renamed, compiled into its own object.
    reference_dir = tmp_path / "reference"
    reference_dir.mkdir()
    shutil.copy(tmp_path / "ABA_PARAM.INC", reference_dir / "ABA_PARAM.INC")
    renamed = reference_dir / "material_reference.for"
    renamed.write_text(source.read_text().replace("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG(", 1))
    reference_object = reference_dir / "material_reference.o"
    subprocess.run(["gfortran", "-O0", "-std=legacy", f"-I{reference_dir}", "-c", str(renamed),
                    "-o", str(reference_object)], check=True, capture_output=True, text=True)
    executable = tmp_path / "check"
    subprocess.run(["gfortran", "-ffree-line-length-none", str(driver),
                    *map(str, output.glob("*.o")), str(reference_object), "-o", str(executable)],
                   check=True, capture_output=True, text=True)
    lines = subprocess.run([str(executable)], check=True, capture_output=True,
                           text=True).stdout.splitlines()

    primal = {row.split()[0]: [float(v) for v in row.split()[1:]]
              for row in lines if row.startswith("PRIMAL_")}
    # Primal parity first: a derivative is only comparable along the same path.
    for got, ref in zip(primal["PRIMAL_OTI"], primal["PRIMAL_ORIGINAL"]):
        assert abs(got - ref) <= 1e-13 * max(1.0, abs(ref)), ("primal", got, ref)
    oti = {int(row.split()[1]): [float(v) for v in row.split()[2:]]
           for row in lines if row.startswith("OTI ")}
    fd: dict[int, dict[int, list[float]]] = {}
    for row in lines:
        if row.startswith("FD "):
            fields = row.split()
            fd.setdefault(int(fields[1]), {})[int(fields[2])] = [float(v) for v in fields[3:]]

    for k, (name, _) in enumerate(PARAMETERS, start=1):
        steps = fd[k]
        # The reference has to be resolved before it can adjudicate: the two
        # finest steps agree with each other far better than the tolerance.
        scale = max(max(abs(v) for v in steps[6]), 1e-30)
        assert max(abs(a - b) for a, b in zip(steps[5], steps[6])) <= 1e-7 * scale, name
        # Every entry this test differentiates is substantive (nonzero), so a
        # dropped derivative cannot hide in a zero-vs-zero agreement.
        assert min(abs(v) for v in steps[6]) > 1e-6 * scale, name
        for got, ref in zip(oti[k], steps[6]):
            assert abs(got - ref) <= 1e-12 + 1e-6 * abs(ref), (name, got, ref)
