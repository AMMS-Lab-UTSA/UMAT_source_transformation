"""B20, Vera's pass25 rulings (rules written before they were run).

1. A deck from a SIBLING example folder is not "the author's own single-element test of this
   material": the provenance says it was verified with a sibling example's deck. Sibling =
   same repository, neither directory an ancestor of the other, common ancestor below the root.
2. The census uses Vera's wording; the rows on separate lines and the freed sources without
   material come from paper_results/corpus/census_lines.json and are not counted in the headline.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import build_corpus_registry as reg  # noqa: E402

pytestmark = pytest.mark.unit

OWN = ("deck.inp: deck.inp *MATERIAL M: 2 constants, *DEPVAR 0 -- deck.inp declares exactly "
       "one element, so it is the author's own single-element test of this material; a section "
       "in deck.inp attaches M to C3D8R")


def test_a_sibling_examples_deck_is_said_to_be_one_and_the_sentence_is_dropped():
    text = reg.sibling_deck_provenance(
        "o__r/examples/neo/neo.for", "o__r/examples/_template/abaqus/job.inp", OWN)
    assert "verified with a sibling example's deck (_template/abaqus)" in text
    assert "the author's own single-element test" not in text
    assert "a section in deck.inp attaches M to C3D8R" in text        # the rest is kept


@pytest.mark.parametrize("source, deck", [
    ("o__r/umat/u.for", "o__r/umat/u.inp"),                   # same directory
    ("o__r/umat/u.for", "o__r/umat/jobs/u.inp"),              # deck below the source
    ("o__r/src/u.for", "o__r/input/u.inp"),                   # common ancestor is the root
    ("o__r/a/u.for", "o__s/a/u.inp"),                         # another repository
])
def test_canary_a_decks_that_is_the_sources_own_keeps_its_sentence(source, deck):
    assert reg.deck_is_a_siblings(source, deck) == ""
    assert reg.sibling_deck_provenance(source, deck, OWN) == OWN


def test_the_rule_changes_exactly_the_two_rows_it_was_written_for():
    path = REPO / "paper_results/corpus/corpus_registry.json"
    if not path.is_file():
        pytest.skip("no registry")
    changed = []
    for record in json.loads(path.read_text(encoding="utf-8"))["records"]:
        new = reg.sibling_deck_provenance(record["source_id"], record["deck"],
                                          record["material_provenance"])
        if new != record["material_provenance"] and "sibling example's deck" in new:
            changed.append(record["source_id"].split("/")[-1])
    assert sorted(changed) == ["array_with_two_pixel_z.for", "neo_hookean_umat.for"]


def _records(spec):
    out = []
    for source_id, state in spec:
        record = reg.Record(source_id=source_id, repository="o/r")
        record.terminal_state, record.kind = state, reg.kind_of(state)
        record.adequately_specified = True
        out.append(record)
    return out


def test_the_census_lines_follow_the_wording_and_separate_lines_leave_the_headline(tmp_path):
    ids = [f"o__r/u{i}.for" for i in range(6)]
    population = tmp_path / "pop.json"
    population.write_text(json.dumps({"acquired": 6, "eligible": 6, "verified": 2,
                                      "source_ids": ids, "eligible_source_ids": ids}))
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps({
        "separate_line_rows": [{"source_id": ids[0], "label": "oriented-frame instrument",
                                "short": "U0"},
                               {"source_id": ids[1], "label": "sibling-deck provenance",
                                "short": "U1"}],
        "freed_but_no_material_kept_in": [ids[4], ids[5]]}))
    records = _records([(ids[0], "fully_verified"), (ids[1], "fully_verified"),
                        (ids[2], "fully_verified"), (ids[3], "transform_refused"),
                        (ids[4], "missing_material_data"), (ids[5], "missing_material_data")])
    for record in records[4:]:
        record.adequately_specified = False
    base = reg.pass23_census(records, population, lines)["pass23_population"]
    assert base["line_as_published"] == "2 of 6 as published (pass23)"
    assert base["line_corrected"] == ("1 of 6 under the corrected pipeline (pass25), "
                                      "provisional until the rerun")
    assert base["line_separate"] == (
        "+2 on separate lines (oriented-frame instrument 1: U0; sibling-deck provenance 1: U1)")
    # the two freed sources without material stay IN the revised denominator
    assert base["line_revised"].startswith("1 of 6 = 6 - 0 + 0")
    assert "kept in" in base["line_revised"]
    assert base["line_247"].startswith("4 = 6 minus the 2 freed sources")
    assert "never as 'of 4' alone" in base["line_247"]
    # moving a row off the separate lines puts it back in the headline
    lines.write_text(json.dumps({"separate_line_rows": [], "freed_but_no_material_kept_in": []}))
    again = reg.pass23_census(records, population, lines)["pass23_population"]
    assert again["line_corrected"].startswith("3 of 6 ")
    assert again["line_separate"] == "+0 on separate lines"


def test_the_committed_lines_file_names_the_two_rows_and_the_five_sources():
    data = json.loads((REPO / "paper_results/corpus/census_lines.json").read_text(encoding="utf-8"))
    assert [row["short"] for row in data["separate_line_rows"]] == [
        "PLANESTRESS-ORTHOTROPIC", "neo_hookean_umat"]
    assert len(data["freed_but_no_material_kept_in"]) == 5
