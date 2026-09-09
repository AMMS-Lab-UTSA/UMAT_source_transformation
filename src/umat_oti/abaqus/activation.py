"""Did the loading actually make the material do anything?

A verification driven at a strain the model answers elastically tests the part
of a UMAT that every build gets right. The stress is linear in the strain, the
tangent is the elastic one, and the state never moves -- so a converted routine
that is wrong about yielding, damage, hardening or rate dependence agrees
perfectly, and the row is recorded as verified.

So the loading is not fixed here. It is searched for: the driver runs the
ORIGINAL material, asks these indicators whether anything happened, and raises
the amplitude until something does. This module is the "did anything happen?"
half, and it answers from numbers rather than from names -- it never needs to
know that ``STATEV(1)`` means equivalent plastic strain.

Each indicator says what it saw and how big it was, so a loading can be
reported as "activated, by state change and a departure from linearity of
3.2%" rather than as a bare yes.

WHAT THIS MODULE CANNOT SEE, and therefore does not claim: dissipated energy
(ALLPD/ALLCD are model-level ODB history output, and this reads a
material-point probe), a ``PNEWDT`` cutback request (the probe records what
the routine returned, not what the solver did with it), and which constitutive
branch executed (that needs the source instrumented, not its output read).
Their absence is never reported as "no activation" -- only as not measured.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

#: A relative movement below this is the last bits of two floating-point
#: numbers, not a material doing something.
NOISE = 1e-9

#: How far the stress may depart from a straight line through the first
#: increment before the response stops being linear. Well above the noise a
#: converged Newton solve leaves, and far below anything a yield surface does.
LINEARITY_TOLERANCE = 1e-3


def _finite(values) -> list[float]:
    return [float(v) for v in (values or ()) if math.isfinite(float(v))]


def _largest(values) -> float:
    return max((abs(v) for v in _finite(values)), default=0.0)


@dataclass
class Indicator:
    """One thing that may have happened, and the size of it."""

    name: str
    fired: bool
    magnitude: float = 0.0
    detail: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "fired": self.fired,
                "magnitude": self.magnitude, "detail": self.detail}


@dataclass
class Activation:
    """What the material did under one loading."""

    indicators: list[Indicator] = field(default_factory=list)
    increments: int = 0
    not_measured: tuple[str, ...] = ()

    @property
    def activated(self) -> bool:
        return any(indicator.fired for indicator in self.indicators)

    @property
    def fired(self) -> list[str]:
        return [i.name for i in self.indicators if i.fired]

    def summary(self) -> str:
        if not self.increments:
            return "nothing ran, so nothing can be said about activation"
        if not self.activated:
            return (f"the response stayed linear and no state moved over "
                    f"{self.increments} increments: this loading exercises the "
                    f"elastic branch only, which is the part every build gets "
                    f"right")
        parts = [f"{i.name} ({i.magnitude:.3g})"
                 for i in self.indicators if i.fired]
        return f"activated over {self.increments} increments by " + ", ".join(parts)

    def as_dict(self) -> dict:
        return {"activated": self.activated, "increments": self.increments,
                "fired": self.fired, "summary": self.summary(),
                "not_measured": list(self.not_measured),
                "indicators": [i.as_dict() for i in self.indicators]}


def _state_moved(records: Sequence[dict]) -> Indicator:
    """Any state variable that is not where it started.

    The strongest and simplest signal: a model with internal state that has
    not changed it has not left its elastic branch.
    """
    first = _finite((records[0] or {}).get("STATEV"))
    if not first:
        return Indicator("state_change", False, 0.0,
                         "the material declares no state variables")
    worst, where = 0.0, 0
    for index, record in enumerate(records[1:], start=1):
        current = _finite(record.get("STATEV"))
        for position, (a, b) in enumerate(zip(first, current)):
            scale = max(abs(a), abs(b), 1.0)
            moved = abs(b - a) / scale
            if moved > worst:
                worst, where = moved, position + 1
    return Indicator("state_change", worst > NOISE, worst,
                     f"largest movement in STATEV({where})" if where else "")


def _departed_from_linear(records: Sequence[dict]) -> Indicator:
    """Does stress still lie on the straight line the first increment set?

    The first increment of a displacement-controlled path is elastic for
    essentially every model, so it fixes the reference slope. A later stress
    that has fallen away from it is the model doing something -- yielding,
    damaging, hardening -- whatever its author called it.
    """
    usable = [r for r in records if _finite(r.get("STRESS")) and _finite(r.get("STRAN"))]
    if len(usable) < 3:
        return Indicator("departure_from_linearity", False, 0.0,
                         "too few increments carry both stress and strain")
    first_stress = _finite(usable[0].get("STRESS"))
    first_strain = _finite(usable[0].get("STRAN"))
    reference = _largest(first_strain)
    if not reference:
        return Indicator("departure_from_linearity", False, 0.0,
                         "the first increment applied no strain")

    worst, at = 0.0, 0
    for index, record in enumerate(usable[1:], start=1):
        strain = _finite(record.get("STRAN"))
        stress = _finite(record.get("STRESS"))
        ratio = _largest(strain) / reference if reference else 0.0
        if ratio <= 0:
            continue
        predicted = [value * ratio for value in first_stress]
        scale = max(_largest(predicted), _largest(stress), 1.0)
        for a, b in zip(predicted, stress):
            departure = abs(a - b) / scale
            if departure > worst:
                worst, at = departure, index
    return Indicator("departure_from_linearity", worst > LINEARITY_TOLERANCE,
                     worst, f"largest at increment {at + 1}" if at else "")


def _tangent_changed(records: Sequence[dict]) -> Indicator:
    """Has DDSDDE moved away from the one the first increment returned?

    A stiffness that changes is a constitutive event by definition. This is
    the indicator that matters most for a derivative claim: a tangent that
    never moves is a tangent whose verification says nothing about the
    material's actual behaviour.
    """
    with_tangent = [r for r in records if _finite(r.get("DDSDDE"))]
    if len(with_tangent) < 2:
        return Indicator("tangent_change", False, 0.0,
                         "fewer than two increments recorded a tangent")
    first = _finite(with_tangent[0].get("DDSDDE"))
    scale = _largest(first) or 1.0
    worst, at = 0.0, 0
    for index, record in enumerate(with_tangent[1:], start=1):
        current = _finite(record.get("DDSDDE"))
        for a, b in zip(first, current):
            moved = abs(a - b) / scale
            if moved > worst:
                worst, at = moved, index
    return Indicator("tangent_change", worst > LINEARITY_TOLERANCE, worst,
                     f"largest at increment {at + 1}" if at else "")


def _residual_after_reversal(records: Sequence[dict],
                             reversal_at: Optional[int]) -> Indicator:
    """Stress left over when the strain has been brought back.

    Only asked where the loading actually reverses. An elastic material
    returns to where it started; anything that does not has kept something.
    """
    if reversal_at is None or reversal_at >= len(records):
        return Indicator("residual_after_reversal", False, 0.0,
                         "this loading does not reverse")
    start_strain = _finite((records[0] or {}).get("STRAN"))
    best = None
    for record in records[reversal_at:]:
        strain = _finite(record.get("STRAN"))
        if not strain:
            continue
        distance = max((abs(a - b) for a, b in zip(start_strain, strain)),
                       default=math.inf)
        if best is None or distance < best[0]:
            best = (distance, record)
    if best is None:
        return Indicator("residual_after_reversal", False, 0.0,
                         "no increment came back near the starting strain")
    _, nearest = best
    stress = _finite(nearest.get("STRESS"))
    reference = max((_largest(r.get("STRESS")) for r in records), default=0.0) or 1.0
    residual = _largest(stress) / reference
    return Indicator("residual_after_reversal", residual > LINEARITY_TOLERANCE,
                     residual, "stress remaining when the strain returned")


def detect_activation(records: Sequence[dict],
                      reversal_at: Optional[int] = None) -> Activation:
    """What the material did, read from a material-point probe history.

    ``reversal_at`` is the index at which the loading turns around, when it
    does; the residual indicator is only meaningful there.
    """
    usable = [r for r in (records or ()) if isinstance(r, dict)]
    if not usable:
        return Activation(indicators=[], increments=0)
    return Activation(
        indicators=[
            _state_moved(usable),
            _departed_from_linear(usable),
            _tangent_changed(usable),
            _residual_after_reversal(usable, reversal_at),
        ],
        increments=len(usable),
        not_measured=(
            "dissipated energy (ALLPD/ALLCD are model-level ODB history, not "
            "material-point probe output)",
            "a PNEWDT cutback request (the probe records what the routine "
            "returned, not what the solver did with it)",
            "which constitutive branch executed (that needs the source "
            "instrumented, not its output read)",
        ),
    )
