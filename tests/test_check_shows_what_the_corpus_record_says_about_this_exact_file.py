"""The corpus record's result for a file that matches it byte for byte: a separate line, never a false green."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.app import verified_lookup as vl            # noqa: E402

pytestmark = pytest.mark.unit
REGISTRY = REPO / "paper_results" / "corpus" / "corpus_registry.json"
TABLE = json.loads((REPO / "docs" / "evidence" / "verified_digests.json").read_text())


def _builder():
    spec = importlib.util.spec_from_file_location("build_digest_table", REPO / "tools" / "build_verified_digest_table.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_table_is_the_registry_it_was_built_from():
    """Rebuilt without the discovery cache (deck digests are carried over from the table) it must be identical."""
    rebuilt = _builder().build(REGISTRY, REPO / "no-such-cache", TABLE)
    assert rebuilt == TABLE
    assert TABLE["records"] == len(TABLE["rows"]) == len(json.loads(REGISTRY.read_text())["records"])


def test_green_count_over_every_row_equals_the_fully_verified_count_and_no_other_row_is_green():
    registry = json.loads(REGISTRY.read_text())["records"]
    verified = sum(1 for r in registry if r["terminal_state"] == "fully_verified")
    assert verified > 0
    green, wrong = 0, []
    for row in TABLE["rows"]:
        match = vl.judge(vl.find_rows(TABLE, row["sha256"], row["deck_sha256"] or None),
                         deck_compared=bool(row["deck_sha256"]))
        if match.colour == "green":
            green += 1
            if row["state"] != "fully_verified" or not row["all_gates_true"]:
                wrong.append(row["source_id"])
    assert not wrong, wrong[:5]
    assert green == verified


def test_a_verified_row_whose_gates_are_not_all_true_is_never_green():
    row = next(r for r in TABLE["rows"] if r["state"] == "fully_verified")
    for gate in row["gates"]:
        broken = json.loads(json.dumps(row))
        broken["gates"][gate] = "false"
        table = {"registry_generated": TABLE["registry_generated"], "rows": [broken]}
        assert vl.judge([broken], deck_compared=True).colour != "green", gate
    unknown = json.loads(json.dumps(row))
    unknown["gates"][next(iter(unknown["gates"]))] = "no_evidence_block"
    assert vl.judge([unknown], deck_compared=True).colour != "green"


def test_a_row_that_says_derivative_truncated_is_not_green_even_with_all_gates_true():
    row = json.loads(json.dumps(next(r for r in TABLE["rows"] if r["state"] == "fully_verified")))
    row["state"] = "derivative_truncated"
    assert vl.judge([row], deck_compared=True).colour == "amber"


def _files(tmp_path, umat_text, deck_text=None):
    umat = tmp_path / "u.for"
    umat.write_text(umat_text)
    deck = None
    if deck_text is not None:
        deck = tmp_path / "d.inp"
        deck.write_text(deck_text)
    return umat, deck


def _table_for(umat, deck, state="fully_verified", gates="true"):
    return {"registry_generated": "2026-10-06T18:47:50+00:00", "rows": [{
        "source_id": "x/u.for", "sha256": vl._digest(umat), "deck": "x/d.inp",
        "deck_sha256": vl._digest(deck) if deck is not None else "", "state": state, "run": "pass23",
        "gates": {g: gates for g in TABLE["rows"][0]["gates"]}, "all_gates_true": gates == "true", "reason": ""}]}


def test_the_exact_files_match_and_one_changed_byte_does_not(tmp_path):
    umat, deck = _files(tmp_path, "      SUBROUTINE UMAT\n      END\n", "*USER MATERIAL, CONSTANTS=1\n1.\n")
    table = _table_for(umat, deck)
    match = vl.lookup(umat, deck, table=table)
    assert match is not None and match.colour == "green"
    lines = vl.render(match, final="blue", why="Nothing could be run here. Second sentence.", table=table)
    assert lines[0].startswith("On record: this exact file was verified earlier (run pass23, 2026-10-06: fully_verified). "
                               "This run could not repeat it: nothing could be run here.")
    assert not any(w in " ".join(lines) for w in ("GREEN", "AMBER", "BLUE", "RED"))
    umat.write_text("      SUBROUTINE UMAT\n      END \n")
    assert vl.lookup(umat, deck, table=table) is None, "one extra space in the UMAT"
    umat.write_text("      SUBROUTINE UMAT\n      END\n")
    deck.write_text("*USER MATERIAL, CONSTANTS=1\n2.\n")
    other = vl.lookup(umat, deck, table=table)
    assert other is not None and other.deck_differs and other.colour != "green", "one changed digit in the deck"
    assert vl.verified_elsewhere(other) is None, "a result for another deck is not this run's result"
    assert vl.verified_with_other_deck(other) == ("pass23", ["d.inp"])
    text = " ".join(vl.render(other, final="amber", table=table, deck_name="mine.inp"))
    assert "this file was verified with a different deck: d.inp" in text and "Your deck mine.inp is not that one" in text
    assert not any(w in text for w in ("GREEN", "AMBER", "BLUE", "RED"))


def test_a_row_that_is_not_verified_shows_its_state_and_its_card_in_the_colour_of_that_card(tmp_path):
    umat, deck = _files(tmp_path, "      SUBROUTINE UMAT\n      END\n", "*USER MATERIAL, CONSTANTS=1\n1.\n")
    table = _table_for(umat, deck, state="tangent_not_verified", gates="no_evidence_block")
    lines = vl.render(vl.lookup(umat, deck, table=table), final="blue", table=table)
    assert lines[0].startswith("On record: this exact file ended as tangent_not_verified (run pass23, 2026-10-06), not as verified.")
    assert not any(w in " ".join(lines) for w in ("GREEN", "AMBER", "BLUE", "RED"))


def test_without_a_deck_the_line_is_green_only_if_every_matching_row_is(tmp_path):
    umat, _ = _files(tmp_path, "      SUBROUTINE UMAT\n      END\n")
    good = _table_for(umat, None)["rows"][0]
    bad = dict(good, state="tangent_not_verified", deck="y/d2.inp",
               gates={g: "no_evidence_block" for g in good["gates"]}, all_gates_true=False)
    assert vl.lookup(umat, None, table={"registry_generated": "2026-10-06", "rows": [good]}).colour == "green"
    mixed = vl.lookup(umat, None, table={"registry_generated": "2026-10-06", "rows": [good, bad]})
    assert mixed.colour != "green"
    assert "GREEN" not in " ".join(vl.render(mixed, final="red", table={"registry_generated": "2026-10-06", "rows": [good, bad]}))


def test_the_line_is_printed_by_check_only_after_the_verdict_and_never_in_the_middle(tmp_path, monkeypatch, capsys):
    import shutil
    from umat_oti.app import check_command as check
    folder = tmp_path / "w"
    folder.mkdir()
    umat = folder / "j2_props.f"
    shutil.copy(REPO / "UMATs" / "UMATs" / "generic_ps" / "j2_props.f", umat)
    table = _table_for(umat, None)
    monkeypatch.setattr(vl, "load_table", lambda path=None: table)
    monkeypatch.chdir(tmp_path)
    check.main([str(umat)])
    out = capsys.readouterr().out
    assert "BLUE: I NEED ONE THING FROM YOU" in out
    assert out.index("On record: this exact file was verified earlier") > out.index("BLUE: I NEED ONE THING FROM YOU")
    assert "GREEN" not in out, "no green word anywhere unless the final verdict is green"
    assert out.rstrip().splitlines()[-2].startswith("On record:") or out.rstrip().splitlines()[-1].startswith("  (")


@pytest.mark.parametrize("deck_text", ["", "** only a comment\n", "*HEADING\nno material here\n*NODE\n1,0.,0.,0.\n"])
def test_an_empty_deck_or_one_without_a_user_material_block_never_shows_the_record(tmp_path, monkeypatch, capsys, deck_text):
    import shutil
    from umat_oti.app import check_command as check
    folder = tmp_path / "w"
    folder.mkdir()
    umat = folder / "j2_props.f"
    shutil.copy(REPO / "UMATs" / "UMATs" / "generic_ps" / "j2_props.f", umat)
    deck = folder / "d.inp"
    deck.write_text(deck_text)
    table = _table_for(umat, None)                       # a UMAT-only green row exists for these bytes
    monkeypatch.setattr(vl, "load_table", lambda path=None: table)
    monkeypatch.chdir(tmp_path)
    check.main([str(umat), "--deck", str(deck)])
    out = capsys.readouterr().out
    assert "Note: The deck d.inp" in out
    assert "On record" not in out and "GREEN" not in out


@pytest.mark.parametrize("final", [None, "green", "amber", "blue", "red"])
@pytest.mark.parametrize("state", ["fully_verified", "tangent_not_verified", "transform_refused", "missing_material_data",
                                   "derivative_truncated", "not_a_umat"])
def test_a_green_word_appears_only_when_the_final_verdict_is_green(tmp_path, state, final):
    umat, deck = _files(tmp_path, "      SUBROUTINE UMAT\n      END\n", "x\n")
    table = _table_for(umat, deck, state=state, gates="true" if state == "fully_verified" else "no_evidence_block")
    lines = vl.render(vl.lookup(umat, deck, table=table), final=final, why="x", table=table)
    words = " ".join(lines)
    assert not any(w in words for w in ("GREEN", "AMBER", "BLUE", "RED")), words
