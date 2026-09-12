"""A refusal is a statement about this pipeline until it says where it looked.

Three sources in ``mholla__growth`` were recorded as "this harness generated no
experiment this source will run: the model produced no numbers at any amplitude
from 8e-07 to 1". What had actually happened is that they were handed nine
constants by a deck that this repository's own README assigns to a different
routine, so ``tau = props(4)`` was 0 and ``exp(-time(2)/tau)`` divided by zero
on the first call. The stage is ``needs_material_data``, the cause is two
numbers, and both can be said.

``tmax`` and ``tau`` is what is missing, by name: five of the seven constants
``umat_area_morph_Abaqus.f`` reads are published by the block its near-namesake
``umat_area_morph.f`` uses, and the two that are not are the growth limit and
the growth time constant.

And ``Benchmarks/Notched_plate_shear/czmHealing.f`` writes STATEV(13) into a
``*Depvar 12`` array. Its own deck is the one that is wrong; reaching past it
to a deck in another benchmark directory -- the only other block in the
repository that fits -- would verify this routine against another experiment's
toughness and bury the defect behind the substitution.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.deck_pairing import (named_constants, pair,
                                          sibling_constants)

pytestmark = pytest.mark.unit

WITH_TMAX = """\
      subroutine umat(stress,statev,ddsdde)
      lam    = props(1)
      mu     = props(2)
      tmax   = props(3)
      tau    = props(4)
      xn0(1) = props(5)
      xn0(2) = props(6)
      xn0(3) = props(7)
      statev(1) = theg
      statev(3) = detfe
      return
      end
"""

WITH_ALPHA = """\
      subroutine umat(stress,statev,ddsdde)
      lam   = props(1)
      mu    = props(2)
      xn0(1) = props(3)
      xn0(2) = props(4)
      xn0(3) = props(5)
      alpha = props(6)
      statev(1) = theg
      statev(3) = detfe
      return
      end
"""

SIX_CONSTANTS = """\
*Node
1, 0., 0., 0.
*Element, type=C3D8
1, 1, 1, 1, 1, 1, 1, 1, 1
*Elset, elset=ALL
 1,
*Solid Section, elset=ALL, material=MAT
*Material, name=MAT
*Depvar
    3,
*User Material, constants=6, unsymm
    0.577, 0.385, 0, 0, 1, 0.02
"""


def test_a_routine_names_its_own_constants_and_the_names_carry_subscripts():
    """``xn0(1) = props(5)`` in one routine and ``xn0(3) = props(5)`` in
    another are not the same constant. Reading both as "XN0" said two routines
    agreed about a fibre direction when they had it in different slots."""
    names = named_constants(WITH_TMAX)
    assert names[3] == "TMAX" and names[4] == "TAU"
    assert names[5] == "XN0(1)" and names[7] == "XN0(3)"
    assert named_constants(WITH_ALPHA)[5] == "XN0(3)"


def test_what_is_missing_is_named_rather_than_counted(tmp_path: Path):
    """Not "no block of seven exists" but "tmax and tau are what nobody
    published". Its near-namesake supplies lam and mu; the two the growth law
    needs and the alpha-parameterised sibling does not have are the ones."""
    umats = tmp_path / "growth" / "umats"
    umats.mkdir(parents=True)
    (umats / "umat_area_morph_Abaqus.f").write_text(WITH_TMAX)
    (umats / "umat_area_morph.f").write_text(WITH_ALPHA)
    note = sibling_constants(umats / "umat_area_morph_Abaqus.f",
                             tmp_path / "growth", WITH_TMAX)
    assert "umat_area_morph.f" in note
    assert "PROPS(1)=LAM" in note and "PROPS(2)=MU" in note
    assert "PROPS(3)=TMAX" in note and "PROPS(4)=TAU" in note


def test_the_refusal_says_how_many_decks_were_opened_and_what_was_in_them(
        tmp_path: Path):
    """A reader who doubts "no material published here can feed this routine"
    can check it against the listed constant counts without opening a file."""
    repository = tmp_path / "growth"
    (repository / "umats").mkdir(parents=True)
    (repository / "input_files").mkdir()
    source = repository / "umats" / "umat_area_morph_Abaqus.f"
    source.write_text(WITH_TMAX)
    (repository / "umats" / "umat_area_morph.f").write_text(WITH_ALPHA)
    (repository / "input_files" / "sheet_noload.inp").write_text(SIX_CONSTANTS)

    answer = pair(source, repository)
    assert answer.found is False
    assert answer.searched["decks_scanned"] == 1
    assert answer.searched["constant_counts_published"] == [6]
    assert answer.searched["expected_nprops"] == 7
    assert "Searched: 1 .inp file(s)" in answer.refusal
    assert "PROPS(3)=TMAX" in answer.refusal


def test_the_deck_beside_the_source_is_not_swapped_for_one_from_elsewhere(
        tmp_path: Path):
    """``Notched_plate_shear/czmHealing.f`` writes STATEV(13) and the deck
    beside it declares ``*Depvar 12`` -- a write past the end of the array
    Abaqus allocates. The only other admissible block in that repository is a
    different benchmark's, with a different toughness. Running it would verify
    one experiment's routine against another's material."""
    repository = tmp_path / "bench"
    near = repository / "Benchmarks" / "Notched"
    far = repository / "Benchmarks" / "Pellet"
    near.mkdir(parents=True)
    far.mkdir(parents=True)
    source = near / "czmHealing.f"
    source.write_text("      subroutine umat(stress,statev)\n"
                      "      k = props(1)\n"
                      "      statev(13) = statev(13) + statev(11)\n"
                      "      return\n      end\n")

    def deck(depvar: int, value: float) -> str:
        return (f"*Material, name=CZM\n*Depvar\n {depvar},\n"
                f"*User Material, constants=1\n {value},\n")

    (near / "notched.inp").write_text(deck(12, 0.33878))
    (far / "pellet.inp").write_text(deck(14, 3.25))

    answer = pair(source, repository)
    assert answer.found is False
    assert "STATEV(13)" in answer.refusal
    assert "*DEPVAR 12" in answer.refusal
    assert "another experiment's constants" in answer.refusal


def test_a_surplus_constant_in_the_author_s_own_deck_is_accepted_and_named(
        tmp_path: Path):
    """A block in the source's own directory is the author's material even
    when it publishes one constant the code does not reach. The czmHealing
    header lists ``Eps_crit`` as PROPS(12) and the code hard-codes it to
    -1e-15 instead, so the deck carries twelve and the routine reads eleven --
    and NPROPS still has to be what the author wrote, because both builds must
    be handed the same one."""
    repository = tmp_path / "bench"
    repository.mkdir()
    source = repository / "law.f"
    source.write_text("      subroutine umat(stress,statev)\n"
                      "      k = props(1)\n      g = props(2)\n"
                      "      statev(1) = 0.\n      return\n      end\n")
    (repository / "law_benchmark.inp").write_text(
        "*Material, name=M\n*Depvar\n 4,\n"
        "*User Material, constants=3\n 1., 2., 3.,\n")
    answer = pair(source, repository)
    assert answer.found is True
    assert answer.material.constants == 3
    assert any("surplus is\naccepted" in warning.replace(" ", " ")
               or "surplus" in warning for warning in answer.warnings)
