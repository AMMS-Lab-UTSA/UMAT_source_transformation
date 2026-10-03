"""Initial-state proof for a council experiment (G6, D-19a rev 2 R5).

The ORIGINAL is driven twice, with the zero-started STATEV slots at 0 and at
a sentinel. Bit-identical STRESS, DDSDDE and written STATEV prove that
starting at zero is harmless (the routine initialises what it reads at
KINC=1); otherwise the source needs SDVINI or a documented initial_statev.
"""
import shutil

import numpy as np
import pytest

from umat_oti.corpus_features import drivers as dv
from umat_oti.corpus_features.harness import CorpusEntry, initial_state_proof

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
     1 STRAN(NTENS),DSTRAN(NTENS),PROPS(NPROPS),DFGRD1(3,3),
     2 TIME(2),COORDS(3),DROT(3,3),DFGRD0(3,3),PREDEF(1),DPRED(1),
     3 DDSDDT(NTENS),DRPLDE(NTENS)
"""

BODY = """\
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = PROPS(1)*(1.D0 + STATEV(1))
        STRESS(I) = STRESS(I) + DDSDDE(I,I)*DSTRAN(I)
      END DO
      STATEV(1) = STATEV(1) + DSTRAN(1)
      STATEV(2) = 5.D0
      RETURN
      END
"""

#: reads STATEV(1) before anything writes it
READS_FIRST = HEADER + BODY
#: initialises STATEV(1) on the first increment, then reads it; STATEV(3) is
#: never touched
INITIALISES = HEADER + "      IF (KINC .EQ. 1) STATEV(1) = 0.25D0\n" + BODY


def _proof(tmp_path, text):
    source = tmp_path / "umat.f"
    source.write_text(text)
    build = dv.build_real(tmp_path / "build", [source], text)
    assert build.ok, build.reason
    entry = CorpusEntry(key="toy", source_id="toy/umat.f", original_source=source,
                        ntens=6, nstatv=3, props=[1000.0])
    increments = [(np.full(6, 1e-3), np.eye(3), np.eye(3), np.eye(3), 0.1, 0.0, 0.0)
                  for _ in range(3)]
    return initial_state_proof(entry, build, tmp_path / "work", increments)


def test_a_routine_that_reads_state_before_writing_it_is_refused(tmp_path):
    proof = _proof(tmp_path, READS_FIRST)
    assert proof["status"] == "needs_initial_state", proof
    assert "increment 1" in proof["reason"]


def test_a_routine_that_initialises_at_kinc_1_is_proven(tmp_path):
    proof = _proof(tmp_path, INITIALISES)
    assert proof["status"] == "proven", proof
    assert proof["slots_started_at_zero"] == [1, 2, 3]
    assert proof["untouched_slots"] == [3]


def test_a_stress_that_reads_state_is_caught_even_when_the_slot_is_overwritten(tmp_path):
    text = READS_FIRST.replace("      STATEV(1) = STATEV(1) + DSTRAN(1)\n",
                               "      STATEV(1) = DSTRAN(1)\n")
    assert text != READS_FIRST
    proof = _proof(tmp_path, text)
    assert proof["status"] == "needs_initial_state", proof
    assert proof["reason"].startswith(("STRESS", "DDSDDE")), proof["reason"]
