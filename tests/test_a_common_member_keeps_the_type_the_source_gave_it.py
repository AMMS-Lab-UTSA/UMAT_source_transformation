"""An undeclared COMMON member is typed by the source's own implicit rule.

Lifting a helper writes a prelude that re-declares what the routine's new
``implicit type(OTI) (a-h,o-z)`` would otherwise capture. A COMMON member the
source never declared has to come back with the type the source gave it -- and
Fortran's default rule, which the prelude restates one line above as
``implicit integer (i-n)``, types I-N INTEGER.

Declaring all of them ``real(8)`` contradicted that rule. gfortran refused the
prelude with "Symbol 'ndim3' already has basic type of INTEGER", so the
transform reported success and the generated Fortran did not build. Four
corpus sources went ``compiled: true`` -> ``compiled: false`` on exactly this
between pass16 (fingerprint dbe9f928191e1d43) and pass17 (650a66ab55825346):
the theysy MML family, whose ``COMMON /KSIZE/ NDIM1..NDIM7`` holds undeclared
array bounds assigned from NTENS. A real(8) array bound would be wrong even if
a compiler accepted it.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.fortran]


SOURCE = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      COMMON /KSIZE/ NDIM3
      COMMON /KOPTION/ HARD_PAR
      NDIM3=NTENS
      HARD_PAR=PROPS(2)
      EMOD=PROPS(1)
      CALL SCALE_STRESS(STRESS,DSTRAN,EMOD)
      DO K1=1,NTENS
        DO K2=1,NTENS
          DDSDDE(K1,K2)=0.D0
        END DO
        DDSDDE(K1,K1)=EMOD
      END DO
      RETURN
      END
      SUBROUTINE SCALE_STRESS(SIG,DEPS,EMOD)
      INCLUDE 'ABA_PARAM.INC'
      COMMON /KSIZE/ NDIM3
      COMMON /KOPTION/ HARD_PAR
      DIMENSION SIG(NDIM3),DEPS(NDIM3)
      DO K1=1,NDIM3
        SIG(K1)=SIG(K1)+EMOD*HARD_PAR*DEPS(K1)
      END DO
      RETURN
      END
"""


@pytest.fixture()
def transformed(tmp_path):
    from umat_oti.corpus.cli import _write_aba_param_stub
    from umat_oti.services.jacobian_request import run_jacobian_transform

    if shutil.which("gfortran") is None:
        pytest.skip("gfortran required")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "umat.for").write_text(SOURCE, encoding="utf-8")
    _write_aba_param_stub(inputs)
    output = tmp_path / "out"
    run = run_jacobian_transform(inputs / "umat.for", output, ntens=6)
    assert run.succeeded, run.report
    return output


def test_an_implicit_integer_common_member_is_declared_integer(transformed):
    """``NDIM3`` is an array bound; the prelude may not make it a real."""
    prelude = (transformed / "umat_oti_helpers.f90").read_text()

    assert "integer :: NDIM3" in prelude
    assert "real(8) :: NDIM3" not in prelude


def test_a_real_common_member_is_still_declared_real(transformed):
    """The rule is the source's implicit rule, not "integer for everything"."""
    prelude = (transformed / "umat_oti_helpers.f90").read_text()

    assert "real(8) :: HARD_PAR" in prelude
    assert "integer :: HARD_PAR" not in prelude


def test_the_lifted_prelude_compiles(transformed, tmp_path):
    """The whole point: the transform succeeding is not the build succeeding.

    Built the way a job builds it: the solver's header on an include path
    (``OBJDIR``, which the build script puts on ``-I``), not beside the source.
    """
    import os
    from umat_oti.corpus.cli import _write_aba_param_stub

    headers = tmp_path / "headers"
    headers.mkdir()
    _write_aba_param_stub(headers)
    built = subprocess.run(["bash", str(transformed / "compile_hint.sh")],
                           cwd=transformed, capture_output=True, text=True,
                           env={**os.environ, "OBJDIR": str(headers)})

    assert built.returncode == 0, built.stdout + built.stderr
    assert "already has basic type" not in built.stderr
    assert (headers / "transformed_umat.o").is_file()
