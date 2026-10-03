"""``*INCLUDE, FILE=`` splices like ``INPUT=`` (G1b).

jpsferreira__UMAT-ABAQUS/test_in_abaqus/cube_umat.inp holds a ``*PARAMETER``
block (lines 60-70) and includes ``sec_ud.inp`` with ``*INCLUDE,
file=sec_ud.inp``; ``sec_ud.inp`` writes ``<KBULK>, <C10>, ...``. Only
``INPUT=`` was spliced, so the parent published nothing and the section deck
was refused as unresolved. Abaqus/Standard 2021.HF5 accepts ``FILE=`` and
substitutes the parent's parameters into the included file (datacheck in
corpus_campaign/batches/B7/gauss_g1b/include_file_check/). pass20 A/B: the
two jpsferreira sources move to cube_umat.inp:UD; nothing else moves.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.deck_pairing import _splice_file_includes, materials_in, pair

pytestmark = pytest.mark.unit

SOURCE = """\
      subroutine umat(stress,statev,ddsdde)
      emod = props(1)
      enu  = props(2)
      statev(1) = 0.d0
      return
      end
"""

PARENT = """\
*Node
1, 0., 0., 0.
*Element, type=C3D8, elset=ALL
1, 1, 1, 1, 1, 1, 1, 1, 1
*Parameter
EMOD=1000.0
ENU=0.3
*INCLUDE, file=sec.inp
"""

SECTION = """\
*Solid Section, elset=ALL, material=UD
*Material, name=UD
*User Material, constants=2
<EMOD>, <ENU>
*Depvar
1,
"""


def _repo(tmp_path: Path, parent: str = PARENT) -> Path:
    repo = tmp_path / "owner__repo"
    (repo / "test").mkdir(parents=True)
    (repo / "test" / "umat.for").write_text(SOURCE)
    (repo / "test" / "parent.inp").write_text(parent)
    (repo / "test" / "sec.inp").write_text(SECTION)
    return repo


def test_the_parent_publishes_the_included_block_with_its_parameters(tmp_path):
    repo = _repo(tmp_path)
    (block,) = materials_in(repo / "test" / "parent.inp")
    assert block.usable and block.values == (1000.0, 0.3)
    found = pair(repo / "test" / "umat.for", repo)
    assert found.found and found.material.deck.name == "parent.inp"
    assert found.material.values == (1000.0, 0.3)


def test_a_missing_file_include_is_named(tmp_path):
    repo = _repo(tmp_path, PARENT.replace("sec.inp", "gone.inp"))
    lines = (repo / "test" / "parent.inp").read_text().splitlines()
    spliced, missing = _splice_file_includes(lines, repo / "test" / "parent.inp")
    assert missing == ["gone.inp"]
    assert "** [unresolved include: gone.inp]" in spliced
    found = pair(repo / "test" / "umat.for", repo)
    assert not found.found and found.refusal_kind == "author_deck_unresolved"


def test_a_commented_include_is_not_spliced(tmp_path):
    repo = _repo(tmp_path, PARENT.replace("*INCLUDE", "**INCLUDE"))
    assert materials_in(repo / "test" / "parent.inp") == ()
