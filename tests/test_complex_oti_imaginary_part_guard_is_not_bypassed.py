"""The imaginary-part guard of a complex-step source cannot be talked around.

A source that computes its own complex-step tangent and branches on an
imaginary part is refused: under the complex OTI type every primal imaginary
part is zero, the branch is never taken, and DDSDDE is the derivative of the
value algorithm where the author needed the other one. Vera (B2 review item 5)
bypassed the guard three ways, each giving DDSDDE(1,1) = 0 against FD of the
original = 100:

* t5b  ``XIM = DBLE(DCMPLX(0,-1)*Z)``   -- Im(Z) without AIMAG;
* t5c  ``CALL IMPART(Z, XIM)``           -- Im(Z) returned through a CALL;
* t5d  the tangent written ``AIMAG(F)*HINV`` -- idiom not detected, guard off.

Reals derived from complex expressions not reduced to a real part or modulus,
and CALL outputs whose callee dummy is tainted (or any real argument of an
unreadable callee given a complex value), are now tainted; the idiom is
detected from the ``DCMPLX(0,h)`` perturbation alone. All four are refused.
The original of each is compiled and run as a control that the branch is live.
"""
import pytest

from test_transform_a_value_set_before_the_seed_block_reaches_its_shadow import (
    DIRECTION, HEADER, build_original, needs_gfortran, run, transform)


def umat(extract: str, getim: str) -> str:
    return HEADER + """      DOUBLE COMPLEX Z, F
      CS_H = 1.D-30
      HINV = 1.D0/CS_H
      E=PROPS(1)
      A=PROPS(2)
      DO I=1,NTENS
        Z = DCMPLX(DSTRAN(I), 0.D0)
        CALL SPEC(Z, A, F)
        STRESS(I) = STRESS(I) + E*DBLE(F)
      END DO
      DO I=1,NTENS
        DO J=1,NTENS
          DDSDDE(I,J)=0.D0
        END DO
        Z = DCMPLX(DSTRAN(I), 0.D0) + DCMPLX(0.D0, CS_H)
        CALL SPEC(Z, A, F)
        DDSDDE(I,I) = E*""" + extract + """
      END DO
      RETURN
      END

      SUBROUTINE SPEC(Z, A, F)
      INCLUDE 'ABA_PARAM.INC'
      DOUBLE COMPLEX Z, F, D
""" + getim + """
      D = Z - A
      IF (ABS(DBLE(D)).LT.1.D-12 .AND. XIM.EQ.0.D0) THEN
        F = 2.D0*A
      ELSE
        F = (Z*Z - A*A)/D
      END IF
      RETURN
      END
      SUBROUTINE IMPART(Z, X)
      INCLUDE 'ABA_PARAM.INC'
      DOUBLE COMPLEX Z
      X = AIMAG(Z)
      RETURN
      END
"""


CASES = {
    "t5a_control": ("AIMAG(F)/CS_H", "      XIM = AIMAG(Z)"),
    "t5b_conj": ("AIMAG(F)/CS_H", "      XIM = DBLE(DCMPLX(0.D0,-1.D0)*Z)"),
    "t5c_call": ("AIMAG(F)/CS_H", "      CALL IMPART(Z, XIM)"),
    "t5d_hinv": ("AIMAG(F)*HINV", "      XIM = AIMAG(Z)"),
}


@needs_gfortran
@pytest.mark.parametrize("name", sorted(CASES))
def test_a_branch_on_an_imaginary_part_is_refused_however_it_is_written(tmp_path, name):
    code, summary, output, source = transform(tmp_path, umat(*CASES[name]))
    report = (output / "transform_report.json").read_text()
    assert code != 0
    assert "branches on an imaginary part in SPEC_OTI" in report, report[:2000]
    # Control: the original compiles and runs; its complex-step tangent away
    # from the switch point is E. (At DSTRAN(1) = A the author's own tangent
    # is 0 -- Im(F) is lost to h**2 underflow -- while FD of its STRESS is 100.)
    original = build_original(tmp_path, source)
    _, _, tangent = run(original, [100.0, 1e-3, 0.0], [0.0], [[1e-3 * v for v in DIRECTION]])
    assert abs(tangent[1][2][1] - 100.0) < 1e-9


def test_a_complex_real_part_or_modulus_does_not_taint_but_anything_else_does():
    from umat_oti.transform.complex_support import _reads_an_imaginary_part

    complex_names = {"Z", "F"}
    assert not _reads_an_imaginary_part("E*DBLE(F)", complex_names, set())
    assert not _reads_an_imaginary_part("ABS(Z(I))+REAL(F, 8)", complex_names, set())
    assert _reads_an_imaginary_part("DBLE(DCMPLX(0.D0,-1.D0)*Z)", complex_names, set())
    assert _reads_an_imaginary_part("AIMAG(Z)", complex_names, set())
    assert _reads_an_imaginary_part("2*Y", complex_names, {"Y"})
    assert _reads_an_imaginary_part("Z*Z", complex_names, set())
