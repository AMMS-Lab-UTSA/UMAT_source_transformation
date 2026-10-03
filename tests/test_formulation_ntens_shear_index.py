"""A loop bounded at three is plane stress only if index 3 is a shear.

``do i=1,3 ... ddsdde(i,i)`` fills three components. In plane stress they are
s11, s22, s12. In plane strain, axisymmetry and 3D they are s11, s22, s33 --
the direct block -- and the shear starts at index 4. Reading the bound alone
as plane stress overrode the author's CAX4T deck for
``awhelanUCD__Lemaitre-damage-UMAT-Public/nonLocalLemaitre/lemaitreDamageNonLocal.f``
and pass16 verified it on CPS4 with tau12 in the slot the routine computes as
s33.

The rule now: a bound of 3 is NTENS=3 evidence only with a witness that index
3 is a shear (or NDI=2 logic). Otherwise the source is undecided and the
author's deck decides, and the record says which side decided.

The inputs below are synthetic: written for this test, each reproducing only
the structure the rule reads (the corpus file it stands for is named beside
it). No corpus text is copied. The cache-backed tests at the end run the same
rules on the real files, pinned by sha256, where the acquisition cache exists.
"""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _workspace import WORKSPACE  # noqa: E402

from umat_oti.abaqus.formulation import from_source, settle

#: Stands for lemaitreDamageNonLocal.f: an isotropic tangent written as a
#: direct block over ``do k=1,3`` and a shear diagonal from index 4.
LEMAITRE = """\
      dimension stress(ntens),ddsdde(ntens,ntens),statev(nstatv)
      do k=1,3
       do l=1,3
        ddsdde(l,k)=alam
       end do
       ddsdde(k,k)=alam+2.d0*gmod
      end do
      do k=4,ntens
       ddsdde(k,k)=gmod
      end do
"""

#: The shear loop of LEMAITRE, removed or replaced by the tests below.
SHEAR_LOOP = "      do k=4,ntens\n       ddsdde(k,k)=gmod\n      end do\n"

#: Stands for the author's axisymmetric deck: a CAX4T element paired to the
#: material through a solid section.
LEMAITRE_DECK = """\
*Element, type=CAX4T
1, 1, 2, 3, 4
*Elset, elset=BAR, generate
1, 1, 1
*Solid Section, elset=BAR, material=Material-1
*Material, name=Material-1
*User Material, constants=7
1., 2., 3., 4., 5., 6., 7.
"""

#: Stands for the CAEAssistant plane-stress orthotropic UMAT: a 3x3 tangent
#: zeroed over a loop, with the 1-3 and 2-3 couplings written as explicit zeros.
CAE_PLANE_STRESS = """\
      DIMENSION STRESS(NTENS),DDSDDE(NTENS,NTENS)
      DO I=1,3
        DO J=1,3
          DDSDDE(I,J)=0.D0
        END DO
      END DO
      DDSDDE(1,1)=Q11
      DDSDDE(2,2)=Q22
      DDSDDE(1,2)=Q12
      DDSDDE(2,1)=Q12
      DDSDDE(1,3)=0.D0
      DDSDDE(3,1)=0.D0
      DDSDDE(2,3)=0.D0
      DDSDDE(3,2)=0.D0
      DDSDDE(3,3)=Q66
"""

#: Stands for abuganza's plane-stress tissue UMAT: a 3-vector built from a
#: 6-vector with the shear (Voigt 4) in slot 3, an i/j index-map pair sending
#: slot 3 to (1,2), and STRESS filled over a loop bounded at 3.
ABUGANZA_PLANE_STRESS = """\
      s3(1) = s6(1)
      s3(2) = s6(2)
      s3(3) = s6(4)
      Kmapi(3) = 1
      Kmapj(1) = 1
      Kmapj(2) = 2
      Kmapj(3) = 2
      do k=1,3
         STRESS(k) = s3(k)
      end do
"""

#: Stands for toruinaba's plane-stress kinematic-hardening UMAT (free form):
#: a guard that leaves unless the layout is plane stress, then a 3x3 copy.
TORUINABA_PLANE_STRESS = """\
    if (NTENS /= 3 .or. NDI /= 2) then
        return
    end if
    do j = 1, 3
        do i = 1, 3
            ddsdde(i,j) = cmat(i,j)
        end do
    end do
"""


def test_lemaitre_three_is_the_direct_block_not_plane_stress():
    found = from_source(LEMAITRE, "lemaitreDamageNonLocal.f")
    assert found.ntens == 0 and found.family == ""
    assert found.min_ntens == 4
    assert "shear starts at index 4" in found.undecided


def test_lemaitre_the_authors_axisymmetric_deck_decides():
    settled = settle(
        LEMAITRE,
        "lemaitreDamageNonLocal.f",
        LEMAITRE_DECK,
        "axiSymmetricNotchedBar.inp",
        "Material-1",
    )
    assert settled.element == "CAX4"
    assert settled.formulation.family == "axisymmetric"
    assert "the deck decides" in settled.agreement
    # Both halves of the evidence are on the record.
    assert "CAX4T" in settled.formulation.reason
    assert "do k=4,ntens" in settled.formulation.reason


def test_lemaitre_on_a_plane_stress_element_is_unsupported_not_run():
    deck = LEMAITRE_DECK.replace("CAX4T", "CPS4")
    settled = settle(LEMAITRE, "lemaitreDamageNonLocal.f", deck, "x.inp", "Material-1")
    assert not settled.element
    assert settled.formulation.reason.startswith("unsupported")


def test_a_bare_bound_of_three_with_no_witness_is_undecided():
    bare = LEMAITRE.replace(SHEAR_LOOP, "")
    assert bare != LEMAITRE
    found = from_source(bare, "umat.f")
    assert not found.known
    assert found.min_ntens == 0
    assert "nothing in the source says index 3 is a shear" in found.undecided


@pytest.mark.parametrize(
    "text, name, witness",
    [
        (CAE_PLANE_STRESS, "PLANESTRESS-ORTHOTROPIC.for", "explicit zero"),
        (ABUGANZA_PLANE_STRESS, "UMAT_Tissue_2d.f", "s3(3) = s6(4)"),
        (TORUINABA_PLANE_STRESS, "yu_kinematic.f90", "NTENS /= 3"),
    ],
)
def test_genuine_plane_stress_sources_are_still_plane_stress(text, name, witness):
    found = from_source(text, name)
    assert found.ntens == 3, found.evidence
    assert found.family == "plane stress"
    assert any(witness in line for line in found.evidence)


def test_an_index_map_alone_is_a_witness():
    only_map = (
        "\n".join(
            line
            for line in ABUGANZA_PLANE_STRESS.splitlines()
            if "s3(3)" not in line
        )
        + "\n"
    )
    found = from_source(only_map, "x.f")
    assert found.ntens == 3
    assert any("index map" in line for line in found.evidence)


def test_a_lone_one_element_assignment_is_not_an_index_map():
    text = LEMAITRE.replace(SHEAR_LOOP, "      n(3) = 1\n      m(3) = 2\n")
    assert text != LEMAITRE
    assert from_source(text, "x.f").ntens == 0


_CACHE = (WORKSPACE / "discovery_cache")
_LEMAITRE = "awhelanUCD__Lemaitre-damage-UMAT-Public"
_CAE = "CAEAssistant-Group__UMAT-Abaqus-Tsai-Hill-Orthotropic-Composite-Subroutine"
#: (cache path, sha256 of the acquired file, the NTENS the source settles).
_FULL = [
    (f"{_LEMAITRE}/nonLocalLemaitre/lemaitreDamageNonLocal.f",
     "f841c77b3c7687f1ff8696a4758f9198aeb85dbd06c97d409c400baaa4f87a38", 0),
    (f"{_LEMAITRE}/HETVAL_nonLocalLemaitre/HETVAL_lemaitreDamageNonLocal.f",
     "05950d293364cca35118efca869e045ef1c37c2fa8193fc758b4697e7edc41ca", 0),
    (f"{_CAE}/PLANESTRESS-ORTHOTROPIC.for",
     "0edb02e263c139f7a018d606e866f1814fe0069cac9c488a9ed9d79865882056", 3),
    ("abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_stress.f",
     "16cb30f2f14c98ed86cc975fc8b9fa382743a7a7c243904756bb14a07d9db094", 3),
    ("abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_strain.f",
     "d4e32013f77be9e17f8eadd5669cc9b56bbdc0e4c646586bd1c0973816736ac6", 4),
    ("toruinaba__manforge/fortran/yu_kinematic_ps.f90",
     "fa77fb52b0580aed13ec6f6ac4dc9be7e1e9cfdc4260979d7a403f4cd3c84d8a", 3),
    ("nsundar__PFM_UMAT_ElastoPlastic/UMAT_phasefield_plasticity.f",
     "c8099067cf56f3e96c52667dc4bf351e183cc0f929c5eb0345521b6294b92ead", 0),
]


def _cached(relative: str, sha256: str) -> str:
    """The acquired file's text, skipping when the cache is absent and failing
    when it holds a different file than the one these expectations were read
    from."""
    path = _CACHE / relative
    if not path.is_file():
        pytest.skip(f"acquisition cache not present: {relative}")
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha256, f"cache changed: {relative}"
    return data.decode("utf-8", "replace")


@pytest.mark.parametrize("relative, sha256, expected", _FULL)
def test_full_corpus_files(relative, sha256, expected):
    found = from_source(_cached(relative, sha256), relative)
    assert found.ntens == expected, found.evidence


def test_full_lemaitre_with_its_own_deck():
    folder = f"{_LEMAITRE}/nonLocalLemaitre"
    source = _cached(f"{folder}/lemaitreDamageNonLocal.f", _FULL[0][1])
    deck = _cached(
        f"{folder}/axiSymmetricNotchedBar.inp",
        "fcd63350df8a8c7c9f76681d57095827a79521ff7e4c93eadae9bf44188ac49f",
    )
    settled = settle(
        source,
        "lemaitreDamageNonLocal.f",
        deck,
        "axiSymmetricNotchedBar.inp",
        "Material-1",
    )
    assert settled.element == "CAX4"
    assert "the deck decides" in settled.agreement
