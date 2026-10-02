"""A UMAT that calls Abaqus's ROTSIG transforms through a contract.

ROTSIG is linked in by the solver, so the author's file never defines it. The
transform supplies the documented body before the helper lifter looks for one
(source_transform: ``supply_reachable_definitions``); without that step the
lifter finds no body, the hypercomplex STRESS is handed to the real ROTSIG,
and the source is refused for a leak. The unit tests of the supplied text do
not notice the step being removed, so this one runs the whole contract.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.services.transformation import (  # noqa: E402
    TransformationOptions, run_transformation)

UMAT = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
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
      DIMENSION SOLD(6)
      E = PROPS(1)
      DO I = 1, NTENS
        STRESS(I) = STRESS(I) + E*DSTRAN(I)
      END DO
      CALL ROTSIG(STRESS, DROT, SOLD, 1, NDI, NSHR)
      DO I = 1, NTENS
        STRESS(I) = SOLD(I)
      END DO
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.0D0
        END DO
        DDSDDE(I,I) = E
      END DO
      RETURN
      END
"""

CONTRACT = {
    "name": "rotsig_caller", "source": "rotsig_caller.f", "ntens": 6, "order": 1,
    "jacobian": {"output": "STRESS", "seed": "DSTRAN", "target": "DDSDDE"},
    "promote": ["SOLD", "STRESS"],
    "constant": ["E", "PROPS", "DROT", "STRAN", "STATEV", "TIME", "DTIME", "TEMP",
                 "DTEMP", "PREDEF", "DPRED", "COORDS", "DFGRD0", "DFGRD1"],
    "real": ["CELENT", "CMNAME", "DDSDDE", "DDSDDT", "DRPLDE", "DRPLDT", "I", "J",
             "KINC", "KSPT", "KSTEP", "LAYER", "NDI", "NOEL", "NPROPS", "NPT",
             "NSHR", "NSTATV", "NTENS", "PNEWDT", "RPL", "SCD", "SPD", "SSE"],
}


def test_a_contract_whose_umat_calls_rotsig_transforms_with_a_lifted_rotsig(tmp_path):
    (tmp_path / "rotsig_caller.f").write_text(UMAT, encoding="utf-8")
    contract = tmp_path / "rotsig_caller.json"
    contract.write_text(json.dumps(CONTRACT), encoding="utf-8")
    out = tmp_path / "out"

    summary, code = run_transformation(contract, out, TransformationOptions(compile_generated=False))

    failed = [name for name, ok in summary.get("semantic_checks", {}).items() if not ok]
    assert code == 0 and summary.get("transform_success") is True, failed
    assert failed == []
    transformed = Path(summary["transformed_source"]).read_text(encoding="utf-8")
    assert "CALL ROTSIG_OTI(STRESS_OTI, DROT_OTI, SOLD_OTI" in transformed
    assert not re.search(r"CALL\s+ROTSIG\s*\(", transformed, re.IGNORECASE)
    helpers = (out / "umat_oti_helpers.f90").read_text(encoding="utf-8").lower()
    assert "subroutine rotsig_oti(" in helpers
