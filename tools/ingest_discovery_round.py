#!/usr/bin/env python3
"""Add the sources a discovery round accepted to the corpus inventory.

The inventory (``paper_results/discovery/discovery_triage.{csv,json}``) is the
denominator: ``tools/transform_all.py --all`` attempts every row of it and
``tools/build_corpus_registry.py`` seeds one record per row. A later discovery
round (for example ``family_round_2026-10-02``) records its own triage of the
files it accepted; this tool copies exactly those rows into the inventory, so
that the accepted sources go through the same pass as every earlier one.

What it checks, refusing on any failure:

* every accepted source has a triage row in the round, and a cached file in
  the acquisition cache whose sha256 is the one ``acceptance.json`` recorded;
* a source already in the inventory is only accepted again with an identical
  row (re-running the tool changes nothing);
* the round's acquisition manifest (``companions.json``) is one the registry
  and the manifest builder read, so every new record gets its pinned commit
  and licence.

The triage rows are copied as the round recorded them; the pass re-transforms
every source at the current transform fingerprint, so a stale triage stage is
context, not a verdict. Rows are kept in the order the triage writes them
(sorted by path components).

    python tools/ingest_discovery_round.py paper_results/discovery/family_round_2026-10-02
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
INVENTORY_DIR = REPO / "paper_results" / "discovery"
DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO.parent / "discovery_cache")

sys.path.insert(0, str(REPO / "tools"))
from run_discovery_triage import COLUMNS  # noqa: E402


class IngestError(RuntimeError):
    pass


def _order(source: str) -> tuple:
    return PurePosixPath(source).parts


def accepted_rows(round_dir: Path, cache_dir: Path | None) -> list[dict]:
    """The round's triage rows for exactly the sources it accepted."""
    acceptance = json.loads((round_dir / "acceptance.json").read_text(encoding="utf-8"))
    triage = {r["source"]: r for r in json.loads(
        (round_dir / "discovery_triage.json").read_text(encoding="utf-8"))["rows"]}
    rows = []
    for entry in acceptance["accepted"]:
        source = entry["source"]
        if source not in triage:
            raise IngestError(f"{source}: accepted, but the round has no triage row")
        if cache_dir is not None:
            cached = cache_dir / source
            if not cached.is_file():
                raise IngestError(f"{source}: not in the acquisition cache {cache_dir.name}")
            digest = hashlib.sha256(cached.read_bytes()).hexdigest()
            if digest != entry["sha256_bytes"]:
                raise IngestError(f"{source}: cached sha256 {digest[:12]} differs from "
                                  f"the accepted {entry['sha256_bytes'][:12]}")
        rows.append(dict(triage[source]))
    if len(rows) != int(acceptance["summary"]["accepted"]):
        raise IngestError(f"acceptance.json lists {len(rows)} accepted sources, its "
                          f"summary says {acceptance['summary']['accepted']}")
    return rows


def merge(existing: list[dict], new: list[dict]) -> tuple[list[dict], list[str]]:
    """Existing rows plus new ones, in triage order. Returns (rows, added)."""
    by_source = {r["source"]: r for r in existing}
    added = []
    for row in new:
        old = by_source.get(row["source"])
        if old is not None:
            if {k: str(old.get(k, "")) for k in COLUMNS} != \
                    {k: str(row.get(k, "")) for k in COLUMNS}:
                raise IngestError(f"{row['source']}: already in the inventory with a "
                                  f"different triage row")
            continue
        by_source[row["source"]] = row
        added.append(row["source"])
    return sorted(by_source.values(), key=lambda r: _order(r["source"])), added


def summary_for(rows: list[dict], previous: dict, rounds: list[dict]) -> dict:
    stages = Counter(r["stage"] for r in rows)
    kinds = Counter(r["blocker_kind"] for r in rows
                    if r["blocker_kind"] not in ("none", ""))
    out = dict(previous)
    out.update(sources=len(rows), by_stage=dict(stages.most_common()),
               by_blocker_kind=dict(kinds.most_common()),
               transformed=stages.get("transformed", 0), rounds_ingested=rounds)
    return out


def ingest(round_dir: Path, inventory_dir: Path = INVENTORY_DIR,
           cache_dir: Path | None = DEFAULT_CACHE) -> list[str]:
    round_dir = Path(round_dir)
    csv_path = inventory_dir / "discovery_triage.csv"
    json_path = inventory_dir / "discovery_triage.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    with csv_path.open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    if [r["source"] for r in csv_rows] != [r["source"] for r in payload["rows"]]:
        raise IngestError("the inventory CSV and JSON list different sources")
    new = accepted_rows(round_dir, cache_dir)
    rows, added = merge(payload["rows"], new)
    if not added:
        return []
    try:
        name = str(round_dir.resolve().relative_to(REPO))
    except ValueError:
        name = round_dir.name
    rounds = [r for r in payload["summary"].get("rounds_ingested", [])
              if r.get("round") != name]
    rounds.append({
        "round": name,
        "accepted": len(new),
        "added": len(added),
        "acceptance_sha256": hashlib.sha256(
            (round_dir / "acceptance.json").read_bytes()).hexdigest(),
        "note": ("triage rows copied from the round's discovery_triage.json; "
                 "the cached files were checked against acceptance.json's sha256"),
    })
    payload = {"summary": summary_for(rows, payload["summary"], rounds), "rows": rows}
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                         encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS),
                                lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("round_dir", type=Path)
    parser.add_argument("--inventory-dir", type=Path, default=INVENTORY_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args(argv)
    try:
        added = ingest(args.round_dir, args.inventory_dir, args.cache_dir)
    except IngestError as error:
        print(f"refused: {error}")
        return 2
    print(f"  {len(added)} sources added to the inventory")
    for source in added:
        print(f"    {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
