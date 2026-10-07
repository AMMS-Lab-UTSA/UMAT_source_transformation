"""``umat-oti check UMAT.for [DECK]`` (Nico, B11; Maya's design M1-M2).

It reads the deck from any path and says where each fact came from, takes the
constants and the loading directly, writes a commented template when there is
nothing to read, and never prints argparse or ``trial_deck`` usage.
"""
import json
import re
import shutil
from pathlib import Path

import pytest

from umat_oti.app import check_command as check
from umat_oti.app import check_intake as intake

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
J2 = ROOT / "UMATs" / "UMATs" / "generic_ps" / "j2_props.f"

DECK = """\
*HEADING
** a small deck
*NODE
1, 0., 0., 0.
*ELEMENT, TYPE=C3D8, ELSET=BLOCK
1, 1, 2, 3, 4, 5, 6, 7, 8
*MATERIAL, NAME=J2
*USER MATERIAL, CONSTANTS=4
210000.0, 0.3,
250.0, 2.0d3
*DEPVAR
1
*STEP, NAME=LOAD, NLGEOM=YES
*STATIC
0.1, 1.0
*END STEP
*STEP, NAME=BACK
*STATIC
*END STEP
"""


@pytest.fixture
def j2(tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    shutil.copy(J2, folder / "j2_props.f")
    return folder / "j2_props.f"


def test_the_deck_gives_constants_state_steps_and_elements_with_their_lines(tmp_path):
    deck = tmp_path / "block.inp"
    deck.write_text(DECK)
    facts = intake.scan_deck(deck)
    (name, constants, depvar), = facts.user_materials()
    assert name == "J2" and constants.value == [210000.0, 0.3, 250.0, 2000.0]
    assert (constants.line, constants.last_line) == (8, 10) and constants.where() == "block.inp lines 8-10"
    assert depvar.value == 1 and depvar.line == 12
    assert [s.value for s in facts.steps] == ["LOAD", "BACK"] and facts.steps[0].line == 13
    assert facts.element_types == ["C3D8"] and facts.nlgeom is True


def test_the_source_gives_the_constants_it_reads_and_their_names(j2):
    facts = intake.scan_source(j2)
    assert facts.has_umat and facts.umat_line == 18 and not facts.other_kind
    assert facts.props_max == 4
    assert [facts.props_names[k].value for k in (1, 2, 3, 4)] == ["E", "XNU", "SIGY0", "H"]
    assert facts.props_names[1].where() == "j2_props.f line 42"


def test_a_vumat_is_named_for_what_it_is(tmp_path):
    source = tmp_path / "v.f"
    source.write_text("      SUBROUTINE VUMAT(NBLOCK)\n      RETURN\n      END\n")
    facts = intake.scan_source(source)
    assert not facts.has_umat and "VUMAT" in facts.other_kind


def test_constants_typed_by_name_or_in_order_and_nothing_guessed(j2):
    names = intake.scan_source(j2).props_names
    assert intake.parse_props("E=210000 xnu=0.3 SIGY0=250 H=2000", names, 4)[0] == [210000.0, 0.3, 250.0, 2000.0]
    assert intake.parse_props("210000 0.3 250 2000", names, 4)[0] == [210000.0, 0.3, 250.0, 2000.0]
    values, _, problems = intake.parse_props("210000 0.3 250", names, 4)
    assert values == [] and "PROPS(4) (H)" in problems[0]
    _, _, problems = intake.parse_props("E=1 poisson=0.3", names, 4)
    assert "'poisson'" in problems[0] and "E, H, SIGY0, XNU" in problems[0]
    assert intake.parse_props("E=1 E=2 xnu=0.3 sigy0=1 h=1", names, 4)[2] == ["PROPS(1) is given twice."]


def test_the_peak_path_goes_out_back_through_zero_and_unloads():
    path = intake.out_back_path(0.02)["increments"]
    total, running = 0.0, []
    for row in path:
        total += row[0]
        running.append(total)
        assert row[1:] == [0.0] * 5
    assert len(path) == 40 and max(running) == pytest.approx(0.02) \
        and min(running) == pytest.approx(-0.02) and running[-1] == pytest.approx(0.0, abs=1e-12)
    with pytest.raises(ValueError, match="--peak"):
        intake.out_back_path(-1.0)


def test_the_template_is_commented_has_blanks_and_is_stripped_before_use(j2):
    template = intake.template_material(intake.scan_source(j2), nstatev=1)
    assert template["props_values"] == [None] * 4
    assert template["_props_values_are"]["1"].startswith("E (j2_props.f line 42)")
    clean = intake.strip_comments(template)
    assert not [k for k in clean if k.startswith("_")]
    assert set(clean) == {"kinematics", "ntens", "nstatev", "props_values", "check_path"}


def test_a_deck_given_by_path_a_folder_or_beside_the_umat_is_found_and_an_ambiguous_one_is_not_guessed(tmp_path):
    source = tmp_path / "a" / "u.f"
    source.parent.mkdir()
    source.write_text("      SUBROUTINE UMAT\n      END\n")
    elsewhere = tmp_path / "decks"
    elsewhere.mkdir()
    (elsewhere / "one.inp").write_text(DECK)
    assert check.resolve_deck(source, None, elsewhere / "one.inp")[:2] == ((elsewhere / "one.inp").resolve(), "given")
    assert check.resolve_deck(source, elsewhere, None)[0] == elsewhere / "one.inp"
    (elsewhere / "two.inp").write_text(DECK)
    deck, how, candidates = check.resolve_deck(source, elsewhere, None)
    assert deck is None and how == "folder" and len(candidates) == 2
    assert check.resolve_deck(source, None, None)[1] == "none"
    (source.parent / "beside.inp").write_text(DECK)
    assert check.resolve_deck(source, None, None) == (source.parent / "beside.inp", "beside the UMAT", [])


def test_a_bad_option_says_one_plain_line_and_never_argparse_usage(j2, capsys):
    assert check.main([str(j2), "--no-such-flag"]) == 2
    err = capsys.readouterr().err
    assert "usage:" not in err.lower() and "trial_deck" not in err
    assert err.startswith("umat-oti check:") and "Example:  umat-oti check" in err
    assert check.main([str(j2.with_name("nothing.f"))]) == 2
    assert "I cannot find the file" in capsys.readouterr().err


def test_a_routine_that_is_not_a_umat_is_refused_with_a_card(tmp_path, capsys):
    source = tmp_path / "v.f"
    source.write_text("      SUBROUTINE VUMAT(NBLOCK)\n      RETURN\n      END\n")
    assert check.main([str(source)]) == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and "Whose move:" in out and "VUMAT" not in out.split("REFUSED")[0]


def test_with_no_deck_and_no_constants_it_stops_with_the_scanners_ask_and_runs_nothing(j2, monkeypatch, capsys):
    monkeypatch.chdir(j2.parent)
    assert check.main([str(j2)]) == 3
    out = capsys.readouterr().out
    assert "Constants: not found" in out and "I NEED ONE THING FROM YOU" in out and "Files: j2_props.f  (no deck)" in out
    assert "the values of its 4 constants: E, XNU, SIGY0, H (read from the material definition)" in out
    assert 'umat-oti check j2_props.f --props "E=<value> XNU=<value> SIGY0=<value> H=<value>"' in out
    assert "usage:" not in out.lower() and "trial_deck" not in out
    assert not list(j2.parent.glob("*_material*.json"))           # no template unless asked for
    assert not (j2.parent / "j2_props_check").exists()            # the pipeline did not run
    record = json.loads((j2.parent / "j2_props_check_input" / "intake.json").read_text())
    assert record["schema"] == "umat-oti/intake/1" and "props_values" in record["needs_user"]
    assert (j2.parent / "j2_props_check_input" / "intake.md").is_file()


def test_a_template_is_written_only_when_asked_for_and_never_over_a_file(j2, monkeypatch, capsys):
    monkeypatch.chdir(j2.parent)
    assert check.main([str(j2), "--template"]) == 3
    out = capsys.readouterr().out
    template = j2.parent / "j2_props_material.json"
    assert template.is_file() and "--material-config j2_props_material.json" in out
    check.main([str(j2), "--template"])
    assert (j2.parent / "j2_props_material_2.json").is_file()


def test_the_template_is_the_fallback_when_the_scanner_is_not_there(j2, monkeypatch, capsys):
    monkeypatch.chdir(j2.parent)
    monkeypatch.setattr(check, "load_scanner", lambda: None)
    assert check.main([str(j2)]) == 3
    out = capsys.readouterr().out
    assert (j2.parent / "j2_props_material.json").is_file()
    assert "--material-config j2_props_material.json" in out and "usage:" not in out.lower()


def test_a_material_file_with_blanks_left_in_it_is_refused(j2, monkeypatch, capsys):
    monkeypatch.chdir(j2.parent)
    check.main([str(j2), "--template"])
    capsys.readouterr()
    assert check.main([str(j2), "--material-config", str(j2.parent / "j2_props_material.json")]) == 2
    assert "still has blanks" in capsys.readouterr().out


class _Item:
    def __init__(self, key, status, needs_user=True, whose="you"):
        self.key, self.status, self.needs_user, self.whose = key, status, needs_user, whose


class _Found:
    def __init__(self, *items):
        self.items = items

    def needs_user(self):
        return [i for i in self.items if i.needs_user]


def test_only_a_missing_item_that_needs_the_user_blocks_and_typed_constants_unblock_the_constants():
    found = _Found(_Item("routine", "FOUND", False), _Item("temperature", "DEFAULT"),
                   _Item("props_values", "MISSING"), _Item("helpers", "MISSING"))
    # the routine's files before its constants: a missing helper is why the constants are moot
    assert [i.key for i in check.blocking_items(found, constants_supplied=False)] == ["helpers", "props_values"]
    assert [i.key for i in check.blocking_items(found, constants_supplied=True)] == ["helpers"]


def test_the_scanner_is_loaded_by_path_and_its_intake_is_printed_with_the_lines_quoted(j2, tmp_path, monkeypatch, capsys):
    deck = tmp_path / "elsewhere" / "block.inp"
    deck.parent.mkdir()
    # CONSTANTS=4 on ONE data line: Abaqus rejects the same four numbers split over two lines (measured), and the scanner then asks for them
    deck.write_text(DECK.replace("NLGEOM=YES", "NLGEOM=NO").replace("210000.0, 0.3,\n250.0, 2.0d3", "210000.0, 0.3, 250.0, 2.0d3"))
    scanner = check.load_scanner()
    assert scanner is not None and hasattr(scanner, "scan") and scanner.SCHEMA == "umat-oti/intake/1"
    found = scanner.scan(j2, deck)
    text = found.to_text()
    assert "FOUND    Material routine" in text and "j2_props.f:18:" in text
    assert "block.inp:" in text and "*USER MATERIAL" in text
    assert not check.blocking_items(found, constants_supplied=False)       # a deck settles the constants


def test_incomplete_typed_constants_stop_before_anything_runs(j2, monkeypatch, capsys):
    monkeypatch.chdir(j2.parent)
    assert check.main([str(j2), "--props", "E=210000 xnu=0.3"]) == 2
    err = capsys.readouterr().err
    assert "PROPS(3) (SIGY0), PROPS(4) (H)" in err and "usage:" not in err.lower()
    assert not (j2.parent / "j2_props_check").exists()


@pytest.mark.slow
@pytest.mark.fortran
def test_typed_constants_and_a_peak_run_the_pipeline_and_the_json_goes_to_a_file(j2, monkeypatch, capsys):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    monkeypatch.chdir(j2.parent)
    code = check.main([str(j2), "--props", "E=210000 xnu=0.3 SIGY0=250 H=2000", "--peak", "0.02"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert '"stages"' not in out and len(out.splitlines()) < 90        # no JSON wall on the screen
    assert "typed with --props" in out and "[--peak]" in out
    summary = json.loads((j2.parent / "j2_props_check" / "workflow_summary.json").read_text())
    assert summary["exit_code"] == 0
    config = json.loads((j2.parent / "j2_props_check_input" / "material_check.json").read_text())
    assert config["props_values"] == [210000.0, 0.3, 250.0, 2000.0] and config["nstatev"] == 1
    assert len(config["check_path"]["increments"]) == 40
    # the intake was printed first, with the lines quoted, and kept beside the output
    assert out.index("Files: j2_props.f") < out.index("Working:")
    assert "FOUND    Material routine" not in out and "--details" in out    # the short view, the long one on request
    record = json.loads((j2.parent / "j2_props_check_input" / "intake.json").read_text())
    assert record["facts"]["props_count"] == 4 and record["facts"]["nstatv"] == 1
    assert (j2.parent / "j2_props_check_input" / "intake.md").is_file()


@pytest.mark.slow
@pytest.mark.fortran
def test_a_deck_in_another_folder_gives_the_constants_and_says_where_from(j2, tmp_path, monkeypatch, capsys):
    if shutil.which("gfortran") is None:
        pytest.skip("gfortran not on PATH")
    deck = tmp_path / "elsewhere" / "block.inp"
    deck.parent.mkdir()
    deck.write_text(DECK.replace("NLGEOM=YES", "NLGEOM=NO").replace("210000.0, 0.3,\n250.0, 2.0d3", "210000.0, 0.3, 250.0, 2000.0").replace(
        "*ELEMENT, TYPE=C3D8, ELSET=BLOCK\n1, 1, 2, 3, 4, 5, 6, 7, 8\n", ""))
    monkeypatch.chdir(j2.parent)
    code = check.main([str(j2), "--deck", str(deck)])
    out = capsys.readouterr().out
    assert re.search(r"Constants \(4\): E=210000, XNU=0\.3, SIGY0=250, H=2000 \(block\.inp:\d+\)", out), out
    assert "Working:" in out                      # it got as far as running the pipeline
    assert code in (0, 1, 2)                      # what the pipeline concludes about a deck without nodes is its own


def test_a_need_is_printed_with_its_ask_whose_move_and_what_to_do(capsys):
    class Item:
        key, whose = "helpers", "you"
        ask = "Your routine calls SHEARMOD, which is not in the files you gave me."
        default = "Put the file that defines SHEARMOD beside your UMAT."

    check.print_need(Item(), extra="(Give the folder with --dependency-root FOLDER.)")
    out = capsys.readouterr().out
    assert "I NEED ONE THING FROM YOU" in out and "Whose move: you." in out
    assert "Next: Put the file that defines SHEARMOD beside your UMAT. (Give the folder with --dependency-root FOLDER.)" in out
    Item.whose = "this program"
    check.print_need(Item())
    assert "REFUSED" in capsys.readouterr().out


def test_details_prints_every_item_with_its_lines_and_the_default_is_the_short_view(j2, tmp_path, monkeypatch, capsys):
    deck = tmp_path / "d" / "block.inp"
    deck.parent.mkdir()
    deck.write_text(DECK.replace("NLGEOM=YES", "NLGEOM=NO"))
    monkeypatch.chdir(j2.parent)
    for flags, long in (([], False), (["--details"], True)):
        # stop right after the intake: the helper is missing in this copy
        source = j2.parent / f"u{len(flags)}.f"
        source.write_text(J2.read_text().replace("      EMU   = E / (TWO * (ONE + XNU))",
                                                 "      CALL SHEARMOD(E, XNU, EMU)"))
        assert check.main([str(source), "--deck", str(deck), *flags]) == 3
        out = capsys.readouterr().out
        assert ("FOUND    Material routine" in out) is long
        assert ("Files: " in out) is (not long)
        assert (j2.parent / f"u{len(flags)}_check_input" / "intake.md").is_file()      # always written


DYNAMIC = """      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,DRPLDE,
     1 DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,CMNAME,NDI,NSHR,
     2 NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,CELENT,DFGRD0,DFGRD1,NOEL,
     3 NPT,LAYER,KSPT,JSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS),PROPS(NPROPS),
     1 DSTRAN(NTENS)
      SUMP=0.D0
      DO I=1,NPROPS
        SUMP=SUMP+PROPS(I)
      END DO
      DO I=1,NTENS
        STRESS(I)=STRESS(I)+SUMP*DSTRAN(I)
      END DO
      RETURN
      END
"""


def _counts(tmp_path, constants, data):
    source = tmp_path / "dyn.for"
    source.write_text(DYNAMIC)
    deck = tmp_path / "dyn.inp"
    deck.write_text(f"*MATERIAL, NAME=M\n*USER MATERIAL, CONSTANTS={constants}\n{data}*DEPVAR\n2\n*STEP\n*STATIC\n0.1, 1.\n*END STEP\n")
    scanner = check.load_scanner()
    found = scanner.scan(source, deck)
    deck_facts = intake.scan_deck(deck)
    facts = intake.scan_source(source)
    old = len(deck_facts.user_materials()[0][1].value)
    return check._constant_count(found, deck_facts, facts), old, check._state_count(found, deck_facts, facts)


def test_the_typed_constants_count_is_the_card_by_card_count_where_the_old_reader_joins_numbers(tmp_path):
    """1.,2.,3.,4., then 5.,6.: Abaqus has ten slots (5 and 6 at slots 9 and 10); the old reader counted the six numbers."""
    new, old, nstatv = _counts(tmp_path, 10, "1., 2., 3., 4.,\n5., 6.\n")
    assert old == 6
    assert new == 10
    assert nstatv == 2


@pytest.mark.parametrize("constants,data", [(4, "1., 2., 3., 4.\n"), (8, "1., 2., 3., 4., 5., 6., 7., 8.\n"),
                                            (10, "1., 2., 3., 4., 5., 6., 7., 8.,\n9., 10.\n"),
                                            (3, "1., 2., 3.\n")])
def test_the_two_readers_agree_on_a_block_written_as_abaqus_wants_it(tmp_path, constants, data):
    new, old, nstatv = _counts(tmp_path, constants, data)
    assert new == old == constants


def test_the_state_count_and_the_constant_count_do_not_use_the_old_deck_reader_when_the_scanner_is_there():
    import inspect
    src = inspect.getsource(check._constant_count) + inspect.getsource(check._state_count)
    assert src.index("if found is not None") < src.index("deck_facts.user_materials()")
