"""B20 INSTRUMENT RULE and WORDS (written before they were run, applied to all growth rows).

Where a growth source keeps its tensor in local variables and no STATEV slot is clock-driven, the
growth quantity is read from the end-state targets the tensor ramps towards (STATEV(k) assigned from
a local name a clock-driven quantity depends on) times the fraction of the author's clock the run
covered, against the same 1% criterion; sources with a clock-driven slot are read as before. And
`reached` is the END of the last increment, so a complete run is not called cut off.
"""
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from umat_oti.abaqus import experiment as ex

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

pytestmark = pytest.mark.unit

LOCAL_G = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
     2 PREDEF,DPRED,CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,
     3 DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),TIME(2),COORDS(3),PROPS(NPROPS)
      DIMENSION DFGRD1(3,3)
      TotalT=10.0
      Lambda2St1=2.0*COORDS(1)
      STATEV(7)=Lambda2St1
      STATEV(3)=COORDS(1)
      G11=1.0+(Lambda2St1-1.0)*(TIME(1)+DTIME)/TotalT
      STRESS(1)=PROPS(1)*G11
      RETURN
      END
"""

CLOCK_SLOT = LOCAL_G.replace("      STATEV(7)=Lambda2St1\n", "").replace(
    "      STRESS(1)=PROPS(1)*G11\n", "      STATEV(8)=G11\n      STRESS(1)=PROPS(1)*G11\n")


def _records(final_target: float, steps: int = 20, dt: float = 0.5):
    return [{"kind": "result", "time": i * dt,
             "STATEV": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, final_target, 0.0, 0.0]}
            for i in range(steps)]


def test_the_targets_are_the_state_slots_assigned_from_a_name_the_clock_quantity_depends_on():
    assert ex.growth_state_slots(LOCAL_G) == {}
    assert sorted(ex.growth_target_slots(LOCAL_G)) == [7]       # not 3: that is COORDS
    # a source that already has a clock-driven slot is read as before
    assert ex.growth_state_slots(CLOCK_SLOT) != {}
    assert ex.growth_target_slots(CLOCK_SLOT) == {}
    # no clock at all: nothing to read
    assert ex.growth_target_slots(LOCAL_G.replace("TIME(1)+DTIME", "1.0")) == {}


def test_a_target_that_grows_is_inferred_never_measured_and_the_gate_stays_null():
    targets = ex.growth_target_slots(LOCAL_G)
    grown = ex.growth_developed(_records(2.0), {}, total_time=10.0, targets=targets)
    # an inference is not a pass: met is None, whatever the targets say
    assert grown.met is None and grown.evidence == "inferred_not_measured"
    assert grown.reason.startswith("growth inferred from state targets, not measured")
    assert grown.magnitude == pytest.approx(1.0, rel=1e-9) and "would meet" in grown.reason
    # the same plan on a source whose target does not move the tensor is also only an inference
    flat = ex.growth_developed(_records(1.0), {}, total_time=10.0, targets=targets)
    assert flat.met is None and flat.evidence == "inferred_not_measured"
    assert "would not meet" in flat.reason
    # a measured finding says so
    slot = ex.growth_developed(_records(1.0), {7: "STATEV(7)=G"}, total_time=10.0)
    assert slot.evidence == "measured" and slot.met is False


def test_the_instrument_still_returns_never_measured_without_slots_or_when_the_targets_do_not_depend_on_the_clock():
    # no target slots and no clock slots
    nothing = ex.growth_developed(_records(2.0), {}, total_time=10.0, targets={})
    assert nothing.met is None and nothing.evidence == "measured"
    assert "never measured" in nothing.reason
    # targets that do not depend on the clock: the clock term is removed, so none are found
    still = LOCAL_G.replace("TIME(1)+DTIME", "1.0")
    assert ex.growth_target_slots(still) == {}
    # a STATEV assigned from a name the clock quantity does NOT depend on is not a target
    unrelated = LOCAL_G.replace("      STATEV(3)=COORDS(1)\n",
                                "      Other=3.0*COORDS(1)\n      STATEV(3)=Other\n")
    assert sorted(ex.growth_target_slots(unrelated)) == [7]


def test_an_inferred_row_cannot_be_counted_fully_verified():
    """The inferred finding is null, so the gate is null and the ladder cannot reach
    verified; and the registry refuses a fully_verified row marked inferred."""
    import build_corpus_registry as reg
    finding = ex.growth_developed(_records(2.0), {}, total_time=10.0,
                                  targets=ex.growth_target_slots(LOCAL_G))
    assert finding.met is None
    import verify_store_in_abaqus as vs
    base = dict(material_found=True, support_ok=True, original_completed=True,
                transformed_completed=True, primal_agrees=True, tangent_verified=True)
    # the gate value the verification records for this finding is None -> not verified
    assert vs.classify_stage(vs.StageEvidence(
        **base, mechanically_informative=None)) == "informativeness_not_established"
    # control: a MEASURED true still verifies
    assert vs.classify_stage(vs.StageEvidence(
        **base, mechanically_informative=True)) == "verified"
    record = reg.Record(source_id="o__r/u.for", repository="o/r")
    record.informativeness_evidence = "inferred_not_measured"
    assert record.terminal_state != "fully_verified"


def test_nothing_to_read_is_said_to_be_never_measured():
    finding = ex.growth_developed(_records(2.0), {}, total_time=10.0, targets={})
    assert finding.met is None and "never measured" in finding.reason


def test_a_complete_run_is_not_called_cut_off_and_a_short_one_is():
    slots = {8: "STATEV(8)=G11"}
    still = [{"kind": "result", "time": i * 0.06, "STATEV": [0.0] * 7 + [1.0, 0.0]}
             for i in range(20)]                     # 20 increments of 0.06 = 1.2
    complete = ex.growth_developed(still, slots, total_time=1.2)
    assert complete.met is False
    assert "cut off" not in complete.reason and "not a short run" in complete.reason
    cut = ex.growth_developed(still[:10], slots, total_time=1.2)
    assert "cut off" in cut.reason
