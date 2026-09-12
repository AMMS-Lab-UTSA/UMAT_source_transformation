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

from umat_oti.abaqus.elements import UnsupportedElement, geometry_for
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


def nodes_for_manifest(manifest: VerificationManifest) -> tuple[tuple, ...]:
    """Where this manifest's element actually sits.

    The registry's reference geometry is a unit cube at the origin, which is a
    fine material point for a routine that never looks at where it is and the
    wrong one for a routine that does. When the manifest carries coordinates --
    one element of the author's own mesh, chosen by
    :mod:`umat_oti.abaqus.coordinate_domain` -- those are used, and the node
    COUNT is still the registry's, because the element type has to match what
    the connectivity describes.
    """
    geometry = geometry_for(manifest.element_type)
    given = tuple(manifest.node_coordinates or ())
    if not given:
        return tuple(geometry.nodes)
    if len(given) != geometry.node_count:
        raise UnsupportedElement(
            f"{geometry.name} has {geometry.node_count} nodes and this "
            f"manifest carries {len(given)} coordinates. A deck that numbered "
            f"a different count would describe a different element than the "
            f"one it names.")
    return tuple((index + 1, float(x), float(y), float(z))
                 for index, (_id, x, y, z) in enumerate(given))


def _nodes_for(element_type: str) -> tuple[tuple, ...]:
    """The reference geometry this element type is driven on.

    Delegates to the registry in :mod:`umat_oti.abaqus.elements`, which
    refuses a name it does not know rather than falling back. This function
    used to choose by prefix and end with ``return _NODES``, so a ten-node
    C3D10 was emitted with four nodes and any unrecognised name -- ``S4R``,
    ``C3D20H``, a typo -- silently became an eight-node hexahedron.
    """
    return tuple(geometry_for(element_type).nodes)


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
    """Where the state starts, in whichever form the author's deck used.

    ``USER`` asks Abaqus to call the source's own SDVINI. Omitting it left
    every state variable at zero, and a model that divides by one -- a growth
    stretch initialised to 1.0, say -- returns NaN from the first increment.
    Five mholla growth UMATs failed exactly that way while their two siblings
    that do not read state verified cleanly.
    """
    if manifest.initial_state_from_user_subroutine:
        return ["*INITIAL CONDITIONS, TYPE=SOLUTION, USER"]
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
    if manifest.orientation_axes is not None:
        axes = tuple(float(value) for value in manifest.orientation_axes)[:6]
        if len(axes) < 6:                          # pragma: no cover - guarded
            raise ValueError("an orientation takes six numbers: a point on "
                             "the local 1-axis and a point in the 1-2 plane")
        axis, angle = manifest.orientation_rotation or (3, 0.0)
        return ["*ORIENTATION, NAME=LOCAL, SYSTEM=RECTANGULAR",
                ", ".join(_fmt(value) for value in axes),
                f"{int(axis)}, {_fmt(float(angle))}"]
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


def _boundary_for(segment: LoadingSegment, nodes, plane: bool = False,
                  geometry=None, plane_strain: tuple = ()) -> list[str]:
    """What holds this element, which depends on what drives it.

    Four kinds of segment and four answers, because a boundary condition that
    suits one makes another meaningless. A prescribed-strain segment drives
    every node. A body-force segment must leave the element free to deform or
    the load does no work. A TIME-driven segment -- a growth, a swelling -- has
    nothing prescribed at all, and holding it would ask the routine about a
    state the author's model never reaches. A cohesive segment prescribes a
    displacement JUMP between two faces, not a strain.
    """
    if geometry is not None and geometry.section == "COHESIVE":
        # Tested on the SECTION and not on the kind string: when the coupled
        # cohesive elements were added their kind became "cohesive thermal",
        # an equality test against "cohesive" stopped matching, and the top
        # face of every COH2D4T silently got a separation of zero -- a deck
        # that looked complete and prescribed nothing.
        return _cohesive_boundary(segment, nodes, geometry)
    if segment.body_force or segment.time_only:
        return _rigid_body_restraint(segment, nodes, plane,
                                     plane_strain=plane_strain)
    lines = []
    for index, x, y, z in nodes:
        ux, uy, uz = _displacement((x, y, z), segment.strain)
        components = (ux, uy) if plane else (ux, uy, uz)
        for dof, value in enumerate(components, start=1):
            lines.append(f"{index}, {dof}, {dof}, {_fmt(value)}")
    return lines


def _cohesive_boundary(segment: LoadingSegment, nodes, geometry) -> list[str]:
    """Hold the bottom face and move the top one by the prescribed separation.

    A cohesive element's two faces are coincident and its connectivity lists
    the bottom one first. The displacement of the top face relative to the
    bottom IS the separation the UMAT is handed, and the components are
    ordered normal first: for COH3D8 the normal is the direction from the
    bottom face to the top, which for a face written counter-clockwise in the
    x-y plane is global 3; for COH2D4 with its bottom edge along x it is
    global 2.

    Written exactly the way the author of ``harshaa765__Bilinear-CZM-UMAT``
    writes it in ``Job_1_Harsh_UMAT.inp``: ``Lower, 1..3`` fixed and the upper
    face driven, there through an equation and here node by node, which is the
    same prescribed jump with one fewer degree of freedom to go wrong.
    """
    half = len(nodes) // 2
    bottom, top = nodes[:half], nodes[half:]
    normal, shear_one, shear_two = (tuple(segment.separation) + (0.0,) * 3)[:3]
    if geometry.dimension == 2:
        # x is the shear direction, y the normal.
        wanted = (shear_one, normal)
    else:
        wanted = (shear_one, shear_two, normal)
    lines: list[str] = []
    for index, *_rest in bottom:
        for dof in range(1, len(wanted) + 1):
            lines.append(f"{index}, {dof}, {dof}, 0.0")
    for index, *_rest in top:
        for dof, value in enumerate(wanted, start=1):
            lines.append(f"{index}, {dof}, {dof}, {_fmt(float(value))}")
    return lines


def _restraint_nodes(nodes) -> tuple:
    """Three nodes that between them remove every rigid-body mode.

    Chosen from the element's own coordinates rather than by node number,
    because the element may be one of the author's -- sitting wherever the
    author's mesh put it -- and "the node at the origin" is then a node that
    does not exist. The anchor is the lowest corner, the second node is the
    one furthest from it along x and the third the one furthest along y, which
    for the reference hexahedron is nodes 1, 2 and 4.
    """
    ordered = sorted(nodes, key=lambda node: (node[1], node[2], node[3]))
    anchor = ordered[0]
    along_x = max(nodes, key=lambda node: (abs(node[1] - anchor[1]),
                                           -abs(node[2] - anchor[2])))
    along_y = max(nodes, key=lambda node: (abs(node[2] - anchor[2]),
                                           -abs(node[1] - anchor[1])))
    return anchor, along_x, along_y


def _rigid_body_restraint(segment: LoadingSegment, nodes,
                          plane: bool = False,
                          plane_strain: tuple = ()) -> list[str]:
    """Remove the rigid-body modes and nothing else.

    A body force does work only on degrees of freedom that are free, and a
    growth tensor produces deformation only where the element may deform.
    Holding every node -- which is what a prescribed-displacement segment
    does -- makes the load do nothing and the growth fight the boundary, so
    the routine is asked about a state it never reaches.

    ``plane_strain`` is different in kind from a support: a deck that writes
    ``Plate-1.WholeRegion, 3, 3`` is imposing a plane-strain condition on the
    material, not holding the model up, so it goes on every node. What is left
    after it is the rigid-body modes, and those are removed at three nodes.
    """
    lines: list[str] = []
    limit = 2 if plane else 3
    constrained = {dof for dof in plane_strain if 1 <= dof <= limit}
    for index, *_rest in nodes:
        for dof in sorted(constrained):
            lines.append(f"{index}, {dof}, {dof}, 0.0")
    clamped = tuple(dof for dof in segment.clamped_face if 1 <= dof <= limit)
    if clamped:
        # The author's own support, applied to the face at minimum x -- their
        # LeftEnd. It restrains the growth without preventing it: the opposite
        # face is still free, so the element can change volume and a nearly
        # incompressible material is never asked to do so against its own bulk
        # modulus. That distinction is the difference between a stress of the
        # order of the material's constants and one 1e4 times them.
        smallest = min(float(node[1]) for node in nodes)
        span = max(float(node[1]) for node in nodes) - smallest
        edge = smallest + 1e-9 * max(span, 1.0)
        for node in nodes:
            if float(node[1]) <= edge:
                for dof in clamped:
                    lines.append(f"{node[0]}, {dof}, {dof}, 0.0")
    anchor, along_x, along_y = _restraint_nodes(nodes)
    free = [dof for dof in range(1, limit + 1) if dof not in constrained]
    for dof in free:
        lines.append(f"{anchor[0]}, {dof}, {dof}, 0.0")
    # The anchor kills translation. The second node kills the rotations that
    # would still turn the element about it, and the third the last one.
    for dof in free[1:]:
        if along_x[0] != anchor[0]:
            lines.append(f"{along_x[0]}, {dof}, {dof}, 0.0")
    for dof in free[2:]:
        if along_y[0] not in (anchor[0], along_x[0]):
            lines.append(f"{along_y[0]}, {dof}, {dof}, 0.0")
    seen: set = set()
    unique = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique


def generate_deck(manifest: VerificationManifest) -> str:
    """The complete .inp for this manifest."""
    # Refuses here, before a single line is written, rather than emitting a
    # deck that describes a different element than the one asked for.
    geometry = geometry_for(manifest.element_type)
    plane = geometry.dimension == 2
    nodes = nodes_for_manifest(manifest)
    if manifest.ntens and manifest.ntens != geometry.ntens:
        raise UnsupportedElement(
            f"{geometry.name} calls a UMAT with NTENS={geometry.ntens} "
            f"({geometry.ndi} direct + {geometry.nshr} shear), but this "
            f"manifest declares NTENS={manifest.ntens}. Running the material "
            f"on an element that hands it a different tensor size would "
            f"compare two different quantities.")

    lines: list[str] = [
        "*HEADING",
        f"single-element verification deck for {manifest.name}",
        "** Generated by umat_oti.abaqus.deck from a verification manifest.",
        f"** kinematics: {manifest.kinematics}; ntens: {manifest.ntens}",
        f"** material provenance: {manifest.material_provenance or 'UNSTATED'}",
        "** geometry: " + (manifest.node_provenance
                           or "the reference element of this harness, "
                              "a unit cell at the origin"),
        "*NODE",
    ]
    for index, x, y, z in nodes:
        lines.append(f"{index}, {_fmt(x)}, {_fmt(y)}"
                     + ("" if plane else f", {_fmt(z)}"))
    lines.append(f"*ELEMENT, TYPE={manifest.element_type}, ELSET=ONE")
    lines.append("1, " + ", ".join(str(index) for index, *_ in nodes))
    if manifest.isothermal_temperature is not None:
        lines.append("*NSET, NSET=ALL")
        lines.append(", ".join(str(index) for index, *_ in nodes))

    if geometry.section == "COHESIVE":
        # RESPONSE=TRACTION SEPARATION is what makes Abaqus call the UMAT with
        # a separation and expect a traction back, and the thickness on the
        # data line is what makes the nominal strain it passes numerically
        # equal to the separation. The author's own patch test writes both.
        section = ("*COHESIVE SECTION, ELSET=ONE, RESPONSE=TRACTION SEPARATION"
                   ", MATERIAL=" + manifest.name.upper()[:60])
    else:
        section = ("*SOLID SECTION, ELSET=ONE, MATERIAL="
                   + manifest.name.upper()[:60])
    if manifest.orientation_axes is not None:
        section += ", ORIENTATION=LOCAL"
    elif manifest.orientation is not None:
        section += ", ORIENTATION=CRYSTAL"
    lines += _orientation(manifest)
    lines.append(section)
    if geometry.needs_thickness:
        lines.append("1.0")
    lines += _material_block(manifest)
    lines += _initial_state(manifest)
    if manifest.isothermal_temperature is not None:
        # The author's own number, applied as an initial condition and then
        # held by a boundary condition on degree of freedom 11 in every step.
        # A single element cannot solve for the temperature its author's model
        # solves for -- there is nothing to conduct to -- so the experiment is
        # isothermal and says so.
        lines += ["** temperature: "
                  + (manifest.temperature_provenance or "UNSTATED"),
                  "*INITIAL CONDITIONS, TYPE=TEMPERATURE",
                  "ALL, " + _fmt(float(manifest.isothermal_temperature))]

    nlgeom = "YES" if manifest.kinematics == "finite" else "NO"
    coupled = geometry.kind.endswith("thermal")
    # TRANSIENT, which is the default form. A healing law integrates its own
    # damage in DTIME -- ``dd = (1/Eta1)*(...)`` and ``(Da-Da0)/DTIME`` -- so
    # a steady-state step would ask it for the answer it reaches after its
    # own kinetics have finished, which is not what its author ran.
    procedure = ("*COUPLED TEMPERATURE-DISPLACEMENT"
                 if coupled else "*STATIC")
    for segment in manifest.loading:
        increment = 1.0 / max(segment.increments, 1)
        lines += [
            f"** {segment.name}: {segment.description}",
            f"*STEP, NLGEOM={nlgeom}, INC={max(segment.increments * 10, 100)}",
            procedure,
            f"{_fmt(increment * segment.period)}, {_fmt(segment.period)}, "
            f"{_fmt(increment * segment.period * 1e-5)}, "
            f"{_fmt(increment * segment.period)}",
            "*BOUNDARY, OP=NEW",
        ]
        lines += _boundary_for(segment, nodes, plane, geometry=geometry,
                               plane_strain=manifest.plane_strain_directions)
        if manifest.isothermal_temperature is not None:
            held = _fmt(float(manifest.isothermal_temperature))
            for index, *_rest in nodes:
                lines.append(f"{index}, 11, 11, {held}")
        if segment.body_force:
            # The reference magnitudes are the author's; the source's own
            # SUBROUTINE DLOAD scales them. Nothing here chooses a force.
            lines.append("*DLOAD, OP=NEW")
            for label, magnitude in segment.body_force:
                lines.append(f"ONE, {label}, {_fmt(magnitude)}")
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
