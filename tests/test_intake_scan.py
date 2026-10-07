"""The intake scanner (tools/intake_scan.py).

Three kinds of test:

* toy sources written here, which always run: every status (FOUND, INFERRED,
  DEFAULT, MISSING), the quoted lines, read-only operation, determinism, the
  plain-language override, and the hand-over to the pipeline;
* golden outputs on five corpus UMATs (a verifying one; one refused for a
  missing helper; one with no material data; one reading COORDS in a
  finite-strain model; one finite-strain elastic one) -- skipped where the
  discovery cache is not on the machine, as the other corpus tests are;
* the agreement test of batches/B11/maya/design.md section 6: on 10 random
  corpus UMATs the scanner agrees with the registry on ntens, props_count,
  nstatv and element in at least 95% of the fields the registry has evidence
  for.

Regenerate the goldens with ``python tests/test_intake_scan.py --regen``.
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE") or REPO.parent / "discovery_cache")
GOLDEN = REPO / "tests" / "golden" / "intake"
REGISTRY = REPO / "paper_results" / "corpus" / "corpus_registry.json"

_spec = importlib.util.spec_from_file_location("intake_scan", REPO / "tools" / "intake_scan.py")
intake_scan = importlib.util.module_from_spec(_spec)
sys.modules["intake_scan"] = intake_scan
_spec.loader.exec_module(intake_scan)

HEADER = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,
     1 RPL,DDSDDT,DRPLDE,DRPLDT,
     2 STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,
     3 NDI,NSHR,NTENS,NSTATEV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     4 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
{use}      CHARACTER*80 CMNAME
      DIMENSION STRESS(NTENS),STATEV(NSTATEV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
     2 STRAN(NTENS),DSTRAN(NTENS),TIME(2),PREDEF(1),DPRED(1),
     3 PROPS(NPROPS),COORDS(3),DROT(3,3),DFGRD0(3,3),DFGRD1(3,3)
"""
BODY = """\
      EMOD=PROPS(1)
      ENU=PROPS(2)
      DO K1=1,6
        DO K2=1,6
          DDSDDE(K1,K2)=0.D0
        END DO
      END DO
      DDSDDE(1,1)=EMOD
      DDSDDE(6,6)=ENU
{extra}      RETURN
      END
"""
DECK = """\
*HEADING
*NODE
1, 0., 0., 0.
2, 1., 0., 0.
*ELEMENT, TYPE=C3D8, ELSET=ALL
1, 1, 2, 3, 4, 5, 6, 7, 8
*SOLID SECTION, ELSET=ALL, MATERIAL=MAT
*MATERIAL, NAME=MAT
*DEPVAR
3,
*USER MATERIAL, CONSTANTS=2
210000., 0.3
*STEP, NLGEOM=NO
*STATIC
1., 1.
*END STEP
"""


def toy(tmp_path, extra="", use="", deck=None, name="toy.for"):
    src = tmp_path / name
    src.write_text(HEADER.format(use=use) + BODY.format(extra=extra), encoding="utf-8")
    if deck is not None:
        (tmp_path / "model.inp").write_text(deck, encoding="utf-8")
    return src


def item(result, key):
    return result.item(key)


# ---------------------------------------------------------------------------
# toys: statuses and quotes
# ---------------------------------------------------------------------------
def test_a_umat_alone_is_inferred_from_its_own_lines_and_asks_for_the_numbers(tmp_path):
    src = toy(tmp_path, extra="      STATEV(3)=STATEV(3)+1.D0\n")
    r = intake_scan.scan(src)
    assert item(r, "routine").status == "FOUND" and item(r, "routine").evidence[0]["line"] == 1
    assert item(r, "deck").status == "MISSING"
    count = item(r, "props_count")
    assert (count.status, count.value) == ("INFERRED", 2)
    assert count.evidence[0]["text"].startswith("ENU=PROPS(2)")
    nstatv = item(r, "nstatv")
    assert (nstatv.status, nstatv.value) == ("INFERRED", 3)
    assert nstatv.evidence[0]["text"] == "STATEV(3)=STATEV(3)+1.D0"
    names = item(r, "props_names")
    assert names.status == "FOUND" and names.value == {"PROPS(1)": "EMOD", "PROPS(2)": "ENU"}
    values = item(r, "props_values")
    assert values.status == "MISSING" and values.needs_user
    assert "PROPS(1) to PROPS(2)" in values.ask and "EMOD, ENU" in values.ask
    assert "never guessed" in values.default
    # six literal indices on the tensors: six components, from the routine
    assert (item(r, "ntens").status, item(r, "ntens").value) == ("INFERRED", 6)
    assert [i.key for i in r.needs_user()] == ["props_values"]
    assert r.material_config["props_values"] is None
    assert r.pipeline_inputs["material_config_needed"] is True


def test_a_deck_beside_it_supplies_the_numbers_and_the_lines_are_quoted(tmp_path):
    r = intake_scan.scan(toy(tmp_path, deck=DECK))
    assert item(r, "deck").status == "FOUND"
    assert item(r, "props_values").value == [210000.0, 0.3]
    assert item(r, "props_values").evidence[0] == {
        "file": "model.inp", "line": 12, "text": "210000., 0.3"}
    assert (item(r, "props_count").status, item(r, "props_count").value) == ("FOUND", 2)
    assert item(r, "props_count").evidence[0]["text"] == "*USER MATERIAL, CONSTANTS=2"
    nstatv = item(r, "nstatv")
    assert (nstatv.status, nstatv.value) == ("FOUND", 3)
    assert nstatv.evidence[0] == {"file": "model.inp", "line": 9, "text": "*DEPVAR"}
    el = item(r, "element")
    assert el.status == "FOUND" and el.evidence[0]["text"] == "*ELEMENT, TYPE=C3D8, ELSET=ALL"
    assert item(r, "kinematics").value.startswith("no")
    assert r.needs_user() == []
    assert r.material_config == {"kinematics": "small_strain", "ntens": 6, "nstatev": 3,
                                 "props_values": [210000.0, 0.3], "check_path": None}
    assert r.pipeline_inputs["material_config_needed"] is False


def test_a_deck_given_by_path_or_by_folder_is_used_wherever_it_lives(tmp_path):
    (tmp_path / "u").mkdir()
    (tmp_path / "d").mkdir()
    src = toy(tmp_path / "u", deck=None)
    (tmp_path / "d" / "model.inp").write_text(DECK, encoding="utf-8")
    by_file = intake_scan.scan(src, tmp_path / "d" / "model.inp")
    by_folder = intake_scan.scan(src, tmp_path / "d")
    for r in (by_file, by_folder):
        assert item(r, "props_values").value == [210000.0, 0.3]
        assert r.deck == "model.inp"
    assert intake_scan.scan(src).item("deck").status == "MISSING"


def test_nlgeom_in_the_deck_is_found_and_reading_dfgrd_is_inferred(tmp_path):
    r = intake_scan.scan(toy(tmp_path, deck=DECK.replace("NLGEOM=NO", "NLGEOM=YES")))
    k = item(r, "kinematics")
    assert k.status == "FOUND" and k.value.startswith("yes")
    assert "NLGEOM=YES" in k.evidence[0]["text"].upper()
    assert r.facts["kinematics"] == "finite"
    sub = tmp_path / "f"
    sub.mkdir()
    r2 = intake_scan.scan(toy(sub, extra="      DET=DFGRD1(1,1)*DFGRD1(2,2)\n"))
    k2 = item(r2, "kinematics")
    assert k2.status == "INFERRED" and "DFGRD1" in k2.evidence[0]["text"]
    assert r2.material_config["kinematics"] == "finite_strain"
    assert "small strain only" in " ".join(r2.pipeline_inputs["material_config_missing"])


def test_reading_temperature_coordinates_noel_and_fields_is_reported_with_defaults(tmp_path):
    extra = ("      T0=TEMP+DTEMP\n      X1=COORDS(1)\n      N1=NOEL\n"
             "      F1=PREDEF(1)\n")
    r = intake_scan.scan(toy(tmp_path, extra=extra))
    t = item(r, "temperature")
    assert (t.status, t.needs_user) == ("DEFAULT", True)
    assert "293.15" in t.value and "293.15" in t.default
    assert t.evidence[0]["text"] == "T0=TEMP+DTEMP"
    c = item(r, "coordinates")
    assert (c.status, c.needs_user) == ("DEFAULT", True) and "origin" in c.value
    assert item(r, "element_number").status == "DEFAULT"
    f = item(r, "fields")
    assert f.status == "DEFAULT" and f.needs_user
    assert {"temperature", "coordinates", "fields", "props_values"} <= {
        i.key for i in r.needs_user()}
    # the argument list names them all; a routine that does not read them says no
    quiet = intake_scan.scan(toy(tmp_path / "..", name="quiet.for"))
    for key in ("temperature", "coordinates", "element_number", "fields"):
        assert (item(quiet, key).status, item(quiet, key).value) == ("FOUND", "no")


def test_a_deck_supplies_coordinates_and_the_element_label(tmp_path):
    extra = "      X1=COORDS(1)\n"
    r = intake_scan.scan(toy(tmp_path, extra=extra, deck=DECK))
    c = item(r, "coordinates")
    assert c.status == "FOUND" and not c.needs_user


def test_a_missing_helper_is_named_with_the_calling_line_and_a_default(tmp_path):
    r = intake_scan.scan(toy(tmp_path, extra="      CALL SHEARMOD(EMOD,ENU)\n"))
    h = item(r, "helpers")
    assert h.status == "MISSING" and h.needs_user
    assert h.value["missing"] == ["SHEARMOD"]
    assert h.evidence[0]["text"] == "CALL SHEARMOD(EMOD,ENU)"
    assert "SHEARMOD" in h.ask and "SHEARMOD" in h.default
    (tmp_path / "helper.for").write_text(
        "      SUBROUTINE SHEARMOD(A,B)\n      A=A\n      RETURN\n      END\n", encoding="utf-8")
    r2 = intake_scan.scan(tmp_path / "toy.for")
    h2 = item(r2, "helpers")
    assert h2.status == "FOUND" and h2.value["present"] == ["SHEARMOD"]
    assert h2.value["files"] == ["helper.for"]


def test_a_missing_include_and_a_missing_module_are_reported(tmp_path):
    src = tmp_path / "toy.for"
    text = HEADER.format(use="      USE MYMOD\n") + BODY.format(
        extra="      INCLUDE 'extra.inc'\n")
    src.write_text(text, encoding="utf-8")
    r = intake_scan.scan(src)
    inc = item(r, "includes")
    assert inc.status == "MISSING" and inc.value == {"missing": ["extra.inc"]}
    mod = item(r, "modules")
    assert mod.status == "MISSING" and mod.value["missing"] == ["MYMOD"]
    assert mod.evidence[0]["text"] == "USE MYMOD"
    (tmp_path / "extra.inc").write_text("      REAL*8 XX\n", encoding="utf-8")
    (tmp_path / "mymod.f90").write_text("module mymod\ninteger :: k\nend module mymod\n",
                                        encoding="utf-8")
    r2 = intake_scan.scan(src)
    assert item(r2, "includes").status == "FOUND"
    assert item(r2, "modules").status == "FOUND" and item(r2, "modules").value == ["MYMOD"]


def test_a_file_that_is_not_a_umat_says_so_and_names_whose_move_it_is(tmp_path):
    src = tmp_path / "helper_only.for"
    src.write_text("      SUBROUTINE SOMETHING(A,B)\n      A=B\n      RETURN\n      END\n",
                   encoding="utf-8")
    r = intake_scan.scan(src)
    routine = item(r, "routine")
    assert routine.status == "MISSING" and routine.needs_user
    assert routine.whose == "you or the author"
    assert r.facts["entry_is_umat"] is False


# ---------------------------------------------------------------------------
# toys: how the constants are read (rules measured on Abaqus 2021.HF5)
# ---------------------------------------------------------------------------
def deck_with(constants: int, data: str) -> str:
    return DECK.replace("*USER MATERIAL, CONSTANTS=2\n210000., 0.3\n",
                        f"*USER MATERIAL, CONSTANTS={constants}\n{data}")


def values_of(tmp_path, constants: int, data: str):
    toy(tmp_path, deck=deck_with(constants, data))
    return intake_scan.scan(tmp_path / "toy.for")


def test_constants_over_two_lines_with_a_trailing_comma_are_read_in_order(tmp_path):
    r = values_of(tmp_path, 10, "1., 2., 3., 4., 5., 6., 7., 8.,\n9., 10.\n")
    v = item(r, "props_values")
    assert (v.status, v.value) == ("FOUND", [float(i) for i in range(1, 11)])
    assert r.facts["props_values_agree_with_pipeline"] is True
    assert r.material_config["props_values"] == v.value


def test_a_comment_line_between_the_data_lines_is_skipped(tmp_path):
    r = values_of(tmp_path, 10, "1., 2., 3., 4., 5., 6., 7., 8.,\n** a comment\n9., 10.\n")
    assert item(r, "props_values").value == [float(i) for i in range(1, 11)]
    assert item(r, "props_values").status == "FOUND"


def test_a_blank_line_between_the_data_lines_is_not_readable(tmp_path):
    """Abaqus rejects the deck (measured); no value is taken from it."""
    r = values_of(tmp_path, 10, "1., 2., 3., 4., 5., 6., 7., 8.,\n\n9., 10.\n")
    v = item(r, "props_values")
    assert v.status == "MISSING" and v.needs_user and v.value is None
    assert "blank line" in v.note
    assert r.material_config["props_values"] is None


def test_two_short_lines_for_a_block_that_fits_on_one_are_never_read_as_zeros(tmp_path):
    """CONSTANTS=4 over two lines: Abaqus rejects it, and the second line's
    numbers used to come back as 0 (SIGY0=0, H=0). They are MISSING."""
    for data in ("200000., 0.3,\n250., 2000.\n", "200000., 0.3\n250., 2000.\n",
                 "200000., 0.3,\n** note\n250., 2000.\n"):
        r = values_of(tmp_path, 4, data)
        v = item(r, "props_values")
        assert v.status == "MISSING" and v.needs_user and v.value is None, data
        assert "fits on 1 data line" in v.note
        assert 0.0 not in (r.material_config["props_values"] or [])
        assert r.facts["props_values_agree_with_pipeline"] is False, (
            "the pipeline's reader takes the first line and zero-fills the rest")
        assert "the pipeline's own reader" in v.note


def test_a_short_line_leaves_the_slots_it_does_not_write_unwritten_not_zero(tmp_path):
    r = values_of(tmp_path, 4, "200000., 0.3,\n")
    v = item(r, "props_values")
    assert v.status == "INFERRED" and not v.needs_user
    assert v.value == [200000.0, 0.3, None, None]
    assert "slots 3 to 4 are not written" in v.note and "fills the rest of a short" in v.note
    assert r.facts["props_values_found"] is False
    assert r.material_config["props_values"] is None
    assert r.facts["props_values_agree_with_pipeline"] is True


def test_a_short_first_line_keeps_the_second_line_in_its_own_card(tmp_path):
    """Measured: ``1.,2.,3.,4.,`` then ``5.,6.,...`` is PROPS 1-4, zeros, 5, 6
    at slots 9 and 10 -- a trailing comma does not continue the line."""
    r = values_of(tmp_path, 10, "1., 2., 3., 4.,\n5., 6., 7., 8., 9., 10.\n")
    v = item(r, "props_values")
    assert v.value == [1.0, 2.0, 3.0, 4.0, None, None, None, None, 5.0, 6.0]
    assert r.facts["props_values_agree_with_pipeline"] is True


def test_a_name_standing_in_the_data_is_reported_not_zeroed(tmp_path):
    r = values_of(tmp_path, 2, "210000., <nu>\n")
    v = item(r, "props_values")
    assert v.status == "MISSING" and v.value is None


def test_fewer_data_lines_than_the_constants_need_leave_the_slots_unwritten(tmp_path):
    """Abaqus accepts a block with fewer lines than CONSTANTS needs (harshaa765:
    19 lines for 160) and zero-fills the rest; the scanner shows them as not
    written."""
    r = values_of(tmp_path, 10, "1., 2., 3., 4., 5., 6., 7., 8.\n")
    v = item(r, "props_values")
    assert v.status == "INFERRED" and v.value[8:] == [None, None]
    assert "slots 9 to 10 are not written" in v.note
    assert r.facts["props_values_agree_with_pipeline"] is True


def test_a_parameter_name_the_deck_defines_is_put_in_as_abaqus_does(tmp_path):
    deck = DECK.replace("*HEADING\n", "*HEADING\n*PARAMETER\nbulk = 5000.\n", 1).replace(
        "210000., 0.3\n", "210000., <bulk>\n")
    toy(tmp_path, deck=deck)
    r = intake_scan.scan(tmp_path / "toy.for")
    v = item(r, "props_values")
    assert (v.status, v.value) == ("FOUND", [210000.0, 5000.0])
    assert "bulk" in v.note.lower()


def test_the_card_reader_alone_on_the_measured_cases():
    read = intake_scan.read_constants
    deck = lambda data, n: "*MATERIAL, NAME=M\n*USER MATERIAL, CONSTANTS=%d\n%s*STEP\n" % (n, data)
    got = read(deck("1., 2., 3., 4., 5., 6., 7., 8., 9.\n", 8), "M", 8)
    assert got["slots"] == [1, 2, 3, 4, 5, 6, 7, 8] and len(got["problems"]) == 1
    got = read(deck("1., 2.,\n", 4), "M", 4)
    assert got["zero_filled"] == [3, 4] and got["problems"] == []
    got = read(deck("1., 2.\n3.\n", 3), "M", 3)
    assert "fits on 1 data line" in got["problems"][0]
    got = read(deck("1., 2., 3., 4., 5., 6., 7., 8.,\n", 12), "M", 12)
    assert got["zero_filled"] == [9, 10, 11, 12] and got["problems"] == []


# ---------------------------------------------------------------------------
# toys: properties of the tool
# ---------------------------------------------------------------------------
def test_the_scan_is_deterministic_and_changes_nothing_on_disk(tmp_path):
    src = toy(tmp_path, extra="      CALL SHEARMOD(EMOD,ENU)\n", deck=DECK)
    before = sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.iterdir())
    first = intake_scan.scan(src).to_json()
    second = intake_scan.scan(src).to_json()
    assert first == second
    assert sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                  for p in tmp_path.iterdir()) == before
    assert str(tmp_path) not in first, "no absolute path may reach the output"
    assert "generated" not in first and "timestamp" not in first


def test_every_item_has_a_status_and_every_request_has_a_default(tmp_path):
    src = toy(tmp_path, extra="      T0=TEMP\n      X=COORDS(2)\n      CALL ZZZ(T0)\n")
    r = intake_scan.scan(src)
    for i in r.items:
        assert i.status in intake_scan.STATUSES
        if i.needs_user:
            assert i.ask and i.default and i.whose
        else:
            assert not i.ask
    assert r.counts() == {s: sum(1 for i in r.items if i.status == s)
                          for s in intake_scan.STATUSES}


def test_command_line_prints_and_writes_intake_json_and_md(tmp_path, capsys):
    src = toy(tmp_path, deck=DECK)
    out = tmp_path / "out"
    assert intake_scan.main([str(src), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "FOUND" in printed and "Needs you: nothing" in printed
    data = json.loads((out / "intake.json").read_text(encoding="utf-8"))
    assert data["schema"] == "umat-oti/intake/1"
    assert data["material_config"]["props_values"] == [210000.0, 0.3]
    md = (out / "intake.md").read_text(encoding="utf-8")
    assert md.startswith("# Intake:") and "| FOUND |" in md
    assert intake_scan.main([str(tmp_path / "nothere.for")]) == 3


def test_the_plain_language_table_can_be_replaced_key_by_key(tmp_path):
    texts = {"props_values": {"ask": "FROM IRIS {slots}", "default": "iris default"}}
    r = intake_scan.scan(toy(tmp_path), texts=texts)
    v = item(r, "props_values")
    assert v.ask.startswith("FROM IRIS PROPS(1) to PROPS(2)") and v.default == "iris default"
    assert v.whose == "you", "keys Iris does not give keep their text"
    assert intake_scan.scan(toy(tmp_path)).item("props_values").ask.startswith(
        "I could not find the numbers")


def test_it_uses_the_existing_inference_and_changes_none_of_it():
    """Imports, never edits: the scanner lives outside the covered code."""
    text = (REPO / "tools" / "intake_scan.py").read_text(encoding="utf-8")
    for name in ("umat_oti.abaqus import deck_pairing", "umat_oti.abaqus.formulation import",
                 "umat_oti.corpus import entry_routines",
                 "umat_oti.transform.dependency_resolution import"):
        assert name in text
    from umat_oti.store.transform_store import transform_fingerprint, harness_fingerprint
    assert len(transform_fingerprint()) == 16 and len(harness_fingerprint()) == 16


# ---------------------------------------------------------------------------
# corpus: goldens and agreement
# ---------------------------------------------------------------------------
GOLDEN_SOURCES = {
    "verified_isotropic_elasticity":
        "CAEAssistant-Group__UMAT-Abaqus-Isotropic-Elasticity-Isothermal-Suboutine/"
        "ISOTROPIC-ELASTICITY.for",
    "refused_missing_helper_reads_temp": "jacojvr__UMATs/UMAT_framework/umat_iso.f",
    "no_material_data": "3MAH__simcoon/testBin/Umats/UMABA/external/UMAT_ABAQUS_ELASTIC.f",
    "reads_coords_finite_growth":
        "Jeff97__growth-of-circular-plate/Wrinkle/l1-is-1--l2-is-12.for",
    "finite_strain_neohookean":
        "AlexanderJFDR__Hyperelastic_phase_field/umat/NeoHookean_umat.for",
}
needs_cache = pytest.mark.skipif(not CACHE.is_dir(), reason=(
    "the discovery cache is not on this machine (set UMAT_OTI_DISCOVERY_CACHE)"))


def scan_corpus(source_id: str):
    return intake_scan.scan(CACHE / source_id, repository=CACHE / source_id.split("/")[0])


@needs_cache
@pytest.mark.parametrize("name", sorted(GOLDEN_SOURCES))
def test_golden_output_on_a_corpus_umat(name):
    got = scan_corpus(GOLDEN_SOURCES[name]).as_dict()
    want = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
    assert got == want


@needs_cache
def test_the_five_goldens_cover_the_five_kinds():
    facts = {n: scan_corpus(s) for n, s in GOLDEN_SOURCES.items()}
    assert facts["verified_isotropic_elasticity"].needs_user() == []
    assert facts["verified_isotropic_elasticity"].facts["props_values_found"]
    refused = facts["refused_missing_helper_reads_temp"]
    assert refused.item("helpers").status == "MISSING"
    assert refused.item("helpers").value["missing"] == ["FISOTROPIC", "SHEARMOD"]
    assert refused.item("temperature").status == "DEFAULT"
    nodata = facts["no_material_data"]
    assert nodata.item("props_values").status == "MISSING"
    assert nodata.item("deck").status == "MISSING"
    coords = facts["reads_coords_finite_growth"]
    assert coords.item("coordinates").status == "FOUND"
    assert coords.item("coordinates").evidence[0]["text"] == "STATEV(3)=COORDS(1)"
    for key in ("reads_coords_finite_growth", "finite_strain_neohookean"):
        assert facts[key].facts["kinematics"] == "finite"
        assert facts[key].item("kinematics").status == "FOUND"


def _comparable(record: dict, facts: dict) -> list:
    """(field, registry value, scanner value) where the registry has EVIDENCE.

    The registry's ntens is a bare default (6, recorded with no element) for
    sources never settled on a formulation, so it is compared only where the
    registry also holds the element it was settled with; element, props count
    and nstatv are compared where the registry holds a value.
    """
    out = []
    if record.get("ntens") is not None and record.get("element_type"):
        out.append(("ntens", record["ntens"], facts["ntens"]))
    if record.get("element_type"):
        out.append(("element", record["element_type"], facts["element"]))
    if record.get("props_count"):
        out.append(("props_count", record["props_count"], facts["props_count"]))
    if record.get("nstatv") is not None:
        out.append(("nstatv", record["nstatv"], facts["nstatv"]))
    return out


@needs_cache
def test_agreement_with_the_registry_on_ten_random_corpus_umats():
    records = json.loads(REGISTRY.read_text(encoding="utf-8"))["records"]
    pool = sorted((r for r in records if r["is_umat"] and (CACHE / r["source_id"]).is_file()),
                  key=lambda r: r["source_id"])
    sample = random.Random(20261006).sample(pool, 10)
    compared = agreed = 0
    disagreements = []
    for record in sample:
        facts = scan_corpus(record["source_id"]).facts
        for field, want, got in _comparable(record, facts):
            compared += 1
            if want == got:
                agreed += 1
            else:
                disagreements.append((record["source_id"], field, want, got))
    assert compared >= 10, "the sample must say something"
    assert agreed / compared >= 0.95, (agreed, compared, disagreements)


# ---------------------------------------------------------------------------
def _regen() -> None:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for name, source_id in sorted(GOLDEN_SOURCES.items()):
        (GOLDEN / f"{name}.json").write_text(scan_corpus(source_id).to_json(), encoding="utf-8")
        print("wrote", GOLDEN / f"{name}.json")


if __name__ == "__main__" and "--regen" in sys.argv:
    _regen()
