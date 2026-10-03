"""A deck the documentation names for a source is the author's (G1b).

``ahartloper__UVC_MatMod/Abaqus/testing/readme.md`` states the pairing in a
list, not a table -- ``- Cube_Cyclic_Disp_UMAT.inp = UVCmultiaxial.for`` --
in a subdirectory, and the matcher read only top-level tables, so the
multiaxial and plane-stress UMATs were refused with their own test decks
beside the readme. ``mholla__growth``'s README names
``cube_1_C3D8_stretch_xyz_iso_Mandel.inp``, which is not in the repository.
A misnamed deck is resolved only when exactly one deck can be meant.

pass20 A/B (corpus_campaign/batches/B7/gauss_g1b/): 5 of 279 pairings move,
all to the deck the documentation states.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.deck_pairing import pair, stated_pairings

pytestmark = pytest.mark.unit

SOURCE = """\
      subroutine umat(stress,statev,ddsdde)
      emod = props(1)
      enu  = props(2)
      statev(1) = 0.d0
      return
      end
"""


def _deck(first: str) -> str:
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
    1,
*User Material, constants=2
    {first}, 0.3
"""


def _repo(tmp_path: Path, files: dict) -> Path:
    repo = tmp_path / "owner__repo"
    for relative, text in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return repo


def test_a_list_line_in_a_subdirectory_readme_pairs_its_deck(tmp_path):
    repo = _repo(tmp_path, {
        "src/multi.for": SOURCE,
        "src/testing/a_first.inp": _deck("100."),
        "src/testing/b_second.inp": _deck("200."),
        "src/testing/readme.md": "Decks:\n- b_second.inp = multi.for\n"})
    found = pair(repo / "src/multi.for", repo)
    assert found.found and found.material.deck.name == "b_second.inp"
    assert "README states that b_second.inp runs with multi.for" in found.why


def test_a_line_naming_two_decks_states_nothing(tmp_path):
    repo = _repo(tmp_path, {
        "src/multi.for": SOURCE,
        "src/a_first.inp": _deck("100."),
        "src/b_second.inp": _deck("200."),
        "README.md": "compare a_first.inp and b_second.inp with multi.for\n"})
    assert stated_pairings(repo)[0] == {}


def test_a_misnamed_deck_is_resolved_only_when_one_deck_can_be_meant(tmp_path):
    table = ("| Input files | UMAT files |\n|---|---|\n"
             "| cube_xyz_iso_stretch.inp | umat_iso_stretch.f |\n"
             "| cube_xyz_iso_mandel.inp | umat_iso_mandel.f |\n")
    files = {"umats/umat_iso_mandel.f": SOURCE,
             "decks/cube_xyz_iso.inp": _deck("100."),
             "decks/cube_xyz_mandel.inp": _deck("200."),
             "README.md": table}
    pairs, notes = stated_pairings(_repo(tmp_path / "a", files))
    # iso_stretch can only mean cube_xyz_iso; that leaves cube_xyz_mandel as
    # the only deck iso_mandel can mean
    assert pairs["umat_iso_stretch.f"] == {"cube_xyz_iso.inp"}
    assert pairs["umat_iso_mandel.f"] == {"cube_xyz_mandel.inp"}
    assert "not in the repository" in notes["cube_xyz_mandel.inp"]
    repo = tmp_path / "a" / "owner__repo"
    found = pair(repo / "umats/umat_iso_mandel.f", repo)
    assert found.found and found.material.deck.name == "cube_xyz_mandel.inp"
    assert "is the only deck it can mean" in found.why

    # without the iso_stretch row both decks fit the misname: no statement
    ambiguous = dict(files, **{"README.md": table.splitlines()[0] + "\n"
                               + table.splitlines()[1] + "\n"
                               + table.splitlines()[3] + "\n"})
    pairs, _notes = stated_pairings(_repo(tmp_path / "b", ambiguous))
    assert pairs["umat_iso_mandel.f"] == {"cube_xyz_iso_mandel.inp"}
