"""Two refusals that were true of the registry and false about Abaqus.

``harshaa765__Bilinear-CZM-UMAT/Bilinear_CZM_UMAT.for`` was refused with "this
source is a cohesive law: it is handed tractions and separations rather than a
stress tensor, and no continuum element in this harness calls a UMAT that way".
Abaqus calls a UMAT for a ``*COHESIVE SECTION, RESPONSE=TRACTION SEPARATION``
and hands it NDI=1 and NSHR=1 or 2. The author of that repository published the
experiment in the same directory as the source: ``Job_1_Harsh_UMAT.inp``, one
COH3D8, opened to 0.2 and then released, described in the README as "Single
element patch test".

``theysy__mml_subroutine_public/MML_U2.for`` was refused with "the deck uses
this material on shell elements (S4R), which do not hand a UMAT the continuum
stress tensor this harness drives". True, and it does not reach the
constitutive routine: Abaqus calls a UMAT from a shell with NDI=2, NSHR=1,
NTENS=3, and from CPS4 with exactly the same three. The source settles it in
its own text -- ``IF(NDIM3 .EQ. 3) THEN !PLANE STRESS`` -- and the author's own
constants select YLD2000_2D, which the routine STOPs on unless NTENS is 3.

What stays refused is what is genuinely out of reach:
``lucassalmon83860-bit``'s healing law runs on COH2D4T and computes
``PROPS(8)*Exp(-PROPS(9)/(8.34*TEMP))``. At TEMP=0 that divides by zero, and
choosing a temperature would choose the experiment.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.deck import generate_deck
from umat_oti.abaqus.elements import geometry_for, is_supported
from umat_oti.abaqus.experiment import build, cohesive_softened
from umat_oti.abaqus.formulation import choose, read_orientation, settle
from umat_oti.abaqus.manifest import VerificationManifest

pytestmark = pytest.mark.unit

CZM_SOURCE = """\
       SUBROUTINE UMAT(STRESS,STATEV,DDSDDE)
      A_KN = PROPS(1)
      TAU_N = PROPS(2)
      G_NC = PROPS(5)
      DELTA_NC = TAU_N/A_KN
      Do I = 1, NTENS
         DELTAT(I) = STRAN(I) + DSTRAN(I)
      Enddo
      RETURN
      END
"""

PATCH_TEST = """\
*Node
 1,      0.,      0.,      0.
 2,      1.,      0.,      0.
 3,      1.,      1.,      0.
 4,      0.,      1.,      0.
 5,      0.,      0.,      0.
 6,      1.,      0.,      0.
 7,      1.,      1.,      0.
 8,      0.,      1.,      0.
*Element, type=COH3D8
1, 1, 2, 3, 4, 5, 6, 7, 8
*Elset, elset=Single_Elem
 1,
*Cohesive Section, elset=Single_Elem, material=Interface, response=TRACTION SEPARATION
1.,
*Material, name=Interface
*Depvar
1
*USER MATERIAL, TYPE=MECHANICAL, CONSTANTS=8, UNSYMM
2000.,200.,200.,200., 100.,100.,100., 1.
*Step, name=Step-1, nlgeom=YES
*Static
0.05, 0.5, 5e-06, 0.05
*End Step
"""


def test_a_cohesive_element_is_in_the_registry_with_the_tensor_it_hands_over():
    """COH3D8 calls a UMAT with one direct component and two shear; COH2D4
    with one and one. Both are traction-separation and neither is a strain."""
    three_d = geometry_for("COH3D8")
    assert (three_d.ndi, three_d.nshr, three_d.ntens) == (1, 2, 3)
    assert three_d.section == "COHESIVE" and three_d.kind == "cohesive"
    planar = geometry_for("COH2D4")
    assert (planar.ndi, planar.nshr, planar.ntens) == (1, 1, 2)


def test_the_coupled_cohesive_element_stays_refused_and_says_why():
    """COH2D4T hands the UMAT a temperature, and a healing law whose kinetics
    are ``Exp(-Ea/(8.34*TEMP))`` divides by zero at TEMP=0."""
    assert is_supported("COH2D4T") is False
    formulation = choose(("COH2D4T",), provenance="the author's deck")
    assert formulation.element == ""
    assert "temperature" in formulation.reason


def test_a_deck_the_author_wrote_settles_which_cohesive_element_to_run():
    """The author's own patch test uses COH3D8, so the verification does."""
    settled = settle(CZM_SOURCE, "Bilinear_CZM_UMAT.for", PATCH_TEST,
                     "Job_1_Harsh_UMAT.inp", "Interface")
    assert settled.element == "COH3D8"
    assert settled.formulation.family == "cohesive"
    assert "TRACTION SEPARATION" in settled.formulation.reason


def test_a_cohesive_deck_prescribes_a_separation_and_not_a_strain():
    """The bottom face is held and the top face is displaced by the jump. On
    COH3D8 the normal is global 3, which is the direction from the bottom face
    to the top; the author's own deck drives exactly that through an
    equation."""
    manifest = VerificationManifest(
        name="CZM", source=Path("czm.for"), element_type="COH3D8",
        props=(2000., 200., 200., 200., 100., 100., 100., 1.), nstatv=1,
        unsymmetric=True, material_provenance="Job_1_Harsh_UMAT.inp",
        kinematics="finite")
    experiment = build(CZM_SOURCE, manifest)
    assert experiment.found is True
    assert experiment.family.name == "cohesive"
    text = generate_deck(experiment.manifest)
    assert "*COHESIVE SECTION, ELSET=ONE, RESPONSE=TRACTION SEPARATION" in text
    opening = text.split("** open")[1].split("*OUTPUT")[0]
    # The four bottom nodes held, the four top nodes driven in direction 3.
    assert "1, 3, 3, 0.0" in opening
    assert "5, 3, 3, " in opening and "5, 3, 3, 0.0" not in opening


def test_how_far_to_open_comes_from_the_law_s_own_constants():
    """``DELTA_NC = TAU_N/A_KN`` is 200/2000 = 0.1 and the separation at which
    the traction reaches zero is ``2*G_NC/TAU_N`` = 2*100/200 = 1.0. Halfway
    down the softening branch is 0.55 -- a number the law supplied, not one
    somebody liked."""
    manifest = VerificationManifest(
        name="CZM", source=Path("czm.for"), element_type="COH3D8",
        props=(2000., 200., 200., 200., 100., 100., 100., 1.), nstatv=1)
    experiment = build(CZM_SOURCE, manifest)
    assert experiment.manifest.loading[0].separation[0] == pytest.approx(0.55)
    assert "onset at 0.1" in experiment.reason
    assert [segment.name for segment in experiment.manifest.loading] == [
        "open", "release", "reopen"]


def test_a_cohesive_law_that_never_softened_did_not_run_its_own_model():
    """Softening is the whole of a cohesive law. An opening that stops on the
    elastic branch verifies a penalty stiffness, which is one number the
    author wrote down."""
    rising = [{"kind": "result", "STRAN": [s], "DSTRAN": [0.0],
               "STRESS": [2000.0 * s]}
              for s in (0.02, 0.04, 0.06, 0.08)]
    assert cohesive_softened(rising).met is False
    softening = rising + [{"kind": "result", "STRAN": [s], "DSTRAN": [0.0],
                           "STRESS": [200.0 * (1.0 - s)]}
                          for s in (0.2, 0.4, 0.6)]
    assert cohesive_softened(softening).met is True


def test_a_shell_umat_is_driven_on_the_element_that_hands_it_the_same_tensor():
    """NDI=2, NSHR=1, NTENS=3 either way. What the substitution drops is the
    shell's bending, transverse shear and through-thickness integration, and
    none of those is a UMAT."""
    formulation = choose(("S4R",), provenance="SHELL_TCT_IM.inp")
    assert formulation.element == "CPS4"
    geometry = geometry_for("CPS4")
    assert (geometry.ndi, geometry.nshr) == (2, 1)
    assert "SUBSTITUTES" in formulation.reason


def test_a_source_that_fills_six_components_is_not_run_as_a_shell():
    """The substitution is only honest where the source agrees it is a
    plane-stress routine. One that fills a six-component tangent and a deck
    that says shell disagree, and this harness does not pick between them."""
    formulation = choose(("S4R",), provenance="deck", ntens_hint=6)
    assert formulation.element == ""
    assert "One of the two is wrong" in formulation.reason


def test_the_frame_an_author_published_is_read_rather_than_refused():
    """``*Orientation, name=Ori-1 / 1.,0.,0., 0.,1.,0. / 3, 0.`` and a ply
    turned thirty degrees on the ``*Shell Section`` data line. The refusal said
    "this harness can read the orientation's name but not its axes"; the axes
    are the global ones and the ply is the rotation."""
    deck = (
        "*Orientation, name=Ori-1\n"
        "          1.,           0.,           0.,           0.,           1.,           0.\n"
        "3, 0.\n"
        "*Elset, elset=CompositeLayup-1-1, generate\n   1,  625,    1\n"
        "*Shell Section, elset=CompositeLayup-1-1, composite, orientation=Ori-1, layup=L\n"
        "0.1, 3, COMPOSITE, 30., Ply-1\n")
    frame = read_orientation(deck, "COMPOSITE")
    assert frame.known is True
    assert frame.axes == (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    assert frame.rotation == (3, 30.0)
    assert "turned a further 30" in frame.provenance


def test_an_orientation_reaches_the_deck_as_the_author_wrote_it():
    """Six numbers and an axis-angle line, which is what *ORIENTATION takes --
    not three Euler angles this harness converted it into."""
    manifest = VerificationManifest(
        name="COMPOSITE", source=Path("c.for"), element_type="CPS4",
        props=(181000., 10300., 0.28, 7170., 2507., 1200., 86., 184., 146.),
        nstatv=1, material_provenance="UMATModel.inp",
        orientation_axes=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        orientation_rotation=(3, 30.0),
        loading=())
    text = generate_deck(manifest)
    assert "*ORIENTATION, NAME=LOCAL, SYSTEM=RECTANGULAR" in text
    assert "1.0, 0.0, 0.0, 0.0, 1.0, 0.0" in text
    assert "3, 30.0" in text
    assert "ORIENTATION=LOCAL" in text
