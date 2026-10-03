"""The quad replay reference of the Abaqus tangent gate (G10, Vera B7 A2).

A stress formed from a quantity near 1 (``E ((1 + a + DSTRAN) - 1)``, the
PureGravity shape K (J - 1)) quantises a double centred difference at small
steps; the REAL(16) replay -- state read as REAL(8) and widened exactly,
outputs differenced exactly -- resolves it.
"""
import shutil

import numpy as np
import pytest

from umat_oti.abaqus.replay import build_replay, difference_tangent, write_state

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")

SOURCE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 STRAN(NTENS),DSTRAN(NTENS),PROPS(NPROPS)
      DO I = 1, NTENS
        STRESS(I) = PROPS(1)*((1.D0 + STRAN(I) + DSTRAN(I)) - 1.D0)
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = PROPS(1)
      END DO
      RETURN
      END
"""

ENTRY = {"NTENS": 3, "NSTATV": 1, "NPROPS": 1, "NDI": 2, "NSHR": 1,
         "STRESS0": [0.0] * 3, "STATEV0": [0.0], "STRAN": [0.3, 0.0, 0.0],
         "DSTRAN": [2.7e-8, 0.0, 0.0], "PROPS": [1000.0], "DTIME": [1.0],
         "TEMP": [0.0, 0.0], "TIME": [0.0, 0.0]}
LADDER = (1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8)


def _sweep(tmp_path, quad):
    work = tmp_path / ("quad" if quad else "double")
    work.mkdir()
    (work / "umat.f").write_text(SOURCE)
    write_state(ENTRY, work / "otis_state.txt")
    build = build_replay(work / "umat.f", work, quad=quad,
                         flags=("-ffixed-line-length-132", "-ffree-line-length-none",
                                "-std=legacy", "-O0", "-w", f"-J{work}"))
    assert build.ok, build.log
    return difference_tangent(build, work, 3, LADDER, scale=1e-6, exact=quad)


def test_double_quantises_and_quad_resolves(tmp_path):
    double, quad = _sweep(tmp_path, False), _sweep(tmp_path, True)
    assert double.ok and quad.ok
    d11 = np.array([double.matrices[r][0][0] for r in LADDER])
    q11 = np.array([quad.matrices[r][0][0] for r in LADDER])
    assert np.max(np.abs(d11 - 1000.0)) > 1e-3          # quantised in double
    assert np.max(np.abs(q11 - 1000.0)) < 1e-9          # resolved in quad
    # the primal: the quad base stress is the double one up to double round-off
    assert abs(quad.unperturbed[0] - double.unperturbed[0]) <= 1e-12 * 300.0
