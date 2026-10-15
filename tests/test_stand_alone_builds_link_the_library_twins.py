"""A stand-alone build of an ORIGINAL that calls LAPACK links the transform's real twins.

Abaqus supplies LAPACK (DGESV, DGETRF, DGETRS, DGETRI, DSPEVD) to a user
subroutine; a stand-alone build has none. Every offline replay of the original
-- the six-check gate's init probe, its routine-level primal, its
finite-difference reference, and the provider verifier's reference -- failed
to link on ``dgesv_``, and two of the six checks went undecided for that alone.
"""
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")

SOLVE = """
PROGRAM t
  IMPLICIT NONE
  REAL(8) :: a(3,3), b(3)
  INTEGER :: ipiv(3), info
  a = RESHAPE([4.0D0, 2.0D0, 1.0D0, 1.0D0, 5.0D0, 2.0D0, 0.5D0, 1.0D0, 6.0D0], [3, 3])
  b = [1.0D0, 2.0D0, 3.0D0]
  CALL DGESV(3, 1, a, 3, ipiv, b, 3, info)
  WRITE(*,'(I3,3ES26.17)') info, b
END PROGRAM t
"""

UMAT_CALLING_DGESV = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 DDSDDT(NTENS),DRPLDE(NTENS),STRAN(NTENS),DSTRAN(NTENS),
     2 TIME(2),PREDEF(1),DPRED(1),PROPS(NPROPS),COORDS(3),DROT(3,3),
     3 DFGRD0(3,3),DFGRD1(3,3)
      DIMENSION A(3,3), B(3)
      INTEGER IPIV(3), INFO
      DO I = 1, 3
        DO J = 1, 3
          A(I,J) = 0.0D0
        END DO
        A(I,I) = PROPS(1)
        B(I) = DSTRAN(I)*PROPS(1)*PROPS(1)
      END DO
      CALL DGESV(3, 1, A, 3, IPIV, B, 3, INFO)
      DO I = 1, NTENS
        STRESS(I) = STRESS(I) + DSTRAN(I)*PROPS(1)
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      STATEV(1) = STATEV(1) + B(1)
      RETURN
      END
"""


def test_the_stub_block_solves_a_system_the_way_lapack_does(tmp_path):
    from umat_oti.abaqus.replay import library_twin_block, utility_stub_block

    assert "SUBROUTINE DGESV(" in library_twin_block()
    assert library_twin_block() in utility_stub_block()
    source = tmp_path / "t.f90"
    source.write_text(SOLVE + utility_stub_block())
    done = subprocess.run(["gfortran", "-O0", "-w", str(source), "-o", str(tmp_path / "t")],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]
    values = subprocess.run([str(tmp_path / "t")], capture_output=True, text=True).stdout.split()
    assert int(values[0]) == 0
    a = np.array([[4.0, 1.0, 0.5], [2.0, 5.0, 1.0], [1.0, 2.0, 6.0]])
    np.testing.assert_allclose([float(v) for v in values[1:]], np.linalg.solve(a, [1.0, 2.0, 3.0]),
                               rtol=1e-14)


def test_a_source_that_defines_a_routine_keeps_its_own(tmp_path):
    from umat_oti.abaqus.replay import utility_stub_block
    from umat_oti.abaqus.single_call import drop_stubs_defined_by

    own = "      SUBROUTINE DGESV(N, NRHS, A, LDA, IPIV, B, LDB, INFO)\n      INFO = 0\n      END\n"
    kept, dropped = drop_stubs_defined_by(utility_stub_block(), own)
    assert "DGESV" in dropped and "SUBROUTINE DGESV(" not in kept
    assert "SUBROUTINE DGETRF(" in kept


def test_the_history_driver_builds_against_an_original_that_calls_dgesv(tmp_path):
    from umat_oti.abaqus.replay import FINIT_ZERO, GFORTRAN_HISTORY_FLAGS, build_history_replay

    source = tmp_path / "original_probed.for"
    source.write_text(UMAT_CALLING_DGESV)
    (tmp_path / "ABA_PARAM.INC").write_text("      IMPLICIT REAL*8 (A-H,O-Z)\n      PARAMETER (NPRECD=2)\n")
    built = build_history_replay(source, tmp_path / "zero", label="zero_init", compiler="gfortran",
                                 flags=(*GFORTRAN_HISTORY_FLAGS, *FINIT_ZERO), include_dirs=[tmp_path])
    assert built.ok, built.reason + built.log[-2000:]


def test_the_provider_reference_links_the_twins_and_only_what_is_missing(tmp_path):
    from umat_oti.validation.parameter_sensitivity_validation import build_original_driver, replay

    source = tmp_path / "umat.for"
    source.write_text(UMAT_CALLING_DGESV)
    executable = build_original_driver(source, tmp_path / "ref", ntens=6, nstatv=1, nprops=1)
    result = replay(executable, [2.0], [[1e-3, 0, 0, 0, 0, 0]], ntens=6, nstatv=1)
    # A = 2 I, B = DSTRAN * 4: the solve returns 2 * DSTRAN
    assert np.asarray(result.statev)[0][0] == pytest.approx(2e-3, rel=1e-15)
    # a source that brings its own DGESV links without a duplicate definition
    own = source.read_text() + ("      SUBROUTINE DGESV(N, NRHS, A, LDA, IPIV, B, LDB, INFO)\n"
                                "      INTEGER N, NRHS, LDA, LDB, IPIV(*), INFO\n"
                                "      DOUBLE PRECISION A(LDA,*), B(LDB,*)\n"
                                "      B(1,1) = -1.0D0\n      INFO = 0\n      END\n")
    mine = tmp_path / "mine.for"
    mine.write_text(own)
    executable = build_original_driver(mine, tmp_path / "mine_ref", ntens=6, nstatv=1, nprops=1)
    result = replay(executable, [2.0], [[1e-3, 0, 0, 0, 0, 0]], ntens=6, nstatv=1)
    assert np.asarray(result.statev)[0][0] == -1.0


def test_the_replay_driver_links_beside_a_umat_that_brings_its_own_dgesv(tmp_path):
    """build_replay (the finite-difference reference) linked the twins beside a
    source defining DGESV itself: ``multiple definition of dgesv_``."""
    from umat_oti.abaqus.replay import build_replay, driver_source

    own = UMAT_CALLING_DGESV + ("      SUBROUTINE DGESV(N, NRHS, A, LDA, IPIV, B, LDB, INFO)\n"
                                "      INTEGER N, NRHS, LDA, LDB, IPIV(*), INFO\n"
                                "      DOUBLE PRECISION A(LDA,*), B(LDB,*)\n"
                                "      DO I = 1, N\n        B(I,1) = B(I,1)/A(I,I)\n      END DO\n"
                                "      INFO = 0\n      RETURN\n      END\n")
    source = tmp_path / "own_dgesv.f"
    source.write_text(own)
    (tmp_path / "ABA_PARAM.INC").write_text("      IMPLICIT REAL*8 (A-H,O-Z)\n      PARAMETER (NPRECD=2)\n")
    assert "SUBROUTINE DGESV(" not in driver_source(source_text=own)
    assert "SUBROUTINE DGETRF(" in driver_source(source_text=own)
    built = build_replay(source, tmp_path / "replay")
    assert built.ok, built.reason + built.log[-2000:]


@pytest.mark.fortran
def test_the_provider_twins_are_the_supplied_bodies_and_never_an_authors_helper(tmp_path):
    """The provider's real twins were made by rewriting the lifted OTI text with regular
    expressions (REAL( -> DBLE(, _oti stripped) and included every lifted routine,
    an author's helper as well. They are now the supplied bodies, pinned here."""
    import json

    from umat_oti.provider.build import build_provider
    from umat_oti.transform.abaqus_utility_definitions import library_twin_sources

    helper = ("      SUBROUTINE MYSCALE(X, F)\n      DOUBLE PRECISION X, F\n"
              "      X = X*F\n      RETURN\n      END\n")
    source = UMAT_CALLING_DGESV.replace(
        "      STATEV(1) = STATEV(1) + B(1)\n",
        "      STATEV(1) = STATEV(1) + B(1)\n      CALL MYSCALE(STRESS(1), PROPS(1))\n") + helper
    model = tmp_path / "model"
    model.mkdir()
    (model / "umat.f").write_text(source)
    (model / "contract.json").write_text(json.dumps({
        "schema": "resasm_umat_transform_v2", "source": {"main_file": "umat.f"},
        "kinematics": "small_strain", "dimensions": {"ntens": 6, "nprops": 1, "nstatev": 1},
        "parameters": [{"name": "E", "props_index": 1}],
        "derivative": {"of": "STRESS", "wrt": "PROPS", "order": 1},
        "history": {"path_dependent": True},
        "output": {"object": "toy.obj", "contract": "toy.json"}}))
    built = build_provider(model / "contract.json", tmp_path / "out")
    twins = (Path(built["build_dir"]) / "real_library_twins.f90").read_text()
    bodies = library_twin_sources()
    assert twins.split("\n\n", 1)[1] == "\n".join(bodies[n] for n in ("DGESV", "DGETRF", "DGETRS"))
    assert "MYSCALE" not in twins.upper()
