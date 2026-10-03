#!/usr/bin/env python3
"""Write, or check, the council-designed experiments of D-19a rev 2 (G9).

For every row of a harvest file or a D-21 council-constants file (JSON
lines), :func:`umat_oti.abaqus.experiment.plan_council` designs the
experiment; this writes ``<out>/<key>/council_plan.json`` and one
``council_<set>.inp`` per parameter set (``abaqus.deck.generate_deck``).
council.inp is an OUTPUT only: nothing reads it back.

``--check`` regenerates everything in memory and compares it byte for byte
with what is on disk (R6.1): any difference -- a changed row, a changed
generator, a hand edit -- names the row and exits 1, and that row is
suspended until it is regenerated through a recorded decision.

Each plan records ``council_fingerprint``: the sha256 of this tool, of the
harness code that designs and writes the experiment (the harness
fingerprint covers abaqus/ and corpus_features/) and of the row itself.

    python tools/make_council_deck.py --rows ROWS.jsonl [--rows MORE.jsonl] [--key K ...]
           [--out DIR] [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.deck import generate_deck                    # noqa: E402
from umat_oti.abaqus.experiment import plan_council               # noqa: E402
from umat_oti.store.transform_store import harness_fingerprint    # noqa: E402

WORKSPACE = Path(__file__).resolve().parents[2]
CACHE = WORKSPACE / "discovery_cache"
OUT = WORKSPACE / "corpus_campaign" / "council_plans"
CACHE_TOKEN = "$DISCOVERY_CACHE"


def row_key(row: dict) -> str:
    return str(row.get("harvest_key") or row.get("key") or "")


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def council_fingerprint(row: dict) -> dict:
    tool = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    row_sha = hashlib.sha256(_canonical(row)).hexdigest()
    harness = harness_fingerprint()
    combined = hashlib.sha256(f"{tool}:{harness}:{row_sha}".encode()).hexdigest()[:16]
    return {"council_fingerprint": combined, "tool_sha256": tool,
            "harness_fingerprint": harness, "row_sha256": row_sha}


def _portable(text: str, cache: Path) -> str:
    return text.replace(str(cache), CACHE_TOKEN)


def render(row: dict, cache: Path = CACHE) -> dict:
    """``{relative path: text}`` of everything one row produces."""
    source = cache / row["source_id"]
    repository = cache / str(row["source_id"]).split("/")[0]
    plan = plan_council(source, repository, row)
    record = plan.as_dict()
    record.update(council_fingerprint(row))
    record["row_key"] = row_key(row)
    files = {"council_plan.json": _portable(json.dumps(record, indent=1, sort_keys=True,
                                                       default=str), cache) + "\n"}
    if plan.found:
        for set_id, set_plan in plan.sets:
            files[f"council_{set_id}.inp"] = _portable(generate_deck(set_plan.manifest), cache)
    return files


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rows", required=True, type=Path, action="append",
                        help="harvest or D-21 rows (JSON lines); repeatable. For a key in "
                             "both, an eligible harvest row (author-published) wins")
    parser.add_argument("--key", action="append", default=[])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    by_key: dict = {}
    for rows_file in args.rows:
        for line in rows_file.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            held = by_key.get(row_key(row))
            if held is None or (row.get("eligible") and held.get("sets") is not None):
                by_key[row_key(row)] = row
    rows = list(by_key.values())
    if args.key:
        rows = [row for row in rows if row_key(row) in set(args.key)]
    differs = []
    for row in rows:
        key = row_key(row)
        files = render(row, args.cache)
        folder = args.out / key
        if args.check:
            on_disk = {p.name for p in folder.glob("*")} if folder.is_dir() else set()
            for name in sorted(set(files) | on_disk):
                path = folder / name
                if name not in files or not path.is_file() \
                        or path.read_text() != files[name]:
                    differs.append(f"{key}/{name}")
            continue
        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.glob("council_*.inp"):
            if stale.name not in files:
                stale.unlink()
        for name, text in files.items():
            (folder / name).write_text(text)
        plan = json.loads(files["council_plan.json"])
        print(f"{key} {row['source_id']}: "
              + ("ready, " + ", ".join(s["set_id"] for s in plan["sets"])
                 if not plan["refusal"] else f"{plan['refusal_code']}: {plan['refusal'][:120]}"))
    if args.check:
        if differs:
            print(f"{len(differs)} file(s) differ from a fresh regeneration -- those rows are "
                  "suspended (R6.1):\n  " + "\n  ".join(differs))
            return 1
        print(f"{len(rows)} row(s): every council plan and deck regenerates byte for byte")
    return 0


if __name__ == "__main__":
    sys.exit(main())
