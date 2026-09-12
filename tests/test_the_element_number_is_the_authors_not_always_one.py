"""A UMAT is handed NOEL, and some of the corpus indexes with it.

``irfancn/Abaqus-UEL-elastic/uel_elastic.for`` is a user-element demo whose
``umat`` is the author's overlay material. Its last four lines are

    kelem = noel - nelem            ! nelem = 185
    do k1 = 1, nsdv
      statev(k1) = uvars(kelem, k1, npt)
    end do

and the author's own ``decoy`` elements are numbered 186 to 370, so ``kelem``
runs 1..185 in his model. A generated deck that calls its single element ``1``
makes that ``-184``, the routine reads far outside ``common/custom/uvars`` and
Abaqus dies with ``signal 11 (Segmentation fault)`` in the ELEMENT LOOP --
recorded against pass9 as ``original_job_failed``, which reads as a verdict on
the author's code for something that is entirely our numbering.

Note what is NOT concluded from this. The stress and tangent of that routine
are a complete plane-strain linear-elastic law built from ``PROPS`` alone --
nothing in lines 216-233 touches the COMMON -- so the file is not excluded as a
companion to a user element. Only the four STATEV lines depend on the UEL, and
they are a visualisation overlay. Calling the whole file unverifiable would
have moved an internal limitation into the external column.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus import deck, manifest as manifest_module
from umat_oti.abaqus.deck_pairing import materials_in

MIXED_DECK = """\
*HEADING
 two element blocks, and the material belongs to the second
*NODE
1, 0., 0., 0.
*Element, type=U1
1,  67,   9,  48
2,  95,  12,  13
*ELEMENT, TYPE=CPS3, ELSET=decoy
186,67,9,48
187,95,12,13
*Solid Section, elset=decoy, material=decoy
*MATERIAL, NAME=decoy
*USER MATERIAL, CONSTANTS=2
1e-11, 0.3
*DEPVAR
8
"""


def test_the_label_comes_from_the_block_of_this_materials_own_type(tmp_path):
    """Not the deck's first element, which in a mixed deck is somebody else's.

    The user elements here are numbered from 1 and the decoy elements from 186.
    Taking "the first element in the deck" would give 1 and reproduce exactly
    the fault this is meant to remove.
    """
    where = tmp_path / "wedge.inp"
    where.write_text(MIXED_DECK)
    found = materials_in(where)
    assert len(found) == 1
    assert found[0].name == "decoy"
    assert found[0].elements == ("CPS3",)
    assert found[0].first_element_label == 186


def test_a_deck_that_says_nothing_useful_leaves_the_label_at_zero(tmp_path):
    where = tmp_path / "plain.inp"
    where.write_text("*MATERIAL, NAME=m\n*USER MATERIAL, CONSTANTS=1\n1.0\n")
    found = materials_in(where)
    assert found and found[0].first_element_label == 0


def _connectivity(written: str) -> str:
    """The line under ``*ELEMENT``, which is the one carrying the label.

    Read positionally rather than by pattern, because the node block above it
    numbers a node 1 too and matching on "1," anywhere would find that.
    """
    lines = written.splitlines()
    for index, line in enumerate(lines):
        if line.upper().startswith("*ELEMENT,"):
            return lines[index + 1]
    raise AssertionError("no *ELEMENT block in:\n" + written)


def test_the_generated_deck_numbers_its_element_as_asked():
    written = deck.generate_deck(manifest_module.VerificationManifest(
        name="m", source=Path("m.f"), element_type="C3D8",
        nprops=1, props=(1.0,), nstatv=1, element_label=186))
    assert _connectivity(written).startswith("186, "), written


def test_the_default_is_still_one_so_nothing_else_moves():
    """Every other entry in the corpus must generate the deck it did before."""
    written = deck.generate_deck(manifest_module.VerificationManifest(
        name="m", source=Path("m.f"), element_type="C3D8",
        nprops=1, props=(1.0,), nstatv=1))
    assert _connectivity(written).startswith("1, "), written


def test_the_real_deck_gives_the_number_the_routine_needs():
    """Measured against the author's published deck, not a fixture."""
    import os
    cache = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                 or Path.home() / "softwarex_work" / "discovery_cache")
    where = cache / "irfancn__Abaqus-UEL-elastic" / "wedge_elast.inp"
    if not where.exists():
        pytest.skip(f"{where} is not on this machine")

    found = [m for m in materials_in(where) if m.name.lower() == "decoy"]
    assert found, [m.name for m in materials_in(where)]
    label = found[0].first_element_label
    assert label == 186
    # which is what the routine's own arithmetic asks for: kelem = noel - 185
    # has to land inside uvars(1:185, ...).
    assert 1 <= label - 185 <= 185
