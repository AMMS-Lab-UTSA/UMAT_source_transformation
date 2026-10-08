"""What a novice sees from ``umat-oti check``: banners with a colour word, an empty deck said so, folders next to the UMAT."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app import check_command as check                      # noqa: E402
from umat_oti.app.refusal_cards import STATE_CARDS                    # noqa: E402
from umat_oti.app.verdict_page import render_verdict                  # noqa: E402

pytestmark = pytest.mark.unit
J2 = REPO / "UMATs" / "UMATs" / "generic_ps" / "j2_props.f"
BANNER = re.compile(r"^(GREEN|AMBER|RED|BLUE): ", re.M)


@pytest.fixture
def work(tmp_path):
    folder = tmp_path / "somewhere" / "umats"
    folder.mkdir(parents=True)
    shutil.copy(J2, folder / "j2_props.f")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    return folder, elsewhere


def test_every_card_printed_on_its_own_has_a_colour_word_in_its_banner(capsys):
    for state in STATE_CARDS:
        check.print_card(state, "")
        banner = capsys.readouterr().out.splitlines()[1:3]
        assert BANNER.match(banner[1]) is not None, (state, banner)


def test_the_request_for_one_thing_and_the_refusal_carry_a_colour_word(capsys):
    class Item:
        key, ask, default, whose = "ntens", "Say how many.", "6", "you"
    check.print_need(Item())
    assert "BLUE: I NEED ONE THING FROM YOU" in capsys.readouterr().out
    Item.whose = "this program"
    check.print_need(Item())
    assert "RED: REFUSED" in capsys.readouterr().out


@pytest.mark.parametrize("record", [{"terminal_state": "fully_verified", "evidence": {}},
                                    {"terminal_state": "tangent_not_verified"},
                                    {"terminal_state": "missing_material_data", "reason": "no deck"},
                                    {"terminal_state": "transform_refused", "reason": "anchors not located"},
                                    {"terminal_state": "not_a_umat"}])
def test_every_verdict_has_a_colour_word_in_its_banner(record):
    assert BANNER.search(render_verdict(record))


def test_an_empty_deck_is_said_to_be_empty_and_is_not_used(work, monkeypatch, capsys):
    folder, elsewhere = work
    deck = folder / "empty.inp"
    deck.write_text("")
    monkeypatch.chdir(elsewhere)
    code = check.main([str(folder / "j2_props.f"), "--deck", str(deck)])
    out = capsys.readouterr().out
    assert "Note: The deck empty.inp is empty" in out and "It is not used" in out
    assert "I NEED ONE THING FROM YOU" in out
    assert code == 3


def test_a_deck_with_no_user_material_block_is_said_so(work, monkeypatch, capsys):
    folder, elsewhere = work
    deck = folder / "geometry.inp"
    deck.write_text("*HEADING\nonly geometry\n*NODE\n1, 0., 0., 0.\n")
    monkeypatch.chdir(elsewhere)
    check.main([str(folder / "j2_props.f"), "--deck", str(deck)])
    out = capsys.readouterr().out
    assert "Note: The deck geometry.inp has no *USER MATERIAL block, so it gives no constants" in out


def test_the_output_folders_and_the_template_go_next_to_the_umat_not_into_the_current_directory(work, monkeypatch, capsys):
    folder, elsewhere = work
    monkeypatch.chdir(elsewhere)
    check.main([str(folder / "j2_props.f"), "--template"])
    out = capsys.readouterr().out
    assert f"Results go to: {folder / 'j2_props_check'}" in out
    assert (folder / "j2_props_check_input").is_dir()
    assert list(elsewhere.iterdir()) == [], "nothing is written into the current directory"
    assert list(folder.glob("j2_props_material*.json")), "the template is next to the UMAT"
    assert str(folder) in out


def test_peak_is_explained_wherever_it_is_suggested():
    from umat_oti.app.refusal_cards import card_for
    action = card_for("tangent_not_verified", "").next_action
    assert "--peak" in action and "how far the test strains the material" in action
    assert "how far to strain the material: 0.02 is 2 %" in check.HELP


def test_help_lists_check_and_doctor_in_the_usage_line_and_the_command_list():
    done = subprocess.run([sys.executable, str(REPO / "umat-oti"), "--help"], capture_output=True, text=True, cwd="/")
    assert done.returncode == 0, done.stderr
    assert "usage: umat-oti [-h] {check,verify,doctor,all,transform,config,jacobian} ..." in done.stdout
    commands = re.findall(r"^    (\w+) ", done.stdout, re.M)
    assert commands[:3] == ["check", "verify", "doctor"] and "all" in commands
