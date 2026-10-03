"""Council cases (D-19a rev 2, package A-1): freeze and check a council-designed experiment.

A council source has no usable author deck; the experiment is the council's
(tools/make_council_deck.py). One case is frozen per parameter set
(``--key <key>#<set>``) and stores, besides what every case stores,
council_plan.json, every council_<set>.inp, the rows files and the row of the
key read from them, and the re-derivation output of the harvest row. Pinned here:

* (gfortran) a council fixture -- a toy source, its harvest row, its plan,
  a registry row carrying the S2 fields -- freezes, and the frozen case passes
  its check, R and P, with ``make_council_deck --check`` over the frozen rows;
* a harvest row edited after the freeze (in the live rows, or in the frozen
  rows with every digest refreshed) fails the check;
* a council .inp edited in the case fails it, also with its digest refreshed;
* an origin, ref or fingerprint that differs from the registry row fails it;
* a licence-restricted source (D-2 not_permitted, D-1 abuganza, a D-21a
  licence hold) gets no case at all;
* the council SOURCE verdict needs every set: a failed or missing set fails it;
* the index anchors (digests) of the committed author-deck cases are unchanged.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKSPACE_REAL = REPO.parent
spec = importlib.util.spec_from_file_location("corpus_cases", REPO / "tools" / "corpus_cases.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

KEY = "0123456789abcdef01234567"
SOURCE_ID = "o__r/src/umat.f"
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


def harvest_row(e="1000.0") -> dict:
    def const(index, name, token, unit):
        return {"index": index, "name": name, "raw": {"tokens": {"x": token}, "unit": unit},
                "value": float(token), "unit": unit, "rule": "literal", "confidence": "exact",
                "never_count_reason": None, "where": "https://example.invalid/o/r/README.md",
                "line_or_page": 3, "quote": f"{name} = {token}"}
    return {"schema_version": 1, "source_id": SOURCE_ID, "key": KEY, "family": "elasticity",
            "duplicate_of": None, "repository": "o/r", "commit": "0" * 40,
            "status": "COMPLETE", "eligible": True,
            "material_data_origin": "author_published_outside_deck",
            "unit_system": {"value": "MPa", "stated": True, "where": None,
                            "line_or_page": None, "quote": None},
            "constants": [const(1, "E", e, "MPa"), const(2, "nu", "0.2", "-")],
            "missing": [], "nstatv": {"value": 1, "rule": "stated", "where": None,
                                      "line_or_page": None, "quote": None},
            "initial_statev": None, "formulation_statement": "NTENS=6 only",
            "documented_domain": {k: None for k in ("strain_max", "stretch_max", "temperature",
                                                     "rate_or_period", "total_time", "geometry")},
            "documented_domain_present": False, "reads_coords_or_noel": False,
            "reads_temp": False, "reads_no_props": False, "mapping": None, "notes": None}


def build_workspace(root: Path, mp: pytest.MonkeyPatch) -> dict:
    """A self-contained workspace: cache, rows, plans, registry, manifest, CAS."""
    from umat_oti.corpus_features import harness as H
    ws = root / "ws"
    (ws / "discovery_cache" / "o__r" / "src").mkdir(parents=True)
    (ws / "discovery_cache" / SOURCE_ID).write_text(SOURCE)
    data = ws / "corpus_campaign" / "material_data"
    data.mkdir(parents=True)
    for name in ("rederive_harvest.py", "harvest_row.schema.json"):
        shutil.copyfile(WORKSPACE_REAL / "corpus_campaign" / "material_data" / name, data / name)
    rows = data / "d19_harvest.jsonl"
    rows.write_text(json.dumps(harvest_row()) + "\n")
    plans = ws / "corpus_campaign" / "council_plans"
    rc, printed = cc.run_make_council_deck(["--rows", rows, "--out", plans,
                                            "--cache", ws / "discovery_cache"])
    assert rc == 0, printed
    plan = json.loads((plans / KEY / "council_plan.json").read_text())
    assert not plan["refusal"], plan["refusal"]
    set_id = plan["sets"][0]["set_id"]
    # as build_corpus_registry (S2) writes them: experiment_origin author|council,
    # refs named from the registry's repository, sets ;-joined
    refs = {"material_data_ref": f"../corpus_campaign/material_data/{rows.name}#key={KEY}",
            "council_deck_ref": f"../corpus_campaign/council_plans/{KEY}/council_plan.json"}
    record = {"key": KEY, "source_id": SOURCE_ID, "cache_path": SOURCE_ID,
              "repository": "o/r", "commit": "0" * 40, "acquisition_url": None,
              "kinematics": "small", "time_dependent": False, "activation_amplitude": None,
              "terminal_state": "missing_material_data",
              "material_data_origin": plan["material_data_origin"],
              "experiment_origin": "council",
              "council_sets": ";".join(s["set_id"] for s in plan["sets"]),
              "council_fingerprint": plan["council_fingerprint"], **refs}
    registry = root / "registry.json"
    registry.write_text(json.dumps({"records": [record]}))
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"rows": [{"source_id": SOURCE_ID, "license": {
        "redistribution": "permitted", "licence_file": "LICENSE", "spdx": "MIT",
        "scope": "repository"}}]}))
    for name, value in (("CASES", root / "cases"), ("ASSETS", root / "assets"),
                        ("WORKSPACE", ws), ("DISCOVERY_CACHE", ws / "discovery_cache"),
                        ("MANIFEST", manifest)):
        mp.setattr(cc, name, value)
    for name, value in (("REGISTRY", registry), ("COUNCIL_PLANS", plans),
                        ("CACHE", ws / "discovery_cache"), ("PASS16", root / "no_pass.jsonl"),
                        ("STORE", root / "no_store"), ("FAMILIES", root / "no_families.json")):
        mp.setattr(H, name, value)
    return {"ws": ws, "rows": rows, "plans": plans, "plan": plan, "set_id": set_id,
            "registry": registry, "record": record, "manifest": manifest}


# ---------------------------------------------------------------------------
# no compiler
# ---------------------------------------------------------------------------

def test_a_licence_restricted_source_gets_no_council_case():
    permitted = {"redistribution": "permitted"}
    assert cc.council_restriction(permitted, SOURCE_ID, [harvest_row()]) == ""
    assert "D-2" in cc.council_restriction({"redistribution": "not_permitted"}, SOURCE_ID, [])
    assert "D-1" in cc.council_restriction(
        permitted, "abuganza__BayesianCalibrationSkinGrowth/GOH_Example.f", [])
    held = dict(harvest_row(), licence_hold="D-21a Licence: all rights reserved")
    assert "D-21a" in cc.council_restriction(permitted, SOURCE_ID, [held])


def test_a_restricted_council_source_is_not_frozen(tmp_path):
    with pytest.MonkeyPatch.context() as mp:
        env = build_workspace(tmp_path, mp)
        held = dict(harvest_row(), licence_hold="D-21a Licence: all rights reserved")
        env["rows"].write_text(json.dumps(held) + "\n")
        rc = cc.main(["freeze", "--key", f"{KEY}#{env['set_id']}", "--council-rows",
                      str(env["rows"])])
        assert rc == 3
        assert not (tmp_path / "cases").exists() or not any((tmp_path / "cases").iterdir())


def test_the_source_verdict_needs_every_set():
    def case(set_id):
        return (None, {"case_id": f"c-{set_id}", "source": {"source_id": SOURCE_ID},
                       "council": {"registry_key": KEY, "council_set": set_id,
                                   "council_sets": ["A", "B"]}})
    both = [case("A"), case("B")]
    ok = [{"case_id": "c-A", "ok": True}, {"case_id": "c-B", "ok": True}]
    assert cc.council_source_verdicts(ok, both)[KEY]["verdict"] == "verified"
    one_fails = [{"case_id": "c-A", "ok": True}, {"case_id": "c-B", "ok": False}]
    verdict = cc.council_source_verdicts(one_fails, both)[KEY]
    assert verdict["verdict"] == "not_verified" and verdict["failed_sets"] == ["B"]
    assert verdict["counts_as_failure"]
    missing = cc.council_source_verdicts(ok[:1], both[:1])[KEY]
    assert missing["verdict"] == "incomplete" and missing["missing_sets"] == ["B"]
    assert missing["counts_as_failure"]
    assert not cc.council_source_verdicts(ok[:1], both[:1], complete_selection=False)[KEY][
        "counts_as_failure"]


def test_the_committed_author_deck_cases_keep_their_index_anchors():
    """Council support changes no committed case: every index row (digests of
    case.json and of the reference) is re-derived exactly as committed, and no
    committed case carries a council block."""
    index = json.loads((cc.CASES / "index.json").read_text())
    assert len(index["cases"]) >= 113
    assert cc.index_rows() == index["cases"]
    for case_json in cc.CASES.glob("*/case.json"):
        assert "council" not in json.loads(case_json.read_text())


# ---------------------------------------------------------------------------
# freeze and check (gfortran)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    if shutil.which("gfortran") is None:
        pytest.fail("gfortran is required (a missing compiler is a failure, not a skip)")
    root = tmp_path_factory.mktemp("council_case")
    mp = pytest.MonkeyPatch()
    try:
        env = build_workspace(root, mp)
        rc = cc.main(["freeze", "--key", f"{KEY}#{env['set_id']}", "--tier", "offline",
                      "--council-rows", str(env["rows"])])
        assert rc == 0
        case_dir = next((root / "cases").glob("*--council-*"))
        env.update(root=root, case_dir=case_dir,
                   case=json.loads((case_dir / "case.json").read_text()))
        yield env, mp
    finally:
        mp.undo()


def _scratch(env, tmp_path):
    """A scratch copy of the frozen case (the committed-style copy stays intact)."""
    case_dir = tmp_path / "cases" / env["case_dir"].name
    shutil.copytree(env["case_dir"], case_dir)
    return case_dir, json.loads((case_dir / "case.json").read_text())


@pytest.mark.fortran
@pytest.mark.slow
def test_a_council_case_freezes_and_passes_its_check(frozen, tmp_path):
    env, _mp = frozen
    case = env["case"]
    block = case["council"]
    assert block["registry_key"] == KEY and block["council_set"] == env["set_id"]
    assert block["material_data_origin"] == "author_published_outside_deck"
    assert block["experiment_origin"] == "council_deck"
    assert block["council_fingerprint"] == env["record"]["council_fingerprint"]
    assert block["material_data_ref"] == f"corpus_campaign/material_data/d19_harvest.jsonl#key={KEY}"
    assert block["council_deck_ref"] == f"corpus_campaign/council_plans/{KEY}/council_plan.json"
    assert "branch_coverage" in block
    stored = {f["path"] for f in block["files"]}
    assert {"council/plan/council_plan.json", f"council/plan/council_{env['set_id']}.inp",
            "council/rows_files/d19_harvest.jsonl", "council/rows/harvest_0.json",
            "council/rederive.json"} <= stored
    rederive = json.loads((env["case_dir"] / "council" / "rederive.json").read_text())
    assert rederive["rows"][0]["applies"] and rederive["rows"][0]["eligible"]
    assert rederive["rows"][0]["problems"] == []
    # the rows files (every row of the campaign) never go into the case
    assert not (env["case_dir"] / "council" / "rows_files").exists()
    index = json.loads((env["root"] / "cases" / "index.json").read_text())
    assert index["cases"][0]["council"]["council_set"] == env["set_id"]
    result = cc.check_case(env["case_dir"], case, ("regenerate", "replay"), tmp_path / "w",
                           current_rule=cc.rule_id())
    assert result["ok"], result["failures"][:3]
    verdicts = cc.council_source_verdicts([result], [(env["case_dir"], case)])
    assert verdicts[KEY]["verdict"] == "verified"


@pytest.mark.fortran
@pytest.mark.slow
def test_a_harvest_row_edited_in_the_live_rows_fails_the_check(frozen, tmp_path):
    env, _mp = frozen
    original = env["rows"].read_text()
    try:
        env["rows"].write_text(json.dumps(harvest_row(e="1001.0")) + "\n")
        out = cc.check_council(env["case_dir"], env["case"], tmp_path)
        assert "council_row_changed" in {f["kind"] for f in out}, out
    finally:
        env["rows"].write_text(original)
    assert cc.check_council(env["case_dir"], env["case"], tmp_path) == []


@pytest.mark.fortran
@pytest.mark.slow
def test_a_harvest_row_tampered_in_the_frozen_rows_fails_even_with_digests_refreshed(
        frozen, tmp_path):
    env, _mp = frozen
    case_dir, case = _scratch(env, tmp_path)
    tampered = tmp_path / "d19_harvest.jsonl"
    tampered.write_text(json.dumps(harvest_row(e="1001.0")) + "\n")
    item = next(f for f in case["council"]["files"]
                if f["path"] == "council/rows_files/d19_harvest.jsonl")
    out = cc.check_council(case_dir, dict(case, council=dict(
        case["council"], files=[dict(f, sha256="0" * 64) if f is item else f
                                for f in case["council"]["files"]])), tmp_path / "a")
    assert "council_assets" in {f["kind"] for f in out}, out
    # digests refreshed: the tampered rows file is in the CAS under its own sha
    item["sha256"] = cc.cas_put(tampered)
    item.pop("workspace_path")
    out = cc.check_council(case_dir, case, tmp_path / "b")
    assert "council_deck_differs" in {f["kind"] for f in out}, out


@pytest.mark.fortran
@pytest.mark.slow
def test_a_council_deck_tampered_in_the_case_fails_the_check(frozen, tmp_path):
    env, _mp = frozen
    case_dir, case = _scratch(env, tmp_path)
    rel = f"council/plan/council_{env['set_id']}.inp"
    deck = case_dir / rel
    deck.write_text(deck.read_text().replace("1000.", "1001.", 1))
    out = cc.check_council(case_dir, case, tmp_path / "a")
    assert "case_corrupted" in {f["kind"] for f in out}, out
    for item in case["council"]["files"]:
        if item["path"] == rel:
            item["sha256"] = cc.sha256_file(deck)
    out = cc.check_council(case_dir, case, tmp_path / "b")
    assert "council_deck_differs" in {f["kind"] for f in out}, out
    full = cc.check_case(case_dir, case, ("replay",), tmp_path / "c", current_rule=cc.rule_id())
    assert not full["ok"]


@pytest.mark.fortran
@pytest.mark.slow
def test_an_origin_ref_or_fingerprint_unlike_the_registry_row_fails(frozen):
    env, _mp = frozen
    plan = cc.frozen_council_plan(env["case_dir"], env["case"])
    assert cc.council_consistency_failures(env["case"], env["record"], plan) == []
    for field, value in (("material_data_origin", "council_chosen"),
                         ("experiment_origin", "author"),
                         ("material_data_ref", f"d21_council_constants.jsonl#key={KEY}"),
                         ("material_data_ref", "d19_harvest.jsonl#key=" + "f" * 24),
                         ("council_deck_ref", "council_plans/" + "f" * 24 + "/council_plan.json"),
                         ("council_fingerprint", "0" * 16),
                         ("council_sets", "author;B")):
        out = cc.council_consistency_failures(env["case"], dict(env["record"], **{field: value}),
                                              plan)
        assert [f["field"] for f in out] == [field], out
    lacking = {k: v for k, v in env["record"].items() if k != "council_fingerprint"}
    assert cc.council_consistency_failures(env["case"], lacking, plan)
    assert cc.council_consistency_failures(env["case"], None, plan)
    case = json.loads(json.dumps(env["case"]))
    case["council"]["branch_coverage"] = {"exercised": "NTENS=3"}
    assert "branch_coverage" in {f.get("field") for f in
                                 cc.council_consistency_failures(case, env["record"], plan)}
