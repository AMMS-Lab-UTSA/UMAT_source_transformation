"""R1 of D-19a rev 2 (G2): a harvest row completes the author's own deck.

Only for ``author_deck_unresolved``: the deck beside the source fits and
leaves its constants as placeholders. Every placeholder needs an ``exact``
or ``interpreted`` harvest value (Q3); one missing, uncertain or
never-counted value leaves the source held back. A block that was rejected
is never completed. The experiment stays the author's; the material data is
``author_published_outside_deck``.

(jpsferreira umat_general, the fixture named in the plan, pairs with its
author's parent deck since G1b, so the fixtures here are synthetic.)
"""
import hashlib
from pathlib import Path

import pytest

from umat_oti.abaqus.deck_pairing import (AUTHOR_DECK_UNRESOLVED, HARVEST_SCHEMA_SHA256,
                                          pair)

pytestmark = pytest.mark.unit

SOURCE = """\
      subroutine umat(stress,statev,ddsdde)
      kbulk = props(1)
      c10   = props(2)
      c01   = props(3)
      k1    = props(4)
      k2    = props(5)
      kdisp = props(6)
      statev(2) = 0.d0
      return
      end
"""


def _deck(depvar: int = 2) -> str:
    return f"""\
*Node
1, 0., 0., 0.
*Element, type=C3D8, elset=ALL
1, 1, 1, 1, 1, 1, 1, 1, 1
*Solid Section, elset=ALL, material=UD
*Material, name=UD
*User Material, constants=6
<KBULK>,<C10>,<C01>,<K1>,<K2>,<KDISP>
*Depvar
{depvar},
"""


def _row(**over):
    values = {"KBULK": 1000.0, "C10": 1.0, "C01": 0.1, "K1": 0.1, "K2": 0.2, "KDISP": 0.1}
    constants = [{"index": i, "name": name, "value": value, "confidence": "exact",
                  "never_count_reason": None, "where": "cube_umat.inp", "line_or_page": 60 + i,
                  "quote": f"{name}={value}"}
                 for i, (name, value) in enumerate(values.items(), start=1)]
    for c in constants:
        c.update(over.get(c["name"], {}))
    return {"key": "row1", "source_id": "owner__repo/test/umat.for", "constants": constants}


def _repo(tmp_path: Path, deck: str) -> Path:
    repo = tmp_path / "owner__repo"
    (repo / "test").mkdir(parents=True)
    (repo / "test" / "umat.for").write_text(SOURCE)
    (repo / "test" / "sec.inp").write_text(deck)
    return repo


def test_without_a_harvest_the_authors_deck_is_unresolved(tmp_path):
    repo = _repo(tmp_path, _deck())
    found = pair(repo / "test" / "umat.for", repo)
    assert not found.found and found.refusal_kind == AUTHOR_DECK_UNRESOLVED


def test_a_complete_row_completes_it_with_six_values(tmp_path):
    repo = _repo(tmp_path, _deck())
    found = pair(repo / "test" / "umat.for", repo, harvest=_row())
    assert found.found and found.material.deck.name == "sec.inp"
    assert found.material.values == (1000.0, 1.0, 0.1, 0.1, 0.2, 0.1)
    d = found.as_dict()
    assert d["material_data_origin"] == "author_published_outside_deck"
    assert d["experiment_origin"] == "author"
    assert "harvest row row1" in found.why and "cube_umat.inp" in found.why


@pytest.mark.parametrize("change", [
    {"K2": {"name": "K_TWO", "index": 9}},                      # no match
    {"K2": {"confidence": "uncertain"}},
    {"K2": {"never_count_reason": "magnitude-inferred unit"}},
])
def test_one_missing_or_uncounted_value_leaves_it_held_back(tmp_path, change):
    repo = _repo(tmp_path, _deck())
    found = pair(repo / "test" / "umat.for", repo, harvest=_row(**change))
    assert not found.found and found.refusal_kind == AUTHOR_DECK_UNRESOLVED
    assert "The harvest row does not complete it" in found.refusal and "K2" in found.refusal


def test_a_rejected_block_is_never_completed(tmp_path):
    repo = _repo(tmp_path, _deck(depvar=1))      # writes STATEV(2) into *DEPVAR 1
    found = pair(repo / "test" / "umat.for", repo, harvest=_row())
    assert not found.found and found.refusal_kind == "author_block_rejected"


def test_a_row_for_another_source_is_not_used(tmp_path):
    repo = _repo(tmp_path, _deck())
    row = dict(_row(), source_id="owner__repo/other/umat.for")
    found = pair(repo / "test" / "umat.for", repo, harvest=row)
    assert not found.found and "not this source" in found.refusal


def test_the_frozen_harvest_schema_is_the_one_read():
    schema = (Path(__file__).resolve().parents[2]
              / "corpus_campaign/material_data/harvest_row.schema.json")
    if not schema.is_file():
        pytest.skip("campaign material_data not present")
    assert hashlib.sha256(schema.read_bytes()).hexdigest() == HARVEST_SCHEMA_SHA256
