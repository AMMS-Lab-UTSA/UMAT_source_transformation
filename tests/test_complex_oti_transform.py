"""The transform's side of DOUBLE COMPLEX: complex_support, and one UMAT end to end.

Unit tests read and rewrite small texts. The end-to-end test transforms a
synthetic complex-step UMAT (stress computed in DOUBLE COMPLEX through SQRT,
EXP and LOG; the author's own DDSDDE by the complex step) and checks the
transformed build's DDSDDE against the original's own complex-step tangent and
against central finite differences of the original's STRESS. It needs the
hook in source_transform/helper_lifting (corpus_campaign B2 ada_c
complex_hook.patch); the hook is part of the transform, so it always runs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from umat_oti.transform import complex_support as cs

FIXED_SOURCE = """\
      SUBROUTINE UMAT(STRESS, DDSDDE, STRAN, DSTRAN, PROPS, NTENS)
      IMPLICIT NONE
      INTEGER NTENS, I, J
      DOUBLE PRECISION STRESS(NTENS), DDSDDE(NTENS,NTENS)
      DOUBLE PRECISION STRAN(NTENS), DSTRAN(NTENS), PROPS(2)
      DOUBLE PRECISION, PARAMETER :: H = 1.0D-20
      DOUBLE COMPLEX :: EZ(6), SZ(6)
      DO I = 1, NTENS
        EZ(I) = DCMPLX(STRAN(I) + DSTRAN(I), 0.0D0)
      END DO
      CALL CSTRESS(EZ, PROPS, SZ)
      DO I = 1, NTENS
        STRESS(I) = DBLE(SZ(I))
      END DO
      DO J = 1, NTENS
        EZ(J) = EZ(J) + DCMPLX(0.0D0, H)
        CALL CSTRESS(EZ, PROPS, SZ)
        DO I = 1, NTENS
          DDSDDE(I,J) = AIMAG(SZ(I)) / H
        END DO
        EZ(J) = DCMPLX(DBLE(EZ(J)), 0.0D0)
      END DO
      END
      SUBROUTINE CSTRESS(E, PROPS, S)
      IMPLICIT NONE
      DOUBLE COMPLEX E(6), S(6), TR, JAC
      DOUBLE PRECISION PROPS(2)
      INTEGER I
      TR = E(1) + E(2) + E(3)
      JAC = SQRT(1.0D0 + TR*TR)
      DO I = 1, 6
        S(I) = 2.0D0*PROPS(1)*E(I)*EXP(-0.5D0*TR) + PROPS(2)*LOG(JAC)
      END DO
      END
"""


def test_declarations_kinds_and_the_authors_complex_step_are_found():
    plan = cs.plan_complex(FIXED_SOURCE, "fixed", "UMAT",
                           {"seed": {"DSTRAN"}, "promote": {"EZ", "SZ", "STRESS"}})
    by = {(d.routine, d.name): d.kind for d in plan.declarations}
    assert by[("UMAT", "EZ")] == "double" and by[("CSTRESS", "JAC")] == "double"
    assert plan.umat_complex_on_path == ["EZ", "SZ"]
    assert not plan.blockers
    [step] = plan.complex_step
    assert step["routine"] == "UMAT"
    assert step["steps"] == {"H": "1.0D-20"}
    assert step["tangent_names"] == ["DDSDDE"]
    assert "never an OTI direction" in step["statement"]


@pytest.mark.parametrize("snippet,needle", [
    ("      COMPLEX Z(3)\n", "not double precision"),
    ("      COMPLEX(KIND=4) :: Z\n", "not double precision"),
    ("      IMPLICIT COMPLEX*16 (Z)\n", "through IMPLICIT"),
    ("      DOUBLE COMPLEX Z(3)\n      COMMON /BLK/ Z\n", "COMMON"),
    ("      DOUBLE COMPLEX Z(3), W\n      W = SUM(Z)\n", "applies SUM"),
    ("      DOUBLE COMPLEX, PARAMETER :: ZI = (0D0,1D0)\n      CALL FOO(ZI)\n", "complex PARAMETER"),
])
def test_what_the_complex_oti_type_cannot_carry_is_refused_by_name(snippet, needle):
    source = "      SUBROUTINE UMAT(STRESS)\n" + snippet + "      END\n"
    plan = cs.plan_complex(source, "fixed", "UMAT", {"seed": set(), "promote": set()})
    assert any(needle in b for b in plan.blockers), plan.blockers


def test_a_named_double_kind_is_double():
    source = ("      SUBROUTINE UMAT(STRESS)\n      INTEGER, PARAMETER :: DP = KIND(1.0D0)\n"
              "      COMPLEX(DP) :: Z\n      END\n")
    plan = cs.plan_complex(source, "fixed", "UMAT")
    assert [d.kind for d in plan.declarations] == ["double"] and not plan.blockers


LIFTED = """\
function det33z_oti(a) result(d)
    use otim6n1, OTI_HELPER_DP => DP
    use oti_intrinsics
    implicit type(ONUMM6N1) (a-h,o-z)
    implicit integer (i-n)
    type(ONUMM6N1) :: d
    DOUBLE COMPLEX, INTENT(IN) :: A(3,3)
    DOUBLE COMPLEX :: d
    d = A(1,1)*A(2,2)
    RETURN
end function det33z_oti

subroutine inv33z_oti(a, ainv)
    use otim6n1, OTI_HELPER_DP => DP
    use oti_intrinsics
    implicit type(ONUMM6N1) (a-h,o-z)
    implicit integer (i-n)
    integer :: k
    k = 1
    DOUBLE COMPLEX, INTENT(IN)  :: A(3,3)
    DOUBLE COMPLEX, INTENT(OUT) :: Ainv(3,3)
    DOUBLE COMPLEX :: d, det33z
    d = DET33Z_OTI(A)
    Ainv(1,1) = CDABS(d) / d
    RETURN
end subroutine inv33z_oti
"""
LIFT_SOURCE = """\
      FUNCTION det33z(A) RESULT(d)
      DOUBLE COMPLEX, INTENT(IN) :: A(3,3)
      DOUBLE COMPLEX :: d
      d = A(1,1)*A(2,2)
      END FUNCTION det33z
"""


def test_lifted_helpers_get_the_complex_oti_type():
    out = cs.retype_lifted_complex(LIFTED, "ONUMM6N1", source_text=LIFT_SOURCE, form="fixed")
    det, inv = out.split("subroutine inv33z_oti", 1)
    assert "type(ZONUMM6N1) :: A(3, 3)" in det and "type(ZONUMM6N1) :: d" in det
    assert "type(ONUMM6N1) :: d" not in det, "the real-OTI result line must go"
    assert det.count("use oti_complex") == 1 and inv.count("use oti_complex") == 1
    # the caller's reference to the lifted complex function is typed complex
    assert "type(ZONUMM6N1) :: det33z_oti" in inv
    # specification part: complex declarations come before the first executable line
    lines = [l.strip() for l in inv.splitlines()]
    assert lines.index("type(ZONUMM6N1) :: Ainv(3, 3)") < lines.index("k = 1")
    assert "ABS(d) / d" in inv and "CDABS" not in inv


def test_a_source_without_complex_is_left_byte_for_byte():
    text = "subroutine f_oti(x)\n    use oti_intrinsics\n    x = 1.0d0\nend subroutine f_oti\n"
    assert cs.retype_lifted_complex(text, "ONUMM6N1", source_text="      X = 1\n") == text
    plan = cs.plan_complex("      SUBROUTINE UMAT(S)\n      S = 1\n      END\n", "fixed", "UMAT")
    assert not plan.active
    assert cs.retype_umat_complex_shadows("whatever", plan, "ONUMM6N1", "fixed") == "whatever"


def test_umat_shadows_are_declared_complex_and_use_the_module():
    plan = cs.plan_complex(FIXED_SOURCE, "fixed", "UMAT", {"seed": set(), "promote": {"EZ", "SZ"}})
    text = ("      USE otim6n1, OTI_MODULE_DP => DP, OTI_E1 => E1,\n"
            "     1OTI_E2 => E2\n"
            "      USE oti_intrinsics\n"
            "      TYPE(ONUMM6N1) :: EZ_OTI(6)\n"
            "      TYPE(ONUMM6N1) :: STRESS_OTI(NTENS)\n")
    out = cs.retype_umat_complex_shadows(text, plan, "ONUMM6N1", "fixed").splitlines()
    assert out[3] == "      USE oti_complex"
    assert out[4] == "      TYPE(ZONUMM6N1) :: EZ_OTI(6)"
    assert out[5] == "      TYPE(ONUMM6N1) :: STRESS_OTI(NTENS)"


def test_a_real_wrap_on_a_complex_name_is_caught_unless_it_changes_nothing():
    original = "IF (ABS(Z) .GT. 1D0) X = DBLE(Z)\n"
    assert cs.real_part_wraps_added(original, "IF (ABS(REAL(Z_OTI)) .GT. 1D0)", ["Z"]) == ["Z"]
    assert cs.real_part_wraps_added(original, "IF (DBLE(REAL(Z_OTI)) .GT. 1D0)", ["Z"]) == []
    assert cs.real_part_wraps_added("Y = REAL(Z)", "Y = REAL(Z_OTI)", ["Z"]) == []


def test_a_real_value_into_a_complex_dummy_is_caught():
    lifted = ("subroutine g_oti(a, b)\n    type(ZONUMM6N1) :: a(3)\n    type(ONUMM6N1) :: b\n"
              "end subroutine g_oti\n")
    transformed = ("      TYPE(ONUMM6N1) :: X_OTI(3)\n      TYPE(ZONUMM6N1) :: Z_OTI\n"
                   "      CALL G_OTI(X_OTI, Z_OTI)\n")
    issues = cs.argument_type_mismatches(transformed, "fixed", lifted, "ONUMM6N1")
    assert len(issues) == 2 and "X_OTI" in issues[0] and "Z_OTI" in issues[1]


CS_AWARE = """\
subroutine eig_oti(a)
    use oti_complex
    type(ZONUMM6N1) :: a(3,3), r
    type(ONUMM6N1) :: max_imag, mreal
    max_imag = ABS(AIMAG(a(1,2)))
    r = DCMPLX(MAX(-1.0d0, DBLE(a(1,1))), AIMAG(a(1,1)))
    IF (DBLE(r) .LT. 0.0d0) r = -r
    IF (max_imag .GT. 0.0d0) THEN
      mreal = AIMAG(a(2,3))
    END IF
end subroutine eig_oti
"""


def test_branches_on_the_imaginary_part_are_found_and_value_branches_are_not():
    found = cs.imaginary_part_branches("", "fixed", CS_AWARE)
    conditions = [f["condition"] for f in found]
    assert conditions == ["IF (max_imag .GT. 0.0d0) THEN"]


def test_they_refuse_only_a_source_that_does_its_own_complex_step():
    with_step = cs.plan_complex(FIXED_SOURCE, "fixed", "UMAT")
    assert cs.complex_step_branch_issues(with_step, "", "fixed", CS_AWARE)
    without = cs.plan_complex(FIXED_SOURCE.replace("DCMPLX(0.0D0, H)", "DCMPLX(1.0D0, 0.0D0)"),
                              "fixed", "UMAT")
    assert not without.complex_step
    assert cs.complex_step_branch_issues(without, "", "fixed", CS_AWARE) == []


# ----------------------------------------------------------------- end to end

def _hook_applied() -> bool:
    import umat_oti.transform.source_transform as st
    import umat_oti.transform.helper_lifting as hl
    return ("complex_support" in Path(st.__file__).read_text()
            and "retype_lifted_complex" in Path(hl.__file__).read_text())


DRIVER = """
program drive
  implicit none
  double precision :: stress(6), ddsdde(6,6), stran(6), dstran(6), props(2)
  integer :: i
  read(*,*) props, stran, dstran
  stress = 0d0
  ddsdde = 0d0
  call umat(stress, ddsdde, stran, dstran, props, 6)
  write(*,'(6ES26.17)') stress
  do i = 1, 6
    write(*,'(6ES26.17)') ddsdde(i,:)
  end do
end program drive
"""


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_complex_step_umat_transforms_and_its_tangent_matches_fd(tmp_path):
    from umat_oti.app.engine import _build_contract
    from umat_oti.corpus.cli import _write_aba_param_stub
    from umat_oti.services.transformation import TransformationOptions, run_transformation
    import json

    source = tmp_path / "cs_umat.for"
    source.write_text(FIXED_SOURCE)
    _write_aba_param_stub(tmp_path)
    config, _finite = _build_contract(source.stem, "auto", "STRESS", "DDSDDE", 6, 1, source)
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps(config))
    out = tmp_path / "out"
    out.mkdir()
    _write_aba_param_stub(out)
    report, _ = run_transformation(contract, out, TransformationOptions(compile_generated=False))
    assert report.get("transform_success"), report.get("blockers")
    assert "oti_complex.f90" in (out / "compile_order.txt").read_text()
    detail = json.loads((out / "transform_report.json").read_text())["complex_arithmetic"]
    assert detail["author_complex_step"][0]["routine"] == "UMAT"

    def build(directory: Path, units):
        flags = {".f90": ["-ffree-form", "-ffree-line-length-none"],
                 ".for": ["-ffixed-form", "-ffixed-line-length-none"]}
        for unit in units:
            done = subprocess.run(["gfortran", *flags[Path(unit).suffix], "-c", unit],
                                  cwd=directory, capture_output=True, text=True)
            assert done.returncode == 0, f"{unit}: {done.stderr[-2000:]}"
        (directory / "drive.f90").write_text(DRIVER)
        subprocess.run(["gfortran", "-c", "drive.f90"], cwd=directory, check=True)
        objects = [Path(u).with_suffix(".o").name for u in units] + ["drive.o"]
        subprocess.run(["gfortran", *objects, "-o", "drive"], cwd=directory, check=True)
        return directory / "drive"

    units = [line.strip() for line in (out / "compile_order.txt").read_text().splitlines() if line.strip()]
    transformed = build(out, units)
    reference_dir = tmp_path / "ref"
    reference_dir.mkdir()
    shutil.copy(source, reference_dir / "cs_umat.for")
    original = build(reference_dir, ["cs_umat.for"])

    props = [3.0, 7.0]
    stran = np.array([0.010, -0.004, 0.006, 0.003, -0.002, 0.005])
    dstran = np.array([0.001, 0.002, -0.001, 0.0005, 0.0, -0.001])

    def run(exe, d):
        text = " ".join(repr(float(v)) for v in [*props, *stran, *d]) + "\n"
        done = subprocess.run([str(exe)], input=text, capture_output=True, text=True, check=True)
        rows = np.array([[float(v) for v in l.split()] for l in done.stdout.strip().splitlines()])
        return rows[0], rows[1:]

    stress_oti, tangent_oti = run(transformed, dstran)
    stress_ref, tangent_cs = run(original, dstran)
    np.testing.assert_allclose(stress_oti, stress_ref, rtol=1e-14, atol=1e-15)
    # the author's complex step (h = 1e-20) is exact to rounding: an independent reference
    np.testing.assert_allclose(tangent_oti, tangent_cs, rtol=1e-12, atol=1e-13)
    # central FD of the original's STRESS, three steps on a plateau
    for j in range(6):
        columns = []
        for h in (1e-4, 1e-5, 1e-6):
            e = np.zeros(6)
            e[j] = h
            columns.append((run(original, dstran + e)[0] - run(original, dstran - e)[0]) / (2 * h))
        np.testing.assert_allclose(columns[1], columns[2], rtol=1e-6, atol=1e-8)
        np.testing.assert_allclose(tangent_oti[:, j], columns[1], rtol=1e-7, atol=1e-8)


def test_the_complex_hook_is_wired_into_the_transform():
    """A rename must fail here, not silently skip the end-to-end check above."""
    assert _hook_applied()
