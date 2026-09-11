"""Which elements a verification deck may be generated on, and their geometry.

The generator used to choose geometry by prefix: anything starting ``C3D4`` or
``C3D10`` got a four-node tetrahedron, and *anything else* fell through to an
eight-node hexahedron. So ``C3D10`` -- a ten-node element -- was emitted with
four nodes, and a request for ``S4R``, ``C3D20H`` or a name with a typo in it
produced a deck that looked complete and described a different element than
the one asked for. A verification deck that silently describes something other
than what it claims is worse than no deck: every number that comes out of it
is attributed to the wrong test.

So this is a registry, not a guess. An element is here with its connectivity
and the stress-tensor shape it implies, or it is refused by name.

Refusals are deliberate, not gaps waiting to be filled:

* Reduced integration (``C3D8R``, ``CPE4R``, ...) needs hourglass stiffness.
  Abaqus rejects a reduced element under a user material without it, and the
  value is a modelling choice about the material -- not something this
  generator may invent to make a job start.
* Structural elements (``S4R``, ``B31``, membranes, rigid bodies) do not hand
  a UMAT the same tensor a continuum element does, and several impose plane
  stress on the material implicitly.
* Coupled temperature-displacement (``CAX4T``, ``C3D8T``) call the UMAT with
  a thermal contract this harness does not drive.
* User elements (``U1``, ``U3``) are the author's own element, not ours.

Cohesive elements are here, and were not. A cohesive law IS drivable: Abaqus
calls a UMAT for a ``*COHESIVE SECTION, RESPONSE=TRACTION SEPARATION``, hands
it NDI=1 direct and NSHR=1 (2D) or 2 (3D) shear components, and what it calls
STRAN is the separation divided by the constitutive thickness. The author of
``harshaa765__Bilinear-CZM-UMAT`` published exactly that experiment --
``Job_1_Harsh_UMAT.inp``, one COH3D8 opened to 0.2 and then released -- and
this harness refused the source with "no continuum element in this harness
calls a UMAT that way", which was true of the registry and not of Abaqus.

What remains genuinely out of reach is the COUPLED form. ``COH2D4T`` calls the
UMAT with a temperature, and ``lucassalmon83860-bit``'s healing law computes
its kinetics as ``PROPS(8)*Exp(-PROPS(9)/(8.34*TEMP))`` -- driven at TEMP=0
that divides by zero, and inventing a temperature would invent the experiment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class UnsupportedElement(ValueError):
    """A deck was asked for on an element this generator will not emit."""


@dataclass(frozen=True)
class ElementGeometry:
    """One accepted element: its nodes, its section, and its tensor shape."""

    name: str
    #: ``(id, x, y, z)`` in the order Abaqus reads the connectivity.
    nodes: tuple[tuple[int, float, float, float], ...]
    #: 2 for a planar or axisymmetric element, 3 for a continuum one.
    dimension: int
    #: Direct and shear components the UMAT is called with.
    ndi: int
    nshr: int
    #: ``*SOLID SECTION`` for continuum, and a thickness line for planar.
    needs_thickness: bool
    note: str = ""
    #: Which section keyword attaches this element to its material, and what
    #: the components of its stress array MEAN. A cohesive element's "stress"
    #: is a traction and its "strain" a separation, and a deck that drives it
    #: with a homogeneous strain tensor is driving something else.
    section: str = "SOLID"
    kind: str = "continuum"

    @property
    def ntens(self) -> int:
        return self.ndi + self.nshr

    @property
    def node_count(self) -> int:
        return len(self.nodes)


def _mid(a, b):
    return ((a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0, (a[3] + b[3]) / 2.0)


def _numbered(points) -> tuple:
    return tuple((index, *point) for index, point in enumerate(points, start=1))


#: Unit cube corners in C3D8 connectivity order: bottom face counter-clockwise
#: seen from outside, then the top face in the same order.
_HEX8 = _numbered([
    (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0)])

#: C3D20 adds the twelve edge midpoints: bottom edges, top edges, then the
#: four verticals, which is the order Abaqus reads them in.
_HEX20 = _HEX8 + _numbered([
    _mid(_HEX8[0], _HEX8[1]), _mid(_HEX8[1], _HEX8[2]),
    _mid(_HEX8[2], _HEX8[3]), _mid(_HEX8[3], _HEX8[0]),
    _mid(_HEX8[4], _HEX8[5]), _mid(_HEX8[5], _HEX8[6]),
    _mid(_HEX8[6], _HEX8[7]), _mid(_HEX8[7], _HEX8[4]),
    _mid(_HEX8[0], _HEX8[4]), _mid(_HEX8[1], _HEX8[5]),
    _mid(_HEX8[2], _HEX8[6]), _mid(_HEX8[3], _HEX8[7])])[8:]
_HEX20 = _HEX8 + tuple((index, x, y, z) for index, (_, x, y, z)
                       in enumerate(_HEX20, start=9))

#: The constant-strain tetrahedron. One integration point, so one material
#: point per job rather than eight identical ones, and -- unlike a reduced
#: hexahedron -- no hourglass modes, so no artificial stiffness is needed.
_TET4 = _numbered([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                   (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)])

#: C3D10 adds six edge midpoints: 5 on 1-2, 6 on 2-3, 7 on 3-1, then 8, 9, 10
#: on the edges rising to node 4.
_TET10 = _TET4 + tuple(
    (index, *point) for index, point in enumerate(
        [_mid(_TET4[0], _TET4[1]), _mid(_TET4[1], _TET4[2]),
         _mid(_TET4[2], _TET4[0]), _mid(_TET4[0], _TET4[3]),
         _mid(_TET4[1], _TET4[3]), _mid(_TET4[2], _TET4[3])], start=5))

_QUAD4 = _numbered([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                    (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)])

#: A cohesive element has two coincident faces. COH3D8 numbers the bottom
#: face 1-4 and the top face 5-8 directly above it, and the separation is the
#: displacement of the top face relative to the bottom. The faces are written
#: coincident, exactly as the author's own patch test writes them: the
#: constitutive thickness comes from the *COHESIVE SECTION data line, not from
#: the geometry, so a zero-thickness element is the normal case rather than a
#: degenerate one.
_COH_HEX8 = _numbered([
    (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)])

#: COH2D4 numbers the bottom edge 1-2 and the top edge 4-3, which is the
#: counter-clockwise order Abaqus reads a four-node cohesive element in.
_COH_QUAD4 = _numbered([
    (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0)])
_QUAD8 = _QUAD4 + tuple(
    (index, *point) for index, point in enumerate(
        [_mid(_QUAD4[0], _QUAD4[1]), _mid(_QUAD4[1], _QUAD4[2]),
         _mid(_QUAD4[2], _QUAD4[3]), _mid(_QUAD4[3], _QUAD4[0])], start=5))
_TRI3 = _numbered([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])


def _continuum(name, nodes, note=""):
    return ElementGeometry(name, nodes, 3, 3, 3, False, note)


def _plane_strain(name, nodes, note=""):
    # Plane strain and axisymmetric both hand the UMAT four components:
    # three direct, one shear. The out-of-plane direct component is present
    # and is not zero, which is why NDI is 3 and not 2.
    return ElementGeometry(name, nodes, 2, 3, 1, True, note)


def _plane_stress(name, nodes, note=""):
    return ElementGeometry(name, nodes, 2, 2, 1, True, note)


def _axisymmetric(name, nodes, note=""):
    return ElementGeometry(name, nodes, 2, 3, 1, False, note)


def _cohesive(name, nodes, dimension, nshr, note=""):
    """A traction-separation element: one direct component, one or two shear.

    ``needs_thickness`` is True because ``*COHESIVE SECTION`` takes the
    constitutive thickness on its data line, and this harness writes 1.0 there
    so that what the UMAT is handed as STRAN is numerically the separation --
    which is what the law's own comments call it.
    """
    return ElementGeometry(name, nodes, dimension, 1, nshr, True, note,
                           section="COHESIVE", kind="cohesive")


SUPPORTED: dict[str, ElementGeometry] = {
    element.name: element for element in (
        _continuum("C3D8", _HEX8),
        _continuum("C3D8H", _HEX8, "hybrid: for a nearly incompressible material"),
        _continuum("C3D4", _TET4, "constant strain, one integration point"),
        _continuum("C3D4H", _TET4, "hybrid constant-strain tetrahedron"),
        _continuum("C3D10", _TET10),
        _continuum("C3D10H", _TET10),
        _continuum("C3D20", _HEX20),
        _continuum("C3D20H", _HEX20, "hybrid: the commonest choice in this corpus"),
        _plane_strain("CPE4", _QUAD4),
        _plane_strain("CPE4H", _QUAD4),
        _plane_strain("CPE3", _TRI3, "constant strain"),
        _plane_strain("CPE8", _QUAD8),
        _plane_stress("CPS4", _QUAD4),
        _plane_stress("CPS3", _TRI3, "constant strain"),
        _plane_stress("CPS8", _QUAD8),
        _axisymmetric("CAX4", _QUAD4),
        _axisymmetric("CAX4H", _QUAD4),
        _axisymmetric("CAX3", _TRI3, "constant strain"),
        _axisymmetric("CAX8", _QUAD8),
        _cohesive("COH3D8", _COH_HEX8, 3, 2,
                  "the author's own single-element patch test in "
                  "harshaa765__Bilinear-CZM-UMAT is one of these"),
        _cohesive("COH2D4", _COH_QUAD4, 2, 1),
    )
}

#: Why a name that is a real Abaqus element is still refused. Checked before
#: the generic message so the refusal says something the reader can act on.
_REFUSALS: tuple[tuple[str, str], ...] = (
    ("R", "reduced integration needs an hourglass stiffness, and that value "
          "is a modelling choice about this material rather than something "
          "this generator may invent to make a job start"),
    ("T", "coupled temperature-displacement calls the UMAT with a thermal "
          "contract this harness does not drive"),
    ("E", "the piezoelectric variant adds an electrical degree of freedom "
          "this harness does not drive"),
)

_STRUCTURAL = {
    "COH": ("a cohesive element is supported in its displacement-only form "
            "(COH2D4, COH3D8); the coupled temperature-displacement form "
            "calls the UMAT with a temperature this harness does not drive, "
            "and a healing or ageing law read at TEMP=0 is not the law"),
    "S": "a shell hands the UMAT a plane-stress tensor it must enforce itself",
    "M": "a membrane carries no bending and imposes plane stress",
    "B": "a beam integrates a cross-section rather than a material point",
    "T": "a truss is uniaxial",
    "R": "a rigid body has no material response",
    "F": "a fluid element is not a continuum material point",
    "U": "a user element is the author's own element, not a material",
    "CONN": "a connector is not a continuum material point",
}


def geometry_for(element_type: str) -> ElementGeometry:
    """The accepted geometry for this element, or a refusal that says why.

    Never falls back. A generator that guesses geometry for a name it does not
    know produces a deck describing a different element than the one asked
    for, and every number attributed to that deck is then attributed wrongly.
    """
    name = str(element_type or "").strip().upper()
    if not name:
        raise UnsupportedElement(
            "no element type was given, and there is no default: the tensor "
            "shape a UMAT is called with depends on it")
    found = SUPPORTED.get(name)
    if found is not None:
        return found

    for prefix, why in sorted(_STRUCTURAL.items(), key=lambda item: -len(item[0])):
        if name.startswith(prefix) and not name.startswith(("CPE", "CPS", "CAX")):
            raise UnsupportedElement(
                f"{name} is not supported: {why}. Supported elements are "
                f"{', '.join(sorted(SUPPORTED))}.")
    for marker, why in _REFUSALS:
        base = name.rstrip("H")
        if base.endswith(marker) and base[:-1] in SUPPORTED:
            raise UnsupportedElement(f"{name} is not supported: {why}")
    raise UnsupportedElement(
        f"{name} is not a supported element type. This generator emits a deck "
        f"only for an element whose connectivity and stress-tensor shape it "
        f"knows exactly. Supported: {', '.join(sorted(SUPPORTED))}.")


def is_supported(element_type: str) -> bool:
    try:
        geometry_for(element_type)
    except UnsupportedElement:
        return False
    return True
