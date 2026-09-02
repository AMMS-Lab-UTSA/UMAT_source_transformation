"""NSTATV comes from the deck that declares it, not from a count of something else.

The triage set nstatv_hint to ``len(promoted_variables)`` -- the number of
stress-path names the transformer lifts into OTI arithmetic. That cardinality
is not a statement about state at all, and it disagreed with the author's own
figure in sixty-seven of seventy-one cases: a growth shell was driven with
NSTATV=78 where its deck says 9.

Nothing was written out of bounds, and that is luck rather than design -- the
count happened to exceed the largest literal STATEV subscript in every case
here. But a model that loops ``DO I = 1, NSTATV`` over its state ran that loop
across sixty-nine slots its author never meant it to touch.

*DEPVAR is how an Abaqus user declares the count, and it sits in the same deck
the material constants are already read from. Reading it is the same move as
reading the source's own SDVINI for the initial state.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_discovered_verification import (  # noqa: E402
    _declared_nstatv, deck_state_variable_count,
)


class TestReadingTheDeck:
    def test_the_count_on_the_line_after_depvar(self, tmp_path):
        deck = tmp_path / "d.inp"
        deck.write_text("*Material, name=NeoHookean\n*Depvar\n      9,\n",
                        encoding="utf-8")
        assert deck_state_variable_count(deck) == 9

    def test_case_and_spacing_do_not_matter(self, tmp_path):
        deck = tmp_path / "d.inp"
        deck.write_text("*DEPVAR\n   16\n", encoding="utf-8")
        assert deck_state_variable_count(deck) == 16

    def test_parameters_on_the_depvar_line_are_ignored(self, tmp_path):
        deck = tmp_path / "d.inp"
        deck.write_text("*Depvar, delete=4\n      12,\n", encoding="utf-8")
        assert deck_state_variable_count(deck) == 12

    def test_a_deck_without_depvar_declares_nothing(self, tmp_path):
        deck = tmp_path / "d.inp"
        deck.write_text("*Material, name=Elastic\n*Elastic\n210000., 0.3\n",
                        encoding="utf-8")
        assert deck_state_variable_count(deck) == 0

    def test_an_unreadable_deck_declares_nothing(self, tmp_path):
        assert deck_state_variable_count(tmp_path / "missing.inp") == 0


class TestChoosingTheCount:
    def _item(self, deck: str, hint: int) -> dict:
        return {"row": {"nstatv_hint": str(hint)},
                "entry": {"material": {"provenance": deck}}}

    def test_the_deck_wins_over_the_hint(self, tmp_path):
        (tmp_path / "d.inp").write_text("*Depvar\n 9,\n", encoding="utf-8")
        count, provenance = _declared_nstatv(
            self._item("d.inp, *Material name=X at line 3", 78), tmp_path)
        assert count == 9
        assert "*DEPVAR" in provenance and "d.inp" in provenance

    def test_the_hint_stands_in_when_the_deck_is_silent(self, tmp_path):
        (tmp_path / "d.inp").write_text("*Material, name=X\n", encoding="utf-8")
        count, provenance = _declared_nstatv(self._item("d.inp", 4), tmp_path)
        assert count == 4
        assert "no *DEPVAR" in provenance

    def test_the_fallback_says_what_it_is(self, tmp_path):
        _, provenance = _declared_nstatv(self._item("gone.inp", 4), tmp_path)
        # A reader must be able to tell a declared count from a stand-in.
        assert "promoted-variable count" in provenance

    def test_no_deck_named_at_all(self, tmp_path):
        count, _ = _declared_nstatv({"row": {"nstatv_hint": "7"},
                                     "entry": {}}, tmp_path)
        assert count == 7


class TestAgainstTheRealCorpus:
    def test_the_declared_count_is_recorded_for_every_case(self):
        """Whatever the number is, the report must say where it came from."""
        from run_discovered_verification import _case, cases_from  # noqa: PLC0415

        triage = REPO_ROOT / "paper_results/discovery/discovery_triage.csv"
        proposals = REPO_ROOT / "paper_results/discovery/proposed_corpus_entries.json"
        cache = Path(__import__("os").environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO_ROOT.parent / "discovery_cache")
        if not (triage.is_file() and proposals.is_file() and cache.is_dir()):
            return
        for item in cases_from(triage, proposals, cache):
            case = _case(item, cache)
            assert case.nstatv >= 1
            assert item["nstatv_provenance"]
