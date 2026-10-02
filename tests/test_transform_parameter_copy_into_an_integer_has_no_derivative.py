"""A parameter copied into an INTEGER carries no derivative, however the INTEGER is typed.

``CNT=PROPS(3)`` with CNT INTEGER truncates. The parameter-direction taint of
the combined entry follows implicitly typed copies (``TAU0=PROPS(3)`` under
ABA_PARAM.INC must carry its derivative), and it used to decide "implicitly
typed" from the file's IMPLICIT statements read at column 7 only. So a CNT made
INTEGER by an INCLUDE'd declaration, an INCLUDE'd IMPLICIT INTEGER, or a
free-form ``implicit integer (c)`` indented by two columns was promoted:
dSIGMA/dPROPS(3) came back 0.0809 where the truth is zero (Vera, B1 review Q7,
toys reproduced here), and with a non-integral PROPS(3) the primal moves too.

Behavioural: the transformed combined entry runs a three-increment history;
the reference is the AUTHOR's routine (renamed UMATORIG, own object), and the
derivative reference is a central difference of it at three step sizes. The
quantity is the TOTAL derivative of STRESS and STATEV(1) along a fixed strain
path w.r.t. PROPS(k), DSTRAN held fixed. PROPS(3)=3.7 so a promoted copy is
also visible in the primal (3.7 instead of 3).

A routine whose INCLUDE is not on disk cannot have its undeclared names typed,
so the request is refused with the reason instead of guessed.
"""
import json
import shutil
import subprocess

import pytest

VALUES = (3.0, 0.7, 3.7)

FIXED = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,DSTRAN,PROPS,NTENS,NSTATV,
     1 NPROPS)
{typing}
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DSTRAN(NTENS),PROPS(NPROPS)
      EMOD=PROPS(1)
      SY=PROPS(2)
      CNT=PROPS(3)
      HARD=EMOD*SY/(EMOD+SY)
      DO K=1,NTENS
        STRESS(K)=STRESS(K)+HARD*DSTRAN(K)+EXP(-SY)*STATEV(1)*CNT
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

FREE = """subroutine umat(stress,statev,ddsdde,dstran,props,ntens,nstatv,nprops)
  implicit double precision (a-b,d-h,o-z)
  implicit integer (c)
  dimension stress(ntens),statev(nstatv),ddsdde(ntens,ntens),dstran(ntens),props(nprops)
  emod=props(1)
  sy=props(2)
  cnt=props(3)
  hard=emod*sy/(emod+sy)
  do k=1,ntens
    stress(k)=stress(k)+hard*dstran(k)+exp(-sy)*statev(1)*cnt
  end do
  statev(1)=statev(1)+sy**2*dstran(1)+emod*statev(1)*dstran(2)
  ddsdde=0.d0
  return
end subroutine umat
"""

MODULE = """module counts
  implicit none
  integer :: cnt
end module counts
subroutine umat(stress,statev,ddsdde,dstran,props,ntens,nstatv,nprops)
  use counts
  implicit double precision (a-h,o-z)
  dimension stress(ntens),statev(nstatv),ddsdde(ntens,ntens),dstran(ntens),props(nprops)
  emod=props(1)
  sy=props(2)
  cnt=props(3)
  hard=emod*sy/(emod+sy)
  do k=1,ntens
    stress(k)=stress(k)+hard*dstran(k)+exp(-sy)*statev(1)*cnt
  end do
  statev(1)=statev(1)+sy**2*dstran(1)+emod*statev(1)*dstran(2)
  ddsdde=0.d0
  return
end subroutine umat
"""

CASES = {
    "include_implicit": ("material.for", FIXED.format(typing="      INCLUDE 'mytypes.inc'"),
                         "      IMPLICIT REAL*8 (A-B,D-H,O-Z)\n      IMPLICIT INTEGER (C)\n"),
    "include_declaration": ("material.for",
                            FIXED.format(typing="      INCLUDE 'ABA_PARAM.INC'\n"
                                                "      INCLUDE 'mytypes.inc'"),
                            "      INTEGER CNT\n"),
    "inline_implicit": ("material.for",
                        FIXED.format(typing="      IMPLICIT REAL*8 (A-B,D-H,O-Z)\n"
                                            "      IMPLICIT INTEGER (C)"), None),
    "free_form_shallow_implicit": ("material.f90", FREE, None),
    "module_declaration": ("material.f90", MODULE, None),
}

DRIVER = """program check
implicit none
integer, parameter :: np = 3, ninc = 3
real(8) :: stress(6), statev(1), ddsdde(6,6), dstran(6), props(3), p0(3)
real(8) :: dsigma(6,np), dstate(1,np), dstate_de(1,6), df0(3,3,np), df1(3,3,np)
real(8) :: sp(6), sm(6), xp(1), xm(1), h
integer :: inc, k, s
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
    h = 10.0d0**(-s) * abs(p0(k))
    call run(k, h, sp, xp)
    call run(k, -h, sm, xm)
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


def _contract(tmp_path, source):
    raw = {
        "schema_version": "1.1",
        "source": str(source), "entry_routine": "UMAT", "ntens": 6,
        "parameters": [{"name": "EMOD", "props_index": 1}, {"name": "SY", "props_index": 2},
                       {"name": "CNT", "props_index": 3}],
        "derivatives": [
            {"target": "DDSDDE", "seed": "DSTRAN", "response": "STRESS", "order": 1},
            {"target": "DSIGMA_DP", "seed": "PROPS", "response": "STRESS", "order": 1},
            {"target": "DSTATEV_DP", "seed": "PROPS", "response": "STATEV", "order": 1},
        ],
        "material_point_driver": {"dstran_per_increment": None, "nstatv": None},
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(raw))
    return path


def _renamed(text: str) -> str:
    for old, new in (("SUBROUTINE UMAT(", "SUBROUTINE UMATORIG("),
                     ("subroutine umat(", "subroutine umatorig("),
                     ("end subroutine umat\n", "end subroutine umatorig\n")):
        text = text.replace(old, new, 1)
    return text


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran required")
@pytest.mark.parametrize("case", sorted(CASES))
def test_a_parameter_copied_into_an_integer_has_no_derivative(tmp_path, case):
    from umat_oti.services.transformation import run_transformation

    name, body, include = CASES[case]
    source = tmp_path / name
    source.write_text(body)
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    if include:
        (tmp_path / "mytypes.inc").write_text(include)
    output = tmp_path / "out"
    summary, code = run_transformation(_contract(tmp_path, source), output)
    if case == "module_declaration":
        # The declaration is in the same file, so the parameter-path validator
        # sees CNT INTEGER and refuses the d/dPROPS(3) request outright --
        # the other honest answer. What must never happen is a derivative.
        assert code != 0
        assert summary.get("status_category") == "non_differentiable_integer_parameter_path"
        return
    assert code == 0, summary
    for header in ("ABA_PARAM.INC", "mytypes.inc"):
        if (tmp_path / header).exists():
            shutil.copy(tmp_path / header, output / header)
    subprocess.run([str(output / "compile_hint.sh")], check=True, capture_output=True,
                   text=True, cwd=output)

    reference_dir = tmp_path / "reference"
    reference_dir.mkdir()
    for header in ("ABA_PARAM.INC", "mytypes.inc"):
        if (tmp_path / header).exists():
            shutil.copy(tmp_path / header, reference_dir / header)
    renamed = reference_dir / ("reference_" + name)
    renamed.write_text(_renamed(body))
    reference_object = reference_dir / "reference.o"
    form = "-ffixed-line-length-none" if name.endswith(".for") else "-ffree-line-length-none"
    subprocess.run(["gfortran", "-O0", "-std=legacy", form, f"-I{reference_dir}", "-c",
                    str(renamed), "-o", str(reference_object)],
                   check=True, capture_output=True, text=True, cwd=reference_dir)
    driver = tmp_path / "driver.f90"
    driver.write_text(DRIVER.format(v1=VALUES[0], v2=VALUES[1], v3=VALUES[2]))
    executable = tmp_path / "check"
    objects = [str(p) for p in output.glob("*.o")]
    subprocess.run(["gfortran", "-ffree-line-length-none", str(driver), *objects,
                    str(reference_object), "-o", str(executable)],
                   check=True, capture_output=True, text=True, cwd=reference_dir)
    lines = subprocess.run([str(executable)], check=True, capture_output=True,
                           text=True).stdout.splitlines()

    primal = {row.split()[0]: [float(v) for v in row.split()[1:]]
              for row in lines if row.startswith("PRIMAL_")}
    # A promoted CNT would carry 3.7 where the original truncates to 3.
    for got, ref in zip(primal["PRIMAL_OTI"], primal["PRIMAL_ORIGINAL"]):
        assert abs(got - ref) <= 1e-13 * max(1.0, abs(ref)), ("primal", got, ref)
    oti = {int(row.split()[1]): [float(v) for v in row.split()[2:]]
           for row in lines if row.startswith("OTI ")}
    fd: dict[int, dict[int, list[float]]] = {}
    for row in lines:
        if row.startswith("FD "):
            fields = row.split()
            fd.setdefault(int(fields[1]), {})[int(fields[2])] = [float(v) for v in fields[3:]]

    # PROPS(3) reaches the stress only through the truncating INTEGER copy:
    # every finite difference of the original is exactly zero, and so must the
    # derivative be.
    for step in fd[3].values():
        assert all(v == 0.0 for v in step), step
    assert all(v == 0.0 for v in oti[3]), oti[3]
    # The real parameters still carry their derivatives (the taint was not
    # simply switched off).
    for k in (1, 2):
        steps = fd[k]
        scale = max(max(abs(v) for v in steps[6]), 1e-30)
        assert max(abs(a - b) for a, b in zip(steps[5], steps[6])) <= 1e-7 * scale
        assert min(abs(v) for v in steps[6][:6]) > 1e-6 * scale
        for got, ref in zip(oti[k], steps[6]):
            assert abs(got - ref) <= 1e-12 + 1e-6 * abs(ref), (k, got, ref)


def test_an_include_that_is_not_there_refuses_instead_of_guessing(tmp_path):
    from umat_oti.services.transformation import run_transformation

    source = tmp_path / "material.for"
    source.write_text(FIXED.format(typing="      INCLUDE 'ABA_PARAM.INC'\n"
                                          "      INCLUDE 'mytypes.inc'"))
    (tmp_path / "ABA_PARAM.INC").write_text("      implicit real*8(a-h,o-z)\n")
    summary, code = run_transformation(_contract(tmp_path, source), tmp_path / "out")
    assert code != 0
    text = json.dumps(summary) if not isinstance(summary, str) else summary
    assert "CNT receives a value derived from" in text
    assert "INCLUDE 'mytypes.inc' is not available" in text


def test_the_typing_reader_sees_each_rule():
    from umat_oti.transform.routine_typing import routine_typing

    free = routine_typing(FREE, "umat")
    assert "C" in free.nonreal_letters and "A" not in free.nonreal_letters
    assert not free.is_known_real("CNT") and free.is_known_real("EMOD")
    module = routine_typing(MODULE, "umat")
    assert "CNT" in module.declared_nonreal and not module.unknown_because
    fixed = routine_typing(FIXED.format(typing="      IMPLICIT REAL*8 (A-B,D-H,O-Z)\n"
                                               "      IMPLICIT INTEGER (C)"), "UMAT")
    assert not fixed.is_known_real("CNT") and fixed.is_known_real("SY")
    # The language default for an IMPLICIT NONE routine: nothing undeclared is real.
    none = routine_typing("      SUBROUTINE UMAT(A)\n      IMPLICIT NONE\n      END\n", "UMAT")
    assert none.implicit_none and not none.is_known_real("X")
    # IMPLICIT rules are per routine: another routine's IMPLICIT INTEGER (A-Z)
    # does not reach UMAT.
    two = ("      SUBROUTINE OTHER\n      IMPLICIT INTEGER (A-Z)\n      END\n"
           "      SUBROUTINE UMAT(A)\n      INCLUDE 'ABA_PARAM.INC'\n      END\n")
    assert routine_typing(two, "UMAT").is_known_real("TAU0")
