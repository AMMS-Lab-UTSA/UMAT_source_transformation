"""Three layouts of ``*USER MATERIAL`` data lines are not read as a card deck (B17 G3b).

Measured with Abaqus/Standard 2021 by a UMAT that writes PROPS on its first call
(corpus_campaign/batches/B8/ada/props_card_probe/measured_results.txt):

* two data lines for CONSTANTS=4 (A, B, C): fatal;
* a blank line between two data lines (M, and I with a comment as well): fatal,
  while a comment line alone between them (L) is read through;
* nine values on one line for CONSTANTS=8 (N): Abaqus reads eight; this reader
  does not guess which eight, so the block is unusable.

A block that breaks one of them keeps the numbers as read, says why in
``unreadable``, and is not ``usable``. Every case below is paired with the same
block one edit away that is read as before, so the check is shown to be able to
fail and to leave the card-of-eight, zero-fill and substitution behaviour alone.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.deck_pairing import materials_in, pair

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


# (user-material text, usable, a word the reason must contain when unusable)
CASES = {
    "more data lines than CONSTANTS needs (A)": (
        "*User Material, constants=4\n200000., 0.3\n250., 2000.\n", False, "more data lines"),
    "one data line for CONSTANTS=4 (edge, usable)": (
        "*User Material, constants=4\n200000., 0.3, 250., 2000.\n", True, ""),
    "a short first line is a full card, so two lines for 4 are too many (B)": (
        "*User Material, constants=4\n200000., 0.3,\n250., 2000.\n", False, "more data lines"),
    "blank line between data lines (M)": (
        "*User Material, constants=10\n1., 2., 3., 4., 5., 6., 7., 8.,\n\n9., 10.\n", False, "blank line"),
    "comment and blank between data lines (I)": (
        "*User Material, constants=10\n1., 2., 3., 4., 5., 6., 7., 8.,\n** c\n\n9., 10.\n", False, "blank line"),
    "comment alone between data lines (L, usable)": (
        "*User Material, constants=10\n1., 2., 3., 4., 5., 6., 7., 8.,\n** c\n9., 10.\n", True, ""),
    "nine values on one line for CONSTANTS=8 (N)": (
        "*User Material, constants=8\n1., 2., 3., 4., 5., 6., 7., 8., 9.\n", False, "9 values"),
    "eight values on one line for CONSTANTS=8 (edge, usable)": (
        "*User Material, constants=8\n1., 2., 3., 4., 5., 6., 7., 8.\n", True, ""),
    "second line short, 10 constants (O, usable)": (
        "*User Material, constants=10\n1., 2., 3., 4., 5., 6., 7., 8.\n9., 10.,\n", True, ""),
    "blank line AFTER the last data line is harmless (usable)": (
        "*User Material, constants=10\n1., 2., 3., 4., 5., 6., 7., 8.,\n9., 10.\n\n*Step\n", True, ""),
    "blank line BEFORE the first data line is harmless (usable)": (
        "*User Material, constants=4\n\n200000., 0.3, 250., 2000.\n", True, ""),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_measured_layouts(tmp_path, name):
    user, usable, word = CASES[name]
    block = _block(tmp_path, user)
    assert block.usable is usable, (name, block.unreadable, block.values)
    if usable:
        assert block.unreadable == ()
    else:
        assert any(word in reason for reason in block.unreadable), block.unreadable
        assert block.as_dict()["usable"] is False and block.as_dict()["unreadable"]


def test_a_short_last_line_is_still_zero_filled_and_a_parameter_is_still_substituted(tmp_path):
    block = _block(tmp_path, """\
*Parameter
e = 210000.
*User Material, constants=10
<e>, 0.3, 1., 2., 3., 4., 5., 6.
7., 8.,
""")
    assert block.usable and block.substituted == ("e",)
    assert block.values == (210000.0, 0.3, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)
    block = _block(tmp_path, "*User Material, constants=24\n210000.0, 0.3\n")
    assert block.usable and len(block.values) == 24 and set(block.values[2:]) == {0.0}


def test_the_rules_apply_to_the_second_material_independently(tmp_path):
    deck = tmp_path / "deck.inp"
    deck.write_text(HEAD + "*User Material, constants=4\n1., 2.\n3., 4.\n"
                    "*Material, name=N\n*Depvar\n1,\n*User Material, constants=4\n1., 2., 3., 4.\n")
    first, second = materials_in(deck)
    assert not first.usable and second.usable


def test_a_pairing_says_why_the_authors_block_is_not_read(tmp_path):
    repo = tmp_path / "owner__repo"
    repo.mkdir()
    source = repo / "umat.for"
    source.write_text("      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)\n      END\n")
    (repo / "model.inp").write_text(
        HEAD + "*User Material, constants=10\n1., 2., 3., 4., 5., 6., 7., 8.,\n\n9., 10.\n")
    result = pair(source, repo)
    # chosen as the author's deck, as an unresolved template is, but it
    # publishes no vector and the pairing says why
    assert result.found and not result.material.usable
    assert "card rules (a blank line between data lines)" in result.why
