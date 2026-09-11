"""One UMAT call, the same inputs, two builds: what the routine itself did.

A history comparison says the two builds parted company. It cannot say where
the difference was *made*, because by the time a stress at increment 137
differs, the state it was computed from differs too, and the solver has been
handing each build its own displacement increment for a hundred increments.
Every quantity on both sides of the equation has moved. Nothing is controlled.

The probe writes two records per call -- everything the routine was given
(``ENTRY``) and everything it returned (``RECORD``). So the controlled
experiment is already in the recorded data and needs no Abaqus run: find a
call where the two builds were handed the *same* arguments, and look at what
each returned. If the inputs are bit-identical and the outputs are not, the
difference was made inside that call by the routine, and no property of the
solve -- iteration count, cutback, load path -- can be blamed for it.

That distinction is the whole point. "The two builds converged to different
iterates" and "the transformed routine computes one output wrongly" predict
different things about such a call:

    different iterate      every output moves, by an amount near the
                           solver's own convergence tolerance, and the two
                           builds took different numbers of iterations

    wrong output           the iteration counts match, most outputs are
                           bit-identical, and the ones that are not are
                           wrong by far more than any tolerance

This module measures which of those the data shows. It does not decide.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

#: Blocks the probe records on entry -- everything the routine is given.
INPUT_BLOCKS = ("STRESS0", "STATEV0", "DSTRAN", "STRAN", "DFGRD0", "DFGRD1",
                "DROT", "PROPS", "TEMP", "DTIME", "TIME", "COORDS")
#: Blocks the probe records on return -- everything the routine sets that the
#: solver carries forward. DDSDDE is deliberately excluded: the transformed
#: build is *supposed* to return a different tangent, so a difference there is
#: the transform working, not failing.
OUTPUT_BLOCKS = ("STRESS", "STATEV")

#: Two values are "the same input" if they differ by less than this fraction
#: of the largest value that block reaches anywhere in either run. A structural
#: zero that Abaqus hands over as 1e-35 in one build and 6e-35 in the other
#: differs by 100% of itself and by 1e-32 of the block, and calling that a
#: different input would throw away every controlled call in the corpus.
INPUT_SAME = 1e-14

#: Reported verdicts. Each is a statement about what was measured, not about
#: what caused it.
SAME_INPUTS_DIFFERENT_OUTPUTS = "same_inputs_different_outputs"
INPUTS_ALREADY_DIVERGED = "inputs_already_diverged"
NO_DIVERGENCE = "no_divergence_in_paired_calls"
NOT_PAIRABLE = "calls_could_not_be_paired"


@dataclass
class SlotDifference:
    """One output component of one call, as each build left it."""

    block: str
    index: int          # zero-based, as parsed
    original: float
    transformed: float

    @property
    def fortran_index(self) -> int:
        """The subscript the author's source would write."""
        return self.index + 1

    @property
    def absolute(self) -> float:
        if not (math.isfinite(self.original) and math.isfinite(self.transformed)):
            return math.inf
        return abs(self.original - self.transformed)

    def relative_to(self, scale: float) -> float:
        if not math.isfinite(self.absolute):
            return math.inf
        return self.absolute / scale if scale else 0.0

    def as_dict(self, scale: float = 0.0) -> dict:
        return {"block": self.block, "index": self.index,
                "fortran_index": self.fortran_index,
                "original": self.original, "transformed": self.transformed,
                "absolute": self.absolute,
                "relative_to_block_scale": self.relative_to(scale)}


@dataclass
class Isolation:
    """What a single call, run twice from the same arguments, showed."""

    verdict: str = NO_DIVERGENCE
    paired_calls: int = 0
    call_index: int = -1
    element: Optional[int] = None
    point: Optional[int] = None
    step: Optional[int] = None
    increment: Optional[int] = None
    time: float = 0.0
    #: Largest input difference at that call, as a fraction of the block's
    #: own scale. Reported even when it is below INPUT_SAME, because the
    #: reader has to be able to see how far below.
    worst_input_relative: float = 0.0
    worst_input_block: str = ""
    worst_input_slot: Optional[SlotDifference] = None
    #: How many output components differ at all (any bit), and how many of
    #: those differ by more than rounding could carry.
    output_slots_total: int = 0
    output_slots_differing: int = 0
    output_slots_beyond_rounding: list = field(default_factory=list)
    #: The stress components, separately, because "the stress agreed and one
    #: state slot did not" is a different finding from "everything moved".
    stress_slots_differing: int = 0
    stress_worst_relative: float = 0.0
    #: The largest magnitude each block reaches anywhere in either run. Kept
    #: so that as_dict can report a slot's difference as a fraction of its own
    #: field: without it every reported relative came back 0.0, because the
    #: scale defaulted to zero at serialisation time and the division was
    #: skipped. A report of 0.0 beside a slot listed as "beyond rounding" is
    #: worse than no number.
    scales: dict = field(default_factory=dict)
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "paired_calls": self.paired_calls,
            "call_index": self.call_index,
            "at": {"element": self.element, "point": self.point,
                   "step": self.step, "increment": self.increment,
                   "time": self.time},
            "worst_input_relative": self.worst_input_relative,
            "worst_input_block": self.worst_input_block,
            "worst_input_slot": (
                self.worst_input_slot.as_dict(
                    self.scales.get(self.worst_input_slot.block, 0.0))
                if self.worst_input_slot else None),
            "output_slots_total": self.output_slots_total,
            "output_slots_differing": self.output_slots_differing,
            "output_slots_beyond_rounding": [
                slot.as_dict(self.scales.get(slot.block, 0.0))
                for slot in self.output_slots_beyond_rounding],
            "stress_slots_differing": self.stress_slots_differing,
            "stress_worst_relative": self.stress_worst_relative,
            "reason": self.reason,
        }


def pair_calls(records: Sequence[dict]) -> list[tuple[Optional[dict], dict]]:
    """Every call the probe saw, as (what went in, what came out).

    Not one per increment: every equilibrium iteration, in the order Abaqus
    made them. ``converged_only`` keeps the last call of each increment, which
    is right for comparing histories and wrong for this -- the call where the
    difference is *made* is usually not the last one of its increment.
    """
    calls: list[tuple[Optional[dict], dict]] = []
    pending: Optional[dict] = None
    for record in records:
        if record.get("kind") == "entry":
            pending = record
        else:
            calls.append((pending, record))
            pending = None
    return calls


def call_site(record: dict) -> tuple:
    return (record.get("step"), record.get("element"),
            record.get("point"), record.get("increment"))


def iteration_counts(calls: Iterable[tuple]) -> dict:
    """How many calls each increment took, per element and point.

    This is the number the "two solvers converged to different iterates"
    hypothesis predicts will differ. It is read off the probe, not guessed
    from the presence of a Newton loop in the source.
    """
    counts: dict = {}
    for _, result in calls:
        counts[call_site(result)] = counts.get(call_site(result), 0) + 1
    return counts


def block_scale(calls: Iterable[tuple], block: str) -> float:
    """The largest magnitude that block reaches anywhere in the run."""
    largest = 0.0
    for entry, result in calls:
        for source in (entry, result):
            if source is None:
                continue
            for value in (source.get(block) or ()):
                if math.isfinite(value):
                    largest = max(largest, abs(value))
    return largest


def first_non_finite(calls: Iterable[tuple]) -> Optional[dict]:
    """The first call at which any recorded value stopped being a number."""
    for index, (entry, result) in enumerate(calls):
        for source, which in ((entry, "entry"), (result, "result")):
            if source is None:
                continue
            for name, values in source.items():
                if not isinstance(values, list):
                    continue
                bad = [position for position, value in enumerate(values)
                       if isinstance(value, float) and not math.isfinite(value)]
                if bad:
                    return {"call_index": index, "record": which,
                            "block": name, "components": bad[:8],
                            "at": {"element": source.get("element"),
                                   "point": source.get("point"),
                                   "increment": source.get("increment"),
                                   "time": source.get("time")}}
    return None


def isolate_first_divergence(
    original: Sequence[dict],
    transformed: Sequence[dict],
    *,
    input_same: float = INPUT_SAME,
    output_rounding: float = 1e-10,
    require_beyond_rounding: bool = False,
) -> Isolation:
    """The first call where the two builds' outputs part, and what went in.

    ``output_rounding`` is a fraction of the block's own scale, used to sort
    the differing slots into "could be rounding" and "could not". It is not a
    pass mark: a call that differs only within it is still reported as a
    divergence, with its magnitude attached.

    ``require_beyond_rounding`` asks a different question, and both have to be
    asked. With it False the answer is "where did the two builds first differ
    at all", which on this corpus is the first call of the analysis in every
    one of the forty-two entries, at one unit in the last place. With it True
    the answer is "where did they first differ by more than rounding could
    carry" -- and for the crystal-plasticity trio that is call 4, where one
    state slot moves by a quarter of the field while the stress stays
    bit-identical. Reporting only the first is how a corpus of forty-two
    distinct behaviours reads as one.
    """
    left = pair_calls(original)
    right = pair_calls(transformed)
    result = Isolation(paired_calls=min(len(left), len(right)))
    if not left or not right:
        result.verdict = NOT_PAIRABLE
        result.reason = "one of the builds recorded no calls"
        return result

    scales = {block: max(block_scale(left, block), block_scale(right, block))
              for block in set(INPUT_BLOCKS) | set(OUTPUT_BLOCKS)}
    result.scales = scales

    for index in range(result.paired_calls):
        (entry_o, out_o), (entry_t, out_t) = left[index], right[index]
        if call_site(out_o) != call_site(out_t):
            result.verdict = NOT_PAIRABLE
            result.call_index = index
            result.reason = (
                f"the builds' call {index} is at {call_site(out_o)} in the "
                f"original and {call_site(out_t)} in the transformed build, "
                f"so from here on no two calls are the same call")
            return result

        differing: list[SlotDifference] = []
        total = 0
        stress_differing = 0
        stress_worst = 0.0
        for block in OUTPUT_BLOCKS:
            a, b = out_o.get(block) or [], out_t.get(block) or []
            total += min(len(a), len(b))
            for position, (x, y) in enumerate(zip(a, b)):
                same = (x == y) or (math.isnan(x) and math.isnan(y))
                if same:
                    continue
                slot = SlotDifference(block, position, x, y)
                differing.append(slot)
                if block == "STRESS":
                    stress_differing += 1
                    stress_worst = max(stress_worst,
                                       slot.relative_to(scales.get(block, 0.0)))
        if not differing:
            continue
        if require_beyond_rounding and not any(
                slot.relative_to(scales.get(slot.block, 0.0)) > output_rounding
                for slot in differing):
            continue

        # This call is the first with a different output. Say what went in.
        worst_input = 0.0
        worst_block = ""
        worst_slot: Optional[SlotDifference] = None
        if entry_o is not None and entry_t is not None:
            for block in INPUT_BLOCKS:
                a, b = entry_o.get(block) or [], entry_t.get(block) or []
                scale = scales.get(block) or 0.0
                for position, (x, y) in enumerate(zip(a, b)):
                    if x == y:
                        continue
                    slot = SlotDifference(block, position, x, y)
                    relative = slot.relative_to(scale)
                    if relative > worst_input:
                        worst_input, worst_block, worst_slot = (
                            relative, block, slot)
            for block in ("DTIME", "TIME"):
                a, b = entry_o.get(block), entry_t.get(block)
                if isinstance(a, list) and isinstance(b, list):
                    continue

        result.call_index = index
        result.element = out_o.get("element")
        result.point = out_o.get("point")
        result.step = out_o.get("step")
        result.increment = out_o.get("increment")
        result.time = float(out_o.get("time") or 0.0)
        result.worst_input_relative = worst_input
        result.worst_input_block = worst_block
        result.worst_input_slot = worst_slot
        result.output_slots_total = total
        result.output_slots_differing = len(differing)
        result.output_slots_beyond_rounding = [
            slot for slot in differing
            if slot.relative_to(scales.get(slot.block, 0.0)) > output_rounding]
        result.stress_slots_differing = stress_differing
        result.stress_worst_relative = stress_worst
        if worst_input <= input_same:
            result.verdict = SAME_INPUTS_DIFFERENT_OUTPUTS
            result.reason = (
                f"at call {index} (element {result.element}, point "
                f"{result.point}, increment {result.increment}) the two "
                f"builds were handed arguments agreeing to "
                f"{worst_input:.2e} of their own scale and returned "
                f"{len(differing)} of {total} output components different, "
                f"{len(result.output_slots_beyond_rounding)} of them by more "
                f"than {output_rounding:.0e} of the field")
        else:
            result.verdict = INPUTS_ALREADY_DIVERGED
            result.reason = (
                f"at call {index} the arguments already differed by "
                f"{worst_input:.2e} of {worst_block}'s scale, so what the "
                f"routine returned is not attributable to the routine")
        return result

    result.verdict = NO_DIVERGENCE
    result.reason = (f"the two builds returned bit-identical outputs over all "
                     f"{result.paired_calls} paired calls")
    return result


def read_pair(work_dir: Path) -> tuple[list[dict], list[dict]]:
    """The two probe files a comparison run leaves behind."""
    from umat_oti.abaqus.probe import parse_probe
    work_dir = Path(work_dir)
    return (parse_probe(work_dir / "original" / "original_probe.txt"),
            parse_probe(work_dir / "transformed" / "transformed_probe.txt"))
