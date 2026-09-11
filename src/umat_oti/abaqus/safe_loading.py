"""A finite prefix is discovery evidence. It is not a verification run.

A run that produces five or more good increments and then returns values that
are not numbers has told the search something worth knowing: the experiment
reaches past the edge of this material's numerical domain, and roughly where
that edge is. That is exactly what a search is for.

It is not a result. A UMAT marked ``fully_verified`` on a history that later
becomes non-finite has been verified on a truncated failed analysis -- the
comparison silently drops everything after the break, the frozen regression
fixture inherits a deck that does not run to completion, and every future
replay of it starts by reproducing a failure. Measured on
BodyForce-Growth-2Stages.for: 280 records, non-finite from record 23, primal
agreement over the first 22, and a verdict of ``verified``.

So the prefix is used for what it is. The last demonstrably safe state is
read out of it, the loading is rebuilt to stop short of the edge with a
margin taken from the bracket the run itself measured, and the whole
experiment is run again from the beginning. What may be verified is only the
run that completes with every requested output finite over its entire
history.

Three things, kept apart on purpose, because collapsing them is how the
truncated history became a verdict:

``discovery_usable_prefix``
    how far a run got before it left the domain, and what that says about
    where the edge is;

``safe_loading_reconstructed``
    the loading rebuilt to stop short of that edge;

``complete_finite_verification_run``
    a run of the rebuilt loading that finished, with no non-finite value
    anywhere in it. Only this one can carry a verdict.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from umat_oti.abaqus import frames

#: Outputs whose finiteness a verification depends on. Defined by
#: :mod:`umat_oti.abaqus.frames`, which does the grouping this module reads.
CHECKED = frames.CHECKED

#: The FIRST PROPOSAL for where to put a rebuilt path's endpoint, as a
#: fraction of the last increment proved safe. Not a proof of safety and not
#: a verification constant: what makes an endpoint safe is a complete finite
#: run at it, and :func:`settle_on_safe_loading` reruns the whole experiment
#: and records the distance between the endpoint it settled on and the
#: failure that was actually observed.
#:
#: The run brackets the edge between the last complete increment and the
#: first that was not -- one increment of the segment, a tenth of it at the
#: usual resolution. A proposal at exactly the last safe increment sits on
#: the near edge of that bracket, where the next run's slightly different
#: arithmetic can cross it; four fifths proposes a point below it. Whether
#: that point IS safe is then measured, not assumed, and refused if the
#: rerun is not finite throughout.
MARGIN = 0.8

#: How many times to rebuild before giving up. A model whose safe region
#: keeps shrinking as it is approached is telling us something the loading
#: cannot fix, and three rebuilds is enough to see that happening.
REBUILDS = 3


@dataclass
class Prefix:
    """How far a run got, in INCREMENTS, before it left its domain.

    Increments, not records: a single-element C3D8 job writes eight records
    per increment, so "twenty-two usable records" is two complete increments
    and six integration points of a third. See
    :mod:`umat_oti.abaqus.frames`.
    """

    history: Any = None

    @property
    def complete(self) -> bool:
        """Every increment complete? Only this can be verified on."""
        return bool(self.history and self.history.complete)

    @property
    def usable(self) -> int:
        """Complete increments from the start -- the number that matters."""
        return int(self.history.complete_increments) if self.history else 0

    @property
    def records(self) -> int:
        return int(self.history.raw_output_records) if self.history else 0

    @property
    def last_safe(self) -> tuple[int, int]:
        return self.history.last_complete if self.history else (0, 0)

    @property
    def first_bad(self) -> tuple[int, int]:
        where = self.history.first_incomplete_increment if self.history else None
        return (int(where["step"]), int(where["increment"])) if where else (0, 0)

    def as_dict(self) -> dict:
        base = self.history.as_dict() if self.history else {}
        base["last_complete_step_increment"] = list(self.last_safe)
        return base

    def reason(self) -> str:
        if not self.history:
            return "the run recorded no history at all"
        if self.complete:
            return (f"{self.history.reason()}, so this run is a verification "
                    f"and not only a probe")
        return (f"{self.history.reason()}. That is where the experiment has "
                f"to stop, not where the comparison has to start ignoring it")


def examine(records: Sequence[dict], expected_points: int = 0) -> Prefix:
    """Read a run's history for where -- and whether -- it left its domain.

    ``expected_points`` is the element's integration-point count, so a
    partially evaluated increment cannot be mistaken for a complete one with
    fewer points.
    """
    return Prefix(history=frames.group(records, expected_points))


@dataclass
class Rebuilt:
    """A loading rebuilt to stop short of where the model left its domain."""

    amplitude: float = 0.0
    fraction: float = 0.0
    from_amplitude: float = 0.0
    reason: str = ""
    attempts: list = field(default_factory=list)

    @property
    def possible(self) -> bool:
        return self.amplitude > 0.0

    def as_dict(self) -> dict:
        return {"amplitude": self.amplitude, "fraction": self.fraction,
                "from_amplitude": self.from_amplitude, "reason": self.reason,
                "attempts": list(self.attempts)}


def reconstruct(prefix: Prefix, amplitude: float,
                loading: Sequence[Any], margin: float = MARGIN) -> Rebuilt:
    """The largest amplitude whose path stays inside what the run proved safe.

    The run reached step ``s`` increment ``i`` before it broke. Every segment
    of this loading is a fraction of ``amplitude``, so scaling the amplitude
    scales the whole path and keeps its shape -- the same tension, shear,
    reversal and hold, driven less far.

    How far less is read from the run rather than chosen: the fraction of the
    breaking segment that was walked, times a margin that puts the endpoint
    outside the bracket the run measured rather than against its edge.
    """
    if prefix.complete or not amplitude or not loading:
        return Rebuilt(reason="nothing to rebuild: the run was already finite "
                              "throughout" if prefix.complete else
                              "nothing to rebuild from")
    step, increment = prefix.last_safe
    if step < 1 or step > len(loading) or increment < 1:
        return Rebuilt(
            reason=(f"the run broke at step {prefix.first_bad[0]} increment "
                    f"{prefix.first_bad[1]}, before completing a single "
                    f"increment, so there is no safe part of this path to "
                    f"rebuild from"))
    segment = loading[step - 1]
    walked = increment / max(1, int(getattr(segment, "increments", 1) or 1))
    # Segments after the first do not raise the peak strain -- a shear, a
    # reversal and a hold all run at the amplitude the first segment reached
    # -- so breaking in one of them says the amplitude itself is too large,
    # and the fraction to scale by is the whole of it.
    fraction = walked if step == 1 else 1.0
    rebuilt = max(0.0, amplitude * fraction * margin)
    if not rebuilt or rebuilt >= amplitude:
        return Rebuilt(reason=(f"the rebuilt amplitude {rebuilt:.3g} is no "
                               f"smaller than the one that failed "
                               f"{amplitude:.3g}"))
    return Rebuilt(
        amplitude=rebuilt, fraction=fraction * margin, from_amplitude=amplitude,
        reason=(f"the run walked {increment} of "
                f"{getattr(segment, 'increments', '?')} increments of "
                f"'{getattr(segment, 'name', 'step %d' % step)}' before it "
                f"left its domain, so {fraction:.3g} of the path was proved "
                f"safe; rebuilt at {rebuilt:.3g}, which is {margin:.3g} of "
                f"that -- outside the bracket the run measured rather than "
                f"against its edge"))

# ---------------------------------------------------------------------------
# what the failure actually responds to
# ---------------------------------------------------------------------------
#: Why a run left the material's numerical domain. Named before anything is
#: changed, because the repair depends on it and shrinking the amplitude is
#: only right for one of these.
#: How much of the path two probes have to differ by before the failure is
#: said to have MOVED. One percent: a break at 55% and one at 55.4% is the
#: same increment of a forty-increment path seen through two roundings.
SAME_PLACE = 0.01

AMPLITUDE_LIMITED = "amplitude_limited"
INCREMENT_RESOLUTION_LIMITED = "increment_resolution_limited"
PATH_SEGMENT_LIMITED = "path_segment_limited"
STEP_TRANSITION_LIMITED = "step_transition_limited"
TIME_LIMITED = "time_limited"
INITIALIZATION_OR_STATE_LIMITED = "initialization_or_state_limited"
UNKNOWN_DOMAIN_FAILURE = "unknown_domain_failure"


@dataclass
class Mechanism:
    """Which quantity the failure moved with, and the evidence for it."""

    kind: str = UNKNOWN_DOMAIN_FAILURE
    reason: str = ""
    probes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "reason": self.reason,
                "probes": list(self.probes)}


def classify(probes: Sequence[dict]) -> Mechanism:
    """Read a set of probe runs for what the failure point responds to.

    Each probe is ``{"varied": name, "value": v, "reached": fraction,
    "step": s}`` -- what was changed, to what, how far along the path the run
    got as a FRACTION of it, and which step it broke in.

    A fraction, not a count of increments. Refining the resolution fourfold
    turns "broke after 22 of 40 increments" into "broke after 88 of 160", and
    comparing the counts says the failure moved when it did not move at all:
    both are 55% of the way along the same path. Measured on
    BodyForce-Growth-2Stages.for, where reading the counts called a failure
    increment-resolution-limited and sent the repair to refine a path whose
    breaking point had not shifted by a single increment of real loading.

    The question is whether the break MOVED. A failure whose location is
    unchanged when the amplitude is halved is not controlled by the
    amplitude, and halving it again is the same experiment driven less far,
    failing in the same place.
    """
    def moved(values: Sequence[float]) -> bool:
        usable = [float(v) for v in values if v is not None and float(v) >= 0.0]
        if len(usable) < 2:
            return False
        return (max(usable) - min(usable)) > SAME_PLACE

    by_variable: dict = {}
    for probe in probes:
        by_variable.setdefault(str(probe.get("varied")), []).append(probe)
    responded: list = []
    unmoved: list = []
    for name, runs in sorted(by_variable.items()):
        reached = [run.get("reached") for run in runs]
        shown = [round(float(v), 3) for v in reached if v is not None and float(v) >= 0]
        (responded if moved(reached) else unmoved).append((name, shown))

    steps = {int(probe.get("step") or 0) for probe in probes
             if probe.get("step") is not None and (probe.get("reached") or -1) >= 0}
    if not responded:
        # Nothing this harness varies moves the break. If every probe broke
        # in the SAME step of the path, the segment is what it will not do --
        # a growth law declining to be driven backwards is not an amplitude
        # or a step size, and no amount of either will repair it.
        if len(steps) == 1 and steps != {0}:
            step = next(iter(steps))
            return Mechanism(
                kind=PATH_SEGMENT_LIMITED,
                reason=(f"every probe broke in step {step} at the same place "
                        f"along the path ("
                        + "; ".join(f"{name} reached {counts}"
                                    for name, counts in unmoved)
                        + f"), so it is that SEGMENT the model will not do, "
                          f"not the amplitude it is driven to or the size of "
                          f"the steps it is walked in"),
                probes=list(probes))
        return Mechanism(
            kind=UNKNOWN_DOMAIN_FAILURE,
            reason=("the run broke at the same point under every change tried ("
                    + "; ".join(f"{name} reached {counts}" for name, counts in unmoved)
                    + "), so nothing this harness varies controls where it "
                      "breaks and shrinking the amplitude again would be the "
                      "same experiment driven less far"),
            probes=list(probes))
    name, counts = responded[0]
    kind = {"amplitude": AMPLITUDE_LIMITED,
            "increments": INCREMENT_RESOLUTION_LIMITED,
            "segment": PATH_SEGMENT_LIMITED,
            "step": STEP_TRANSITION_LIMITED,
            "period": TIME_LIMITED,
            "initial_state": INITIALIZATION_OR_STATE_LIMITED}.get(
                name, UNKNOWN_DOMAIN_FAILURE)
    return Mechanism(
        kind=kind,
        reason=(f"the failure point moved with {name}: the run reached "
                f"{counts} of the path as it was varied, so that is the "
                f"quantity the repair has to change"
                + ("; " + "; ".join(f"{other} did not move it ({c})"
                                    for other, c in unmoved) if unmoved else "")),
        probes=list(probes))
