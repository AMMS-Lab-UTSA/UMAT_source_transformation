"""The Abaqus D-4 gate end to end on replayed Fortran toys (G10; Vera's G10
review: A2 refusal, A8 direction mismatch and parse failure, frozen states).
"""
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

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
     1 STRAN(NTENS),DSTRAN(NTENS),PROPS(NPROPS)
      E = PROPS(1)
      DO I = 1, NTENS
        DO J = 1, NTENS
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = E
"""
LINEAR = HEADER + """\
        STRESS(I) = STRESS(I) + E*DSTRAN(I)
      END DO
      STATEV(1) = STRESS(1)
      RETURN
      END
"""
#: the stress carried through a cancellation of 1e8: double cannot resolve
#: the difference, and a quad build is a different function of it
CANCELLED = HEADER + """\
        STRESS(I) = STRESS(I) + E*((DSTRAN(I) + 1.D8) - 1.D8)
      END DO
      STATEV(1) = STRESS(1)
      RETURN
      END
"""


@pytest.fixture()
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "tools"))
    sys.modules.pop("verify_store_in_abaqus", None)
    import verify_store_in_abaqus
    return verify_store_in_abaqus


def _histories(e=1000.0, n=6, step=1e-4):
    original, transformed = [], []
    stress = [0.0] * 6
    for inc in range(1, n + 1):
        entry = {"NTENS": 6, "NSTATV": 1, "NPROPS": 1, "NDI": 3, "NSHR": 3,
                 "STRESS0": list(stress), "STATEV0": [stress[0]],
                 "STRAN": [step * (inc - 1)] + [0.0] * 5, "DSTRAN": [step] + [0.0] * 5,
                 "PROPS": [e], "DTIME": [0.1], "TEMP": [0.0, 0.0], "TIME": [0.1 * (inc - 1)] * 2,
                 "element": 1, "point": 1, "step": 1, "increment": inc}
        stress = [stress[0] + e * step] + stress[1:]
        common = {"step": 1, "increment": inc, "element": 1, "point": 1,
                  "STRESS": list(stress), "STATEV": [stress[0]],
                  "DSTRAN": [step] + [0.0] * 5,
                  "DDSDDE": [e if i == j else 0.0 for i in range(6) for j in range(6)]}
        original.append(dict(common))
        transformed.append(dict(common, entry=entry))
    return original, transformed


def _run(tool, tmp_path, text, **kw):
    from umat_oti.abaqus.manifest import VerificationManifest
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "umat.f"
    source.write_text(text)
    manifest = VerificationManifest(name="TOY", source=source, element_type="C3D8",
                                    props=(1000.0,), nprops=1, nstatv=1)
    original, transformed = _histories()
    return tool.verify_tangent(manifest, source, transformed, tmp_path / "work",
                               transformed=source, form="fixed",
                               original_history=original, **kw)


def test_a_linear_toy_verifies_and_freezes_its_states(tool, tmp_path):
    out = _run(tool, tmp_path, LINEAR)
    assert out["verified"], out["reason"]
    states = out["chosen_states"]
    assert all({"step", "increment", "element", "point"} <= set(s) for s in states)
    again = _run(tool, tmp_path / "again", LINEAR, frozen_states=states[:2])
    assert again["state_selection"]["selected_from"] == "frozen"
    assert [s["increment"] for s in again["states"]] == [s["increment"] for s in states[:2]]


def test_a_quad_reference_that_is_a_different_function_is_refused(tool, tmp_path):
    out = _run(tool, tmp_path, CANCELLED)
    assert not out["verified"] and not out["failed"], out["reason"]
    notes = [s.get("quad_reference") for s in out["states"] if s.get("quad_reference")]
    assert notes and all(n["status"] == "refused" for n in notes)


def test_a_direction_mismatch_fails_and_an_unreadable_seed_map_is_unresolved(tool, tmp_path,
                                                                              monkeypatch):
    from umat_oti.abaqus import tangent_gate
    monkeypatch.setattr(tangent_gate, "direction_check", lambda *a, **k: {
        "applies": True, "all_match": False, "mismatched": [4]})
    out = _run(tool, tmp_path / "a", LINEAR)
    assert out["failed"] and not out["verified"] and "[4]" in out["reason"]

    def broken(*a, **k):
        raise ValueError("cannot parse")
    monkeypatch.setattr(tangent_gate, "direction_check", broken)
    out = _run(tool, tmp_path / "b", LINEAR)
    assert not out["verified"] and not out.get("failed") and "unresolved" in out["reason"]


def test_a_frozen_state_not_found_stays_in_the_denominator(tool, tmp_path):
    """Two frozen states found and judged, two not found: 2 of 4 is 50%, and
    the not-found ones count (A5). With three not found, 2 of 5 is under."""
    states = _run(tool, tmp_path / "base", LINEAR)["chosen_states"]
    gone = [dict(states[0], increment=99 + k) for k in range(3)]
    ok = _run(tool, tmp_path / "a", LINEAR, frozen_states=states[:2] + gone[:2])
    assert ok["states_chosen"] == 4 and ok["verified"], ok["reason"]
    short = _run(tool, tmp_path / "b", LINEAR, frozen_states=states[:2] + gone)
    assert short["states_chosen"] == 5 and not short["verified"]
    assert "2 of 5" in short["reason"]
