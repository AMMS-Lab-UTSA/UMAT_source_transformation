"""``umat-oti all`` and ``umat-oti jacobian`` through the front door: a refusal is
a plain card, never the raw JSON error or an internal script's usage text, the raw
output is kept in a file, the exit code is the command's own, and a success passes
through unchanged (the transform fingerprint covers ``umat_oti/cli.py``, so the cards are
added around it, not in it).
"""
import json
import shutil
from pathlib import Path

import pytest

from umat_oti.app import front_door as door

pytestmark = pytest.mark.unit

J2 = Path(__file__).resolve().parents[1] / "UMATs" / "UMATs" / "generic_ps" / "j2_props.f"
EMU = "      EMU   = E / (TWO * (ONE + XNU))"


@pytest.fixture
def folder(tmp_path):
    shutil.copy(J2, tmp_path / "j2_props.f")
    text = J2.read_text().replace(EMU, "      CALL SHEARMOD(E, XNU, EMU)")
    (tmp_path / "missing_helper.f").write_text(text)
    return tmp_path


def _no_internals(out):
    assert "usage:" not in out.lower() and "trial_deck" not in out and "Traceback" not in out
    assert '"error"' not in out and '"stages"' not in out


def test_all_asks_about_the_routine_first_and_runs_nothing_when_it_cannot_be_converted(folder, capsys):
    out = folder / "o"
    assert door.main(["all", str(folder / "missing_helper.f"), "--out", str(out)]) == 2
    text = capsys.readouterr().out
    import re
    assert re.search(r"^(BLUE: I NEED ONE THING FROM YOU|RED: REFUSED)$", text, re.M), "a colour word in the banner"
    assert "SHEARMOD" in text and "--dependency-root" in text
    _no_internals(text)
    assert not out.exists()


def test_jacobian_prints_the_card_keeps_the_raw_output_and_the_exit_code(folder, capsys):
    out = folder / "j"
    code = door.main(["jacobian", str(folder / "missing_helper.f"), "--ntens", "6", "--out", str(out),
                      "--discover-dependencies"])
    text = capsys.readouterr().out
    assert code == 1 and "SHEARMOD" in text and "Whose move: you." in text   # the command's own exit code
    _no_internals(text)
    raw = out / "umat-oti-jacobian-output.json"
    assert raw.is_file() and "SHEARMOD" in raw.read_text()
    assert f"recorded is in {raw}" in text


def test_all_with_no_deck_shows_a_card_and_keeps_the_internal_usage_in_the_file(folder, capsys):
    out = folder / "o2"
    code = door.main(["all", str(folder / "j2_props.f"), "--out", str(out)])
    text = capsys.readouterr().out
    assert code != 0 and "could not find the numbers" in text and "--material-config" in text
    _no_internals(text)
    raw = (out / "umat-oti-all-output.json").read_text()
    assert "trial_deck.py" in raw                      # the evidence is kept, just not shown


def test_a_plain_text_refusal_shows_the_card_and_the_programs_own_line(folder, capsys):
    code = door.main(["jacobian", str(folder / "j2_props.f"), "--ntens", "5", "--out", str(folder / "j5")])
    text = capsys.readouterr().out
    assert code == 2 and "REFUSED" in text and "The program said:" in text and "ntens" in text.lower()


def test_a_success_passes_through_unchanged_and_writes_no_output_file(folder, capsys):
    out = folder / "ok"
    code = door.main(["jacobian", str(folder / "j2_props.f"), "--ntens", "6", "--out", str(out)])
    printed = capsys.readouterr().out
    assert code == 0 and json.loads(printed)["transform_success"] is True
    assert not (out / "umat-oti-jacobian-output.json").exists()


def test_a_mistyped_command_line_says_one_plain_line_not_a_usage_block(capsys):
    assert door.main(["all"]) == 2
    err = capsys.readouterr().err
    assert "usage:" not in err.lower() and err.startswith("umat-oti all: the following arguments are required")
    assert "umat-oti check my_umat.for" in err


def test_asking_for_help_still_prints_the_commands_own_help(capsys):
    with pytest.raises(SystemExit) as stop:
        door.main(["all", "--help"])
    assert stop.value.code == 0 and "--material-config" in capsys.readouterr().out
