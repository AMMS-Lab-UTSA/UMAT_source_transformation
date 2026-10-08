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


def test_a_target_that_grows_is_developed_and_the_same_run_with_no_growth_is_not():
    targets = ex.growth_target_slots(LOCAL_G)
    grown = ex.growth_developed(_records(2.0), {}, total_time=10.0, targets=targets)
    assert grown.met is True and grown.magnitude == pytest.approx(1.0, rel=1e-9)
    assert "local variable" in grown.reason
    # canary: the same plan on a source whose target does not move the tensor
    flat = ex.growth_developed(_records(1.0), {}, total_time=10.0, targets=targets)
    assert flat.met is False and flat.magnitude == 0.0
    # and a run that covered a tenth of the clock sees a tenth of the target
    short = ex.growth_developed(_records(1.05, steps=2, dt=0.5), {}, total_time=10.0,
                                targets=targets)
    assert short.met is False


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
