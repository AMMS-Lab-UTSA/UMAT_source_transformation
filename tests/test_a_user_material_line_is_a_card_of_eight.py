"""``*USER MATERIAL`` data lines are cards of eight (G1c).

Abaqus fills a short data line with zeros, and a block that stops short of
CONSTANTS= with zeros too. Measured with Abaqus/Standard 2021.HF5 and a UMAT
writing PROPS on its first call (corpus_campaign/batches/B7/gauss_g1c/
abaqus_props_probe/): harshaa765__UMATFile/Input_file.inp (crystal
plasticity, 19 short lines between ``**`` comments, CONSTANTS=160) and
davidmorin V_UMAT/example_UMAT.inp (CONSTANTS=24, last line ``100.0, 1.0``)
-- the parser now reads both bit-identically to Abaqus. Read packed, the
first published 48 values and the second 18, so both manifests ended with
"no material constants". Over the 12060 blocks of the discovery cache 16
change, all from unusable to usable; no usable block's values move
(cache_values_ab.out there).
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.deck_pairing import materials_in

pytestmark = pytest.mark.unit

HEAD = """\
*Node
1, 0., 0., 0.
*Element, type=C3D8, elset=ALL
1, 1, 1, 1, 1, 1, 1, 1, 1
*Solid Section, elset=ALL, material=M
*Material, name=M
*Depvar
1,
"""


def _block(tmp_path: Path, user: str):
    deck = tmp_path / "deck.inp"
    deck.write_text(HEAD + user)
    (block,) = materials_in(deck)
    return block


def test_a_short_line_between_comments_is_padded_to_eight(tmp_path):
    block = _block(tmp_path, """\
*User Material, constants=16
**  c11, c12, c44
  108000., 61300., 28500.,
**  number of slip sets
  1.,
""")
    assert block.usable
    assert block.values == (108000.0, 61300.0, 28500.0, 0, 0, 0, 0, 0,
                            1.0, 0, 0, 0, 0, 0, 0, 0)


def test_a_block_that_stops_short_of_constants_is_zero_filled(tmp_path):
    block = _block(tmp_path, """\
*User Material, constants=24
 210000.0, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
 100.0, 1.0
""")
    assert block.usable and len(block.values) == 24
    assert block.values[8:10] == (100.0, 1.0) and set(block.values[10:]) == {0.0}


def test_full_cards_are_read_as_they_are(tmp_path):
    block = _block(tmp_path, """\
*User Material, constants=10
 1., 2., 3., 4., 5., 6., 7., 8.
 9., 10.
""")
    assert block.values == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0)


def test_a_line_holding_a_placeholder_stays_unusable(tmp_path):
    block = _block(tmp_path, """\
*User Material, constants=2
<EMOD>, 0.3
""")
    assert not block.usable and block.unresolved == ("<EMOD>",)
    # read as before: no zeros invented around a slot nobody filled
    assert block.values == (0.3,)


@pytest.mark.parametrize("line, count", [
    # williammora1984 GTN test_ht_vol.inp: 12 numbers on one line and a
    # "0.1. 0.3" typo
    (" 210.0e3, 0.33, 200.0, 50.0, 100.0, 1.5, 1.0, 1.5, 0.004, 0.1. 0.3, 0.2025, 0.1", 11),
    (" 1., 2., 3., 4., 5., 6., 7., 8., 9.", 9),     # more than eight numbers
    (" 1., 2., 3.x\n 4., 5.", 4),                     # a token Abaqus cannot read
])
def test_a_garbled_block_is_not_zero_filled(tmp_path, line, count):
    block = _block(tmp_path, f"*User Material, constants=13\n{line}\n")
    assert not block.usable
    # read as written: the numbers that parse, packed, no zeros invented
    assert len(block.values) == count and 0.0 not in block.values
