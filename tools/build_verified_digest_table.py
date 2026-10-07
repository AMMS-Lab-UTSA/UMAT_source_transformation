#!/usr/bin/env python3
"""Build docs/evidence/verified_digests.json from the corpus registry.

    python tools/build_verified_digest_table.py [--registry FILE] [--cache DIR] [--out FILE] [--check]

``umat-oti check`` shows a corpus result for a file whose bytes match a registry row. The registry
(paper_results/corpus/corpus_registry.json, 2.3 MB) is not part of an installed package, so this
small table carries what the lookup needs: per row the SHA-256 of the UMAT and of its deck, the
terminal state, the six gate readings and the reason text the plain-language card reads.

The deck's bytes are hashed from the discovery cache (the registry records only the deck's name);
a row whose deck is not in the cache keeps the digest the existing table already holds, or none
(then a deck can never match that row). ``--check`` rebuilds in memory and exits 1 when the file
differs, so a changed registry cannot leave the table behind.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES = ("abaqus_job_completed", "all_requested_outputs_present", "complete_history_finite",
         "derivatives_verified", "primal_agreed", "mechanically_informative")
SCHEMA = "umat-oti/verified-digests/1"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(registry: Path, cache: Path, previous: dict) -> dict:
    data = json.loads(Path(registry).read_text(encoding="utf-8"))
    old = {(r["sha256"], r["deck"]): r.get("deck_sha256", "") for r in previous.get("rows", [])}
    rows = []
    for rec in data["records"]:
        deck = rec.get("deck") or ""
        deck_sha = ""
        if deck:
            path = Path(cache) / deck
            deck_sha = sha256_of(path) if path.is_file() else old.get((rec["sha256"], deck), "")
        source = str(rec.get("verification_source") or "")
        rows.append({
            "source_id": rec["source_id"], "sha256": rec["sha256"], "deck": deck, "deck_sha256": deck_sha,
            "state": rec["terminal_state"], "run": source.split("/", 1)[0] if source else "",
            "gates": {g: rec.get("gate_" + g) for g in GATES},
            "all_gates_true": bool(rec.get("verified_on_every_gate")),
            "reason": str(rec.get("reason") or rec.get("not_verified_reason") or "")[:600]})
    rows.sort(key=lambda r: (r["sha256"], r["deck"], r["source_id"]))
    return {"schema": SCHEMA, "registry_generated": data["generated"],
            "registry_sha256": sha256_of(registry), "records": len(rows), "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", type=Path, default=ROOT / "paper_results/corpus/corpus_registry.json")
    ap.add_argument("--cache", type=Path, default=Path.home() / "softwarex_work/discovery_cache")
    ap.add_argument("--out", type=Path, default=ROOT / "docs/evidence/verified_digests.json")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    previous = json.loads(args.out.read_text(encoding="utf-8")) if args.out.is_file() else {}
    table = build(args.registry, args.cache, previous)
    text = json.dumps(table, indent=1, sort_keys=True) + "\n"
    if args.check:
        same = args.out.is_file() and args.out.read_text(encoding="utf-8") == text
        print("verified_digests.json is current" if same else "verified_digests.json differs from the registry")
        return 0 if same else 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(table['rows'])} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
