"""D-21a (e) dynamic re-check of a static-scan override (G12).

The ORIGINAL is run over the same history once per variant of the
overridden input (TEMP 0 and 500, or the element at two COORDS); the
override stands only with bit-identical STRESS, DDSDDE and STATEV.
"""
import shutil

import numpy as np
import pytest

from umat_oti.corpus_features import drivers as dv
from umat_oti.corpus_features.harness import CorpusEntry, static_scan_override_check

pytestmark = pytest.mark.skipif(shutil.which("gfortran") is None, reason="gfortran not on PATH")

HEADER = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 STRAN(NTENS),DSTRAN(NTENS),PROPS(NPROPS),COORDS(3)
"""
BODY = """\
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = E
        STRESS(I) = STRESS(I) + E*DSTRAN(I)
      END DO
      STATEV(1) = STRESS(1)
      RETURN
      END
"""


def _check(tmp_path, text, override):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "umat.f"
    source.write_text(text)
    build = dv.build_real(tmp_path / "build", [source], text)
    assert build.ok, build.reason
    entry = CorpusEntry(key="toy", source_id="toy/umat.f", original_source=source,
                        ntens=6, nstatv=1, props=[1000.0])
    increments = [(np.full(6, 1e-3), np.eye(3), np.eye(3), np.eye(3), 0.1, 20.0, 0.0)
                  for _ in range(3)]
    return static_scan_override_check(entry, build, tmp_path / "work", increments, [0.0],
                                      override)


TEMP = {"flag": "reads_temp", "variants": [{"temp": 0.0}, {"temp": 500.0}]}
COORDS = {"flag": "reads_coords_or_noel",
          "variants": [{"coords": [0, 0, 0.5]}, {"coords": [0, 0, 200.5]}]}


def test_a_temp_that_is_only_declared_passes(tmp_path):
    assert _check(tmp_path, HEADER + "      E = PROPS(1)\n" + BODY, TEMP)["passed"]


def test_a_temp_that_is_used_rejects_the_override(tmp_path):
    check = _check(tmp_path, HEADER + "      E = PROPS(1)*(1.D0 - 1.D-4*TEMP)\n" + BODY, TEMP)
    assert not check["passed"] and "STRESS" in check["reason"]


def test_a_coordinate_switch_over_identical_blocks_passes_and_a_real_one_fails(tmp_path):
    same = HEADER + "      K = 1\n      IF (COORDS(3) .GT. 100.D0) K = 1\n      E = PROPS(K)\n"
    assert _check(tmp_path / "a", same + BODY, COORDS)["passed"]
    real = HEADER + "      E = PROPS(1)\n      IF (COORDS(3) .GT. 100.D0) E = 2*PROPS(1)\n"
    assert not _check(tmp_path / "b", real + BODY, COORDS)["passed"]
