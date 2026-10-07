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
    assert check.main([str(missing_helper)]) == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and "SHEARMOD" in out and "--dependency-root" in out
    assert "USER MATERIAL" not in out and "trial_deck" not in out and "usage:" not in out.lower()
    assert not list(missing_helper.parent.glob("*_material*.json"))     # no template for a routine that cannot run
    assert not (missing_helper.parent / "uses_shearmod_check").exists()


def test_a_module_the_program_cannot_read_is_named(missing_module, monkeypatch, capsys):
    monkeypatch.chdir(missing_module.parent)
    assert check.main([str(missing_module)]) == 2
    out = capsys.readouterr().out
    assert "module TENSORLIB" in out and "DEVIAT" in out and "--dependency-root" in out
    assert "USER MATERIAL" not in out


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


def test_a_routine_that_converts_goes_on_to_the_material_question(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "ok"
    folder.mkdir()
    source = folder / "j2_props.f"
    shutil.copy(J2, source)
    monkeypatch.chdir(folder)
    assert check.main([str(source)]) == 3                      # converts; then needs the constants
    out = capsys.readouterr().out
    assert "can find where it sets stress and stiffness  [ok]" in out
    assert (folder / "j2_props_material.json").is_file()
