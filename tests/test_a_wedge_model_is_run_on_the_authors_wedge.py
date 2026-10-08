"""B20 rule H1: a model meshed with wedges only is run on the author's wedge element.

Alex / Car / Robot (C3D6H), Bunny, Model_car, Human-face, Alex 20470 and 749 (C3D15) were driven on a unit
hexahedron: 8 integration points where the author's element has 2 or 9, and the author's nodes thrown away
because a wedge has 6 corners and a hexahedron 8. A deck that mixes wedges with hexahedra keeps the
hexahedron family.
"""
from pathlib import Path

import pytest

from umat_oti.abaqus.coordinate_domain import AuthorElement, author_elements
from umat_oti.abaqus.deck import generate_deck, nodes_for_manifest
from umat_oti.abaqus.elements import (UnsupportedElement, geometry_for,
                                      with_midside_nodes)
from umat_oti.abaqus.experiment import plan
from umat_oti.abaqus.formulation import choose
from umat_oti.abaqus.frames import points_for

pytestmark = pytest.mark.unit

SOURCE = """\
      subroutine umat(stress,statev,ddsdde,sse,spd,scd,rpl,ddsddt,drplde,
     1 drpldt,stran,dstran,time,dtime,temp,dtemp,predef,dpred,cmname,
     2 ndi,nshr,ntens,nstatv,props,nprops,coords,drot,pnewdt,celent,
     3 dfgrd0,dfgrd1,noel,npt,layer,kspt,kstep,kinc)
      include 'aba_param.inc'
      character*80 cmname
      dimension stress(ntens),statev(nstatv),ddsdde(ntens,ntens),
     1 stran(ntens),dstran(ntens),props(nprops),coords(3)
      real*8 thick
      if (npt .eq. 1) thick = -0.5d0
      if (npt .eq. 2) thick = 0.5d0
      statev(1) = coords(3)
      statev(2) = thick
      do i=1,ntens
        stress(i)=stress(i)+props(1)*dstran(i)
        ddsdde(i,i)=props(1)
      end do
      return
      end
"""


def _deck(element, nodes):
    # two wedges stacked on a 1 x 1 x 0.01 plate so the author's nodes are not the unit ones
    body = ["*Node"]
    pts = [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 0.01), (2, 0, 0.01), (0, 2, 0.01)]
    for i, p in enumerate(pts, start=1):
        body.append(f"{i}, {p[0]}, {p[1]}, {p[2]}")
    body.append(f"*Element, type={element}")
    body.append("1, " + ", ".join(str(i) for i in range(1, 7)))
    body += ["*Elset, elset=ALL", " 1,", "*Solid Section, elset=ALL, material=MAT",
             "*Material, name=MAT", "*Depvar", "    2,", "*User Material, constants=2",
             "    100., 0.3"]
    return "\n".join(body) + "\n"


def test_wedge_geometry_has_the_authors_node_counts():
    assert geometry_for("C3D6H").node_count == 6
    assert geometry_for("C3D15").node_count == 15
    assert geometry_for("C3D15H").ndi == 3 and geometry_for("C3D15H").nshr == 3
    mids = geometry_for("C3D15").nodes[6:]
    assert mids[0][1:] == (0.5, 0.0, 0.0)          # node 7 on edge 1-2
    assert mids[8][1:] == (0.0, 1.0, 0.5)          # node 15 on the vertical 3-6


def test_integration_points_are_the_elements_own():
    assert points_for("C3D6H") == 2 and points_for("C3D6") == 2
    assert points_for("C3D15") == 9 and points_for("C3D15H") == 9
    assert points_for("C3D8H") == 8


@pytest.mark.parametrize("kinds,expected", [
    (("C3D6H",), "C3D6H"), (("C3D6",), "C3D6"), (("C3D15",), "C3D15"),
    (("C3D15H",), "C3D15H"), (("C3D15", "C3D15H"), "C3D15H"),
    # not wedge-only: the existing choice, unchanged
    (("C3D6H", "C3D8H"), "C3D8H"), (("C3D8",), "C3D8"), (("C3D20H",), "C3D8H"),
    (("C3D4",), "C3D8"), (("C3D6", "C3D8"), "C3D8")])
def test_only_a_wedge_only_deck_runs_on_a_wedge(kinds, expected):
    assert choose(kinds).element == expected


def test_a_hexahedron_forced_onto_a_wedge_fails_the_node_check(tmp_path):
    # PLANTED ERROR: eight corner coordinates handed to a six-node element
    repo = tmp_path / "owner__repo"
    repo.mkdir()
    (repo / "umat.for").write_text(SOURCE)
    (repo / "job.inp").write_text(_deck("C3D6H", 6))
    found = plan(repo / "umat.for", repo)
    assert found.found, found.experiment.refusal
    manifest = found.manifest
    assert manifest.element_type == "C3D6H"
    from dataclasses import replace
    bad = replace(manifest, node_coordinates=tuple(
        (i, float(i), 0.0, 0.0) for i in range(1, 9)))
    with pytest.raises(UnsupportedElement):
        nodes_for_manifest(bad)


def test_the_plan_for_a_wedge_deck_is_the_wedge_with_the_authors_nodes(tmp_path):
    repo = tmp_path / "owner__repo"
    repo.mkdir()
    (repo / "umat.for").write_text(SOURCE.replace(
        "statev(1) = coords(3)", "z = coords(3)\n      statev(1) = 1.0d0/(z+10.0d0)"))
    (repo / "job.inp").write_text(_deck("C3D6H", 6))
    found = plan(repo / "umat.for", repo)
    assert found.found, found.experiment.refusal
    assert found.settled.element == "C3D6H"
    deck = generate_deck(found.manifest)
    assert "TYPE=C3D6H" in deck and "TYPE=C3D8H" not in deck
    assert "*SOLID SECTION" in deck.upper()
    nodes = nodes_for_manifest(found.manifest)
    assert len(nodes) == 6
    # the element is the author's coordinates (thin plate), not a unit cube, when the routine reads COORDS
    if found.manifest.node_coordinates:
        assert max(abs(n[3]) for n in nodes) == pytest.approx(0.01)


def test_a_quadratic_wedge_is_completed_with_edge_midpoints(tmp_path):
    corners = tuple((i, x, y, z) for i, (x, y, z) in enumerate(
        [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 0.01), (2, 0, 0.01), (0, 2, 0.01)], start=1))
    full = with_midside_nodes("C3D15", corners)
    assert len(full) == 15 and full[6][1:] == (1.0, 0.0, 0.0) and full[14][1:] == (0.0, 2.0, 0.005)
    assert with_midside_nodes("C3D6H", corners) == corners


def test_the_sample_points_of_a_wedge_are_its_gauss_points():
    nodes = tuple((i, x, y, z) for i, (x, y, z) in enumerate(
        [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1)], start=1))
    two = AuthorElement(1, "C3D6H", nodes).sample_points()
    nine = AuthorElement(1, "C3D15", nodes).sample_points()
    assert len(two) == 6 + 1 + 2 and len(nine) == 6 + 1 + 9
    zs = sorted({round(p[2], 6) for p in two[7:]})
    assert zs == [round(0.5 - 0.5 / 3 ** 0.5, 6), round(0.5 + 0.5 / 3 ** 0.5, 6)]
