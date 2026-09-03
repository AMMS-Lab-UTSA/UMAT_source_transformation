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
    kinematics: str = "small strain"          # or "finite"
    ntens: int = 6
    ndi: int = 3
    nshr: int = 3
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
    fd_steps: tuple[float, ...] = (1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8)
    #: A component smaller than this fraction of the largest entry of the
    #: tangent is reported against the largest entry instead of against itself.
    near_zero_fraction: float = 1e-8
    primal_tolerance: float = 1e-10
    notes: str = ""
    status: str = "ready"

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
