"""Nico, B11: for a UMAT with no deck ``umat-oti all`` said "no deck with a
*USER MATERIAL block" and hid the real blocker -- a helper nobody supplied, a
module it cannot read. ``check`` runs the transformer's dependency discovery and
anchor location first, so that is the message.
"""
import shutil
from pathlib import Path

import pytest

from umat_oti.app import check_command as check
from umat_oti.app import check_intake as intake
from umat_oti.app import check_preflight as pre

pytestmark = pytest.mark.unit

J2 = Path(__file__).resolve().parents[1] / "UMATs" / "UMATs" / "generic_ps" / "j2_props.f"
EMU = "      EMU   = E / (TWO * (ONE + XNU))"


def _variant(tmp_path, name, edit):
    folder = tmp_path / name
    folder.mkdir()
    source = folder / f"{name}.f"
    text = J2.read_text()
    assert EMU in text
    source.write_text(edit(text))
    return source


@pytest.fixture
def missing_helper(tmp_path):
    return _variant(tmp_path, "uses_shearmod",
                    lambda t: t.replace(EMU, "      CALL SHEARMOD(E, XNU, EMU)"))


@pytest.fixture
def missing_module(tmp_path):
    return _variant(tmp_path, "uses_tensorlib", lambda t: t.replace(
        "      INCLUDE 'ABA_PARAM.INC'", "      USE TENSORLIB\n      INCLUDE 'ABA_PARAM.INC'", 1
    ).replace(EMU, EMU + " + DEVIAT(E)"))


def test_the_normaliser_puts_the_pipelines_wording_in_the_cards_form():
    text = ("ValueError: dependency_roots do not resolve the closure of umat_iso.f: "
            "missing FISOTROPIC, SHEARMOD; ambiguous ; see x/dependency_report.json")
    assert pre.normalise(text) == "Helper lifting requires source definitions for ['FISOTROPIC', 'SHEARMOD']"
    assert pre.normalise("something else") == "something else"


def test_a_missing_helper_is_the_first_thing_said_even_with_no_deck(missing_helper, monkeypatch, capsys):
    monkeypatch.chdir(missing_helper.parent)
    assert check.main([str(missing_helper)]) == 3          # needs one thing from you: the helper's file
    out = capsys.readouterr().out
    card = out.split("=" * 70)[-1]                       # what the person is told, after the reading
    assert "SHEARMOD" in card and "--dependency-root" in card and "Whose move: you." in card
    assert "USER MATERIAL" not in card and "numbers this material needs" not in card
    assert "trial_deck" not in out and "usage:" not in out.lower()
    assert not list(missing_helper.parent.glob("*_material*.json"))     # no template for a routine that cannot run
    assert not (missing_helper.parent / "uses_shearmod_check").exists()


def test_a_module_the_program_cannot_read_is_named(missing_module, monkeypatch, capsys):
    monkeypatch.chdir(missing_module.parent)
    assert check.main([str(missing_module)]) == 3
    out = capsys.readouterr().out
    card = out.split("=" * 70)[-1]
    assert "TENSORLIB" in card and "--dependency-root" in card
    assert "USER MATERIAL" not in card and "numbers this material needs" not in card


def test_the_helper_supplied_in_a_root_lets_the_routine_through(missing_helper, tmp_path):
    folder = tmp_path / "helpers"
    folder.mkdir()
    (folder / "shearmod.f").write_text(
        "      SUBROUTINE SHEARMOD(E, XNU, EMU)\n      DOUBLE PRECISION E, XNU, EMU\n"
        "      EMU = E / (2.0D0 * (1.0D0 + XNU))\n      RETURN\n      END\n")
    facts = intake.scan_source(missing_helper)
    assert pre.preflight(missing_helper, facts, [], tmp_path / "w1") is not None
    assert pre.preflight(missing_helper, facts, [folder], tmp_path / "w2") is None


def test_unresolved_modules_are_those_no_file_defines(missing_module, tmp_path):
    facts = intake.scan_source(missing_module)
    assert pre.unresolved_modules(facts, [], missing_module) == ["TENSORLIB"]
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "t.f90").write_text("module tensorlib\ncontains\nend module tensorlib\n")
    assert pre.unresolved_modules(facts, [tmp_path / "lib"], missing_module) == []


def test_unlocated_anchors_with_an_unread_module_name_the_module_not_the_symptom(missing_module):
    facts = intake.scan_source(missing_module)
    summary = {"completion_issues": [{"kind": "missing_stress_update_regions"}]}
    state, reason = pre.refusal_from_summary(summary, exit_code=2, succeeded=False, facts=facts,
                                             roots=[], source=missing_module)
    assert "USEs TENSORLIB without defining it" in reason
    from umat_oti.app.refusal_cards import card_for
    card = card_for(state, reason)
    assert card.rule == "rule:module_use" and "module TENSORLIB" in card.sentence and card.whose_move == "you"
    # with no module to blame the card is the honest "not supported yet" one
    plain = pre.refusal_from_summary(summary, exit_code=2, succeeded=False)
    assert plain[1].startswith("anchors not located") and card_for(*plain).whose_move == "this program"
