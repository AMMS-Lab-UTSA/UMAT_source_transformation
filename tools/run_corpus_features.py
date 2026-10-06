#!/usr/bin/env python3
"""Routine-level feature verification of corpus UMATs (no Abaqus).

One JSONL record per (UMAT, feature, loading path). Features:
primal_stress_state, ddsdde, internal_jacobian, stress_param_sens_local,
state_param_sens_local, stress_param_sens_total, state_param_sens_total,
stress_state_sens_local, state_state_sens_local. Definitions and the verdict
rule are in ``umat_oti.corpus_features.harness`` and
``corpus_campaign/batches/B1/gauss/DESIGN.md``.

    PYTHONPATH=src python tools/run_corpus_features.py --key c7bf17b21519e33da0b7bbb1 \\
        --out $UMAT_OTI_WORKSPACE/corpus_campaign/batches/B1/gauss/evidence
    PYTHONPATH=src python tools/run_corpus_features.py --fully-verified --limit 5 ...

Each run REPLACES ``<out>/corpus_features.jsonl`` and ``manifest_cells.jsonl``
(written to a temporary file, then renamed) and writes ``run_id.json`` (run id,
command, start/end, git HEAD, live transform fingerprint) and ``roots.json``
(the root map of every ``<root>:<relative path>`` evidence locator). Every
record carries the ``run_id``.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.corpus_features import fd  # noqa: E402
from umat_oti.corpus_features.harness import (  # noqa: E402
    FEATURES, REGISTRY, locator, resolve_entry, roots_map, run_entry)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--key", action="append", default=[], help="registry key (repeatable)")
    parser.add_argument("--fully-verified", action="store_true",
                        help="every registry record with terminal_state == fully_verified")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--features", default=",".join(FEATURES))
    parser.add_argument("--out", required=True, help="output directory (durable, not /tmp)")
    parser.add_argument("--work", default="", help="work directory (default: <out>/work)")
    parser.add_argument("--rtol", type=float, default=fd.DEFAULT_RTOL)
    parser.add_argument("--verification-records", type=Path, default=None,
                        help="store_verification.jsonl whose rows supply each key's "
                             "experiment manifest (default: pass16's). Needed for a "
                             "store built at another transform fingerprint, whose keys "
                             "only that pass knows")
    parser.add_argument("--registry", type=Path, default=None,
                        help="corpus registry that maps keys to sources (default: the "
                             "committed paper_results/corpus/corpus_registry.json)")
    parser.add_argument("--council-plans", type=Path, default=None,
                        help="the council plans folder (<key>/council_plan.json) a "
                             "council key <registry key>#<set> is resolved from (default: "
                             "the harness's corpus_campaign/council_plans); give the folder "
                             "written at the harness fingerprint being run")
    parser.add_argument("--supply-utilities", action="store_true",
                        help="OPT-IN workaround: append abaqus_utility_definitions (ROTSIG, ...) "
                             "to the LIFT input; recorded in build.workarounds")
    parser.add_argument("--ntens", type=int, default=0,
                        help="override NTENS (ndi/nshr from the Abaqus layout); recorded")
    parser.add_argument("--evaluate-despite-hidden-state", action="store_true",
                        help="DIAGNOSTIC: evaluate a source whose hidden-state gate tripped anyway; "
                             "its records stay not_attempted and carry "
                             "status_before_hidden_state_gate")
    args = parser.parse_args(argv)
    # The harness reads both through module constants; overriding them here
    # (tools/ is outside the transform and harness fingerprints) points a run at
    # another pass without changing what the harness IS.
    import umat_oti.corpus_features.harness as _harness
    if args.verification_records is not None:
        _harness.PASS16 = args.verification_records.resolve()
    if args.registry is not None:
        _harness.REGISTRY = args.registry.resolve()
    if args.council_plans is not None:
        _harness.COUNCIL_PLANS = args.council_plans.resolve()

    keys = list(args.key)
    if args.fully_verified:
        registry = json.loads(REGISTRY.read_text())
        keys += [r["key"] for r in registry["records"] if r["terminal_state"] == "fully_verified"]
    if args.limit:
        keys = keys[:args.limit]
    if not keys:
        parser.error("no keys selected")
    # Absolute, always: the drivers are compiled and run from their own work
    # directories, and a relative --out made every original "not build" (the
    # paths it handed gfortran were relative to the wrong directory) -- a silent
    # all-not_attempted result that read like a property of the source.
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(args.work).resolve() if args.work else out / "work"
    features = [f for f in args.features.split(",") if f]
    target = out / "corpus_features.jsonl"
    run_id = datetime.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                          text=True).stdout.strip()
    try:
        from umat_oti.store.transform_store import transform_fingerprint
        fingerprint = transform_fingerprint()
    except Exception as error:                                       # noqa: BLE001
        fingerprint = f"unavailable: {error}"
    run_info = {"run_id": run_id, "argv": sys.argv, "keys": keys, "features": features,
                "started": datetime.datetime.now().isoformat(timespec="seconds"),
                "git_head": head, "transform_fingerprint_live": fingerprint,
                "note": "git_head does not include uncommitted edits; the live fingerprint does"}
    (out / "roots.json").write_text(json.dumps(roots_map(), indent=1))
    written = 0
    partial = target.with_name(target.name + f".{run_id}.partial")
    with partial.open("w", encoding="utf-8") as handle:
        for key in keys:
            started = time.time()
            try:
                entry = resolve_entry(key)
            except (KeyError, LookupError) as error:
                record = {"schema": "umat-oti/corpus-feature/2", "key": key, "run_id": run_id,
                          "feature": "*", "status": "blocked", "reason": str(error)}
                handle.write(json.dumps(record) + "\n")
                print(f"{key}: blocked -- {error}")
                continue
            if args.ntens:
                layout = {6: (3, 3), 4: (3, 1), 3: (2, 1)}[args.ntens]
                entry.provenance["ntens_override"] = (f"NTENS {entry.ntens} -> {args.ntens} "
                                                      "(command line)")
                entry.ntens, (entry.ndi, entry.nshr) = args.ntens, layout
            records = run_entry(entry, work, features=features, rtol=args.rtol,
                                supply_utilities=args.supply_utilities,
                                evaluate_despite_trips=args.evaluate_despite_hidden_state)
            for record in records:
                record["run_id"] = run_id
                handle.write(json.dumps(record, default=float) + "\n")
                written += 1
            handle.flush()
            tally = {}
            for r in records:
                tally.setdefault(r["feature"], []).append(r["status"])
            summary = "; ".join(f"{f}: " + ",".join(f"{s}x{v.count(s)}" for s in sorted(set(v)))
                                for f, v in tally.items())
            print(f"{key} {entry.source_id} ({time.time() - started:.1f}s): {summary}")
    os.replace(partial, target)
    run_info["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    run_info["records"] = written
    (out / "run_id.json").write_text(json.dumps(run_info, indent=1))
    print(f"{written} records written to {target} (run {run_id}, previous contents replaced)")
    # One cell per (source_id, feature), checked against the manifest's merge
    # contract when that module is importable.
    from umat_oti.corpus_features.cells import fold
    records = [json.loads(line) for line in target.read_text().splitlines() if line.strip()]
    cells = fold([r for r in records if r.get("feature") != "*"], evidence=locator(target))
    problems = []
    try:
        from umat_oti.corpus_features.manifest import validate_cell
        for cell in cells:
            issues = validate_cell(cell["feature"], cell)
            if issues:
                problems.append({"source_id": cell["source_id"], "feature": cell["feature"],
                                 "problems": issues})
    except ImportError:
        problems.append("manifest.validate_cell not importable; cells unchecked")
    for cell in cells:
        cell["run_id"] = run_id
    tmp = out / f"manifest_cells.jsonl.{run_id}.partial"
    tmp.write_text("".join(json.dumps(c) + "\n" for c in cells))
    os.replace(tmp, out / "manifest_cells.jsonl")
    print(f"{len(cells)} manifest cells -> {out / 'manifest_cells.jsonl'}; "
          f"merge-contract problems: {problems or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
