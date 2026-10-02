"""Part (b) of the primal gate: the original's response under the transformed
build's Jacobian, against the transformed run. Fixtures are real Abaqus runs
(pass16 and corpus_campaign/batches/B2/curie_g cc_cug_11, 12, 17)."""
import gzip
import json
import shutil
from pathlib import Path

import pytest

from umat_oti.abaqus.compare import compare_calls, compare_primal, stiffness_scale
from umat_oti.abaqus.replay import (build_history_replay, jacobian_matched_source,
                                    run_history_replay)

FIXTURES = Path(__file__).parent / "fixtures" / "primal_gate"


def case(name):
    with gzip.open(FIXTURES / f"{name}.json.gz", "rt") as handle:
        return json.load(handle)


def fe_disagrees(original, transformed):
    return not compare_primal(original, transformed, tolerance=1e-10).agrees


def matched(reference, transformed):
    return compare_calls(reference, transformed,
                         stiffness=stiffness_scale(transformed), tolerance=1e-10)


def test_minsur1_disagrees_in_fe_and_agrees_once_the_jacobian_is_the_same():
    c = case("minsur1")
    assert fe_disagrees(c["original"], c["transformed"])
    result = matched(c["jacobian_matched"], c["transformed"])
    assert result.agrees, result.reason


def test_case4_a_40_percent_fe_difference_is_the_jacobian_plus_declared_precision():
    c = case("case4")
    assert fe_disagrees(c["original"], c["transformed"])
    # The original walked 208 records and the transformed 192: different
    # Newton paths. With the same Jacobian the solver walks the same 192.
    assert len(c["jacobian_matched_widened"]) == len(c["transformed"])
    result = matched(c["jacobian_matched_widened"], c["transformed"])
    assert result.agrees, result.reason


def test_puregravity_negative_control_the_jacobian_was_never_the_difference():
    c = case("puregravity")
    # Swapping in the transformed Jacobian changed nothing measurable ...
    unchanged = matched(c["jacobian_matched"], c["original"])
    assert unchanged.agrees, unchanged.reason
    # ... and the control agrees with the transformed run.
    result = compare_calls(c["jacobian_matched"], c["transformed"],
                           stiffness=stiffness_scale(c["transformed"]),
                           tolerance=1e-10, excluded={"STATEV": [7]})
    assert result.agrees, result.reason


ORIGINAL = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
        STRESS(I) = STRESS(I) + HELP(PROPS(1))*DSTRAN(I)
        DO J=1,NTENS
          DDSDDE(I,J) = %(jac)s
        END DO
      END DO
      STATEV(1) = STATEV(1) + %(state)s
      RETURN
      END
      FUNCTION HELP(X)
      INCLUDE 'ABA_PARAM.INC'
      HELP = %(help)s*X
      RETURN
      END
"""


@pytest.mark.skipif(shutil.which("gfortran") is None, reason="needs gfortran")
def test_the_control_takes_stress_and_state_from_the_original_and_ddsdde_from_the_transform(tmp_path):
    original = ORIGINAL % {"jac": "111.D0", "state": "1.D0", "help": "2.D0"}
    transformed = ORIGINAL % {"jac": "222.D0", "state": "5.D0", "help": "7.D0"}
    text, note = jacobian_matched_source(original, transformed, "fixed")
    assert note["renamed_in_transformed"] == ["HELP->HELP_T"]
    source = tmp_path / "jm.for"
    source.write_text(text)
    include = tmp_path / "inc"
    include.mkdir()
    for name in ("aba_param.inc", "ABA_PARAM.INC"):
        (include / name).write_text("      implicit real*8(a-h,o-z)\n")
    build = build_history_replay(source, tmp_path / "build", label="jm",
                                 compiler="gfortran",
                                 flags=("-O0", "-std=legacy", "-w"),
                                 include_dirs=[include])
    assert build.ok, build.log
    entry = {"NTENS": 6, "NSTATV": 1, "NPROPS": 1, "NDI": 3, "NSHR": 3,
             "DTIME": [1.0], "TIME": [0.0, 0.0], "STRESS0": [0.0] * 6,
             "STATEV0": [0.0], "STRAN": [0.0] * 6, "DSTRAN": [1e-3] * 6,
             "PROPS": [10.0], "COORDS": [0.0, 0.0, 0.0, 1.0]}
    replay = run_history_replay(build, [entry], tmp_path / "build")
    assert replay.ok, replay.reason
    call = replay.calls[0]
    assert call["STRESS"] == pytest.approx([2.0 * 10.0 * 1e-3] * 6)   # original's HELP
    assert call["STATEV"] == [1.0]                                     # original's state
    assert set(call["DDSDDE"]) == {222.0}                              # transformed's Jacobian
