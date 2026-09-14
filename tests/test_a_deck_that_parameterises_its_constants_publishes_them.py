"""``*PARAMETER`` substitution is what Abaqus does, so the pairing does it too.

Six pass11 entries settled at ``manifest_refused`` with the words "no material
constants" against decks whose ``*USER MATERIAL`` line declares nine of them.
The data line reads::

    *User Material, constants=9, unsymm
    <lam>, <mu>, <xn0_1>, <xn0_2>,<xn0_3>, <kk> , <tcrt>, <mm>
    <nn>

Abaqus substitutes those from the deck's own ``*PARAMETER`` block at
input-processing time. Reading them is not inventing them; it is reading what
Abaqus reads, and it is a general feature of the format rather than a fix for
one repository.

The other half of this is what must NOT happen. A block whose placeholders are
still standing does not publish a material, and the numbers it DOES hold have
moved: ``{{youngs_modulus}}, 0.3`` reads as a one-element vector holding 0.3,
which arrives at the routine as PROPS(1) -- Poisson's ratio in Young's
modulus's slot, a material nobody wrote, driven to a plausible-looking answer.

The parsing itself is covered by tests/test_deck_parameter_substitution.py,
against the same implementation. What is covered here is the PAIRING: which
block a source is given, and what is said when it cannot be given one.
"""
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.deck_pairing import (materials_in,  # noqa: E402
                                          pair, published_placeholder_values)

pytestmark = pytest.mark.unit

SOURCE = """\
      SUBROUTINE UMAT(STRESS,STATEV,DDSDDE,SSE,SPD,SCD,RPL,DDSDDT,
     1 DRPLDE,DRPLDT,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,PREDEF,DPRED,
     2 CMNAME,NDI,NSHR,NTENS,NSTATV,PROPS,NPROPS,COORDS,DROT,PNEWDT,
     3 CELENT,DFGRD0,DFGRD1,NOEL,NPT,LAYER,KSPT,KSTEP,KINC)
      INCLUDE 'ABA_PARAM.INC'
      DIMENSION STRESS(NTENS),STATEV(NSTATV),DDSDDE(NTENS,NTENS)
      LAM = PROPS(1)
      MU  = PROPS(2)
      STRESS(1) = LAM + MU
      STATEV(1) = LAM
      DDSDDE(1,1) = MU
      RETURN
      END
"""

DECK = """\
*Heading
 a deck that writes its constants as parameters
*Parameter
lam = 0.598
mu  = 0.814
*Node
1, 0., 0., 0.
*Element, type=C3D8
1, 1, 1, 1, 1, 1, 1, 1, 1
*Solid Section, elset=all, material=tissue
*Material, name=tissue
*Depvar
1
*User Material, constants=2
<lam>, <mu>
*Step, name=s1, nlgeom=YES
*Static
0.1, 1.0, 1e-9, 0.1
*End Step
"""


def _repo(tmp_path, deck_text=DECK, name="model.inp", source="umat.for"):
    repository = tmp_path / "owner__repo"
    repository.mkdir(parents=True, exist_ok=True)
    (repository / source).write_text(SOURCE)
    (repository / name).write_text(textwrap.dedent(deck_text))
    return repository


# ---- what the deck itself defines ---------------------------------------
def test_the_authors_own_parameters_are_read(tmp_path):
    repository = _repo(tmp_path)
    material, = materials_in(repository / "model.inp")
    assert material.values == (0.598, 0.814)
    assert material.usable
    assert list(material.substituted) == ["lam", "mu"]
    assert material.unresolved == ()


def test_a_source_is_paired_with_it_and_the_provenance_says_how(tmp_path):
    repository = _repo(tmp_path)
    pairing = pair(repository / "umat.for", repository)
    assert pairing.found
    assert pairing.material.values == (0.598, 0.814)
    assert not pairing.refusal


def test_parameters_kept_in_an_included_file_are_spliced_in(tmp_path):
    """An ``*INCLUDE`` is resolved before the parameters are read, because
    Abaqus resolves it first."""
    repository = _repo(tmp_path, DECK.replace(
        "*Parameter\nlam = 0.598\nmu  = 0.814\n",
        "*include, input=param.param\n"))
    (repository / "param.param").write_text("*Parameter\nlam = 0.598\n"
                                            "mu  = 0.814\n")
    material, = materials_in(repository / "model.inp")
    assert material.values == (0.598, 0.814) and material.usable


# ---- what must not happen -----------------------------------------------
def test_a_block_with_a_placeholder_still_standing_is_not_usable(tmp_path):
    """The failure this guards is a silent one. ``{{youngs_modulus}}, 0.3``
    yields a one-element vector holding 0.3, and 0.3 would arrive as PROPS(1)
    -- Poisson's ratio where Young's modulus belongs."""
    repository = _repo(tmp_path, DECK.replace("<lam>, <mu>",
                                              "{{youngs_modulus}}, 0.3"))
    material, = materials_in(repository / "model.inp")
    assert material.values == (0.3,)
    assert not material.usable, (
        "a short vector is not a material: every constant after the gap has "
        "moved one position left")
    assert list(material.unresolved) == ["{{youngs_modulus}}"]


def test_an_unusable_block_reaches_the_manifest_as_no_constants(tmp_path):
    """Not as the constants it happened to hold. ``props=()`` stops the
    manifest at "no material constants", which is the truth."""
    from umat_oti.abaqus.experiment import plan
    repository = _repo(tmp_path, DECK.replace("<lam>, <mu>",
                                              "{{youngs_modulus}}, 0.3"))
    built = plan(repository / "umat.for", repository)
    manifest = getattr(built, "manifest", None)
    if manifest is None:
        # The pairing refused before a manifest was built, which is the same
        # answer arrived at one step earlier and says the same thing.
        assert not built.found
        assert "{{youngs_modulus}}" in (built.pairing.refusal
                                        or built.pairing.why)
        return
    assert tuple(manifest.props or ()) == ()
    assert "no material constants" in manifest.missing_requirements()


def test_a_missing_include_is_named_rather_than_read_as_silence(tmp_path):
    """A refusal that does not say where it looked is a claim. The deck says
    ``*include, input=param.param``; the answer has to say that file is not in
    the repository."""
    repository = _repo(tmp_path, DECK.replace(
        "*Parameter\nlam = 0.598\nmu  = 0.814\n",
        "*include, input=param.param\n"))
    material, = materials_in(repository / "model.inp")
    assert not material.usable
    assert list(material.unresolved_includes) == ["param.param"]
    pairing = pair(repository / "umat.for", repository)
    assert "param.param" in (pairing.refusal or pairing.why)


def test_another_directorys_constants_are_not_borrowed(tmp_path):
    """The mistake this whole module exists to prevent, in the shape it takes
    once substitution works. One directory defers its nine constants to an
    uncommitted file; another publishes nine of its own. They are different
    experiments and the second's numbers are not an answer about the first."""
    repository = tmp_path / "owner__repo"
    (repository / "study").mkdir(parents=True)
    (repository / "example").mkdir(parents=True)
    (repository / "study" / "umat.for").write_text(SOURCE)
    (repository / "study" / "study.inp").write_text(textwrap.dedent(
        DECK.replace("*Parameter\nlam = 0.598\nmu  = 0.814\n",
                     "*include, input=param.param\n")))
    (repository / "example" / "example.inp").write_text(textwrap.dedent(DECK))
    pairing = pair(repository / "study" / "umat.for", repository)
    assert not pairing.found, (
        "the example's constants are not the study's material")
    assert "param.param" in pairing.refusal
    assert "another" in pairing.refusal


# ---- a value the repository states somewhere else ------------------------
def test_a_value_stated_elsewhere_is_usable_only_with_its_provenance(tmp_path):
    repository = _repo(tmp_path, DECK.replace("<lam>, <mu>",
                                              "{{youngs_modulus}}, 0.3"))
    (repository / "README.md").write_text('    "youngs_modulus": 210000,\n')
    stated = published_placeholder_values(repository, ["youngs_modulus"])
    assert stated["youngs_modulus"]["agrees"] is True
    assert stated["youngs_modulus"]["value"] == 210000.0
    assert stated["youngs_modulus"]["stated_in"] == ["README.md:1"]
    pairing = pair(repository / "umat.for", repository)
    assert pairing.found and pairing.material.values == (210000.0, 0.3)
    assert "README.md:1" in pairing.why


def test_a_repository_that_states_two_values_has_published_neither(tmp_path):
    """Yutu0k__ABQflow is exactly this: README.md and four pages of docs bind
    ``youngs_modulus`` to 210000, and test/integration/test_stage_separation.py
    binds the same name to 200000. Picking the commoner one would be a vote,
    not a reading."""
    repository = _repo(tmp_path, DECK.replace("<lam>, <mu>",
                                              "{{youngs_modulus}}, 0.3"))
    (repository / "README.md").write_text('"youngs_modulus": 210000,\n')
    (repository / "test.py").write_text('params={"youngs_modulus": 200000}\n')
    stated = published_placeholder_values(repository, ["youngs_modulus"])
    assert stated["youngs_modulus"]["agrees"] is False
    assert stated["youngs_modulus"]["values_found"] == [200000.0, 210000.0]
    assert stated["youngs_modulus"]["value"] is None
    pairing = pair(repository / "umat.for", repository)
    assert not (pairing.material and pairing.material.usable)


def test_a_sweep_is_not_a_material(tmp_path):
    """``YOUNGS_MODULUS_LIST = [190000, 200000, 210000]`` binds a different
    name to a list of candidates. A parameter study is not a published
    constant."""
    repository = _repo(tmp_path)
    (repository / "sweep.py").write_text(
        "YOUNGS_MODULUS_LIST = [190000, 200000, 210000]\n")
    assert published_placeholder_values(repository, ["youngs_modulus"]) == {}


def test_no_value_is_ever_taken_from_another_deck(tmp_path):
    """A number in another ``.inp`` is another analysis's material."""
    repository = _repo(tmp_path)
    (repository / "other.inp").write_text("lam = 1234.0\n")
    assert published_placeholder_values(repository, ["lam"]) == {}
