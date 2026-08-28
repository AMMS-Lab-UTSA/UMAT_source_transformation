"""The deck parser reads what a deck declares, and never fills a gap.

A source's material vector is the thing the corpus round cannot invent, and
for most externally authored UMATs the only place it is written down is the
example deck the author shipped. Reading it is worth doing; guessing at it is
the one thing this project forbids, so a deck that declares nothing must yield
nothing and a deck that contradicts itself must say so.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from umat_oti.corpus.abaqus_deck import DeckMaterial, parse_deck

# The pinned snapshot, by the convention the rest of the
# suite uses: an absolute path here records this machine's
# home directory in a tracked file.
SNAPSHOT_ROOT = Path(
    os.environ.get("UMAT_OTI_SNAPSHOT_ROOT")
    or REPO_ROOT.parent / "Residual_Assembler" / "sources")


def _write(tmp_path: Path, text: str) -> Path:
    deck = tmp_path / "job.inp"
    deck.write_text(text, encoding="utf-8")
    return deck


def test_a_plain_material_block_is_read(tmp_path: Path):
    deck = _write(tmp_path, """\
*Material, name=STEEL
*User Material, constants=4
210000.0, 0.3, 250.0, 2000.0
*Depvar
1
""")
    (material,) = parse_deck(deck)
    assert material.name == "STEEL"
    assert material.props == [210000.0, 0.3, 250.0, 2000.0]
    assert material.declared_constants == 4
    assert material.nstatv == 1
    assert material.consistent


def test_keywords_are_case_and_space_insensitive(tmp_path: Path):
    deck = _write(tmp_path, """\
*MATERIAL,NAME=CRYSTAL
*USER MATERIAL,CONSTANTS=3,UNSYMM
1.0, 2.0, 3.0
*DEPVAR
125
""")
    (material,) = parse_deck(deck)
    assert material.props == [1.0, 2.0, 3.0]
    assert material.unsymmetric
    assert material.nstatv == 125


def test_comment_lines_between_data_are_ignored(tmp_path: Path):
    deck = _write(tmp_path, """\
*Material, name=M
*User Material, constants=4
** all the constants below must be real numbers
1.0, 2.0,
** a note in the middle of the vector
3.0, 4.0
""")
    (material,) = parse_deck(deck)
    assert material.props == [1.0, 2.0, 3.0, 4.0]
    assert material.consistent


def test_a_declared_count_that_disagrees_is_reported_not_repaired(tmp_path: Path):
    """The Huang/Kysar deck does exactly this, and it must not be smoothed."""
    deck = _write(tmp_path, """\
*Material, name=M
*User Material, constants=160
1.0, 2.0, 3.0
""")
    (material,) = parse_deck(deck)
    assert material.props == [1.0, 2.0, 3.0], "the values must not be padded"
    assert material.declared_constants == 160
    assert not material.consistent
    assert any("160" in p and "3 values" in p for p in material.problems)


def test_a_deck_with_no_material_yields_nothing(tmp_path: Path):
    deck = _write(tmp_path, "*Heading\na mesh and nothing else\n*Node\n1, 0., 0.\n")
    assert parse_deck(deck) == []


def test_fortran_exponents_are_read(tmp_path: Path):
    deck = _write(tmp_path, "*Material, name=M\n*User Material, constants=2\n1.5D-3, 2.0d6\n")
    (material,) = parse_deck(deck)
    assert material.props == [1.5e-3, 2.0e6]


def test_several_materials_in_one_deck_stay_separate(tmp_path: Path):
    deck = _write(tmp_path, """\
*Material, name=A
*User Material, constants=2
1.0, 2.0
*Material, name=B
*User Material, constants=1
9.0
*Depvar
7
""")
    a, b = parse_deck(deck)
    assert (a.name, a.props) == ("A", [1.0, 2.0])
    assert (b.name, b.props, b.nstatv) == ("B", [9.0], 7)
    assert a.nstatv is None, "B's Depvar must not attach to A"


def test_every_value_carries_where_it_came_from(tmp_path: Path):
    deck = _write(tmp_path, "*Material, name=M\n*User Material, constants=1\n5.0\n")
    (material,) = parse_deck(deck)
    record = material.as_dict()
    assert str(deck) in record["provenance"]
    assert "M" in record["provenance"]
    assert record["line_numbers"]["user_material"] == 2


@pytest.mark.skipif(not SNAPSHOT_ROOT.is_dir(), reason="snapshot root absent")
def test_the_real_huang_kysar_deck_reads_and_reports_its_contradiction():
    deck = (SNAPSHOT_ROOT / "license-unknown" / "Huang_Kysar_Single_Crystal_UMAT"
            / "umatcryspl_mod.inp")
    if not deck.is_file():
        pytest.skip("that deck is not in this snapshot")
    (material,) = parse_deck(deck)
    assert material.name == "CRYSTAL"
    assert material.nstatv == 125
    assert material.declared_constants == 160
    assert len(material.props) == 46
    assert not material.consistent, (
        "the deck says 160 constants and gives 46; a parser that returned a "
        "clean vector here would be inventing the other 114")
