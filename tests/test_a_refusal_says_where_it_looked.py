"""A refusal that does not say where it searched is a claim, not a finding.

Forty-one corpus entries came back as "no deck is paired with this source, so
it has no published material constants". That sentence asserts a negative
about somebody's repository without naming one thing that was examined, and a
reader cannot tell it apart from a pairing step that never ran. The pairing
scan already records the search -- which decks, how many constants each
publishes, how many the source's own PROPS references reach -- so the refusal
quotes it.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import verify_store_in_abaqus as verify  # noqa: E402

PROPOSAL = {
    "repository": "3MAH__simcoon",
    "pairing": {
        "alternatives": [f"3MAH__simcoon/examples/d{n}/parameters.inp"
                         for n in range(36)],
        "checked_by": "umat_oti.corpus.abaqus_deck",
        "verdict": "contradicted",
        "metadata": {"expected_nprops": 2},
        "evidence": ("none of the 36 decks publishes at least 2 constants "
                     "under *User Material or *UEL PROPERTY, which is how "
                     "far the PROPS references of UMAT in this source reach"),
    },
}


def test_the_refusal_names_the_repository_and_counts_what_it_read():
    said = verify.where_we_looked("3MAH__simcoon/UMAT_ABAQUS_ELASTIC.f", PROPOSAL)
    assert "36 .inp file(s)" in said
    assert "3MAH__simcoon" in said
    assert ".md, .rst and .txt" in said
    assert "inventing them" in said


def test_the_evidence_from_the_scan_is_carried_through_verbatim():
    said = verify.where_we_looked("3MAH__simcoon/x.f", PROPOSAL)
    assert PROPOSAL["pairing"]["evidence"] in said


def test_a_repository_with_no_deck_at_all_says_so():
    said = verify.where_we_looked("x__y/z.f", {"repository": "x__y",
                                               "pairing": {}})
    assert "no .inp file at all" in said
    assert "Searched" in said


def test_the_places_are_recorded_as_data_not_only_as_prose():
    places = verify.searched_places("3MAH__simcoon/x.f", PROPOSAL)
    assert places["decks_scanned"] == 36
    assert len(places["decks"]) == 36
    assert places["repository"] == "3MAH__simcoon"
    assert places["scanner"] == "umat_oti.corpus.abaqus_deck"
    assert places["expected_nprops"] == 2
    assert "extracted.inp" in places["documentation"]


def test_a_long_list_is_truncated_but_says_how_much_it_kept():
    proposal = {"repository": "big",
                "pairing": {"alternatives": [f"d{n}.inp" for n in range(120)]}}
    places = verify.searched_places("big/x.f", proposal)
    assert places["decks_scanned"] == 120
    assert len(places["decks"]) == 40
    assert places["decks_not_listed"] == 80


def test_the_record_carries_the_search():
    text = (pathlib.Path(__file__).resolve().parents[1]
            / "tools" / "verify_store_in_abaqus.py").read_text()
    assert '"searched_for_material_data": plan.searched' in text, (
        "the search would be computed and then dropped on the floor")


# ---------------------------------------------------------------------------
# and the panel a reader actually looks at shows it too
# ---------------------------------------------------------------------------
def test_the_corpus_panel_shows_what_the_search_read():
    from umat_oti.app.corpus_view import _requirements

    row = {"stage": "needs_material_data",
           "searched_for_material_data": {
               "repository": "3MAH__simcoon", "decks_scanned": 36,
               "evidence": "none of the 36 decks publishes at least 2 constants"}}
    detail = next(r.detail for r in _requirements(row)
                  if r.name == "published material constants")
    assert "36 .inp file(s)" in detail and "3MAH__simcoon" in detail


def test_a_row_from_before_the_search_was_recorded_still_reads():
    from umat_oti.app.corpus_view import _requirements

    row = {"stage": "needs_material_data", "reason": "nothing publishes them"}
    detail = next(r.detail for r in _requirements(row)
                  if r.name == "published material constants")
    assert detail == "nothing publishes them"


def test_a_repository_with_no_deck_says_so_in_the_panel():
    from umat_oti.app.corpus_view import _requirements

    row = {"stage": "needs_material_data",
           "searched_for_material_data": {"repository": "x__y",
                                          "decks_scanned": 0}}
    detail = next(r.detail for r in _requirements(row)
                  if r.name == "published material constants")
    assert "no .inp file at all" in detail
