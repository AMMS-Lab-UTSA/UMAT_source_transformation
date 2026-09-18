"""A compact contract can name where the helpers its UMAT calls are published.

UMAT_PCO.for calls KCLEAR, KMMULT, KSMULT, ... and defines none of them; its
family (the EAFIT ICP UMATs, MIT-licensed upstream at jgomezc1/ABAQUS-US) defines
them in sibling files. The committed benchmark contract used to fail the
transform for that reason. It now declares ``"dependency_roots"`` and the
transformation service resolves the routine closure, writes it entry file first
(so every line anchor still points at the same statement) and transforms that
one file; the paired validation reads the same resolved file for the original.
"""
from __future__ import annotations

import json
import shutil
import warnings
from pathlib import Path

import pytest

from umat_oti.services.transformation import (
    TransformationOptions, _payload_with_resolved_closure, run_transformation,
)

REPO = Path(__file__).resolve().parents[1]
pytestmark = [pytest.mark.regression]

ENTRY = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),DSTRAN(NTENS),DDSDDE(NTENS,NTENS),PROPS(NPROPS)
      CALL KSCALE(DDSDDE,NTENS,PROPS(1))
      RETURN
      END
"""
HELPER = """\
      SUBROUTINE KSCALE(A,N,S)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION A(N,N)
      DO I=1,N
        A(I,I)=S
      END DO
      RETURN
      END
"""


def _contract(tmp_path: Path, roots) -> Path:
    (tmp_path / "entry").mkdir()
    (tmp_path / "helpers").mkdir()
    (tmp_path / "entry" / "umat_entry.for").write_text(ENTRY)
    (tmp_path / "helpers" / "library.for").write_text(HELPER)
    path = tmp_path / "contract.json"
    payload = {"name": "entry", "source": "entry/umat_entry.for", "ntens": 6, "order": 1,
               "jacobian": {"seed": "DSTRAN", "output": "STRESS", "target": "DDSDDE"}}
    if roots is not None:
        payload["dependency_roots"] = roots
    path.write_text(json.dumps(payload))
    return path


def test_a_contract_without_roots_is_read_unchanged(tmp_path):
    path = _contract(tmp_path, None)
    payload, closure = _payload_with_resolved_closure(path, tmp_path / "out")
    assert closure is None
    assert payload == path.read_bytes()


def test_declared_roots_resolve_the_helper_entry_file_first(tmp_path):
    path = _contract(tmp_path, ["helpers"])
    payload, closure = _payload_with_resolved_closure(path, tmp_path / "out")
    resolved = Path(closure["resolved_source"])
    assert [d["routine"] for d in closure["external_definitions"]] == ["KSCALE"]
    text = resolved.read_text()
    assert text.startswith(ENTRY.rstrip("\n"))
    assert "SUBROUTINE KSCALE" in text
    assert json.loads(payload)["source"] == str(resolved)


def test_a_root_that_lacks_the_helper_is_an_error_not_a_guess(tmp_path):
    path = _contract(tmp_path, ["entry"])
    with pytest.raises(ValueError, match="KSCALE"):
        _payload_with_resolved_closure(path, tmp_path / "out")


@pytest.mark.fortran
def test_the_pco_benchmark_transforms_and_compiles_from_its_committed_contract(tmp_path):
    if not shutil.which("gfortran"):
        pytest.fail("gfortran is required for this regression")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        summary, code = run_transformation(REPO / "benchmarks" / "UMAT_PCO.json", tmp_path / "t",
                                           TransformationOptions(compile_generated=True))
    assert code == 0 and summary["transform_success"], summary.get("blockers")
    assert summary["compilation"]["status"] == "compiled"
    closure = summary["dependency_closure"]
    assert closure["multi_file"] is True
    helpers = {d["routine"] for d in closure["external_definitions"]}
    assert {"KCLEAR", "KMMULT", "KSMULT"} <= helpers
    assert summary["source"] == closure["resolved_source"]
