"""Every pairing refusal names which of the four it is (G1, D-19a rev 2 R0).

The routing of a source with no usable author deck depends on WHY there is
none: a repository with no *USER MATERIAL block at all, or one whose blocks
all belong to other sources, may get a council-designed experiment; an
author's own block that does not fit stays refused; an author's deck that
fits and leaves its constants as placeholders is completed from the harvest
and stays the author's experiment.

Over the 64 pass20 needs_material_data rows the split is 45 / 12 / 6 / 1
(no_deck_in_repository / no_deck_names_this_source / author_deck_unresolved /
author_block_rejected), 44 / 12 / 5 / 1 without the two duplicates:
corpus_campaign/batches/B7/gauss_g1/split_g1.json.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.deck_pairing import (AUTHOR_BLOCK_REJECTED,
                                          AUTHOR_DECK_UNRESOLVED,
                                          NO_DECK_IN_REPOSITORY,
                                          NO_DECK_NAMES_THIS_SOURCE,
                                          REFUSAL_KINDS, pair)

pytestmark = pytest.mark.unit

#: Reads PROPS(1:3), writes STATEV(1:4).
SOURCE = """\
      subroutine umat(stress,statev,ddsdde)
      emod = props(1)
      enu  = props(2)
      sy   = props(3)
      statev(4) = 0.d0
      return
      end
"""


def _deck(constants: str, count: int, depvar: int) -> str:
    return f"""\
*Node
1, 0., 0., 0.
*Element, type=C3D8
1, 1, 1, 1, 1, 1, 1, 1, 1
*Elset, elset=ALL
 1,
*Solid Section, elset=ALL, material=MAT
*Material, name=MAT
*Depvar
    {depvar},
*User Material, constants={count}
    {constants}
"""


FITS = _deck("200000., 0.3, 250.", 3, 4)
TOO_FEW_STATEV = _deck("200000., 0.3, 250.", 3, 2)
TOO_FEW_CONSTANTS = _deck("200000.", 1, 4)
PLACEHOLDERS = _deck("<E>, <NU>, <SY>", 3, 4)


def _repo(tmp_path: Path, decks: dict) -> tuple[Path, Path]:
    repo = tmp_path / "owner__repo"
    source = repo / "src" / "umat.f"
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE)
    for relative, text in decks.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return source, repo


def _kind(tmp_path, decks):
    source, repo = _repo(tmp_path, decks)
    found = pair(source, repo)
    assert not found.found, found.why
    assert found.as_dict()["refusal_kind"] == found.refusal_kind
    return found


def test_no_block_anywhere(tmp_path):
    found = _kind(tmp_path, {"README.md": "nothing here\n"})
    assert found.refusal_kind == NO_DECK_IN_REPOSITORY


def test_every_block_rejected_and_none_is_the_authors(tmp_path):
    found = _kind(tmp_path, {"other/other_model.inp": TOO_FEW_CONSTANTS})
    assert found.refusal_kind == NO_DECK_NAMES_THIS_SOURCE


def test_every_block_rejected_and_one_sits_beside_the_source(tmp_path):
    found = _kind(tmp_path, {"src/job.inp": TOO_FEW_STATEV})
    assert found.refusal_kind == AUTHOR_BLOCK_REJECTED


def test_every_block_rejected_and_the_readme_names_one_for_this_source(tmp_path):
    found = _kind(tmp_path, {
        "decks/job.inp": TOO_FEW_STATEV,
        "README.md": "| input file | subroutine |\n|---|---|\n| job.inp | umat.f |\n"})
    assert found.refusal_kind == AUTHOR_BLOCK_REJECTED


def test_the_block_beside_it_is_rejected_while_another_directory_fits(tmp_path):
    found = _kind(tmp_path, {"src/job.inp": TOO_FEW_STATEV,
                             "other/other_model.inp": FITS})
    assert found.refusal_kind == AUTHOR_BLOCK_REJECTED
    assert "the deck beside this source" in found.refusal


def test_the_deck_beside_it_leaves_its_constants_as_placeholders(tmp_path):
    found = _kind(tmp_path, {"src/job.inp": PLACEHOLDERS})
    assert found.refusal_kind == AUTHOR_DECK_UNRESOLVED


def test_a_pairing_has_no_refusal_kind(tmp_path):
    source, repo = _repo(tmp_path, {"src/job.inp": FITS})
    found = pair(source, repo)
    assert found.found and found.refusal_kind == ""


def test_the_kinds_are_the_four_routes():
    assert set(REFUSAL_KINDS) == {NO_DECK_IN_REPOSITORY, NO_DECK_NAMES_THIS_SOURCE,
                                  AUTHOR_BLOCK_REJECTED, AUTHOR_DECK_UNRESOLVED}


def test_the_authors_rejected_block_is_named_first_with_its_depvar(tmp_path):
    """mholla iso_Mandel: the README's deck declares *DEPVAR 3 and the routine
    writes STATEV(5); it was the seventh rejection and the reason quoted six."""
    decks = {f"other/a{i}.inp": TOO_FEW_CONSTANTS for i in range(7)}
    decks["decks/z_own.inp"] = TOO_FEW_STATEV
    decks["README.md"] = "- z_own.inp = umat.f\n"
    found = _kind(tmp_path, decks)
    assert found.refusal_kind == AUTHOR_BLOCK_REJECTED
    assert ("the author's own block: z_own.inp:MAT: the routine subscripts "
            "STATEV(4) and this block declares only *DEPVAR 2") in found.refusal
