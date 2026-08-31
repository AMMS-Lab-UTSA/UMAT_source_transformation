"""MATMUL over the OTI type: which forms exist, and whether they are right.

The generated OTI algebra defines MATMUL for two rank-2 arguments and stops
there, so the most ordinary stress update a linear-elastic UMAT can write --

    STRESS = MATMUL(DDSDDE, STRAN + DSTRAN)

-- matches no specific procedure once DSTRAN is promoted, and gfortran reports
"Generic function 'matmul' is not consistent with a specific intrinsic
interface". The extension module supplies the six rank-mixed forms.

The numeric test here is the point of the file. A MATMUL overload that
compiles proves nothing: an accumulator that is never zeroed, or a contraction
index written the wrong way round, still compiles and still returns a
plausible-looking stress with a wrong derivative attached. So the driver
computes each product twice -- once through the overload, once as a hand
written loop over the same OTI ``*`` and ``+`` -- and compares the real part
and every extracted imaginary part, and additionally compares the first-order
derivative of the mixed real/OTI product against the analytic answer, which is
just the matrix entry itself.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from umat_oti.oti.module_generator import generate_otilib_module
from umat_oti.transform.parameter_sensitivity_transform import (
    _emit_intrinsic_extensions,
)

#: Deliberately not square and deliberately not 6 or 3: the emitted procedures
#: take assumed-shape arguments and must size the result from them. A UMAT
#: calls MATMUL on 3x3 kinematics and on NTENS-by-NTENS material matrices in
#: the same file, so the driver also does a second shape further down.
DRIVER = """\
PROGRAM MATMUL_CHECK
  USE master_parameters, ONLY: DP
  USE {module}
  USE oti_intrinsics
  IMPLICIT NONE

  INTEGER, PARAMETER :: M = 4, N = 3, P = 3
  TYPE({type_name}) :: AO(M,N), XO(N), YO(M), YREF(M)
  TYPE({type_name}) :: VO(M), WO(N), WREF(N)
  TYPE({type_name}) :: XM(N,1), YM(M,1), VM(1,M), WM(1,N)
  TYPE({type_name}) :: TO33(P,P), UO3(P), ZO3(P), ZREF3(P)
  REAL(DP) :: AR(M,N), XR(N), VR(M), TR33(P,P), UR3(P)
  REAL(DP) :: EXPECTED(M), GOT(M)
  INTEGER :: I, J, K, D, FAILURES

  FAILURES = 0

  DO I = 1, M
    DO J = 1, N
      AR(I,J) = 1.5_DP*REAL(I,DP) - 0.25_DP*REAL(J,DP) + 0.125_DP*REAL(I*J,DP)
    END DO
  END DO
  DO J = 1, N
    XR(J) = 0.5_DP + 0.25_DP*REAL(J,DP)
  END DO
  DO I = 1, M
    VR(I) = 0.75_DP - 0.125_DP*REAL(I,DP)
  END DO
  DO I = 1, P
    UR3(I) = 2.0_DP - 0.5_DP*REAL(I,DP)
    DO J = 1, P
      TR33(I,J) = 0.375_DP*REAL(I,DP) + 0.75_DP*REAL(J,DP) - 0.0625_DP*REAL(I*J,DP)
    END DO
  END DO

! x carries one seeded direction per component: x_j = xr_j + e_j.
  DO J = 1, N
    XO(J) = XR(J)
  END DO
  XO(1) = XO(1) + E1
  XO(2) = XO(2) + E2
  XO(3) = XO(3) + E3

! A carries directions of its own, in E4..E6, so the product rule is
! exercised rather than only the part that is linear in x.
  DO I = 1, M
    DO J = 1, N
      AO(I,J) = AR(I,J)
    END DO
  END DO
  AO(1,1) = AO(1,1) + E4
  AO(2,3) = AO(2,3) + E5
  AO(4,2) = AO(4,2) + E6

  DO I = 1, M
    VO(I) = VR(I)
  END DO
  VO(1) = VO(1) + E1
  VO(3) = VO(3) + E2

  DO I = 1, P
    UO3(I) = UR3(I)
  END DO
  UO3(1) = UO3(1) + E1
  UO3(2) = UO3(2) + E2
  UO3(3) = UO3(3) + E3
  DO I = 1, P
    DO J = 1, P
      TO33(I,J) = TR33(I,J)
    END DO
  END DO
  TO33(2,2) = TO33(2,2) + E4

! 1. MATMUL(real matrix, oti vector) -- the UMAT stress-update form.
  YO = MATMUL(AR, XO)
  YREF = 0.0_DP
  DO I = 1, M
    DO K = 1, N
      YREF(I) = YREF(I) + AR(I,K)*XO(K)
    END DO
  END DO
  CALL COMPARE("MATMUL(real m, oti v) vs hand loop", YO, YREF, M)
! and against the analytic derivative: d y_i / d x_j is A(i,j), and zero in
! every direction nothing was seeded in.
  DO D = 0, {ndir}
    DO I = 1, M
      IF (D == 0) THEN
        EXPECTED(I) = 0.0_DP
        DO K = 1, N
          EXPECTED(I) = EXPECTED(I) + AR(I,K)*XR(K)
        END DO
      ELSE IF (D <= N) THEN
        EXPECTED(I) = AR(I,D)
      ELSE
        EXPECTED(I) = 0.0_DP
      END IF
    END DO
    GOT = GETIM(YO, D)
    CALL COMPARE_R("MATMUL(real m, oti v) vs analytic", GOT, EXPECTED, M, D)
  END DO

! 2. MATMUL(oti matrix, oti vector) -- both operands differentiated.
  YO = MATMUL(AO, XO)
  YREF = 0.0_DP
  DO I = 1, M
    DO K = 1, N
      YREF(I) = YREF(I) + AO(I,K)*XO(K)
    END DO
  END DO
  CALL COMPARE("MATMUL(oti m, oti v) vs hand loop", YO, YREF, M)
  DO D = 0, {ndir}
    DO I = 1, M
      EXPECTED(I) = 0.0_DP
    END DO
    IF (D == 0) THEN
      DO I = 1, M
        DO K = 1, N
          EXPECTED(I) = EXPECTED(I) + AR(I,K)*XR(K)
        END DO
      END DO
    ELSE IF (D <= N) THEN
      DO I = 1, M
        EXPECTED(I) = AR(I,D)
      END DO
    ELSE IF (D == 4) THEN
      EXPECTED(1) = XR(1)
    ELSE IF (D == 5) THEN
      EXPECTED(2) = XR(3)
    ELSE IF (D == 6) THEN
      EXPECTED(4) = XR(2)
    END IF
    GOT = GETIM(YO, D)
    CALL COMPARE_R("MATMUL(oti m, oti v) vs analytic", GOT, EXPECTED, M, D)
  END DO

! 2b. The same product against the generated algebra's own rank-2 MATMUL,
! reached by making the vector a one-column matrix. That routine is written
! component-wise on top of the intrinsic MATMUL, so it shares no code with the
! loop under test and is an independent answer rather than a restatement.
  DO K = 1, N
    XM(K,1) = XO(K)
  END DO
  YM = MATMUL(AO, XM)
  DO I = 1, M
    YREF(I) = YM(I,1)
  END DO
  CALL COMPARE("MATMUL(oti m, oti v) vs vendored rank-2", YO, YREF, M)

! 3. MATMUL(oti matrix, real vector).
  YO = MATMUL(AO, XR)
  YREF = 0.0_DP
  DO I = 1, M
    DO K = 1, N
      YREF(I) = YREF(I) + AO(I,K)*XR(K)
    END DO
  END DO
  CALL COMPARE("MATMUL(oti m, real v) vs hand loop", YO, YREF, M)

! 4-6. The row-vector forms.
  WO = MATMUL(VO, AO)
  WREF = 0.0_DP
  DO J = 1, N
    DO K = 1, M
      WREF(J) = WREF(J) + VO(K)*AO(K,J)
    END DO
  END DO
  CALL COMPARE("MATMUL(oti v, oti m) vs hand loop", WO, WREF, N)

  WO = MATMUL(VR, AO)
  WREF = 0.0_DP
  DO J = 1, N
    DO K = 1, M
      WREF(J) = WREF(J) + VR(K)*AO(K,J)
    END DO
  END DO
  CALL COMPARE("MATMUL(real v, oti m) vs hand loop", WO, WREF, N)

  WO = MATMUL(VO, AR)
  WREF = 0.0_DP
  DO J = 1, N
    DO K = 1, M
      WREF(J) = WREF(J) + VO(K)*AR(K,J)
    END DO
  END DO
  CALL COMPARE("MATMUL(oti v, real m) vs hand loop", WO, WREF, N)

! 6b. The row-vector form against the vendored rank-2 MATMUL as well.
  WO = MATMUL(VO, AO)
  DO K = 1, M
    VM(1,K) = VO(K)
  END DO
  WM = MATMUL(VM, AO)
  DO J = 1, N
    WREF(J) = WM(1,J)
  END DO
  CALL COMPARE("MATMUL(oti v, oti m) vs vendored rank-2", WO, WREF, N)

! 7. A second, different shape in the same program.
  ZO3 = MATMUL(TO33, UO3)
  ZREF3 = 0.0_DP
  DO I = 1, P
    DO K = 1, P
      ZREF3(I) = ZREF3(I) + TO33(I,K)*UO3(K)
    END DO
  END DO
  CALL COMPARE("MATMUL(3x3, 3) vs hand loop", ZO3, ZREF3, P)

  WRITE(*,*) "FAILURES", FAILURES
  IF (FAILURES /= 0) STOP 1
  WRITE(*,*) "OK"

CONTAINS

  SUBROUTINE COMPARE(LABEL, GOTV, WANTV, NV)
    CHARACTER(LEN=*), INTENT(IN) :: LABEL
    TYPE({type_name}), INTENT(IN) :: GOTV(:), WANTV(:)
    INTEGER, INTENT(IN) :: NV
    REAL(DP) :: G(NV), W(NV)
    INTEGER :: DD, II
    DO DD = 0, {ndir}
      G = GETIM(GOTV, DD)
      W = GETIM(WANTV, DD)
      DO II = 1, NV
        IF (ABS(G(II) - W(II)) > 1.0E-13_DP*(1.0_DP + ABS(W(II)))) THEN
          WRITE(*,*) "MISMATCH ", LABEL, " dir ", DD, " row ", II, G(II), W(II)
          FAILURES = FAILURES + 1
        END IF
      END DO
    END DO
    WRITE(*,*) "checked ", LABEL
  END SUBROUTINE COMPARE

  SUBROUTINE COMPARE_R(LABEL, GOTV, WANTV, NV, DD)
    CHARACTER(LEN=*), INTENT(IN) :: LABEL
    REAL(DP), INTENT(IN) :: GOTV(:), WANTV(:)
    INTEGER, INTENT(IN) :: NV, DD
    INTEGER :: II
    DO II = 1, NV
      IF (ABS(GOTV(II) - WANTV(II)) > 1.0E-13_DP*(1.0_DP + ABS(WANTV(II)))) THEN
        WRITE(*,*) "MISMATCH ", LABEL, " dir ", DD, " row ", II, GOTV(II), WANTV(II)
        FAILURES = FAILURES + 1
      END IF
    END DO
  END SUBROUTINE COMPARE_R

END PROGRAM MATMUL_CHECK
"""


@pytest.mark.unit
def test_the_extension_declares_only_the_forms_the_algebra_lacks():
    """Redeclaring a form the generated algebra already has breaks every build.

    Two specific procedures with the same argument types in one generic are an
    ambiguous interface, and gfortran rejects it at the USE line of any scope
    importing both modules -- so a duplicate TRANSPOSE here would stop every
    transformed UMAT compiling, not just the ones that call it.
    """
    text = _emit_intrinsic_extensions("otim6n1", "ONUMM6N1")
    for name in ("oti_matmul_oo_mv", "oti_matmul_ro_mv", "oti_matmul_or_mv",
                 "oti_matmul_oo_vm", "oti_matmul_ro_vm", "oti_matmul_or_vm"):
        assert name in text, name
    # Every emitted MATMUL argument pair mixes a rank-2 and a rank-1 operand.
    # The rank-2 by rank-2 forms, TRANSPOSE and DOT_PRODUCT come from the
    # generated algebra and must not be defined a second time here.
    assert "INTERFACE TRANSPOSE" not in text
    assert "INTERFACE DOT_PRODUCT" not in text
    assert " :: A(:,:)" in text and " :: B(:)" in text
    assert " :: A(:)" in text and " :: B(:,:)" in text
    # The accumulator is zeroed, in all six. An OTI shadow left at whatever
    # was in memory is a wrong derivative that still compiles.
    assert text.count("    RES = 0.0_DP") == 6


@pytest.mark.unit
def test_the_result_extent_comes_from_the_arguments():
    """No emitted bound may be a literal: NTENS is 3, 4 or 6 across the corpus."""
    text = _emit_intrinsic_extensions("otim4n1", "ONUMM4N1")
    assert "RES(SIZE(A, 1))" in text
    assert "RES(SIZE(B, 2))" in text
    assert "SIZE(A, 2)" in text and "SIZE(B, 1)" in text
    for bound in ("RES(3)", "RES(4)", "RES(6)", "RES(6,6)", "RES(3,3)"):
        assert bound not in text, bound


def _build_and_run_driver(tmp_path, *, ntens, order, template, ndir):
    """Emit the library and the driver beside it, build both, run the driver."""
    module = generate_otilib_module(output_dir=tmp_path, ntens=ntens, order=order)
    (tmp_path / "oti_intrinsics.f90").write_text(
        _emit_intrinsic_extensions(module.module_name, module.type_name),
        encoding="utf-8")
    (tmp_path / "matmul_check.f90").write_text(
        template.format(module=module.module_name, type_name=module.type_name,
                        ndir=ndir),
        encoding="utf-8")

    units = ["master_parameters", "real_utils", module.module_name,
             "oti_intrinsics"]
    flags = ["-O1", "-std=legacy", "-ffree-line-length-none", "-fcheck=bounds",
             f"-I{tmp_path}", f"-J{tmp_path}"]
    for unit in units:
        built = subprocess.run(
            ["gfortran", *flags, "-c", str(tmp_path / f"{unit}.f90"),
             "-o", str(tmp_path / f"{unit}.o")],
            capture_output=True, text=True)
        assert built.returncode == 0, f"{unit}: {built.stderr}"

    exe = tmp_path / "matmul_check"
    linked = subprocess.run(
        ["gfortran", *flags,
         *[str(tmp_path / f"{unit}.o") for unit in units],
         str(tmp_path / "matmul_check.f90"), "-o", str(exe)],
        capture_output=True, text=True)
    assert linked.returncode == 0, linked.stderr

    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=180)
    assert "MISMATCH" not in run.stdout, run.stdout
    assert run.returncode == 0, run.stdout + run.stderr
    assert "OK" in run.stdout
    return run.stdout


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_matmul_overloads_agree_with_a_hand_loop_in_value_and_derivative(tmp_path):
    """Numeric, not by inspection: value and every imaginary part must agree.

    Regression for two ways a MATMUL overload is wrong while still compiling:
    an accumulator that is never zeroed reads whatever was in memory, and a
    contraction index written the wrong way round silently transposes the
    product. Both are caught by the hand-loop comparison; the analytic
    comparison catches a derivative dropped altogether, and the cross-check
    against the generated algebra's own rank-2 MATMUL is an answer computed by
    code this loop shares nothing with.
    """
    stdout = _build_and_run_driver(tmp_path, ntens=6, order=1,
                                   template=DRIVER, ndir=6)
    # Every comparison must actually have run; a driver that silently skipped
    # them would also print no mismatch.
    assert stdout.count("checked ") == 9, stdout


#: Order 2, and a different NTENS. Nothing in the emitted procedures mentions a
#: component of the type, so the same loop has to carry second-order terms
#: without being told they exist; this is what checks that claim rather than
#: asserting it. The comparison is over every component the type has, so it
#: needs no knowledge of how the higher-order directions are laid out.
HIGHER_ORDER_DRIVER = """\
PROGRAM MATMUL_CHECK_HO
  USE master_parameters, ONLY: DP
  USE {module}
  USE oti_intrinsics
  IMPLICIT NONE

  INTEGER, PARAMETER :: M = 4, N = 3
  TYPE({type_name}) :: AO(M,N), XO(N), YO(M), YREF(M), XM(N,1), YM(M,1)
  REAL(DP) :: AR(M,N), XR(N)
  INTEGER :: I, J, K, D, FAILURES
  REAL(DP) :: G(M), W(M)

  FAILURES = 0
  DO I = 1, M
    DO J = 1, N
      AR(I,J) = 0.5_DP*REAL(I,DP) + 0.25_DP*REAL(J,DP) - 0.125_DP*REAL(I*J,DP)
    END DO
  END DO
  DO J = 1, N
    XR(J) = 1.25_DP - 0.5_DP*REAL(J,DP)
  END DO

  DO I = 1, M
    DO J = 1, N
      AO(I,J) = AR(I,J)
    END DO
  END DO
  DO J = 1, N
    XO(J) = XR(J)
  END DO
! Both operands carry directions, so the product carries the second-order
! cross terms the first order alone would never produce.
  AO(1,1) = AO(1,1) + E1
  AO(2,2) = AO(2,2) + E2
  AO(3,3) = AO(3,3) + E3
  XO(1) = XO(1) + E2
  XO(2) = XO(2) + E3
  XO(3) = XO(3) + E1

  YO = MATMUL(AO, XO)
  YREF = 0.0_DP
  DO I = 1, M
    DO K = 1, N
      YREF(I) = YREF(I) + AO(I,K)*XO(K)
    END DO
  END DO
  CALL COMPARE("order 2: MATMUL(oti m, oti v) vs hand loop", YO, YREF)

  DO K = 1, N
    XM(K,1) = XO(K)
  END DO
  YM = MATMUL(AO, XM)
  DO I = 1, M
    YREF(I) = YM(I,1)
  END DO
  CALL COMPARE("order 2: MATMUL(oti m, oti v) vs vendored rank-2", YO, YREF)

  WRITE(*,*) "FAILURES", FAILURES
  IF (FAILURES /= 0) STOP 1
  WRITE(*,*) "OK"

CONTAINS

  SUBROUTINE COMPARE(LABEL, GOTV, WANTV)
    CHARACTER(LEN=*), INTENT(IN) :: LABEL
    TYPE({type_name}), INTENT(IN) :: GOTV(:), WANTV(:)
    INTEGER :: DD, II
! Every component of the type, real part included, so no direction can be
! silently dropped: NUM_IM_DIR is the module's own count.
    DO DD = 0, NUM_IM_DIR - 1
      G = GETIM(GOTV, DD)
      W = GETIM(WANTV, DD)
      DO II = 1, M
        IF (ABS(G(II) - W(II)) > 1.0E-13_DP*(1.0_DP + ABS(W(II)))) THEN
          WRITE(*,*) "MISMATCH ", LABEL, " dir ", DD, " row ", II, G(II), W(II)
          FAILURES = FAILURES + 1
        END IF
      END DO
    END DO
    WRITE(*,*) "checked ", LABEL
  END SUBROUTINE COMPARE

END PROGRAM MATMUL_CHECK_HO
"""


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_matmul_overloads_carry_second_order_terms(tmp_path):
    """A different NTENS and a higher order, checked over every component."""
    stdout = _build_and_run_driver(tmp_path, ntens=3, order=2,
                                   template=HIGHER_ORDER_DRIVER, ndir=0)
    assert stdout.count("checked ") == 2, stdout


#: The stress update that named the gap. MATMUL of the tangent with the total
#: strain is how a linear-elastic UMAT is most often written.
MATMUL_UMAT = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,JSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      E=PROPS(1)
      ANU=PROPS(2)
      ALAMBDA=E/(1.0D0+ANU)/(1.0D0-2.0D0*ANU)
      DO I=1,NTENS
         DO J=1,NTENS
            DDSDDE(I,J)=0.0D0
         ENDDO
      ENDDO
      DO I=1,NDI
         DDSDDE(I,I)=ALAMBDA*(1.0D0-ANU)
      ENDDO
      DO I=NDI+1,NTENS
         DDSDDE(I,I)=ALAMBDA*0.5D0*(1.0D0-2.0D0*ANU)
      ENDDO
      STRESS = MATMUL(DDSDDE, STRAN + DSTRAN)
      STATEV(1)=STRESS(1)
      RETURN
      END
"""


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_a_umat_whose_stress_update_is_a_matmul_transforms_and_compiles(tmp_path):
    """End to end: MATMUL must survive as MATMUL and then resolve.

    Two separate defects stood between this source and a build. The name was
    promoted like a variable and renamed with it, so the emitted line read
    ``STRESS_OTI = MATMUL_OTI(...)`` and stopped at "Unclassifiable statement";
    and once the name survived, no specific procedure took a rank-2 and a
    rank-1 argument. Compiling is the claim being made here -- nothing about
    the derivative this build would produce is asserted.
    """
    from umat_oti.app.engine import _build_contract
    from umat_oti.corpus.cli import _write_aba_param_stub
    from umat_oti.services.transformation import (
        TransformationOptions, run_transformation,
    )
    import json

    staged = tmp_path / "matmul_elastic.f"
    staged.write_text(MATMUL_UMAT, encoding="utf-8")
    _write_aba_param_stub(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    _write_aba_param_stub(out)

    config, _finite = _build_contract(
        "matmul_elastic", "auto", "STRESS", "DDSDDE", 6, 1, staged)
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    report, _code = run_transformation(
        contract_path, out, TransformationOptions(compile_generated=True))
    assert report.get("transform_success"), report.get("blockers")

    emitted = next(out.glob("*_oti.f")).read_text(encoding="utf-8")
    assert "MATMUL_OTI" not in emitted, "an intrinsic was renamed like a variable"
    assert "MATMUL(DDSDDE, STRAN + DSTRAN_OTI)" in emitted

    compilation = report.get("compilation") or {}
    assert compilation.get("status") == "compiled", compilation.get("stderr")


#: The same stress update in the fixed-form spelling the parameter-sensitivity
#: contract takes, with the two properties that round differentiates against.
PS_MATMUL_UMAT = """\
      SUBROUTINE UMAT(STRESS, STATEV, DDSDDE, SSE, SPD, SCD, RPL,
     1 DDSDDT, DRPLDE, DRPLDT, STRAN, DSTRAN, TIME, DTIME, TEMP,
     2 DTEMP, PREDEF, DPRED, CMNAME, NDI, NSHR, NTENS, NSTATV, PROPS,
     3 NPROPS, COORDS, DROT, PNEWDT, CELENT, DFGRD0, DFGRD1, NOEL,
     4 NPT, LAYER, KSPT, KSTEP, KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS), STATEV(NSTATV), DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS), DRPLDE(NTENS), STRAN(NTENS), DSTRAN(NTENS),
     2 TIME(2), PREDEF(1), DPRED(1), PROPS(NPROPS), COORDS(3),
     3 DROT(3,3), DFGRD0(3,3), DFGRD1(3,3)
      EMOD=PROPS(1)
      ENU=PROPS(2)
      EG=EMOD/(2.0D0*(1.0D0+ENU))
      ELAM=EMOD*ENU/((1.0D0+ENU)*(1.0D0-2.0D0*ENU))
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K2,K1)=0.0D0
        END DO
      END DO
      DO K1=1,NDI
        DO K2=1,NDI
          DDSDDE(K2,K1)=ELAM
        END DO
        DDSDDE(K1,K1)=ELAM+2.0D0*EG
      END DO
      DO K1=NDI+1,NTENS
        DDSDDE(K1,K1)=EG
      END DO
      STRESS = MATMUL(DDSDDE, STRAN + DSTRAN)
      STATEV(1)=STRESS(1)
      RETURN
      END
"""


@pytest.mark.slow
@pytest.mark.fortran
@pytest.mark.regression
@pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")
def test_the_parameter_sensitivity_path_builds_and_runs_a_matmul_umat(tmp_path):
    """The other path that emits this module, taken as far as a running binary.

    Two paths emit oti_intrinsics.f90 and this is the second one. It seeds two
    parameters rather than six strain directions, so the overloads are reached
    through a differently named type with a different direction count -- the
    extents have to come from the arguments rather than from NTENS.
    """
    from umat_oti.transform.parameter_sensitivity_transform import (
        GenericPSContract, compile_generic_ps, run_generic_ps,
        transform_umat_for_parameter_sensitivity,
    )

    source = tmp_path / "ps_matmul.for"
    source.write_text(PS_MATMUL_UMAT, encoding="utf-8")
    contract = GenericPSContract(
        name="ps_matmul", umat_source_path=source,
        parameters=(("EMOD", 1), ("ENU", 2)),
        parameter_values=(200000.0, 0.3),
        state_variables=(("S11", 1),),
        ntens=6, nstatv=1, ndi=3, nshr=3,
        dstran_per_increment=(1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        n_increments=3, static_props=(200000.0, 0.3))
    layout = transform_umat_for_parameter_sensitivity(
        contract=contract, output_dir=tmp_path / "out")
    assert layout.type_name == "ONUMM2N1", layout.type_name

    result = run_generic_ps(compile_generic_ps(layout))
    assert result.returncode == 0, result.stderr
    rows = result.dsigma_csv.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) > 1, "the run produced no stress-sensitivity rows"
