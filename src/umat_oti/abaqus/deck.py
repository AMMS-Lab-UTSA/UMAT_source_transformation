"""A single-element Abaqus deck built from a manifest.

One template, parameterised, rather than a deck written by hand per UMAT. The
model-specific part is the manifest; nothing here knows the name of any
particular material.

Single element and displacement-controlled on purpose. The strain history of
the material point is then known before the job runs, which is what makes a
finite-difference check possible at all: a perturbation has to be applied to a
known increment of strain, and a load-controlled model solves for its own.

The element is driven through every node so that the deformation is homogeneous
and every integration point sees the same strain. That matters for the
comparison -- an inhomogeneous element gives eight different answers and no
statement about the constitutive law.
"""
from __future__ import annotations

from typing import Iterable

from umat_oti.abaqus.manifest import LoadingSegment, VerificationManifest

#: Unit cube corners, in the order Abaqus expects for C3D8.
_NODES = (
    (1, 0.0, 0.0, 0.0), (2, 1.0, 0.0, 0.0), (3, 1.0, 1.0, 0.0), (4, 0.0, 1.0, 0.0),
    (5, 0.0, 0.0, 1.0), (6, 1.0, 0.0, 1.0), (7, 1.0, 1.0, 1.0), (8, 0.0, 1.0, 1.0),
)

#: Plane elements use the first four.
_PLANE_NODES = _NODES[:4]

#: The constant-strain tetrahedron. One integration point, so one material
#: point per job rather than eight identical ones, and -- unlike a reduced
#: hexahedron -- no hourglass modes, so no artificial stiffness has to be
#: supplied. Abaqus rejects a reduced-integration element under a user
#: material without one, and inventing that number is not available here.
_TET_NODES = (
    (1, 0.0, 0.0, 0.0), (2, 1.0, 0.0, 0.0), (3, 0.0, 1.0, 0.0), (4, 0.0, 0.0, 1.0),
)


def _nodes_for(element_type: str) -> tuple[tuple, ...]:
    """The reference geometry this element type is driven on."""
    name = element_type.upper()
    if name.startswith(("CPE", "CPS", "CAX")):
        return _PLANE_NODES
    if name.startswith(("C3D4", "C3D10")):
        return _TET_NODES
    return _NODES


def _displacement(node: tuple[float, float, float],
                  strain: tuple[float, ...]) -> tuple[float, float, float]:
    """Where a corner goes under a homogeneous engineering strain.

    Engineering shear, halved onto the symmetric off-diagonal entries, so that
    the strain the UMAT is handed is the tensor the deck names. Getting that
    factor wrong would perturb a different component than the one the
    finite-difference column is being compared against.
    """
    e11, e22, e33, g12, g13, g23 = (tuple(strain) + (0.0,) * 6)[:6]
    x, y, z = node
    return (
        e11 * x + 0.5 * g12 * y + 0.5 * g13 * z,
        0.5 * g12 * x + e22 * y + 0.5 * g23 * z,
        0.5 * g13 * x + 0.5 * g23 * y + e33 * z,
    )


def _fmt(value: float) -> str:
    return f"{value!r}"


def _material_block(manifest: VerificationManifest) -> list[str]:
    lines = [f"*MATERIAL, NAME={manifest.name.upper()[:60]}"]
    if manifest.nstatv:
        lines += ["*DEPVAR", f"{manifest.nstatv},"]
    header = f"*USER MATERIAL, CONSTANTS={len(manifest.props)}"
    if manifest.unsymmetric:
        header += ", UNSYMM"
    lines.append(header)
    # Eight to a line, which is the fixed-format limit Abaqus reads.
    values = [_fmt(value) for value in manifest.props]
    for start in range(0, len(values), 8):
        lines.append(", ".join(values[start:start + 8]))
    return lines


def _initial_state(manifest: VerificationManifest) -> list[str]:
    if not any(manifest.initial_statev):
        return []
    values = [_fmt(value) for value in manifest.initial_statev]
    lines = ["*INITIAL CONDITIONS, TYPE=SOLUTION"]
    for start in range(0, len(values), 7):
        prefix = "ONE," if start == 0 else ""
        lines.append(prefix + ", ".join(values[start:start + 7]) + ",")
    return lines


def _orientation(manifest: VerificationManifest) -> list[str]:
    """A local system for a model whose response depends on direction.

    Written as three points rather than three angles because Abaqus's
    *ORIENTATION takes an axis definition, and rotating the frame by naming
    where its axes point is checkable by inspection.
    """
    if manifest.orientation is None:
        return []
    import math

    phi1, capital_phi, phi2 = (math.radians(angle) for angle in manifest.orientation)
    c1, s1 = math.cos(phi1), math.sin(phi1)
    c, s = math.cos(capital_phi), math.sin(capital_phi)
    c2, s2 = math.cos(phi2), math.sin(phi2)
    # Bunge ZXZ, the convention every crystal-plasticity code in this corpus
    # states in its own comments.
    a = (
        (c1 * c2 - s1 * s2 * c, s1 * c2 + c1 * s2 * c, s2 * s),
        (-c1 * s2 - s1 * c2 * c, -s1 * s2 + c1 * c2 * c, c2 * s),
        (s1 * s, -c1 * s, c),
    )
    return [
        "*ORIENTATION, NAME=CRYSTAL, SYSTEM=RECTANGULAR",
        ", ".join(_fmt(v) for v in (a[0][0], a[0][1], a[0][2],
                                    a[1][0], a[1][1], a[1][2])),
        "3, 0.",
    ]


def _boundary_for(segment: LoadingSegment, nodes, plane: bool = False) -> list[str]:
    lines = []
    for index, x, y, z in nodes:
        ux, uy, uz = _displacement((x, y, z), segment.strain)
        components = (ux, uy) if plane else (ux, uy, uz)
        for dof, value in enumerate(components, start=1):
            lines.append(f"{index}, {dof}, {dof}, {_fmt(value)}")
    return lines


def generate_deck(manifest: VerificationManifest) -> str:
    """The complete .inp for this manifest."""
    plane = manifest.element_type.upper().startswith(("CPE", "CPS", "CAX"))
    nodes = _nodes_for(manifest.element_type)

    lines: list[str] = [
        "*HEADING",
        f"single-element verification deck for {manifest.name}",
        "** Generated by umat_oti.abaqus.deck from a verification manifest.",
        f"** kinematics: {manifest.kinematics}; ntens: {manifest.ntens}",
        f"** material provenance: {manifest.material_provenance or 'UNSTATED'}",
        "*NODE",
    ]
    for index, x, y, z in nodes:
        lines.append(f"{index}, {_fmt(x)}, {_fmt(y)}"
                     + ("" if plane else f", {_fmt(z)}"))
    lines.append(f"*ELEMENT, TYPE={manifest.element_type}, ELSET=ONE")
    lines.append("1, " + ", ".join(str(index) for index, *_ in nodes))

    section = "*SOLID SECTION, ELSET=ONE, MATERIAL=" + manifest.name.upper()[:60]
    if manifest.orientation is not None:
        section += ", ORIENTATION=CRYSTAL"
    lines += _orientation(manifest)
    lines.append(section)
    if plane:
        lines.append("1.0")
    lines += _material_block(manifest)
    lines += _initial_state(manifest)

    nlgeom = "YES" if manifest.kinematics == "finite" else "NO"
    for segment in manifest.loading:
        increment = 1.0 / max(segment.increments, 1)
        lines += [
            f"** {segment.name}: {segment.description}",
            f"*STEP, NLGEOM={nlgeom}, INC={max(segment.increments * 10, 100)}",
            "*STATIC",
            f"{_fmt(increment * segment.period)}, {_fmt(segment.period)}, "
            f"{_fmt(increment * segment.period * 1e-5)}, "
            f"{_fmt(increment * segment.period)}",
            "*BOUNDARY, OP=NEW",
        ]
        lines += _boundary_for(segment, nodes, plane)
        lines += [
            "*OUTPUT, FIELD, FREQUENCY=1",
            "*ELEMENT OUTPUT, POSITION=INTEGRATION POINTS",
            ", ".join(manifest.outputs),
            "*EL PRINT, POSITION=INTEGRATION POINTS, FREQ=1",
        ]
        lines += [f"{name}," for name in manifest.outputs]
        lines.append("*END STEP")
    return "\n".join(lines) + "\n"


def total_increments(loading: Iterable[LoadingSegment]) -> int:
    """How many increments a job built from this loading should report."""
    return sum(segment.increments for segment in loading)
