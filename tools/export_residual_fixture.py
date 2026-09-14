#!/usr/bin/env python3
"""Freeze a verified corpus case as a fixture the residual assembler can use.

The Residual Assembler's job is to build R from ingredients. Two of those
ingredients come from a UMAT -- the stress at each integration point and the
material tangent -- and until now its tests supplied them from a reference
model written for the purpose. That tests the assembly and nothing about the
bridge: a fixture written to make the assembler pass cannot also be evidence
that the assembler consumes what the pipeline actually produces.

So this writes one out of a case that VERIFIED: the manifest that was run, the
stress and state history the original produced in Abaqus, the tangent the
converted build reported at each increment, and the digests of everything
behind them. It is small on purpose -- a few increments, one material point --
because what it has to carry is the contract, not a dataset.

What it is not: it is not a licence to redistribute anybody's source. The
fixture holds numbers the pipeline computed and the identity of the file they
came from, never the file.

And it is not a place to put a nearly-good run. A regression fixture is the
thing later runs are compared against, so anything wrong inside it is wrong
in every comparison made against it forever after, silently. A NaN frozen into
a fixture does not fail: it propagates, and the comparison that should have
caught it is being made against the NaN. So a case is frozen only when its
history is complete and finite from end to end -- every increment present,
every material point present, every number a number -- and the check is made
twice: against what the batch RECORDED about the run, and against the numbers
actually being written into the fixture. A case that fails either is refused
with the reason, not written with a warning. Measured on
BodyForce-Growth-2Stages.for, where both builds "completed" 35 increments and
both were non-finite from the third.

    tools/export_residual_fixture.py \\
        --results <run>/results/store_verification.jsonl \\
        --work-dir <run>/work \\
        --only BristolCompositesInstitute \\
        --out ../Residual_Assembler/tests/fixtures/verified
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

SCHEMA = "umat-oti/residual-fixture/1"

#: The gates that have to have been measured TRUE before a run may be frozen.
#: The tangent gates are not here: a fixture carries stress and tangent for an
#: assembler to integrate, and whether the tangent verified is recorded in it
#: rather than required of it. These three are about whether the history
#: exists at all, and a history that does not exist cannot be a baseline.
REQUIRED_GATES = ("abaqus_job_completed", "all_requested_outputs_present",
                  "complete_history_finite")

#: The arrays in a carried increment that must be numbers. ``ddsdde`` is in
#: the list: a fixture whose stress is finite and whose tangent is not would
#: freeze a NaN that only shows up once somebody assembles a stiffness.
CARRIED_ARRAYS = ("strain", "dstrain", "stress", "state", "ddsdde")

#: The arrays scanned across the WHOLE probe history rather than only the
#: carried window, under the names the probe writes them. A window is six
#: increments out of hundreds, and a run that went to NaN at increment 200 has
#: a perfectly finite window at increment 4 -- so scanning only what is
#: carried cannot tell a verification apart from the salvageable prefix of a
#: failed analysis.
PROBE_ARRAYS = ("STRESS", "STATEV", "DDSDDE")


class FixtureRefused(ValueError):
    """A case that may not be frozen, said in terms of what is wrong with it."""


def at_either_level(row: dict, name: str) -> Any:
    """A field the batch writes at the top of a record in some runs and inside
    ``discovery`` in others. Absent from both is ``None``, which is "never
    recorded" -- and never recorded is not the same as recorded false.

    Public because ``promote_verified_umats.py`` freezes the same run into a
    contract and has to read it the same way. Two copies of a rule are two
    rules, and they drift."""
    value = row.get(name)
    if value is not None:
        return value
    inner = row.get("discovery")
    return inner.get(name) if isinstance(inner, dict) else None


def not_a_number(values, label: str) -> list:
    """Every entry of one array that is not a finite number, named.

    Public for the same reason as :func:`at_either_level`: the promotion tool
    scans the same probe histories before it freezes a contract out of them."""
    problems = []
    for index, value in enumerate(values or ()):
        try:
            number = float(value)
        except (TypeError, ValueError):
            problems.append(f"{label}[{index}] is {value!r}, which is not a "
                            f"number at all")
            continue
        if not math.isfinite(number):
            problems.append(f"{label}[{index}] is {number}")
    return problems


def scan_whole_history(records: list, side: str) -> dict:
    """Every value in an ENTIRE probe history that is not a finite number.

    The third reading, and the one the other two cannot do. What the batch
    recorded is a claim about the run; the carried window is six increments of
    it; this is every number the run wrote. A fixture is not allowed to be the
    finite prefix of an analysis that stopped being numbers later on, because
    such a fixture is evidence that a run which failed produced a baseline --
    and the failure is then invisible in every comparison made against it.

    Returns the count scanned and the first offending value, named down to the
    record, the array and the index, so a refusal points at a number rather
    than at a file.
    """
    scanned = 0
    for position, record in enumerate(records or ()):
        if not isinstance(record, dict):
            continue
        for name in PROBE_ARRAYS:
            for index, value in enumerate(record.get(name) or ()):
                scanned += 1
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    return {"side": side, "values_scanned": scanned,
                            "records_scanned": position + 1,
                            "first_non_finite": {
                                "record": position, "array": name,
                                "index": index, "value": repr(value),
                                "increment": record.get("increment"),
                                "element": record.get("element"),
                                "point": record.get("point"),
                                "time": record.get("time")}}
                if not math.isfinite(number):
                    return {"side": side, "values_scanned": scanned,
                            "records_scanned": position + 1,
                            "first_non_finite": {
                                "record": position, "array": name,
                                "index": index, "value": str(number),
                                "increment": record.get("increment"),
                                "element": record.get("element"),
                                "point": record.get("point"),
                                "time": record.get("time")}}
    return {"side": side, "values_scanned": scanned,
            "records_scanned": len(records or ()), "first_non_finite": None}


def why_this_may_not_be_frozen(row: dict, carried: dict) -> list:
    """Every reason this case may not become a regression fixture.

    Two independent readings, because either alone can be fooled. What the
    batch RECORDED about the run -- the gates it measured, and the grouping
    that says whether every increment produced every material point and where
    the first value that was not a number is. And the numbers actually about
    to be written, scanned one by one, because a record that says a history
    was finite and a history that is finite are two different claims and the
    fixture carries the second.

    Returns the reasons. Empty means it may be frozen.
    """
    problems: list = []
    source = str(row.get("source") or "this case")

    # -- what the batch recorded -----------------------------------------
    if row.get("stage") != "verified":
        problems.append(
            f"{source} settled at {row.get('stage')!r}, not 'verified'; a "
            f"baseline built out of a case that did not verify is a baseline "
            f"nothing can be compared against")
    if at_either_level(row, "complete_finite_verification_run") is not True:
        problems.append(
            f"{source} has complete_finite_verification_run="
            f"{at_either_level(row, 'complete_finite_verification_run')!r}; "
            f"a fixture must carry a run that was finite from end to end")
    measured = row.get("evidence") or {}
    for gate in REQUIRED_GATES:
        if measured.get(gate) is not True:
            problems.append(
                f"{source} has evidence.{gate}="
                f"{measured.get(gate, 'not measured')!r}")
    grouping = at_either_level(row, "history_grouping") or {}
    for side in ("original", "transformed"):
        payload = grouping.get(side)
        if not isinstance(payload, dict):
            problems.append(f"{source} records no history grouping for the "
                            f"{side} build, so nothing says its history was "
                            f"complete")
            continue
        if payload.get("complete") is not True:
            problems.append(f"{source}: the {side} history is not marked "
                            f"complete")
        incomplete = payload.get("first_incomplete_increment")
        if incomplete:
            problems.append(
                f"{source}: the {side} history's first incomplete increment "
                f"is {incomplete.get('increment')} at time "
                f"{incomplete.get('time')} -- "
                f"{incomplete.get('points')} of "
                f"{incomplete.get('expected_points')} material points")
        non_finite = payload.get("first_non_finite_material_point")
        if non_finite:
            problems.append(
                f"{source}: the {side} history stops being numbers at element "
                f"{non_finite.get('element')} point {non_finite.get('point')} "
                f"of increment {non_finite.get('increment')}")

    # -- the window was not carved out of a run that stopped early --------
    # A regression fixture that is short is a fixture built on however far a
    # failed analysis happened to get. Worse, it is short SILENTLY: the window
    # clamps itself to whatever is on disk and the artefact records the
    # shortened number as though it had been asked for.
    evidence = carried.get("finite_history") or {}
    asked = evidence.get("increments_requested")
    got = evidence.get("increments_carried")
    if isinstance(asked, int) and isinstance(got, int) and got < asked:
        problems.append(
            f"{source}: the window carries {got} increment(s) of the {asked} "
            f"asked for, because only {evidence.get('records_available')} "
            f"record(s) are on disk from {evidence.get('records_requested_from')}"
            f" -- a fixture that is short is a fixture built on however far "
            f"an analysis got before it stopped, and nothing downstream can "
            f"tell that from a run that was meant to be that length")

    # -- and every number the run wrote, not only the ones being carried ---
    # A window of six increments out of hundreds is finite in a run that went
    # to NaN at increment 200. Scanning only the window cannot tell a
    # verification apart from the salvageable prefix of a failed analysis.
    for side, scan in (evidence.get("whole_history") or {}).items():
        if not isinstance(scan, dict):
            continue
        if not scan.get("records_scanned"):
            problems.append(
                f"{source}: the {side} probe history on disk is empty, so no "
                f"reading of the numbers themselves was possible")
            continue
        where = scan.get("first_non_finite")
        if where:
            problems.append(
                f"{source}: the {side} history stops being numbers OUTSIDE "
                f"the carried window -- {where.get('array')}"
                f"[{where.get('index')}] is {where.get('value')} at record "
                f"{where.get('record')}, increment {where.get('increment')}, "
                f"element {where.get('element')} point {where.get('point')}. "
                f"The window is finite and the run is not, so a fixture taken "
                f"from it would be the prefix of a failed analysis")

    # -- and the numbers themselves ---------------------------------------
    ntens = int((carried.get("material_point") or {}).get("ntens") or 0)
    for side in ("original", "converted"):
        records = carried.get(side) or []
        if not records:
            problems.append(f"{source}: the {side} history carries no "
                            f"increments, so there is nothing to freeze")
        for record in records:
            where = f"{side} increment {record.get('increment')}"
            for name in CARRIED_ARRAYS:
                problems.extend(not_a_number(record.get(name), f"{where} {name}"))
            for name in ("time",):
                problems.extend(not_a_number([record.get(name)], f"{where} {name}"))
            stress = list(record.get("stress") or ())
            if ntens and len(stress) != ntens:
                problems.append(
                    f"{where}: the stress has {len(stress)} components and "
                    f"the case states NTENS={ntens}, so this increment is "
                    f"short of the material point it should have produced")
            tangent = list(record.get("ddsdde") or ())
            if ntens and tangent and len(tangent) < ntens * ntens:
                problems.append(
                    f"{where}: the tangent has {len(tangent)} entries and "
                    f"NTENS={ntens} needs {ntens * ntens}")
    return problems

#: How many increments to carry. Enough that a state variable has moved and a
#: tangent has been asked for more than once; few enough that the fixture stays
#: readable and a failure points at a line rather than at a file.
INCREMENTS = 6


def _rows(path: Path) -> list:
    rows = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _history(work_dir: Path, key: str, job: str) -> list:
    path = Path(work_dir) / key / job / f"{job}_history.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def window_start(row: dict, available: int, increments: int) -> int:
    """Which record the frozen window begins at.

    Not the first, by default. The first records of a history are where a
    material is still elastic and where, one increment later, it yields -- and
    a chord taken ACROSS that corner is not the derivative of anything. It is
    the average of two branch stiffnesses, so a consumer that checks "does
    D dstrain predict the stress increment" fails on it and is right to.
    Measured on the bundled J2 control: increments 1 to 2 cross yield and the
    check misses by 2.75e-01; increments 2 onward are linear hardening and it
    is exact.

    So the window starts where the pipeline MEASURED a tangent -- the record
    index of the first verified state -- because that is the state its own
    regime classifier judged smooth enough to differentiate at. Clamped back
    so a full window still fits, and 0 when no state was recorded.
    """
    states = (row.get("tangent") or {}).get("states") or []
    indices = [state.get("record_index") for state in states
               if state.get("verified") and isinstance(
                   state.get("record_index"), int)]
    start = min(indices) if indices else 0
    return max(0, min(start, available - increments))


def fixture_from(row: dict, work_dir: Path, increments: int = INCREMENTS, *,
                 start: Optional[int] = None) -> Optional[dict]:
    """One verified case, as the ingredients an assembler needs."""
    key = str(row.get("key") or "")
    original = _history(work_dir, key, "original")
    converted = _history(work_dir, key, "transformed")
    if not original or not converted:
        return None
    # Kept whole beside the window, because the check that a fixture is not
    # the finite prefix of a failed run has to read the records the window
    # does NOT carry.
    original_records, converted_records = list(original), list(converted)
    manifest = row.get("manifest") or {}
    available = min(len(original), len(converted))
    if start is None:
        start = window_start(row, available, increments)
    start = max(0, min(int(start), max(0, available - 1)))
    take = min(increments, available - start)
    original = original[start:]
    converted = converted[start:]
    # The deck both builds were driven by, verbatim. It is a file this
    # pipeline generated, so it may be carried; and it is the experiment, so
    # carrying it is what lets a reader of the fixture see what produced the
    # numbers rather than take them on trust.
    deck = ""
    try:
        deck = (Path(work_dir) / key / "original" / "original.inp").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        deck = ""
    # PROPS and the tensor split are in the probe's ENTRY record whether or
    # not the run recorded a manifest beside it.
    entry = (original[0] or {}).get("entry") or {}

    def point(record: dict) -> dict:
        from umat_oti.abaqus.activation import increment_of, strain_at
        return {
            "increment": record.get("increment"),
            "time": record.get("time"),
            "strain": strain_at(record),
            "dstrain": increment_of(record),
            "stress": list(record.get("STRESS") or ()),
            "state": list(record.get("STATEV") or ()),
            "ddsdde": list(record.get("DDSDDE") or ()),
        }

    return {
        "schema": SCHEMA,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "what_this_is": (
            "the ingredients one verified corpus case produced: the stress and "
            "state the ORIGINAL UMAT computed in Abaqus at one material point, "
            "and the tangent the OTI-CONVERTED build reported at the same "
            "increments. Both ran the same deck; their histories agreed; the "
            "tangent agreed with a finite difference of the original. Nothing "
            "here is a source file."),
        "source_id": row.get("source"),
        "source_sha256": row.get("source_sha256"),
        "repository": row.get("repository"),
        "transform_fingerprint": row.get("fingerprint"),
        "deck_digest": row.get("deck_digest"),
        "material": {
            "provenance": row.get("material_provenance"),
            "props": list(manifest.get("props") or entry.get("PROPS") or ()),
            "nstatv": manifest.get("nstatv") or entry.get("NSTATV"),
        },
        "deck": deck,
        "material_point": {
            "element_type": manifest.get("element_type") or row.get("element_type"),
            "ntens": manifest.get("ntens") or row.get("ntens") or entry.get("NTENS"),
            "ndi": manifest.get("ndi") or entry.get("NDI"),
            "nshr": manifest.get("nshr") or entry.get("NSHR"),
            "kinematics": manifest.get("kinematics") or row.get("kinematics"),
            "voigt_order": ("11, 22, 33, 12, 13, 23 with ENGINEERING shear on "
                            "the off-diagonals, which is what Abaqus hands a "
                            "UMAT and what DDSDDE is expressed in"),
        },
        "verification": {
            "worst_stress_relative": (row.get("primal") or {}).get(
                "worst_stress_relative"),
            "worst_state_relative": (row.get("primal") or {}).get(
                "worst_state_relative"),
            "tangent": (row.get("tangent") or {}).get("reason"),
            "states_agreeing": (row.get("tangent") or {}).get("states_agreeing"),
            "states_checked": (row.get("tangent") or {}).get("states_checked"),
        },
        # What makes this freezable, carried so the assertion can be made
        # again by whoever loads it rather than taken on trust from the tool
        # that wrote it. A fixture that says it is finite and is not would
        # otherwise be caught nowhere.
        "finite_history": {
            "rule": ("a fixture carries a completely finite successful "
                     "history and nothing else: every increment present, "
                     "every material point present, every number a number. "
                     "Refused at freeze time by "
                     "why_this_may_not_be_frozen() and again at load time."),
            "evidence": dict(row.get("evidence") or {}),
            "complete_finite_verification_run": at_either_level(
                row, "complete_finite_verification_run"),
            "history_grouping": at_either_level(row, "history_grouping"),
            "increments_carried": take,
            # What was ASKED for, beside what was got. Without it a short
            # window is indistinguishable from a short request, and a fixture
            # built on however far a failed analysis got reads as deliberate.
            "increments_requested": increments,
            "records_available": available,
            "records_requested_from": {"original": len(original_records),
                                       "transformed": len(converted_records)},
            # Every number the run wrote, scanned, not only the ones carried.
            "whole_history": {
                "original": scan_whole_history(original_records, "original"),
                "transformed": scan_whole_history(converted_records,
                                                  "transformed")},
            "window_starts_at_record": start,
            "why_that_record": (
                "the first record the pipeline verified a tangent at, whose "
                "regime classifier judged it smooth. A window starting at the "
                "first record of a history straddles yield, and a chord "
                "across a corner is not a derivative."),
        },
        "original": [point(record) for record in original[:take]],
        "converted": [point(record) for record in converted[:take]],
    }


def freeze(row: dict, work_dir: Path, increments: int = INCREMENTS, *,
           start: Optional[int] = None) -> dict:
    """One verified case as a fixture, or a refusal saying why not.

    The refusal is an exception rather than a ``None`` on purpose: a caller
    that forgets to check a return value writes the fixture anyway, and this
    is exactly the check nobody may forget.
    """
    carried = fixture_from(row, work_dir, increments, start=start)
    if carried is None:
        raise FixtureRefused(
            f"{row.get('source')}: no probe history on disk under "
            f"{Path(work_dir) / str(row.get('key') or '')}")
    problems = why_this_may_not_be_frozen(row, carried)
    if problems:
        raise FixtureRefused(
            f"{row.get('source')} may not be frozen as a fixture:\n  - "
            + "\n  - ".join(problems))
    return carried


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", default="",
                        help="substring of the source's path within the cache")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--increments", type=int, default=INCREMENTS)
    parser.add_argument("--start", type=int, default=None,
                        help="record index the frozen window begins at; by "
                             "default the first record a tangent verified at")
    args = parser.parse_args(argv)

    verified = [row for row in _rows(args.results)
                if row.get("stage") == "verified"
                and args.only.lower() in str(row.get("source") or "").lower()]
    if args.limit:
        verified = verified[:args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    refused = 0
    for row in verified:
        try:
            fixture = freeze(row, args.work_dir, args.increments,
                             start=args.start)
        except FixtureRefused as refusal:
            print(f"  REFUSED {refusal}")
            refused += 1
            continue
        name = hashlib.sha256(str(row.get("source")).encode()).hexdigest()[:10]
        stem = Path(str(row.get("source"))).stem.lower()
        path = args.out / f"{stem}--{name}.json"
        path.write_text(json.dumps(fixture, indent=1) + "\n", encoding="utf-8")
        print(f"  wrote {path.name}  ({len(fixture['original'])} increments, "
              f"{fixture['material_point']['element_type']})")
        written += 1
    print(f"  {written} fixture(s) frozen and {refused} refused, from "
          f"{len(verified)} verified case(s)")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
