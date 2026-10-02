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

Every excerpt below is verbatim corpus text (file and line given); the
cache-backed test reads the full files where the acquisition cache exists.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.formulation import from_source, settle

#: awhelanUCD__Lemaitre-damage-UMAT-Public/nonLocalLemaitre/
#: lemaitreDamageNonLocal.f lines 16-17 and 56-64.
LEMAITRE = """\
      dimension stress(ntens),statev(nstatv),ddsdde(ntens,ntens),
     1 ddsddt(ntens),drplde(ntens),stran(ntens),dstran(ntens),
      do i=1,3
       do j=1,3
        ddsdde(j,i)=elam
       end do
       ddsdde(i,i)=2.d0*eg+elam
      end do
      do i=4,ntens
       ddsdde(i,i)=eg
      end do
"""

#: The author's deck beside it, reduced to what pairs the material
#: (axiSymmetricNotchedBar.inp: *Element, type=CAX4T at line 4661 and
#: *Solid Section ... material=Material-1 at line 9177).
LEMAITRE_DECK = """\
*Element, type=CAX4T
1, 1, 2, 3, 4
*Elset, elset=Set-34, generate
1, 1, 1
*Solid Section, elset=Set-34, material=Material-1
*Material, name=Material-1
*User Material, constants=7
1., 2., 3., 4., 5., 6., 7.
"""

#: CAEAssistant-Group__UMAT-Abaqus-Tsai-Hill-Orthotropic-Composite-Subroutine/
#: PLANESTRESS-ORTHOTROPIC.for lines 57-70.
CAE_PLANE_STRESS = """\
      DIMENSION STRESS(NTENS),STATEV(NSTATV),
     1 DDSDDE(NTENS,NTENS),DDSDDT(NTENS),DRPLDE(NTENS),
      DO K1=1,3
        DO K2=1,3
            DDSDDE(K2,K1)=0.0
        END DO
      END DO
      DDSDDE(1,1)=D11
      DDSDDE(1,2)=D12
      DDSDDE(2,2)=D22
      DDSDDE(1,3)=0.0
      DDSDDE(2,3)=0.0
      DDSDDE(3,3)=D66
      DDSDDE(2,1)=D12
      DDSDDE(3,1)=0.0
      DDSDDE(3,2)=0.0
"""

#: abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_stress.f
#: lines 421-423, 470-473 and 606-607.
ABUGANZA_PLANE_STRESS = """\
      sigma2D(1) = sigma(1)
      sigma2D(2) = sigma(2)
      sigma2D(3) = sigma(4)
      Itoi2D(3) = 1
      Itoj2D(1) = 1
      Itoj2D(2) = 2
      Itoj2D(3) = 2
      do II=1,3
         STRESS(II) = sigma2D(II)
      end do
"""

#: toruinaba__manforge/fortran/yu_kinematic_ps.f90 lines 1433-1434 (the
#: plane-stress guard) and the tangent copy at 1204-1205.
TORUINABA_PLANE_STRESS = """\
    if (NTENS /= 3 .or. NDI /= 2 .or. NSHR /= 1 .or. &
        NSTATV < 13 .or. NPROPS < 12) then
        return
    end if
    do jj = 1, 3
        do ii = 1, 3
            ddsdde(ii,jj) = C(ii,jj)
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
    assert "do i=4,ntens" in settled.formulation.reason


def test_lemaitre_on_a_plane_stress_element_is_unsupported_not_run():
    deck = LEMAITRE_DECK.replace("CAX4T", "CPS4")
    settled = settle(LEMAITRE, "lemaitreDamageNonLocal.f", deck, "x.inp", "Material-1")
    assert not settled.element
    assert settled.formulation.reason.startswith("unsupported")


def test_a_bare_bound_of_three_with_no_witness_is_undecided():
    bare = LEMAITRE.replace(
        "      do i=4,ntens\n       ddsdde(i,i)=eg\n      end do\n", ""
    )
    found = from_source(bare, "umat.f")
    assert not found.known
    assert found.min_ntens == 0
    assert "nothing in the source says index 3 is a shear" in found.undecided


@pytest.mark.parametrize(
    "text, name, witness",
    [
        (CAE_PLANE_STRESS, "PLANESTRESS-ORTHOTROPIC.for", "explicit zero"),
        (ABUGANZA_PLANE_STRESS, "UMAT_Tissue_2d.f", "sigma2D(3) = sigma(4)"),
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
            if "sigma2D(3)" not in line
        )
        + "\n"
    )
    found = from_source(only_map, "x.f")
    assert found.ntens == 3
    assert any("index map" in line for line in found.evidence)


def test_a_lone_one_element_assignment_is_not_an_index_map():
    text = LEMAITRE.replace(
        "      do i=4,ntens\n       ddsdde(i,i)=eg\n      end do\n",
        "      n(3) = 1\n      m(3) = 2\n",
    )
    assert from_source(text, "x.f").ntens == 0


_CACHE = Path("/home/ammslab3/softwarex_work/discovery_cache")
_LEMAITRE = "awhelanUCD__Lemaitre-damage-UMAT-Public"
_CAE = "CAEAssistant-Group__UMAT-Abaqus-Tsai-Hill-Orthotropic-Composite-Subroutine"
_FULL = [
    (f"{_LEMAITRE}/nonLocalLemaitre/lemaitreDamageNonLocal.f", 0),
    (f"{_LEMAITRE}/HETVAL_nonLocalLemaitre/HETVAL_lemaitreDamageNonLocal.f", 0),
    (f"{_CAE}/PLANESTRESS-ORTHOTROPIC.for", 3),
    ("abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_stress.f", 3),
    ("abuganza__UMAT_anisotropic_damage/UMAT_Tissue_2d_plane_strain.f", 4),
    ("toruinaba__manforge/fortran/yu_kinematic_ps.f90", 3),
    ("nsundar__PFM_UMAT_ElastoPlastic/UMAT_phasefield_plasticity.f", 0),
]


@pytest.mark.parametrize("relative, expected", _FULL)
def test_full_corpus_files(relative, expected):
    path = _CACHE / relative
    if not path.is_file():
        pytest.skip(f"acquisition cache not present: {relative}")
    found = from_source(path.read_text(errors="replace"), str(path))
    assert found.ntens == expected, found.evidence


def test_full_lemaitre_with_its_own_deck():
    folder = _CACHE / "awhelanUCD__Lemaitre-damage-UMAT-Public/nonLocalLemaitre"
    source, deck = (
        folder / "lemaitreDamageNonLocal.f",
        folder / "axiSymmetricNotchedBar.inp",
    )
    if not (source.is_file() and deck.is_file()):
        pytest.skip("acquisition cache not present")
    settled = settle(
        source.read_text(errors="replace"),
        str(source),
        deck.read_text(errors="replace"),
        deck.name,
        "Material-1",
    )
    assert settled.element == "CAX4"
    assert "the deck decides" in settled.agreement
