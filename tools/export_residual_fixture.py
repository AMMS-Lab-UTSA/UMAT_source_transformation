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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

SCHEMA = "umat-oti/residual-fixture/1"

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


def fixture_from(row: dict, work_dir: Path, increments: int = INCREMENTS) -> Optional[dict]:
    """One verified case, as the ingredients an assembler needs."""
    key = str(row.get("key") or "")
    original = _history(work_dir, key, "original")
    converted = _history(work_dir, key, "transformed")
    if not original or not converted:
        return None
    manifest = row.get("manifest") or {}
    take = min(increments, len(original), len(converted))
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
        "original": [point(record) for record in original[:take]],
        "converted": [point(record) for record in converted[:take]],
    }


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
    args = parser.parse_args(argv)

    verified = [row for row in _rows(args.results)
                if row.get("stage") == "verified"
                and args.only.lower() in str(row.get("source") or "").lower()]
    if args.limit:
        verified = verified[:args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    for row in verified:
        fixture = fixture_from(row, args.work_dir, args.increments)
        if fixture is None:
            print(f"  {row.get('source')}: no probe history on disk; skipped")
            continue
        name = hashlib.sha256(str(row.get("source")).encode()).hexdigest()[:10]
        stem = Path(str(row.get("source"))).stem.lower()
        path = args.out / f"{stem}--{name}.json"
        path.write_text(json.dumps(fixture, indent=1) + "\n", encoding="utf-8")
        print(f"  wrote {path.name}  ({len(fixture['original'])} increments, "
              f"{fixture['material_point']['element_type']})")
        written += 1
    print(f"  {written} fixture(s) from {len(verified)} verified case(s)")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
