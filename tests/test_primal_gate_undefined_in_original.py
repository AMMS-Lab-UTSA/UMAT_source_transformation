"""D-12 in the Abaqus path: outputs that differ between the zero- and
snan-initialised original are undefined_in_original, and nothing else is."""
import gzip
import json
import shutil
import sys
from pathlib import Path

import pytest

from umat_oti.abaqus.replay import FINIT_SNAN, FINIT_ZERO, undefined_outputs

FIXTURES = Path(__file__).parent / "fixtures" / "primal_gate"
REPO = Path(__file__).resolve().parents[1]


def test_the_init_pair_is_the_one_corpus_features_uses():
    from umat_oti.corpus_features import harness
    assert FINIT_SNAN == harness.FINIT_SNAN and FINIT_ZERO == harness.FINIT_ZERO


def test_puregravity_lambda1z2_makes_statev7_undefined_and_nothing_else():
    # Jeff97 PureGravity.for writes the never-assigned Lambda1z2 to STATEV(7).
    with gzip.open(FIXTURES / "puregravity.json.gz", "rt") as handle:
        c = json.load(handle)
    found = undefined_outputs(c["init_zero"], c["init_snan"], ntens=6)
    assert found["STATEV"] == [7]
    assert found["STRESS"] == [] and found["DDSDDE"] == []
    assert found["details"][0]["output"] == "STATEV(7)"


UMAT = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
      DO I=1,NTENS
        STRESS(I) = STRESS(I) + PROPS(1)*DSTRAN(I)
        DDSDDE(I,I) = PROPS(1)
      END DO
      STATEV(1) = STATEV(1) + 1.D0
      STATEV(2) = UNSET
      RETURN
      END
"""


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_an_uninitialised_variable_is_found_in_the_slot_it_reaches(tmp_path):
    sys.path.insert(0, str(REPO / "tools"))
    import verify_store_in_abaqus as V
    source = tmp_path / "original_probed.for"
    source.write_text(UMAT)
    include = tmp_path / "inc"
    include.mkdir()
    for name in ("aba_param.inc", "ABA_PARAM.INC"):
        (include / name).write_text("      implicit real*8(a-h,o-z)\n")
    entry = {"NTENS": 6, "NSTATV": 2, "NPROPS": 1, "NDI": 3, "NSHR": 3,
             "DTIME": [1.0], "TIME": [0.0, 0.0], "STRESS0": [0.0] * 6,
             "STATEV0": [0.0, 0.0], "STRAN": [0.0] * 6, "DSTRAN": [1e-3] * 6,
             "PROPS": [10.0], "COORDS": [0.0, 0.0, 0.0, 1.0]}
    check = V.init_variant_check(source, [entry, entry], tmp_path / "work",
                                 ntens=6, include_dirs=[include])
    assert check["established"], check
    assert check["undefined"]["STATEV"] == [2]
    assert check["undefined"]["STRESS"] == [] and check["undefined"]["DDSDDE"] == []
