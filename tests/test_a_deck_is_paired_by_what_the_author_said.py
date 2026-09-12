"""Proximity is not evidence, and it paired three growth UMATs with a stranger.

Measured on ``mholla__growth``. ``umats/umat_iso_morph_Abaqus.f`` reads
``props(1:4)`` -- ``lam, mu, tmax, tau`` -- by literal subscript and nothing
else, and writes ``statev(1:3)``. The harness paired it with
``input_files/circle_pressure.inp``, which publishes 9 constants and
``*Depvar 6`` and which that repository's own README table assigns to
``umat_area_stretch.f``. Driven with it, ``tau`` becomes ``props(4) = 0`` and
the growth factor ``(tmax-1)*(1-exp(-time(2)/tau)) + 1`` divides by zero on the
first call. The verdict recorded was "the model produced no numbers at any
amplitude from 8e-07 to 1 ... there is no loading here this harness can drive
it at". The loading was never the problem.

Measured on ``theysy__mml_subroutine_public``: ``MML_U2/MML_U2.for`` was paired
with ``MML_V2F/SHELL_GTN_NECK.inp``, a deck for a different subroutine two
directories away, and no material was read from it at all -- the recorded
``material_provenance`` is the empty string. Its own directory holds
``MML_U2/SHELL_TCT_IM.inp``, whose ``*Shell Section`` names
``TR1180_HAH20_U2``.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.deck_pairing import (Demand, declared_stages, demanded,
                                          materials_in, pair, stated_pairs)

pytestmark = pytest.mark.unit

EXACT_SOURCE = """\
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,rpl,ddsdt,
     # drplde,drpldt,stran,dstran,time,dtime,temp,dtemp,predef,dpred,
     # cmname,ndi,nshr,ntens,nstatv,props,nprops,coords,drot,pnewdt,
     # celent,dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc)
      lam   = props(1)
      mu    = props(2)
      tmax  = props(3)
      tau   = props(4)
      theg = (tmax-1.d0)*(1.d0-exp(-time(2)/tau)) + 1.d0
      statev(1) = theg
      statev(2) = theg*theg*theg
      statev(3) = detfe
      return
      end
"""

NINE_CONSTANTS = """\
*Heading
** somebody else's material
*Node
1, 0., 0., 0.
*Element, type=C3D8
1, 1, 1, 1, 1, 1, 1, 1, 1
*Solid Section, elset=ALL, material=MAT
*Material, name=MAT
*Depvar
    6,
*User Material, constants=9, unsymm
    0.577, 0.385, 0, 0, 1, 0.2, 1.1, 1.5
    1,
*Step, name=pressure
*Static
0.01, 1., 1e-05, 1.
*End Step
"""


def test_a_routine_that_names_every_constant_states_its_own_nprops():
    """``umat_iso_morph_Abaqus.f`` subscripts PROPS only by literal number, so
    the four it reads are the four it takes. Measured: nprops 4, exact True."""
    demand = demanded(EXACT_SOURCE)
    assert demand.nprops == 4
    assert demand.props_exact is True
    assert demand.nstatv == 3


def test_a_block_with_more_constants_is_a_different_material():
    """Nine constants fed to a routine that names four does not give it four
    with slack: it gives it somebody else's third and fourth, which here are
    ``0, 0`` where the routine expects a growth limit and a time constant."""
    admitted, why = demanded(EXACT_SOURCE).admits(constants=9, depvar=6)
    assert admitted is False
    assert "different parameterisation" in why


def test_depvar_is_a_floor_and_not_a_count():
    """``l1-is-1--l2-is-101.for`` writes STATEV(1:9) and its author's own deck
    declares ``*Depvar 10``. Treating that as a mismatch would refuse the only
    material the repository publishes."""
    assert demanded(EXACT_SOURCE).admits(constants=4, depvar=10)[0] is True
    assert demanded(EXACT_SOURCE).admits(constants=4, depvar=2)[0] is False


def test_the_wrong_sized_material_is_refused_rather_than_used(tmp_path: Path):
    """The whole corpus finding in one call: the only deck in the repository
    publishes nine constants, the routine takes four, and what comes back is a
    refusal naming the mismatch instead of a manifest that would divide by a
    zero time constant."""
    repository = tmp_path / "growth"
    (repository / "umats").mkdir(parents=True)
    (repository / "input_files").mkdir()
    source = repository / "umats" / "umat_iso_morph_Abaqus.f"
    source.write_text(EXACT_SOURCE)
    (repository / "input_files" / "circle_pressure.inp").write_text(NINE_CONSTANTS)

    answer = pair(source, repository)
    assert answer.found is False
    assert "PROPS(1:4)" in answer.refusal
    assert "circle_pressure.inp" in answer.refusal


def test_a_readme_table_is_the_author_saying_it_outright(tmp_path: Path):
    """``mholla__growth``'s README carries a two-column table of seventeen
    rows headed "Input files" and "UMAT files". That is the strongest evidence
    a pairing can have and it costs one regular expression to read."""
    repository = tmp_path / "growth"
    repository.mkdir()
    (repository / "README.md").write_text(
        "| Input files | UMAT files |\n"
        "|---|---|\n"
        "| muffin_noload.inp | umat_iso_morph.f |\n"
        "| circle_pressure.inp | umat_area_stretch.f |\n")
    pairs = stated_pairs(repository)
    assert pairs["umat_iso_morph.f"] == {"muffin_noload.inp"}
    assert pairs["umat_area_stretch.f"] == {"circle_pressure.inp"}


def test_the_step_structure_a_law_needs_is_read_from_its_own_branches():
    """``BodyForce-Growth-2Stages.for`` branches on TIME(2) at 1.0, 2.0 and
    3.0. TIME(2) is the whole analysis, so those are three steps of unit
    period -- and its author's ArcUp deck runs exactly three."""
    text = ("      IF ( (TIME(2)+DTIME) .LE. 1.0) THEN\n"
            "      ELSE IF ( (TIME(2)+DTIME) .LE. 2.0) THEN\n"
            "      ELSE IF ( (TIME(2)+DTIME) .LE. 3.0) THEN\n"
            "      END IF\n")
    assert declared_stages(text) == (1.0, 2.0, 3.0)


def test_a_material_a_section_names_outranks_one_merely_defined_beside_it(
        tmp_path: Path):
    """``MML_U2/SHELL_TCT_IM.inp`` defines seven materials and its
    ``*Shell Section`` names one of them, ``TR1180_HAH20_U2``. The other six
    are siblings for other options of the same routine, and a pairing that
    took the first defined took ``AA6022_HAH20_U2``."""
    deck = tmp_path / "SHELL_TCT_IM.inp"
    deck.write_text(
        "*Node\n1, 0., 0., 0.\n"
        "*Element, type=S4R\n1, 1, 1, 1, 1\n"
        "*Elset, elset=Set-1\n 1,\n"
        "*Shell Section, elset=Set-1, material=TR1180_HAH20_U2\n1., 3\n"
        "*Material, name=AA6022_HAH20_U2\n*Depvar\n 65,\n"
        "*User Material, constants=2\n1., 2.\n"
        "*Material, name=TR1180_HAH20_U2\n*Depvar\n 65,\n"
        "*User Material, constants=2\n3., 4.\n")
    materials = {material.name: material for material in materials_in(deck)}
    assert materials["TR1180_HAH20_U2"].explicit is True
    assert materials["AA6022_HAH20_U2"].explicit is False
    assert materials["TR1180_HAH20_U2"].values == (3.0, 4.0)


def test_a_deck_that_writes_a_question_mark_publishes_no_material(
        tmp_path: Path):
    """``mholla__growth/input_files/square_noload_orient.inp`` carries
    ``*User Material, constants=?`` and ``?, ?`` for its values: a template
    the author never filled in. Reading it as a count would attribute numbers
    to an author who wrote a question mark."""
    deck = tmp_path / "orient.inp"
    deck.write_text("*Material, name=MAT\n*Depvar\n    ?,\n"
                    "*User Material, constants=?, unsymm\n    ?, ?\n")
    materials = materials_in(deck)
    assert all(material.constants == 0 for material in materials)
