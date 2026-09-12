"""Every source in the corpus was driven on six components. Most are not.

``row["ntens"] = ntens`` in the triage, where ``ntens`` was the parameter's
own default of 6. Nothing ever inferred it, so a plane-strain routine, a
plane-stress one and a three-dimensional one all reached Abaqus as NTENS=6 on
a C3D4 tetrahedron -- and the two that are not three-dimensional were asked
for components they never compute and compared against components they never
returned.

``abuganza__UMAT_anisotropic_damage`` is the case that shows it: the same
model in three formulations, three nearly identical files. Their DDSDDE fills
are bounded at 4, 3 and 6, and every one of those numbers is the answer.

Two independent witnesses decide it now. The source says what tensor it fills.
The author's deck says what element the material runs on. Where they agree the
answer is as good as it gets; where they disagree the source decides, because
the source is what executes and the deck was paired to it by counting
constants -- which is how a plane-strain routine came to be holding a CPS8R
deck's material.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.formulation import (choose, elements_using,  # noqa: E402
                                         from_source, settle)

PLANE_STRAIN = """\
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,
     # rpl,ddsddt,drplde,drpldt,stran,dstran,time,dtime)
      include 'aba_param.inc'
      dimension stress(ntens), ddsdde(ntens,ntens)
      do II=1,4
        do JJ=1,4
          ddsdde(II,JJ) = cciso(II,JJ)
        end do
        stress(II) = sigma(II)
      end do
c...      print *, ddsdde(1,1), ddsdde(1,5), ddsdde(1,6)
      return
      end
"""

THREE_D = PLANE_STRAIN.replace("do II=1,4", "do II=1,6").replace(
    "do JJ=1,4", "do JJ=1,6")

DECK_PLANE_STRESS = """\
*Node
1, 0., 0.
*Element, type=CPS8R
1, 1, 2, 3, 4, 5, 6, 7, 8
*Elset, elset=Body, generate
1, 1, 1
*Solid Section, elset=Body, material=Skin
*Material, name=Skin
*Depvar
11,
*User Material, constants = 10
1., 2., 3., 4., 5., 6., 7., 8.
9., 10.
"""

DECK_3D = DECK_PLANE_STRESS.replace("type=CPS8R", "type=C3D8RH")


def test_a_commented_out_print_does_not_make_a_source_three_dimensional():
    """All three tissue UMATs carry ``c... print *, ddsdde(1,1) ... (1,6)``.
    Reading it made every one of them look six-component."""
    found = from_source(PLANE_STRAIN, "UMAT_Tissue_2d_plane_strain.f")
    assert found.ntens == 4
    assert found.family == "plane strain"


def test_the_loop_bound_around_the_tangent_is_the_signal():
    assert from_source(THREE_D, "x.f").ntens == 6
    assert any("DO loop bounded at 6" in line
               for line in from_source(THREE_D, "x.f").evidence)


def test_a_source_that_says_nothing_says_nothing():
    quiet = "      subroutine umat(stress)\n      return\n      end\n"
    assert not from_source(quiet, "umat.for").known


def test_the_deck_names_the_element_through_its_element_set():
    """``*Element`` often carries no ``elset=``, so the connection runs through
    the element numbers and the ``*Elset`` that gathers them."""
    kinds, where = elements_using(DECK_PLANE_STRESS, "Skin")
    assert kinds == ("CPS8R",)
    assert "Solid Section" in where


def test_the_authors_element_is_not_the_one_the_verification_runs():
    """CPS8R is reduced-integration and second-order. What is kept is the
    formulation; what is dropped is everything else."""
    chosen = choose(("CPS8R",))
    assert chosen.element == "CPS4"
    assert chosen.family == "plane stress"


def test_a_hybrid_element_keeps_its_hybrid_formulation():
    assert choose(("C3D8RH",)).element == "C3D8H"


def test_when_the_source_and_the_deck_agree_that_is_the_answer():
    settled = settle(THREE_D, "UMAT_Tissue_3d.f", DECK_3D, "3D_UMAT.inp", "Skin")
    assert settled.element == "C3D8H"
    assert "agree" in settled.agreement


def test_when_they_disagree_the_source_decides():
    """The measured case: a plane-strain routine holding a CPS8R deck's
    constants, because the pairing matched on constant count."""
    settled = settle(PLANE_STRAIN, "UMAT_Tissue_2d_plane_strain.f",
                     DECK_PLANE_STRESS, "2D_UMAT_Cyclic.inp", "Skin")
    assert settled.element == "CPE4"
    assert "the source decides" in settled.agreement
    assert "CPS8R" in settled.formulation.reason


def test_a_cohesive_law_is_refused_rather_than_driven_as_plane_stress():
    """A cohesive law is handed tractions and separations. Three components
    does not make it plane stress.

    What the refusal RESTS ON has changed, and the claim has not. A cohesive
    law is now drivable -- Abaqus calls a UMAT for a ``*COHESIVE SECTION,
    RESPONSE=TRACTION SEPARATION``, and ``harshaa765__Bilinear-CZM-UMAT``
    publishes a one-element COH3D8 patch test of exactly that. What is refused
    here is the case this test builds: a source that names itself a cohesive
    law with NO deck beside it, where COH2D4 hands the routine two separation
    components and COH3D8 hands it three, and nothing says which the author
    used. Driving it as plane stress is still wrong; driving it as the wrong
    cohesive element would be too."""
    settled = settle("      subroutine umat(stress)\n      end\n",
                     "Bilinear_CZM_UMAT.for")
    assert not settled.element
    assert "tractions" in settled.formulation.reason


def test_more_than_one_formulation_on_one_material_is_not_resolved_here():
    chosen = choose(("CPS4R", "C3D8"))
    assert not chosen.known
    assert "2 different formulations" in chosen.reason


def test_neither_witness_leaves_a_labelled_assumption():
    settled = settle("      subroutine umat(stress)\n      end\n", "umat.for")
    assert settled.element == "C3D8"
    assert "ASSUMED" in settled.formulation.reason
