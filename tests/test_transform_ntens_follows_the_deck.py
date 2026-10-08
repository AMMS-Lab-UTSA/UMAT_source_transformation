"""B17 rule G2b: the transform is built at the NTENS of the deck's element.

The transform (tools/transform_all.py::_ntens_of) and the verification
(umat_oti.abaqus.experiment.plan) read the element from ONE function,
``deck_element``. Before, they read two different decks for some sources, so
PhaseFieldComp / Bilinear-CZM / czmHealing were transformed at NTENS 6 / 2 / 6
and driven at 4 / 3 / 2. The guard that refuses a mismatch stays and is the
planted-error canary: a wrong NTENS mapping must fail, never run.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from umat_oti.abaqus.experiment import deck_element, ntens_of_deck_element, plan

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

SOURCE = """\
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,rpl,ddsddt,drplde,
     1 drpldt,stran,dstran,time,dtime,temp,dtemp,predef,dpred,cmname,
     2 ndi,nshr,ntens,nstatv,props,nprops,coords,drot,pnewdt,celent,
     3 dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc)
      include 'aba_param.inc'
      character*80 cmname
      dimension stress(ntens),statev(nstatv),ddsdde(ntens,ntens),
     1 stran(ntens),dstran(ntens),props(nprops)
      do i=1,ntens
        do j=1,ntens
          ddsdde(i,j)=0.d0
        end do
        ddsdde(i,i)=props(1)
        stress(i)=stress(i)+props(1)*dstran(i)
      end do
      return
      end
"""


def _deck(element: str, nodes: int) -> str:
    ids = ", ".join(str(i + 1) for i in range(nodes))
    return f"""\
*Node
1, 0., 0., 0.
*Element, type={element}
1, {ids}
*Elset, elset=ALL
 1,
*Solid Section, elset=ALL, material=MAT
*Material, name=MAT
*Depvar
    1,
*User Material, constants=2
    100., 0.3
"""


def _repo(tmp_path, element, nodes):
    repo = tmp_path / "owner__repo"
    repo.mkdir()
    (repo / "umat.for").write_text(SOURCE)
    (repo / "job.inp").write_text(_deck(element, nodes))
    return repo


@pytest.mark.parametrize("element,nodes,expected", [("CPE4", 4, 4), ("CPS4", 4, 3),
                                                    ("CAX4", 4, 4), ("C3D8", 8, 6)])
def test_the_transform_ntens_is_the_deck_elements(tmp_path, element, nodes, expected):
    repo = _repo(tmp_path, element, nodes)
    ntens, why = ntens_of_deck_element(repo / "umat.for", repo)
    assert ntens == expected, why
    import transform_all
    got, evidence = transform_all._ntens_of({}, repo / "umat.for", None, tmp_path)
    assert got == expected, evidence


def test_transform_and_verification_read_the_same_element(tmp_path):
    repo = _repo(tmp_path, "CPE4", 4)
    pairing, settled, _ = deck_element(repo / "umat.for", repo)
    planned = plan(repo / "umat.for", repo)
    assert planned.settled.element == settled.element == "CPE4"


def test_a_stored_transform_at_the_wrong_ntens_is_refused_never_run():
    # PLANTED ERROR: the pass23 store held NTENS 6 / 2 / 6 for elements calling
    # with 4 / 3 / 2. The guard must name both numbers and refuse.
    import verify_store_in_abaqus as V
    for stored, element, ntens in ((6, "CPE4", 4), (2, "COH3D8", 3), (6, "COH2D4T", 2)):
        manifest = SimpleNamespace(ntens=ntens, element_type=element)
        refusal = V.ntens_mismatch(stored, manifest)
        assert refusal and f"NTENS={stored}" in refusal and f"NTENS={ntens}" in refusal
    # and the right mapping passes
    assert V.ntens_mismatch(4, SimpleNamespace(ntens=4, element_type="CPE4")) == ""


def test_a_deliberately_wrong_element_mapping_is_caught_by_the_guard(tmp_path, monkeypatch):
    # PLANTED ERROR in the mapping itself: if CPE4 were mapped to the 6-component
    # geometry, the transform would be built at 6 while the true element calls
    # with 4; the guard compares against the planner's manifest and refuses.
    import verify_store_in_abaqus as V
    repo = _repo(tmp_path, "CPE4", 4)
    right, _ = ntens_of_deck_element(repo / "umat.for", repo)
    from umat_oti.abaqus import elements
    real = elements.geometry_for

    def wrong(element, *a, **k):
        g = real("C3D8" if element == "CPE4" else element, *a, **k)
        return g
    monkeypatch.setattr("umat_oti.abaqus.experiment.geometry_for", wrong)
    mapped, _ = ntens_of_deck_element(repo / "umat.for", repo)
    assert mapped == 6 != right
    refusal = V.ntens_mismatch(mapped, SimpleNamespace(ntens=right, element_type="CPE4"))
    assert refusal


CACHE = REPO.parent / "discovery_cache"
THREE = {
    "MCM-QMUL__PhaseFieldComp/Subroutine/UELUMATPhaseField_AT2.for": 4,
    "harshaa765__Bilinear-CZM-UMAT/Bilinear_CZM_UMAT.for": 3,
    "lucassalmon83860-bit__thesis-benchmark-cases/Benchmarks/Fuel_pellet_quarter/czmHealing.f": 2,
}


@pytest.mark.skipif(not CACHE.is_dir(), reason="needs the discovery cache")
@pytest.mark.parametrize("source,expected", sorted(THREE.items()))
def test_the_three_sources_the_pass23_guard_refused_are_now_transformed_at_the_element(
        source, expected):
    import transform_all
    path = CACHE / source
    if not path.is_file():
        pytest.skip("source not in the cache")
    got, _ = transform_all._ntens_of({}, path, None, CACHE)
    assert got == expected
    planned = plan(path, CACHE / source.split("/")[0])
    from umat_oti.abaqus.elements import geometry_for
    assert geometry_for(planned.settled.element).ntens == expected
