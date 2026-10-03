"""The blind hold-out of a council template (D-19a rev 2 R6.3, package A-2; tier ``holdout``).

Vera picks >= 5 verified author-deck sources blind; tools/corpus_holdout.py
takes her list (it never picks). Their author-deck constants become
harvest-format rows with origin holdout_from_author_deck, go through
plan_council (on a deckless copy of the repository, so the source takes the
council route) and the council deck, and through the same gates as the author
deck. Pinned here:

* a selection that is not Vera's, not blind, or empty is not run; 1-4 sources
  give a falsification-only report (a disagreement withdraws, agreement
  accepts nothing);
* the author side is the CURRENT pass's records, and a selected key that moved
  with the transform fingerprint is followed through the source it names;
* TEMP / COORDS reads follow the reviewed standard of a council row (accepted
  overrides included); an unreviewed name-scan hit leaves the run incomplete;
* a source that is not a verified author-deck source is not run;
* the hold-out rows carry the author deck's constants and an origin the harvest
  schema rejects (a hold-out row can never be merged into the harvest), and
  re-derive bit for bit otherwise;
* the plans route as no_deck_in_repository although the repository has a deck,
  and land in the hold-out folder only;
* every verdict agreeing holds the template for review; ONE injected verdict
  flip withdraws it, through the command line as well;
* (gfortran) the routine-level gate runs both sides of one toy source and agrees.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKSPACE_REAL = REPO.parent
sys.path.insert(0, str(REPO / "tools"))
spec = importlib.util.spec_from_file_location("corpus_holdout", REPO / "tools" / "corpus_holdout.py")
ho = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ho)

SOURCE = """\
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
        DDSDDE(I,I) = E*(1.D0 + PROPS(2))
        STRESS(I) = STRESS(I) + DDSDDE(I,I)*DSTRAN(I)
      END DO
      STATEV(1) = 0.D0
      RETURN
      END
"""

KEYS = [f"{i:x}" * 24 for i in range(1, 7)]
DECK = """*HEADING
author deck
*MATERIAL, NAME=MAT
*USER MATERIAL, CONSTANTS=2
1000.0, 0.2
*DEPVAR
1
"""


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from umat_oti.corpus_features import harness as H
    cache = tmp_path / "cache"
    records, verification = [], []
    for n, key in enumerate(KEYS):
        source_id = f"o{n}__r/src/umat.f"
        (cache / source_id).parent.mkdir(parents=True)
        (cache / source_id).write_text(SOURCE)
        (cache / f"o{n}__r" / "run.inp").write_text(DECK)
        records.append({"key": key, "source_id": source_id, "cache_path": source_id,
                        "repository": f"o{n}/r", "commit": "0" * 40,
                        "terminal_state": "missing_material_data" if n == 5
                        else "fully_verified",
                        "kinematics": "small", "time_dependent": False,
                        "activation_amplitude": None})
        verification.append({"key": key, "manifest": {
            "props": [1000.0 + n, 0.2], "nprops": 2, "nstatv": 1, "ntens": 6, "ndi": 3,
            "nshr": 3, "element_type": "C3D8", "kinematics": "small strain", "name": "MAT",
            "material_provenance": f"o{n}__r/run.inp *USER MATERIAL MAT"}})
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"records": records}))
    pass_file = tmp_path / "store_verification.jsonl"
    pass_file.write_text("".join(json.dumps(v) + "\n" for v in verification))
    (tmp_path / "live_plans").mkdir()
    for name, value in (("REGISTRY", registry), ("PASS16", pass_file), ("CACHE", cache),
                        ("COUNCIL_PLANS", tmp_path / "live_plans"),
                        ("STORE", tmp_path / "no_store"), ("FAMILIES", tmp_path / "no.json")):
        monkeypatch.setattr(H, name, value)
    monkeypatch.setattr(ho, "CURRENT_RECORDS", pass_file)
    monkeypatch.setattr(ho, "REVIEWED_SCANS", ())
    return tmp_path


def selection(path: Path, keys=KEYS[:5], **over) -> Path:
    payload = {"template": "strain-driven", "selected_by": "vera", "blind": True,
               "date": "2026-10-03", "keys": list(keys), **over}
    path.write_text(json.dumps(payload))
    return path


def test_only_a_blind_selection_by_vera_is_run_and_under_five_is_falsification_only(tmp_path):
    full = ho.load_selection(selection(tmp_path / "s.json"), "strain-driven")
    assert full["keys"] == KEYS[:5] and full["mode"] == ho.HOLDOUT
    for n in (1, 4):
        small = ho.load_selection(selection(tmp_path / "s.json", keys=KEYS[:n]), "strain-driven")
        assert small["mode"] == ho.FALSIFICATION_ONLY
    for over in ({"keys": []}, {"selected_by": "atlas"}, {"blind": False},
                 {"keys": KEYS[:4] + KEYS[:1]}, {"template": "growth"}):
        with pytest.raises(ho.SelectionError):
            ho.load_selection(selection(tmp_path / "s.json", **over), "strain-driven")


def test_a_source_that_is_not_verified_with_its_author_deck_is_not_run(env):
    with pytest.raises(ho.SelectionError, match="not a verified"):
        ho.prepare(KEYS[1:], env / "out")


def test_the_hold_out_rows_and_plans(env):
    from umat_oti.abaqus import deck_pairing
    # in the source's own repository the author deck pairs ...
    assert deck_pairing.pair(env / "cache" / "o0__r/src/umat.f", env / "cache" / "o0__r").found
    prepared = ho.prepare(KEYS[:5], env / "out")
    assert prepared["regenerates"], prepared["printed"]
    rows = [json.loads(l) for l in prepared["rows_file"].read_text().splitlines()]
    assert [r["key"] for r in rows] == KEYS[:5]
    rederive = importlib.util.spec_from_file_location(
        "rederive_harvest_t", WORKSPACE_REAL / "corpus_campaign/material_data/rederive_harvest.py")
    module = importlib.util.module_from_spec(rederive)
    rederive.loader.exec_module(module)
    import jsonschema
    validator = jsonschema.Draft202012Validator(json.loads(
        (WORKSPACE_REAL / "corpus_campaign/material_data/harvest_row.schema.json").read_text()))
    for n, row in enumerate(rows):
        assert row["material_data_origin"] == "holdout_from_author_deck"
        assert [c["value"] for c in row["constants"]] == [1000.0 + n, 0.2]
        problems, eligible = module.check_row(row, validator)
        assert eligible and problems and all("material_data_origin" in p for p in problems)
        plan = json.loads((prepared["plans"] / row["key"] / "council_plan.json").read_text())
        # ... in the deckless copy it cannot, so the source takes the council route
        assert plan["route"] == "no_deck_in_repository" and not plan["refusal"], plan["refusal"]
        manifest = plan["sets"][0]["plan"]["experiment"]["manifest"]
        assert manifest["props"] == [1000.0 + n, 0.2]
    assert not list((env / "out" / "cache").rglob("*.inp"))
    assert not any((env / "live_plans").iterdir())


def _gate(flip: str = ""):
    def gate(key, plans):
        base = key.partition("#")[0]
        if plans is not None and base == flip:
            return {"verdict": "not_verified"}
        return {"verdict": "verified"}
    return gate


def test_one_injected_verdict_flip_withdraws_the_template(env):
    prepared = ho.prepare(KEYS[:5], env / "out")
    held = ho.judge("strain-driven", KEYS[:5], prepared["plans"], _gate())
    assert held["status"] == "held_for_vera_review" and held["disagreements"] == []
    flipped = ho.judge("strain-driven", KEYS[:5], prepared["plans"], _gate(flip=KEYS[2]))
    assert flipped["status"] == "withdrawn" and flipped["disagreements"] == [KEYS[2]]
    assert [s["agree"] for s in flipped["sources"]] == [True, True, False, True, True]


def test_a_refused_council_plan_is_a_disagreement(env):
    prepared = ho.prepare(KEYS[:5], env / "out")
    path = prepared["plans"] / KEYS[0] / "council_plan.json"
    plan = json.loads(path.read_text())
    path.write_text(json.dumps(dict(plan, refusal="x", refusal_code="needs_nstatv")))
    report = ho.judge("strain-driven", KEYS[:5], prepared["plans"], _gate())
    assert report["status"] == "withdrawn" and report["disagreements"] == [KEYS[0]]


def test_the_command_reports_a_flip_as_withdrawn(env):
    verdicts = env / "verdicts.jsonl"
    lines = [{"key": k, "side": "author", "verdict": "verified"} for k in KEYS[:5]]
    lines += [{"key": k, "side": "council", "set_id": "author",
               "verdict": "failed" if k == KEYS[4] else "verified"} for k in KEYS[:5]]
    verdicts.write_text("".join(json.dumps(l) + "\n" for l in lines))
    out = env / "run"
    rc = ho.main(["--template", "strain-driven", "--selection",
                  str(selection(env / "vera.json")), "--out", str(out),
                  "--gates", str(verdicts)])
    report = json.loads((out / "holdout_report.json").read_text())
    assert rc == 1 and report["status"] == "withdrawn" and report["disagreements"] == [KEYS[4]]
    assert report["tier"] == "holdout" and report["selection"]["selected_by"] == "vera"
    # a verdict nobody produced is not an agreement
    verdicts.write_text("".join(json.dumps(l) + "\n" for l in lines[:5]))
    assert ho.main(["--template", "strain-driven", "--selection", str(env / "vera.json"),
                    "--out", str(env / "run2"), "--gates", str(verdicts)]) == 2


@pytest.mark.fortran
@pytest.mark.slow
def test_the_routine_gate_runs_both_sides_of_a_toy_and_they_agree(env):
    if shutil.which("gfortran") is None:
        pytest.fail("gfortran is required (a missing compiler is a failure, not a skip)")
    prepared = ho.prepare(KEYS[:5], env / "out")
    report = ho.judge("strain-driven", KEYS[:1], prepared["plans"],
                      ho.routine_gate(env / "work"))
    source = report["sources"][0]
    assert source["author"]["verdict"] == "verified", source
    assert source["council"]["verdict"] == "verified", source
    assert report["status"] == "held_for_vera_review"


# ---------------------------------------------------------------------------
# Vera's review before the first hold-out run (2026-10-03)
# ---------------------------------------------------------------------------
def test_the_author_side_is_the_current_pass_not_pass16(env, monkeypatch):
    from umat_oti.corpus_features import harness as H
    stale = env / "pass16.jsonl"
    stale.write_text(json.dumps({"key": KEYS[0], "manifest": {"props": [1.0, 2.0]}}) + "\n")
    monkeypatch.setattr(H, "PASS16", stale)
    _record, manifest = ho.author_side(KEYS[0])
    assert manifest["props"] == [1000.0, 0.2]          # CURRENT_RECORDS, not H.PASS16
    _record, manifest = ho.author_side(KEYS[0], verification_records=stale)
    assert manifest["props"] == [1.0, 2.0]             # an explicit pass wins
    with pytest.raises(ho.SelectionError, match="no verification records"):
        ho.author_side(KEYS[0], verification_records=env / "missing.jsonl")
    assert ho.CURRENT_RECORDS.name == "store_verification.jsonl"
    monkeypatch.undo()
    assert "pass21" in str(ho.CURRENT_RECORDS)


def test_a_selected_key_that_moved_is_followed_through_its_source(env):
    old = "f" * 24
    chosen = [{"key": old, "source_id": "o1__r/src/umat.f"}, {"key": KEYS[2],
                                                              "source_id": "o2__r/src/umat.f"}]
    picked = ho.load_selection(selection(env / "s.json", keys=[old, KEYS[2]], chosen=chosen),
                               "strain-driven")
    assert ho.current_keys(picked) == [(old, KEYS[1], "o1__r/src/umat.f"),
                                       (KEYS[2], KEYS[2], "o2__r/src/umat.f")]
    lost = ho.load_selection(selection(env / "s.json", keys=["e" * 24]), "strain-driven")
    with pytest.raises(ho.SelectionError, match="not in the current registry"):
        ho.current_keys(lost)


READS = SOURCE.replace("      STATEV(1) = 0.D0\n",
                       "      STATEV(1) = 0.D0\n      WRITE(6,*) NOEL, TEMP\n")


def _reads_source(env):
    for n in range(5):
        (env / "cache" / f"o{n}__r/src/umat.f").write_text(READS)


def test_an_unreviewed_name_scan_hit_leaves_the_run_incomplete(env):
    _reads_source(env)
    with pytest.raises(ho.SelectionError, match="needs a reviewed static scan for reads_temp, "
                                                "reads_coords_or_noel"):
        ho.prepare(KEYS[:5], env / "out")


def test_the_reviewed_scan_decides_reads_as_for_a_council_row(env):
    _reads_source(env)
    review = env / "reviewed.jsonl"
    rows = [{"source_id": f"o{n}__r/src/umat.f", "reads_temp": False,
             "reads_coords_or_noel": False, "coords_note": "NOEL only in a WRITE"}
            for n in range(5)]
    review.write_text("".join(json.dumps(r) + "\n" for r in rows))
    prepared = ho.prepare(KEYS[:5], env / "out", reviewed_scans=[review])
    assert prepared["regenerates"], prepared["printed"]
    for row in map(json.loads, prepared["rows_file"].read_text().splitlines()):
        assert row["reads_temp"] is False and row["reads_coords_or_noel"] is False
        assert "reviewed static scan (reviewed.jsonl)" in row["notes"]
        plan = json.loads((prepared["plans"] / row["key"] / "council_plan.json").read_text())
        assert not plan["refusal"], plan["refusal"]
    # a reviewed TEMP read is refused exactly as a council row's is
    rows[0]["reads_temp"] = True
    review.write_text("".join(json.dumps(r) + "\n" for r in rows))
    prepared = ho.prepare(KEYS[:5], env / "out2", reviewed_scans=[review])
    plan = json.loads((prepared["plans"] / KEYS[0] / "council_plan.json").read_text())
    assert plan["refusal_code"] == "needs_documented_temperature"


def test_an_accepted_override_reaches_the_hold_out_plan(env):
    _reads_source(env)
    review = env / "reviewed.jsonl"
    rows = [{"source_id": f"o{n}__r/src/umat.f", "reads_temp": True,
             "reads_coords_or_noel": False,
             "static_scan_overrides": [{"flag": "reads_temp", "proposed": False,
                                        "status": "accepted by Vera (D-21a e)",
                                        "static_evidence": "TEMP only in a WRITE"}]}
            for n in range(5)]
    review.write_text("".join(json.dumps(r) + "\n" for r in rows))
    prepared = ho.prepare(KEYS[:5], env / "out", reviewed_scans=[review])
    plan = json.loads((prepared["plans"] / KEYS[0] / "council_plan.json").read_text())
    assert not plan["refusal"], plan["refusal"]
    assert plan["static_scan_overrides"][0]["flag"] == "reads_temp"


def test_under_five_sources_a_disagreement_withdraws_and_agreement_accepts_nothing(env):
    prepared = ho.prepare(KEYS[:3], env / "out")
    quiet = ho.judge("strain-driven", KEYS[:3], prepared["plans"], _gate(),
                     ho.FALSIFICATION_ONLY)
    assert quiet["status"] == "not_withdrawn_falsification_only"
    assert quiet["mode"] == ho.FALSIFICATION_ONLY and "does not accept" in quiet["rule"]
    flipped = ho.judge("strain-driven", KEYS[:3], prepared["plans"], _gate(flip=KEYS[1]),
                       ho.FALSIFICATION_ONLY)
    assert flipped["status"] == "withdrawn" and flipped["disagreements"] == [KEYS[1]]
    verdicts = env / "verdicts.jsonl"
    lines = [{"key": k, "side": side, "set_id": "author" if side == "council" else "",
              "verdict": "verified"} for k in KEYS[:3] for side in ("author", "council")]
    verdicts.write_text("".join(json.dumps(l) + "\n" for l in lines))
    rc = ho.main(["--template", "strain-driven", "--selection",
                  str(selection(env / "vera3.json", keys=KEYS[:3])), "--out", str(env / "r"),
                  "--gates", str(verdicts)])
    report = json.loads((env / "r" / "holdout_report.json").read_text())
    assert rc == 3 and report["status"] == "not_withdrawn_falsification_only"
