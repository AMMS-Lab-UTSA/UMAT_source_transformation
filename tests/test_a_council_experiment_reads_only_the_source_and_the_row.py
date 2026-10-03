"""plan_council (G3, D-19a rev 2 R2; D-21 sets).

For a source with no author deck the council designs the experiment: it
reads the SOURCE and the row (a harvest row, or a D-21 council row with >= 2
parameter sets, each its own experiment) and never an author's deck. Every
manifest value carries its origin; author-deck manifests do not serialise
an ``origins`` key, so they read as before. Corpus run over the 34 D-21 rows
and 30 eligible harvest rows: corpus_campaign/batches/B7/gauss_g3/.
"""
import json
import re
from pathlib import Path

import pytest

from umat_oti.abaqus.experiment import plan_council
from umat_oti.abaqus.manifest import VerificationManifest

pytestmark = pytest.mark.unit

HEADER = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),
     1 STRAN(NTENS),DSTRAN(NTENS),PROPS(NPROPS),DFGRD1(3,3),COORDS(3)
"""

ELASTIC = HEADER + """\
      E = PROPS(1)
      ENU = PROPS(2)
      DO I = 1, 6
        DO J = 1, 6
          DDSDDE(I,J) = 0.D0
        END DO
        DDSDDE(I,I) = E/(1.D0+ENU)
        STRESS(I) = STRESS(I) + DDSDDE(I,I)*DSTRAN(I)
      END DO
      STATEV(1) = STATEV(1) + DSTRAN(1)
      RETURN
      END
"""


def _set(set_id, e, nu):
    return {"set_id": set_id, "constants": [
        {"index": 1, "name": "E", "value": e, "basis": "handbook", "confidence": "class-typical"},
        {"index": 2, "name": "nu", "value": nu, "basis": "handbook", "confidence": "class-typical"}]}


def _row(**over):
    row = {"source_id": "owner__repo/src/umat.f", "harvest_key": "k1",
           "material_data_origin": "council_chosen", "experiment_origin": "council_deck",
           "nstatv": 1, "nstatv_basis": "STATEV(1) only", "initial_statev": None,
           "reads_temp": False, "reads_coords_or_noel": False,
           "formulation_3d_only": "hard-codes 6 components: NTENS=6",
           "sets": [_set("A", 210000.0, 0.3), _set("B", 70000.0, 0.33)]}
    row.update(over)
    return row


def _repo(tmp_path: Path, text: str = ELASTIC, decks: dict = None) -> Path:
    repo = tmp_path / "owner__repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "umat.f").write_text(text)
    for name, deck in (decks or {}).items():
        (repo / name).write_text(deck)
    return repo


def _plan(tmp_path, text=ELASTIC, **over):
    repo = _repo(tmp_path, text)
    return plan_council(repo / "src" / "umat.f", repo, _row(**over))


def test_two_sets_give_two_experiments_with_origins(tmp_path):
    cp = _plan(tmp_path)
    assert cp.found and cp.route == "no_deck_in_repository"
    assert [s for s, _p in cp.sets] == ["A", "B"]
    (_, a), (_, b) = cp.sets
    assert a.manifest.props == (210000.0, 0.3) and b.manifest.props == (70000.0, 0.33)
    origins = a.manifest.as_dict()["origins"]
    assert origins["props"]["origin"] == "council_choice"
    assert origins["kinematics"]["origin"] == "council_default"
    assert origins["initial_statev"]["origin"] == "council_default"
    assert cp.ceiling == 0.02 and cp.as_dict()["counts_only_if_every_set_passes"]


def test_no_serialised_council_plan_cites_an_authors_deck(tmp_path):
    d = _plan(tmp_path).as_dict()
    for entry in d["sets"]:
        entry["plan"]["experiment"]["manifest"].pop("material_provenance")
    text = json.dumps(d)
    assert not re.search(r"author's deck|paired deck|\.inp\b", text, re.I)


def test_an_author_deck_manifest_serialises_no_origins():
    m = VerificationManifest(name="x", source=Path("u.f"), props=(1.0,))
    assert "origins" not in m.as_dict()


@pytest.mark.parametrize("over, text, code", [
    ({"sets": [_set("A", 210000.0, 0.3)]}, ELASTIC, "insufficient_material_data"),
    ({"reads_temp": True}, ELASTIC, "needs_documented_temperature"),
    ({"reads_coords_or_noel": True}, ELASTIC, "needs_documented_geometry"),
    ({"reads_temp": None}, ELASTIC, "needs_static_scan"),
    ({"formulation_3d_only": None}, ELASTIC.replace("DO I = 1, 6", "DO I = 1, NTENS")
     .replace("DO J = 1, 6", "DO J = 1, NTENS"), "formulation_not_documented"),
    ({"nstatv": None}, ELASTIC.replace("STATEV(1) = STATEV(1) + DSTRAN(1)",
                                       "K = 1\n      STATEV(K) = DSTRAN(1)"), "needs_nstatv"),
    ({"experiment_origin": "author_deck_with_council_parameters"}, ELASTIC,
     "not_a_council_deck"),
])
def test_every_r2_refusal(tmp_path, over, text, code):
    cp = _plan(tmp_path, text, **over)
    assert not cp.found and cp.refusal_code == code, (cp.refusal_code, cp.refusal)


def test_a_body_force_is_not_a_council_choice(tmp_path):
    text = ELASTIC + """\
      SUBROUTINE DLOAD(F,KSTEP,KINC,TIME,NOEL,NPT,LAYER,KSPT,COORDS,JLTYP,SNAME)
      INCLUDE 'ABA_PARAM.INC'
      F = 9.81D0*TIME(2)
      RETURN
      END
"""
    cp = _plan(tmp_path, text)
    assert cp.refusal_code == "body_force", cp.refusal


def test_an_author_deck_that_pairs_wins(tmp_path):
    deck = """\
*Node
1, 0., 0., 0.
*Element, type=C3D8, elset=ALL
1, 1, 1, 1, 1, 1, 1, 1, 1
*Solid Section, elset=ALL, material=M
*Material, name=M
*Depvar
1,
*User Material, constants=2
200000., 0.3
"""
    repo = _repo(tmp_path, decks={"src/job.inp": deck})
    cp = plan_council(repo / "src" / "umat.f", repo, _row())
    assert cp.refusal_code == "pairing_changed"


def test_an_author_block_rejected_is_not_a_council_route(tmp_path):
    deck = """\
*Material, name=M
*Depvar
0,
*User Material, constants=2
200000., 0.3
"""
    repo = _repo(tmp_path, decks={"src/job.inp": deck})
    cp = plan_council(repo / "src" / "umat.f", repo, _row())
    assert cp.refusal_code == "not_a_council_route" and cp.route == "author_block_rejected"


def test_a_growth_law_without_a_documented_clock_is_held_back(tmp_path):
    text = HEADER + """\
      TAU = PROPS(1)
      G = 1.D0 + 0.1D0*TIME(2)
      STATEV(1) = G
      RETURN
      END
"""
    cp = _plan(tmp_path, text)
    assert cp.refusal_code == "growth_needs_total_time" and "clock" in cp.refusal


def test_a_harvest_row_is_one_author_published_set(tmp_path):
    row = {"source_id": "owner__repo/src/umat.f", "key": "h1", "eligible": True,
           "status": "COMPLETE", "nstatv": {"value": 1, "rule": "stated"},
           "initial_statev": {"value": [0.0], "rule": "stated", "where": "README"},
           "reads_temp": False, "reads_coords_or_noel": False,
           "formulation_statement": "small-strain elasticity, NTENS=6 only",
           "documented_domain": {"strain_max": {"value": 0.004, "where": "README",
                                                "quote": "up to 0.4%"}},
           "constants": [{"index": 1, "name": "E", "value": 1000.0, "confidence": "exact",
                          "never_count_reason": None, "where": "README"},
                         {"index": 2, "name": "nu", "value": 0.25, "confidence": "interpreted",
                          "never_count_reason": None, "where": "paper p. 3"}]}
    repo = _repo(tmp_path)
    cp = plan_council(repo / "src" / "umat.f", repo, row)
    assert cp.found and [s for s, _ in cp.sets] == ["author"]
    assert cp.material_data_origin == "author_published_outside_deck"
    assert cp.ceiling == 0.004 and cp.ceiling_origin[0] == "author_published"
    row["constants"][1]["confidence"] = "uncertain"
    assert plan_council(repo / "src" / "umat.f", repo, row).refusal_code == \
        "insufficient_material_data"


BRANCHING = HEADER + """\
      E = PROPS(1)
      ENU = PROPS(2)
      IF (NDI == 3) THEN
        DO I = 1, NTENS
          DO J = 1, NTENS
            DDSDDE(I,J) = 0.D0
          END DO
          DDSDDE(I,I) = E/(1.D0+ENU)
        END DO
      ELSE
        DDSDDE(1,1) = E
      END IF
      IF (NTENS == 4) THEN
        STRESS(4) = 0.D0
      END IF
      STATEV(1) = 0.D0
      RETURN
      END
"""


def test_the_d21_formulation_field_decides_the_element(tmp_path):
    formulation = {"statement": "3D", "element": "C3D8 (NDI=3, NTENS=6)",
                   "evidence": ["umat.f:12 if (ndi==3) then ! 3D"], "origin": "council_choice"}
    cp = _plan(tmp_path, BRANCHING, formulation_3d_only=None, formulation=formulation)
    assert cp.found, cp.refusal
    manifest = cp.sets[0][1].manifest
    assert manifest.element_type == "C3D8"
    origin = manifest.as_dict()["origins"]["element_type"]
    assert origin["origin"] == "council_choice" and "umat.f:12" in origin["provenance"]


def test_a_branching_routine_names_the_branch_it_does_not_exercise(tmp_path):
    formulation = {"statement": "3D", "element": "C3D8", "evidence": [], "origin": "council_choice"}
    cp = _plan(tmp_path, BRANCHING, formulation_3d_only=None, formulation=formulation)
    coverage = cp.as_dict()["branch_coverage"]
    assert sorted(coverage["not_exercised"]) == ["ELSE of NDI == 3", "NTENS == 4"]
    assert coverage["exercised"].startswith("NTENS=6")
    assert coverage["statement"].startswith("verified on the 3D branch (NTENS=6)")
    assert _plan(tmp_path / "plain").branch_coverage is None


def test_identical_sets_are_not_independent(tmp_path):
    cp = _plan(tmp_path, sets=[_set("A", 210000.0, 0.3), _set("B", 210000.0, 0.3)])
    assert cp.refusal_code == "insufficient_material_data" and "identical" in cp.refusal


def test_a_council_rows_kinematics_and_ceiling_are_council_choices(tmp_path):
    domain = {"stretch_max": {"value": 1.1, "where": "council", "quote": "q"}}
    cp = _plan(tmp_path, formulation_3d_only="NTENS=6, finite strain", documented_domain=domain)
    origins = cp.sets[0][1].manifest.as_dict()["origins"]
    assert origins["kinematics"]["origin"] == "council_choice"
    assert cp.ceiling_origin[0] == "council_choice" and abs(cp.ceiling - 0.1) < 1e-12


def test_a_domain_stated_only_in_words_is_carried_as_not_enforced(tmp_path):
    domain = {"strain_max": {"value": "up to failure", "where": "README", "quote": "q"},
              "temperature": {"value": [290, 300], "where": "README", "quote": "q"}}
    cp = _plan(tmp_path, documented_domain=domain)
    assert cp.found and cp.as_dict()["domain_not_enforced"] == ["strain_max"]


PLANS = Path(__file__).resolve().parents[2] / "corpus_campaign" / "council_plans"


def test_no_real_council_plan_cites_an_authors_deck():
    """Vera's G review C4: the A1 string test on the generated plans, with the
    verbatim row-provenance fields left out (constant provenance, origin
    provenance, documented-domain quotes, notes)."""
    files = sorted(PLANS.glob("*/council_plan.json"))
    if not files:
        pytest.skip("corpus_campaign/council_plans not present")
    bad = []
    for path in files:
        plan = json.loads(path.read_text())
        plan.pop("documented_domain", None)
        plan.pop("notes", None)
        for entry in plan.get("sets") or ():
            manifest = entry["plan"]["experiment"]["manifest"] or {}
            manifest.pop("material_provenance", None)
            for origin in (manifest.get("origins") or {}).values():
                origin.pop("provenance", None)
        if re.search(r"author's deck|paired deck|\.inp\b", json.dumps(plan), re.I):
            bad.append(path.parent.name)
    assert not bad, bad
