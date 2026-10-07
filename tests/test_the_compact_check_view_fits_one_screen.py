"""The compact default view of the intake: short, plain, nothing hidden that needs you."""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app.check_compact import DETAILS_HINT, compact_intake   # noqa: E402
from umat_oti.app.unified_app import jargon_in                         # noqa: E402

pytestmark = pytest.mark.unit

TOY = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,
     1 DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR,
     2 NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,
     3 NPT,LAYER,KSPT,JSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),PROPS(NPROPS),
     1 DSTRAN(NTENS)
      EMOD=PROPS(1)
      ENU=PROPS(2)
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+EMOD*DSTRAN(I)
      END DO
      RETURN
      END
"""


def _scan(tmp_path, deck=None):
    spec = importlib.util.spec_from_file_location("scan_for_compact", REPO / "tools" / "intake_scan.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    src = tmp_path / "toy.for"
    src.write_text(TOY)
    return mod.scan(src, deck)


def test_the_view_is_short_and_points_to_the_details(tmp_path):
    found = _scan(tmp_path)
    text = compact_intake(found)
    lines = text.splitlines()
    assert len(lines) <= 14, lines
    assert lines[0].startswith("Files: toy.for")
    assert DETAILS_HINT in text and "--details" in text


def test_what_still_needs_the_user_is_never_hidden(tmp_path):
    found = _scan(tmp_path)
    text = compact_intake(found)
    assert found.needs_user(), "the toy has no deck, so the constants are needed"
    assert "Needs you:" in text and found.item("props_values").ask in text


def test_found_constants_show_names_values_and_where_from(tmp_path):
    found = _scan(tmp_path)
    scan = sys.modules["scan_for_compact"]
    ev = [{"file": "toy.inp", "line": 7, "text": "200000.0, 0.3"}]
    for item in found.items:
        if item.key == "props_values":
            item.status, item.value, item.evidence = "FOUND", [200000.0, 0.3], ev
            item.needs_user = False
    text = compact_intake(found)
    assert "Constants (2): EMOD=200000, ENU=0.3 (toy.inp:7)" in text


def test_no_expert_vocabulary_in_the_compact_view(tmp_path):
    text = compact_intake(_scan(tmp_path))
    text = re.sub(r"\b[A-Z][A-Z0-9_]{2,}\b", "NAME", text)
    assert jargon_in([text]) == []


def test_a_constant_the_deck_does_not_write_is_named_and_listed_as_assumed(tmp_path):
    toy = TOY.replace("      ENU=PROPS(2)\n", "      ENU=PROPS(2)\n      H=PROPS(3)\n")
    src = tmp_path / "toy.for"
    src.write_text(toy)
    deck = tmp_path / "toy.inp"
    deck.write_text("*MATERIAL, NAME=M\n*USER MATERIAL, CONSTANTS=3\n200000., 0.3\n*DEPVAR\n1\n*STEP\n*STATIC\n0.1, 1.\n*END STEP\n")
    spec = importlib.util.spec_from_file_location("scan_for_compact_h", REPO / "tools" / "intake_scan.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    found = mod.scan(src, deck)
    text = compact_intake(found)
    assert "None" not in text
    assert "H not written (Abaqus uses 0)" in text
    assert "H is not written in your deck, so Abaqus uses 0" in text.split("Assumed", 1)[1]
    assert "Constants (3): EMOD=200000, ENU=0.3, H not written (Abaqus uses 0)" in text


def _scan_with(tmp_path, constants, data):
    toy = TOY.replace("      ENU=PROPS(2)\n", "      ENU=PROPS(2)\n      H=PROPS(4)\n")
    src = tmp_path / "toy2.for"
    src.write_text(toy)
    deck = tmp_path / "toy2.inp"
    deck.write_text(f"*MATERIAL, NAME=M\n*USER MATERIAL, CONSTANTS={constants}\n{data}*DEPVAR\n1\n*STEP\n*STATIC\n0.1, 1.\n*END STEP\n")
    spec = importlib.util.spec_from_file_location("scan_for_compact_amber", REPO / "tools" / "intake_scan.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.scan(src, deck)


def test_a_block_abaqus_rejects_but_the_pipeline_reads_gets_an_amber_note_naming_the_constants(tmp_path):
    found = _scan_with(tmp_path, 4, "200000., 0.3,\n250., 2000.\n")
    assert found.facts["props_values_agree_with_pipeline"] is False
    assert [d["slot"] for d in found.facts["props_values_differ"]] == [1, 2]
    text = compact_intake(found)
    notes = [ln for ln in text.splitlines() if ln.startswith("Amber note:")]
    assert len(notes) == 1, text
    assert "does not accept this constants block" in notes[0]
    for pair in ("EMOD = 200000", "ENU = 0.3"):
        assert pair in notes[0], notes[0]


def test_two_readers_with_different_numbers_give_an_amber_note_naming_the_constants(tmp_path):
    """The two readers have never differed on a usable block of the discovery cache; the note exists for the day they do."""
    found = _scan_with(tmp_path, 4, "200000., 0.3, 250., 2000.\n")
    found.facts["props_values_agree_with_pipeline"] = False
    found.facts["props_values_differ"] = [{"slot": 4, "card_reader": 2000.0, "pipeline_reader": 0.0}]
    note = [ln for ln in compact_intake(found).splitlines() if ln.startswith("Amber note:")]
    assert len(note) == 1
    assert "H (as Abaqus reads it: 2000; the pipeline's reader: 0)" in note[0]


def test_the_amber_note_is_also_printed_with_the_details():
    import inspect
    from umat_oti.app import check_command
    src = inspect.getsource(check_command)
    assert src.count("amber_notes(found)") >= 1 and "compact_intake(found)" in src


def test_no_amber_note_when_the_readers_agree(tmp_path):
    found = _scan_with(tmp_path, 4, "200000., 0.3, 250., 2000.\n")
    assert found.facts["props_values_agree_with_pipeline"] is True
    assert "Amber note" not in compact_intake(found)


def test_a_constant_is_named_by_its_slot_not_by_its_position_in_the_list_of_named_ones(tmp_path):
    """The routine names PROPS(1), PROPS(2) and PROPS(4) but not PROPS(3): slot 4 is H, slot 3 is constant 3."""
    found = _scan_with(tmp_path, 4, "200000., 0.3, 250., 2000.\n")
    text = compact_intake(found)
    assert "EMOD=200000, ENU=0.3, constant 3=250, H=2000" in text
