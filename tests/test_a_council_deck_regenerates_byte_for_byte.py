"""tools/make_council_deck.py (G9, D-19a rev 2 R6.1).

--check regenerates every council plan and deck and compares them byte for
byte with what is on disk: it passes on fresh output and fails after a
one-byte change to the row, to a written file, or when a file is missing.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

SOURCE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 STRAN(NTENS),DSTRAN(NTENS),PROPS(NPROPS)
      E = PROPS(1)
      DO I = 1, 6
        DO J = 1, 6
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = E*(1.D0 + PROPS(2))
        STRESS(I) = STRESS(I) + DDSDDE(I,I)*DSTRAN(I)
      END DO
      STATEV(1) = 0.D0
      RETURN
      END
"""


def _row(e=210000.0):
    def one(set_id, value):
        return {"set_id": set_id, "constants": [
            {"index": 1, "name": "E", "value": value, "basis": "b", "confidence": "class-typical"},
            {"index": 2, "name": "nu", "value": 0.3, "basis": "b", "confidence": "class-typical"}]}
    return {"source_id": "o__r/src/umat.f", "harvest_key": "k1", "nstatv": 1,
            "experiment_origin": "council_deck", "reads_temp": False,
            "reads_coords_or_noel": False, "initial_statev": None,
            "formulation": {"statement": "3D", "element": "C3D8", "evidence": ["umat.f:9"],
                            "origin": "council_choice"},
            "sets": [one("A", e), one("B", 70000.0)]}


@pytest.fixture()
def tool(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "tools"))
    sys.modules.pop("make_council_deck", None)
    import make_council_deck
    return make_council_deck


def _setup(tmp_path, row):
    cache = tmp_path / "cache"
    (cache / "o__r" / "src").mkdir(parents=True)
    (cache / "o__r" / "src" / "umat.f").write_text(SOURCE)
    rows = tmp_path / "rows.jsonl"
    rows.write_text(json.dumps(row) + "\n")
    return cache, rows, tmp_path / "out"


def test_check_passes_on_fresh_output_and_fails_after_any_change(tool, tmp_path, capsys):
    cache, rows, out = _setup(tmp_path, _row())
    common = ["--rows", str(rows), "--out", str(out), "--cache", str(cache)]
    assert tool.main(common) == 0
    written = sorted(p.name for p in (out / "k1").iterdir())
    assert written == ["council_A.inp", "council_B.inp", "council_plan.json"]
    plan = json.loads((out / "k1" / "council_plan.json").read_text())
    assert plan["council_fingerprint"] and plan["row_sha256"] and plan["tool_sha256"]
    assert str(cache) not in (out / "k1" / "council_plan.json").read_text()
    assert tool.main(common + ["--check"]) == 0

    # a one-byte change to the row (210000.0 -> 210001.0)
    rows.write_text(json.dumps(_row(210001.0)) + "\n")
    assert tool.main(common + ["--check"]) == 1
    assert "k1/council_plan.json" in capsys.readouterr().out
    rows.write_text(json.dumps(_row()) + "\n")
    assert tool.main(common + ["--check"]) == 0

    # a one-byte change to a written deck, and a missing file
    deck = out / "k1" / "council_B.inp"
    deck.write_text(deck.read_text().replace("70000.", "70001.", 1))
    assert tool.main(common + ["--check"]) == 1
    deck.unlink()
    assert tool.main(common + ["--check"]) == 1


def test_an_eligible_harvest_row_wins_over_a_council_row(tool, tmp_path):
    cache, rows, out = _setup(tmp_path, _row())
    harvest = tmp_path / "harvest.jsonl"
    harvest.write_text(json.dumps({
        "key": "k1", "source_id": "o__r/src/umat.f", "eligible": True, "status": "COMPLETE",
        "nstatv": {"value": 1}, "reads_temp": False, "reads_coords_or_noel": False,
        "formulation_statement": "NTENS=6 only",
        "constants": [{"index": 1, "value": 1000.0, "confidence": "exact", "name": "E"},
                      {"index": 2, "value": 0.2, "confidence": "exact", "name": "nu"}]}) + "\n")
    for order in ([rows, harvest], [harvest, rows]):
        args = sum((["--rows", str(p)] for p in order), [])
        assert tool.main(args + ["--out", str(out), "--cache", str(cache)]) == 0
        plan = json.loads((out / "k1" / "council_plan.json").read_text())
        assert plan["material_data_origin"] == "author_published_outside_deck"
        assert [s["set_id"] for s in plan["sets"]] == ["author"]
        assert sorted(r.split(" ")[0] for r in plan["rows_read"]) == ["harvest.jsonl",
                                                                       "rows.jsonl"]
    # an INELIGIBLE harvest row loses to the D-21 row, in either order
    text = harvest.read_text().replace('"eligible": true', '"eligible": false')
    harvest.write_text(text)
    for order in ([rows, harvest], [harvest, rows]):
        args = sum((["--rows", str(p)] for p in order), [])
        assert tool.main(args + ["--out", str(out), "--cache", str(cache)]) == 0
        plan = json.loads((out / "k1" / "council_plan.json").read_text())
        assert plan["material_data_origin"] == "council_chosen"


def test_check_reports_an_orphan_folder(tool, tmp_path, capsys):
    cache, rows, out = _setup(tmp_path, _row())
    common = ["--rows", str(rows), "--out", str(out), "--cache", str(cache)]
    assert tool.main(common) == 0
    (out / "stale_key").mkdir()
    assert tool.main(common + ["--check"]) == 1
    assert "stale_key" in capsys.readouterr().out
