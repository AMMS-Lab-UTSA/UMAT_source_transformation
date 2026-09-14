"""What a UMAT needs in order to be run and checked, stated once.

A verification manifest is the whole of what the deck generator and the job
runner know about a source. Keeping it in one declared object rather than
spread through the generator is what stops model-specific assumptions leaking
into code that is supposed to serve every model.

Every field that carries a number a result depends on carries its provenance
beside it. ``material_provenance`` is not decoration: the rule this project
works under is that material constants are read from something the author
published and never invented, and a manifest that cannot say where its
constants came from is a manifest whose results mean nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


#: A UMAT that cannot be run because nobody has established what it is made of.
NEEDS_MATERIAL_DATA = "needs_material_data"


@dataclass(frozen=True)
class LoadingSegment:
    """One leg of a loading history, as displacement on the driven face.

    Displacement-controlled, because a single element under prescribed
    displacement has a strain history that is known before the job runs -- and
    a verification that has to solve for its own strain increment cannot say
    which increment it perturbed.
    """

    name: str
    #: Engineering strain applied over this segment, per component
    #: (11, 22, 33, 12, 13, 23). Only the components the deck drives.
    strain: tuple[float, ...]
    increments: int = 10
    #: Step time. Rate-dependent models read DTIME from it.
    period: float = 1.0
    description: str = ""
    #: Body-force components this segment applies, as the author's own deck
    #: names them: ``(("BYNU", 1.0),)``. A segment carrying these is driven by
    #: a force per unit volume that the source's own SUBROUTINE DLOAD
    #: computes, not by prescribed displacement, so the deck holds only the
    #: rigid-body modes and lets the element deform. See
    #: :mod:`umat_oti.abaqus.body_force`.
    body_force: tuple[tuple[str, float], ...] = ()
    #: Which degrees of freedom the held face keeps, read from the author's
    #: deck. Only meaningful beside ``body_force``.
    held: tuple[int, ...] = ()
    #: Separation of the two faces of a COHESIVE element, in the order the
    #: element hands them to the UMAT: normal first, then the one or two shear
    #: directions. A cohesive law is given a displacement jump, not a strain
    #: tensor, and driving it with ``strain`` would drive a different
    #: quantity. Empty for every non-cohesive segment.
    separation: tuple[float, ...] = ()
    #: Degrees of freedom held on EVERY node of the face at minimum x, as the
    #: author's own support holds one end of their plate. Only meaningful
    #: beside a time-driven or body-force segment, where the element is
    #: otherwise free: it turns a freely growing element -- which is close to
    #: traction-free by construction, and so close to saying nothing -- into a
    #: partly restrained one that carries a real stress. The other face stays
    #: free, so the volume can still change and a nearly incompressible
    #: material is not asked to change volume against its own bulk modulus.
    clamped_face: tuple[int, ...] = ()
    #: Nothing is prescribed and nothing is loaded; only the clock advances
    #: over ``period``. This is the whole experiment for a law whose driver is
    #: TIME -- a growth stretch, a swelling, an ageing -- and the segment that
    #: makes such a law's development visible without changing the
    #: constitutive problem by shortening its clock.
    time_only: bool = False
    #: A rigid rotation superposed on this segment, row-major 3x3, or empty
    #: for none. The nodes are driven to ``Q(I+E)X`` instead of ``(I+E)X``, so
    #: Abaqus hands the routine ``F = Q(I+E)`` and a DROT carrying Q. The
    #: strain the material sees is unchanged; only the frame it is presented in
    #: moves. That is what objectivity means, and losing DROT is what it
    #: catches -- a conversion can agree perfectly in an unrotated frame and
    #: drop the rotation term with nothing to show for it.
    #:
    #: LAST in the field order deliberately. Every other field here has been
    #: passed positionally somewhere, and inserting this one after ``strain``
    #: silently bound ``increments`` to it.
    rotation: tuple[float, ...] = ()
    #: Whether this segment is the one in which the rotation itself is applied,
    #: turning the element from the identity to ``rotation`` at zero strain.
    #: Only that segment needs amplitude tables. Once the rotation is FIXED, a
    #: plain prescribed displacement is exact: Abaqus interpolates linearly
    #: between the two end positions, and a fixed Q commutes with a linear
    #: interpolation -- Q.lerp(a, b) = lerp(Qa, Qb) -- so every intermediate
    #: state is precisely the rotated intermediate state of the unrotated run.
    rotation_lead_in: bool = False

    @property
    def driven_by(self) -> str:
        """What makes something happen in this segment, in one word."""
        if self.body_force:
            return "body force"
        if self.separation:
            return "separation"
        if self.time_only:
            return "time"
        return "strain"


@dataclass(frozen=True)
class VerificationManifest:
    """Everything needed to build a deck for one UMAT and check its result."""

    name: str
    #: The entry source. Its bundle is every file that has to compile with it.
    source: Path
    bundle: tuple[Path, ...] = ()
    source_form: str = "fixed"
    compiler_flags: tuple[str, ...] = ()

    # ---- the material point ------------------------------------------------
    element_type: str = "C3D8"
    #: The label the single element carries in the generated deck.
    #:
    #: Normally 1, and normally nothing depends on it. But a UMAT is handed
    #: ``NOEL`` and some of the corpus indexes with it. ``irfancn/
    #: Abaqus-UEL-elastic`` computes ``kelem = noel - nelem`` with ``nelem=185``
    #: because the author's own elements start at 186; with ``NOEL=1`` that is
    #: ``-184``, the routine reads far outside a COMMON block, and Abaqus dies
    #: with a signal 11 inside the element loop -- a segmentation fault that
    #: reads as the author's code being broken and is entirely our numbering.
    #:
    #: So where the author's deck is known, the element takes a label the
    #: author's own model uses. Nothing downstream assumes 1: the probe records
    #: carry the label Abaqus reports and :mod:`umat_oti.abaqus.frames` groups
    #: on whatever that is.
    element_label: int = 1
    #: Where the element sits, as ``(id, x, y, z)`` per node. Empty means the
    #: registry's reference geometry, which is a unit cube at the origin.
    #:
    #: Not decoration. A UMAT that reads COORDS computes a different material
    #: at a different place, and ``Jeff97__.../PureGrowth.for`` builds a growth
    #: tensor whose determinant passes through zero at ``y = 0.79`` -- a point
    #: the unit cube has and the author's millimetre-thick plate does not. See
    #: :mod:`umat_oti.abaqus.coordinate_domain`.
    node_coordinates: tuple[tuple[int, float, float, float], ...] = ()
    node_provenance: str = ""
    #: The temperature to hold every node at, and where that number came
    #: from. Only meaningful on a coupled temperature-displacement element.
    #:
    #: Held, not solved. A single element has no neighbour to conduct to, no
    #: gap to radiate across and no surface to film from, so the temperature
    #: the author's own model SOLVES for cannot be reproduced at one element.
    #: What can be reproduced is a temperature the author STATED:
    #: ``*Initial Conditions, type=TEMPERATURE / Set-3, 673.``. The experiment
    #: is then isothermal at the author's own 673 K, which exercises the
    #: law at that temperature and does not exercise its temperature
    #: dependence -- and the second half of that sentence belongs in every
    #: report of it.
    isothermal_temperature: Optional[float] = None
    temperature_provenance: str = ""
    #: Degrees of freedom the author's deck constrains on EVERY node, which is
    #: a statement about the material's kinematics rather than a support.
    #: ``Plate-1.WholeRegion, 3, 3`` beside a plane-strain growth problem is
    #: the plane-strain condition; dropping it would let the plate thicken out
    #: of plane and change what the routine is asked.
    plane_strain_directions: tuple[int, ...] = ()
    kinematics: str = "small strain"          # or "finite"
    #: Zero means "take it from the element", which is where it comes from:
    #: the element decides how many components Abaqus hands the UMAT, and a
    #: manifest that says otherwise describes a run that cannot happen. These
    #: used to default to a 3D continuum shape whatever the element was, so a
    #: CPE4 manifest carried NTENS=6 while CPE4 calls a UMAT with four.
    ntens: int = 0
    ndi: int = 0
    nshr: int = 0
    nprops: int = 0
    nstatv: int = 1
    props: tuple[float, ...] = ()
    material_provenance: str = ""
    initial_statev: tuple[float, ...] = ()
    initial_statev_provenance: str = ""
    #: The author's deck says ``*INITIAL CONDITIONS, TYPE=SOLUTION, USER``,
    #: which asks Abaqus to call the source's own SDVINI rather than listing
    #: values. Carried rather than translated into numbers: the values are the
    #: subroutine's to decide, and reading them out of Fortran to retype into a
    #: deck would be inventing what the author chose to compute.
    initial_state_from_user_subroutine: bool = False
    #: Three Euler angles plus the local-axis convention, when the model needs
    #: an orientation. Crystal plasticity usually does.
    orientation: Optional[tuple[float, float, float]] = None
    orientation_provenance: str = ""
    #: An orientation written the way a deck writes one: six numbers giving a
    #: point on the local 1-axis and a point in the local 1-2 plane, plus an
    #: ``(axis, angle)`` rotation about one of them.
    #:
    #: Carried beside the Euler form rather than converted into it because
    #: this is what an author publishes. ``CAEAssistant-Group``'s deck says
    #: ``*Orientation, name=Ori-1 / 1.,0.,0., 0.,1.,0. / 3, 0.`` and then
    #: rotates the ply 30 degrees about the shell normal on its
    #: ``*Shell Section`` data line. Both halves are the author's, and a
    #: verification that dropped either would run the composite in a frame its
    #: author did not.
    orientation_axes: Optional[tuple[float, ...]] = None
    orientation_rotation: Optional[tuple[int, float]] = None
    unsymmetric: bool = False

    # ---- what to run -------------------------------------------------------
    loading: tuple[LoadingSegment, ...] = ()
    outputs: tuple[str, ...] = ("S", "SDV")

    # ---- what to check -----------------------------------------------------
    #: Which columns of DDSDDE the finite difference reconstructs. Empty means
    #: every one of them.
    perturbation_components: tuple[int, ...] = ()
    #: Relative step sizes for the sweep, largest first. A single step cannot
    #: distinguish a truncation error from a cancellation one.
    #:
    #: The sweep has to BRACKET its minimum. A minimum at the edge is not a
    #: minimum: it says the U-curve turns somewhere the sweep never looked,
    #: and one agreeing step cannot be told from a lucky crossing.
    #:
    #: Measured on Growth-MinSur2.for at 1e-3 to 1e-8: the relative error rose
    #: monotonically as the step fell -- 8.6e-08, 2.2e-06, 8.3e-06, 3.8e-05,
    #: 7.6e-04, 1.0e-02 -- which is 1/h over six decades with no h^2 branch
    #: anywhere in it. Adding 1e-2 bracketed thirteen such entries and left
    #: three, and those three say the same thing one decade up. Measured on
    #: From-2D-to-3D-Genhel.for, increment 4: 1.10e-09 at 1e-2 against
    #: 8.26e-06, 8.26e-05, 4.11e-04, 4.11e-03, 4.12e-02, 4.12e-01 below it --
    #: an exact 1/h line, and a point at 1e-2 that sits seven hundred times
    #: BELOW where that line would put it. Cancellation has stopped
    #: dominating there and truncation has not yet taken over, which is where
    #: the minimum is; a step above it is what shows the minimum was passed.
    #:
    #: Widening cannot weaken a verdict. The plateau still needs two steps
    #: within tolerance spanning a decade, and a perturbation that crosses a
    #: constitutive branch is caught by the one-sided gap whatever its size.
    fd_steps: tuple[float, ...] = (1e-1, 1e-2, 1e-3, 1e-4, 1e-5, 1e-6, 1e-7,
                                   1e-8)
    #: A component smaller than this fraction of the largest entry of the
    #: tangent is reported against the largest entry instead of against itself.
    near_zero_fraction: float = 1e-8
    primal_tolerance: float = 1e-10
    notes: str = ""
    status: str = "ready"

    def __post_init__(self) -> None:
        """Fill the tensor shape from the element, or refuse to contradict it.

        The element is the authority: Abaqus decides NDI and NSHR from it and
        the UMAT is called accordingly. A manifest carrying a different shape
        does not describe a different run -- it describes no run at all, and
        every number attributed to it would be attributed to the wrong test.

        An unknown element is left alone here rather than refused, so that a
        manifest can still be built and inspected; the refusal comes from
        :func:`umat_oti.abaqus.deck.generate_deck`, which is where a deck
        would otherwise be written.
        """
        try:
            from umat_oti.abaqus.elements import geometry_for
            geometry = geometry_for(self.element_type)
        except Exception:
            if not self.ntens:
                object.__setattr__(self, "ndi", self.ndi or 3)
                object.__setattr__(self, "nshr", self.nshr or 3)
                object.__setattr__(self, "ntens", self.ndi + self.nshr)
            return
        for field, value in (("ndi", geometry.ndi), ("nshr", geometry.nshr),
                             ("ntens", geometry.ntens)):
            declared = getattr(self, field)
            if declared and declared != value:
                raise ValueError(
                    f"{self.element_type} calls a UMAT with {field.upper()}="
                    f"{value}, but this manifest declares {declared}. The "
                    f"element decides the tensor shape; a manifest cannot "
                    f"overrule it.")
            object.__setattr__(self, field, value)

    def as_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["source"] = str(self.source)
        record["bundle"] = [str(path) for path in self.bundle]
        record["loading"] = [asdict(segment) for segment in self.loading]
        return record

    def missing_requirements(self) -> tuple[str, ...]:
        """What stops this manifest from being run, in its own words."""
        missing: list[str] = []
        if not self.props:
            missing.append("no material constants")
        elif not self.material_provenance:
            missing.append("material constants with no stated provenance")
        if self.orientation is not None and not self.orientation_provenance:
            missing.append("an orientation with no stated provenance")
        if self.initial_statev and not self.initial_statev_provenance:
            missing.append("initial state variables with no stated provenance")
        if not self.loading:
            missing.append("no loading history")
        return tuple(missing)


#: Displacement-controlled paths a single element can be driven along. Named
#: rather than numbered: a reader has to be able to tell from a result which
#: physical test produced it.
def uniaxial(strain: float = 0.01, increments: int = 10) -> LoadingSegment:
    return LoadingSegment(
        "uniaxial", (strain, 0.0, 0.0, 0.0, 0.0, 0.0), increments,
        description="prescribed extension along x, lateral faces free to move "
                    "only in their own plane")


def simple_shear(strain: float = 0.01, increments: int = 10) -> LoadingSegment:
    return LoadingSegment(
        "simple_shear", (0.0, 0.0, 0.0, strain, 0.0, 0.0), increments,
        description="prescribed engineering shear in the x-y plane")


def under_body_force(components: tuple, held: tuple = (1, 2),
                     increments: int = 10, period: float = 1.0,
                     provenance: str = "") -> LoadingSegment:
    """The author's own body force, over the author's own step time.

    No strain is prescribed: the element is held only where the author's deck
    holds it, and deforms under the force its own DLOAD routine computes.
    Nothing about the magnitude is chosen here -- the reference values come
    from the deck and the routine scales them.
    """
    return LoadingSegment(
        "body_force", (0.0,) * 6, increments, period,
        description=("the author's own body force, applied through the "
                     "source's SUBROUTINE DLOAD; the element is held only "
                     "where rigid-body motion requires"
                     + (f" ({provenance})" if provenance else "")),
        body_force=tuple(components), held=tuple(held))


def hold(segment: LoadingSegment, period: float = 10.0,
         increments: int = 10) -> LoadingSegment:
    """Stay where the previous segment finished, and let time pass.

    The boundary values are the same, so the strain does not change; only the
    step time does. A rate-independent material returns the same stress at the
    end of it as at the start. Anything with a viscosity, a creep law, a
    relaxation time or an ageing clock does not, and the difference IS the
    behaviour -- it is invisible to every amplitude, because raising the strain
    does not make time pass.
    """
    return LoadingSegment(
        f"{segment.name}_hold", segment.strain, increments, period,
        description=(f"the strain of {segment.name} held for {period:g} of "
                     f"step time, so that stress change means time dependence"))


def at_rate(segment: LoadingSegment, factor: float) -> LoadingSegment:
    """The same strain path, walked in ``factor`` times the step time.

    Same targets, same number of increments, different DTIME. Two runs of this
    differ only in how fast the strain was applied, so a difference between
    their stresses at the same strain is rate dependence and nothing else.
    """
    return LoadingSegment(
        f"{segment.name}_x{factor:g}", segment.strain, segment.increments,
        segment.period * float(factor),
        description=(f"{segment.name} applied over {factor:g} times the step "
                     f"time, to separate rate dependence from amplitude"))


def reverse(segment: LoadingSegment, fraction: float = -0.5) -> LoadingSegment:
    """The same path run backwards, to make state evolution observable.

    A monotonic path cannot distinguish a model that stores state from one that
    recomputes it, because both give the same answer going out.
    """
    return LoadingSegment(
        f"{segment.name}_reversed",
        tuple(value * fraction for value in segment.strain),
        segment.increments, segment.period,
        description=f"reversal of {segment.name} to exercise state evolution")

# ---------------------------------------------------------------------------
# the family of tests a material is put through
# ---------------------------------------------------------------------------
#: One deck is one question. A material that yields in tension may be linear
#: in shear, one that is pressure-dependent shows nothing under deviatoric
#: loading, and one with kinematic hardening looks identical to isotropic
#: hardening until the load reverses. So the generator builds a family, and
#: each member exists to activate something a different constitutive law does.


def compression(strain: float = 0.01, increments: int = 10) -> LoadingSegment:
    """Extension's mirror. A model with different tensile and compressive
    responses -- concrete, soil, most damage laws -- shows it only here."""
    return LoadingSegment(
        "compression", (-abs(strain), 0.0, 0.0, 0.0, 0.0, 0.0), increments,
        description="prescribed shortening along x, lateral faces free to "
                    "move only in their own plane")


def hydrostatic(strain: float = 0.01, increments: int = 10) -> LoadingSegment:
    """Equal direct strain in three directions and no shear.

    Deviatoric loading leaves a pressure-dependent model looking linear: a
    Drucker-Prager or Mohr-Coulomb surface is reached by pressure, and a path
    that never changes the pressure never reaches it.
    """
    return LoadingSegment(
        "hydrostatic", (strain, strain, strain, 0.0, 0.0, 0.0), increments,
        description="equal direct strain in all three directions, no shear")


def strain_basis(component: int, strain: float = 0.01,
                 increments: int = 6) -> LoadingSegment:
    """One component of the strain increment alone.

    Six of these exercise the whole tangent: a column of DDSDDE that no
    loading ever drives is a column no comparison can say anything about.
    """
    values = [0.0] * 6
    values[component] = strain
    names = ("e11", "e22", "e33", "g12", "g13", "g23")
    return LoadingSegment(
        f"basis_{names[component]}", tuple(values), increments,
        description=f"prescribed {names[component]} alone, to drive column "
                    f"{component + 1} of the tangent")


def load_unload(strain: float = 0.01, increments: int = 10) -> tuple:
    """Out and all the way back.

    An elastic material returns to where it started. Anything that does not
    has kept something, and the residual is the evidence -- which is why this
    returns BOTH segments: the reversal is only meaningful beside the loading
    that preceded it.
    """
    out = uniaxial(strain, increments)
    return (out, LoadingSegment(
        "unload", tuple(-value for value in out.strain), increments,
        out.period,
        description="the whole of the loading removed, so that anything left "
                    "over is permanent"))


def cyclic(strain: float = 0.01, increments: int = 8, cycles: int = 2) -> tuple:
    """Out, back past zero, and out again.

    Kinematic hardening is invisible to a monotonic path and invisible to a
    single unloading; it shows as the second excursion meeting a different
    stress than the first.
    """
    segments = []
    for cycle in range(max(1, cycles)):
        segments.append(LoadingSegment(
            f"cycle{cycle + 1}_forward", (strain, 0.0, 0.0, 0.0, 0.0, 0.0),
            increments, description="forward excursion"))
        segments.append(LoadingSegment(
            f"cycle{cycle + 1}_reverse", (-2.0 * strain, 0.0, 0.0, 0.0, 0.0, 0.0),
            increments, description="reversal through zero to the other side"))
    return tuple(segments)


#: What each named test is FOR. Carried into the manifest so a result says
#: which physical question it answers, and so a test that activates nothing
#: can be reported as "this material does not do that" rather than dropped.
TEST_PURPOSE: dict[str, str] = {
    "elastic_basis": "drive each strain component alone, to exercise every "
                     "column of the tangent",
    "monotonic": "extension and compression, to find yielding, damage or any "
                 "other threshold and any tension-compression asymmetry",
    "shear": "deviatoric loading, which activates behaviour a direct path "
             "leaves untouched",
    "hydrostatic": "pressure change, which is the only way to reach a "
                   "pressure-dependent surface",
    "load_unload": "out and back, so that permanent strain and irreversible "
                   "state changes become visible",
    "cyclic": "reversal through zero, which is what separates kinematic "
              "hardening from isotropic",
}


def family(name: str, strain: float = 0.01,
           increments: int = 10) -> tuple[LoadingSegment, ...]:
    """The segments one named test is made of."""
    if name == "elastic_basis":
        return tuple(strain_basis(component, strain) for component in range(6))
    if name == "monotonic":
        return (uniaxial(strain, increments), compression(strain, increments))
    if name == "shear":
        return (simple_shear(strain, increments),)
    if name == "hydrostatic":
        return (hydrostatic(strain, increments),)
    if name == "load_unload":
        return load_unload(strain, increments)
    if name == "cyclic":
        return cyclic(strain, increments)
    raise ValueError(
        f"{name!r} is not a test this generator knows. Known tests: "
        f"{', '.join(sorted(TEST_PURPOSE))}")


# ---------------------------------------------------------------------------
# loadings for laws whose driver is not a prescribed strain
# ---------------------------------------------------------------------------
def let_time_pass(period: float, increments: int = 10,
                  name: str = "grow", why: str = "") -> LoadingSegment:
    """Nothing prescribed, nothing loaded, the clock running for ``period``.

    THE experiment for a time-driven law, and the one this harness did not
    have. A growth tensor, a swelling, an ageing or a healing develops because
    TIME advances; the element is left free at every node but the ones rigid
    motion requires, so the growth produces the deformation instead of fighting
    a boundary condition that was never the author's.

    ``period`` is not a numerical knob here. ``PureGrowth.for`` normalises its
    own clock by ``TotalT = 1.0`` and ``l1-is-1--l2-is-101.for`` by
    ``TotalT = 10.0``; running for less is running a smaller growth, which is
    a different constitutive problem rather than a gentler version of the same
    one. See :mod:`umat_oti.abaqus.time_scale`.
    """
    return LoadingSegment(
        name, (0.0,) * 6, increments, float(period), time_only=True,
        description=("no strain is prescribed and no load is applied; the "
                     "step runs for " + f"{float(period):g}" + " of analysis "
                     "time so that whatever this law does with the clock is "
                     "what the element does" + (f" ({why})" if why else "")))


def separate(normal: float = 0.0, shear: float = 0.0, second_shear: float = 0.0,
             increments: int = 10, period: float = 1.0, name: str = "open",
             why: str = "") -> LoadingSegment:
    """Pull the two faces of a cohesive element apart by a known jump.

    The components are in the order a cohesive element hands them to the UMAT:
    the through-thickness separation first, then the one or two shear
    directions. ``harshaa765__Bilinear-CZM-UMAT`` reads them as
    ``DELTA_N = STRAN(1) + DSTRAN(1)``, ``DELTA_S``, ``DELTA_T`` and says so in
    its own comments.
    """
    return LoadingSegment(
        name, (0.0,) * 6, increments, float(period),
        separation=(float(normal), float(shear), float(second_shear)),
        description=("the top face of the cohesive element is displaced "
                     f"relative to the bottom by normal {normal:g}, shear "
                     f"{shear:g}" + (f", second shear {second_shear:g}"
                                     if second_shear else "")
                     + (f" ({why})" if why else "")))


def under_body_force_over(components: tuple, held: tuple, period: float,
                          increments: int = 10, name: str = "body_force",
                          provenance: str = "") -> LoadingSegment:
    """The author's own body force over the author's own step period.

    The period matters as much as the components. ``BodyForce-Growth-2Stages``
    reads ``F = TargetF*(TIME(1))/TotalT`` in its DLOAD and switches its growth
    stage on ``TIME(2)``, so a step of a different length applies a different
    fraction of the author's load AND lands in a different stage of the growth.
    """
    return LoadingSegment(
        name, (0.0,) * 6, increments, float(period),
        description=("the author's own body force, applied through the "
                     "source's SUBROUTINE DLOAD over a step of "
                     f"{float(period):g}; the element is held only where "
                     "rigid-body motion requires"
                     + (f" ({provenance})" if provenance else "")),
        body_force=tuple(components), held=tuple(held))


def cohesive_open_and_release(onset: float, final: float,
                             increments: int = 10) -> tuple[LoadingSegment, ...]:
    """Open past the damage onset, then release, which is the author's own test.

    ``Job_1_Harsh_UMAT.inp`` is two steps: ``control, 3, 3, 0.2`` over half a
    unit of time, then the same boundary condition removed. The opening carries
    the traction up the elastic branch, past the onset separation
    ``TAU_N/A_KN`` and down the softening one; the release is what shows the
    damage did not come back. A monotonic opening alone cannot tell a damage
    law from a nonlinear elastic one.
    """
    return (
        separate(normal=float(final), increments=increments, name="open",
                 why=f"onset separation is {onset:g}, so this reaches "
                     f"{final / onset:.1f} times it"),
        separate(normal=0.0, increments=increments, name="release",
                 why="the whole opening removed, so that a traction that does "
                     "not return to its elastic value is damage and not "
                     "nonlinearity"),
        separate(normal=float(final), increments=increments, name="reopen",
                 why="reopened to the same separation; a bilinear damage law "
                     "returns a smaller traction than the first time and an "
                     "elastic law returns the same one"),
    )


def off_axis(strain: float = 0.01, increments: int = 10) -> LoadingSegment:
    """A direct strain along the deck's global axis, for an oriented material.

    Meaningless without an orientation and decisive with one: in a frame
    rotated off the loading axis, a pure direct strain produces a SHEAR stress,
    and a build that lost the rotation produces none. That coupling is the
    observable that says the local frame reached the routine.
    """
    return LoadingSegment(
        "off_axis", (float(strain), 0.0, 0.0, 0.0, 0.0, 0.0), increments,
        description=("prescribed extension along the deck's global x, which "
                     "is off the material's own axes; the shear stress it "
                     "produces is the evidence that the orientation reached "
                     "the routine"))


#: The rotation superposed to test objectivity, row-major 3x3.
#:
#: Thirty degrees about the axis (1,1,1)/sqrt(3) in three dimensions. Chosen
#: to be far from any symmetry of the element and of the loading: a rotation
#: about a coordinate axis, or by ninety degrees, permutes components rather
#: than mixing them, and a conversion that dropped DROT could reproduce the
#: answer by accident. Every component of Q is nonzero here.
OBJECTIVITY_ROTATION: tuple[float, ...] = (
    0.9106836025229592, -0.24401693585629242, 0.3333333333333333,
    0.3333333333333333, 0.9106836025229592, -0.24401693585629242,
    -0.24401693585629242, 0.3333333333333333, 0.9106836025229592,
)

#: The same angle about z, for a two-dimensional element. An out-of-plane
#: rotation would take the element out of its own plane, which is a different
#: analysis rather than the same one seen from a different frame.
OBJECTIVITY_ROTATION_PLANE: tuple[float, ...] = (
    0.8660254037844387, -0.49999999999999994, 0.0,
    0.49999999999999994, 0.8660254037844387, 0.0,
    0.0, 0.0, 1.0,
)


def rotated(loading, plane: bool = False):
    """The same loading with a rigid rotation superposed on every segment.

    The material is driven along exactly the same strain path; only the frame
    it is presented in moves. A routine that handles DROT correctly returns
    the same response rotated, and a conversion that dropped DROT does not.
    """
    from dataclasses import replace as _replace

    turn = OBJECTIVITY_ROTATION_PLANE if plane else OBJECTIVITY_ROTATION
    if not loading:
        return ()
    # A lead-in that turns the undeformed element from the identity to Q at
    # zero strain, then the author's own path with Q held fixed.
    #
    # Without the lead-in the rotation has to ramp inside the first segment,
    # and a ramping rotation cannot be written as a prescribed displacement:
    # Abaqus interpolates it linearly, half of a rotation's displacement is
    # the chord rather than half the rotation, and the element is squashed.
    # Driving it by amplitude tables instead fixed that but broke something
    # else -- with OP=NEW each segment's table restarts from the undeformed
    # state, so a reversal segment walked 0 to -E where the unrotated run
    # walks +E to -E. Measured: at step 2 increment 1 the unrotated run
    # carried a stress trace of 0.0211 and the "rotated" one carried
    # -5.85e-07, because its element had been unloaded.
    lead_in = LoadingSegment(
        name="rigid_rotation_lead_in",
        strain=tuple(0.0 for _ in (loading[0].strain or (0.0,))),
        increments=max(int(loading[0].increments), 8),
        period=loading[0].period,
        description=("the element is turned rigidly from the identity to the "
                     "superposed rotation at zero strain, which an objective "
                     "material answers with no change at all"),
        rotation=turn, rotation_lead_in=True)
    return (lead_in,) + tuple(
        _replace(segment, rotation=turn) for segment in loading)
