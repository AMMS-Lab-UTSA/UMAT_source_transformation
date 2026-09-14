#!/usr/bin/env python3
"""Re-emit every triage source and record exactly what came out.

Written for one question a store cannot answer: when transform code changes,
WHICH outputs changed and how. The store keys an entry by the transform
fingerprint, so a change makes every entry stale and the old bytes are no
longer addressable beside the new ones. This writes the emitted entry source
and the transform report to a plain directory named by the source identity, so
two snapshots taken either side of a change can be diffed line by line.

It reuses transform_all's own recipe -- the same ntens, the same contract, the
same seed "auto" -- by importing it, so a snapshot cannot drift from what the
batch does.

PYTHONHASHSEED is pinned by the caller, not here: several passes iterate sets
of names, and an unpinned hash seed reorders declarations between runs, which
would show up as a diff that no code change caused.

    PYTHONHASHSEED=0 python tools/reemit_snapshot.py --out <dir> --jobs 12
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from transform_all import (  # noqa: E402
    DEFAULT_CACHE, DEFAULT_TRIAGE, plan_work, read_work_list, select_work,
    transform_one, work_dir_for)


def transform_package_in_use() -> str:
    """Where the umat_oti this process will transform with actually lives.

    ``umat_oti`` is pip-installed editable against one checkout, so a bare
    import from a worktree resolves to the OTHER tree's source. A before/after
    snapshot taken that way measures a package neither side edited, and reports
    "nothing changed" for a change that is there -- or reports somebody else's
    merge as this change. The sys.path insert at the top of this file is what
    prevents it; this states the outcome so that every snapshot carries the
    answer rather than relying on the insert having worked.
    """
    import umat_oti
    return str(Path(umat_oti.__file__).resolve().parent)


def _assert_the_package_is_this_tree() -> str:
    found = transform_package_in_use()
    expected = str((REPO_ROOT / "src" / "umat_oti").resolve())
    if found != expected:
        raise SystemExit(
            f"refusing to snapshot: this process would transform with\n"
            f"  {found}\n"
            f"but this tool lives in\n"
            f"  {expected}\n"
            f"An editable install is shadowing the worktree. Run with "
            f"PYTHONPATH={REPO_ROOT / 'src'} or fix sys.path.")
    return found


class _NoStore:
    """A store that holds nothing, so every row is transformed afresh."""

    root = "none"
    fingerprint = "none"

    def get(self, *_args, **_kwargs):
        return None


def _snapshot(item, work_root: Path, out_root: Path, compile_generated: bool) -> dict:
    work = work_dir_for(work_root, item)
    result = transform_one(item, work)
    record = {
        "source_id": item.source_id,
        "ntens": item.ntens,
        "ok": bool(result.ok),
        "reason": result.reason,
        "compiled": (result.metadata or {}).get("compiled"),
        "compile_status": (result.metadata or {}).get("compile_status", ""),
        "blockers": (result.metadata or {}).get("blockers") or [],
        "entry_sha256": "",
        "entry_name": "",
    }
    safe = hashlib.sha256(item.source_id.encode()).hexdigest()[:16]
    destination = out_root / safe
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "identity.txt").write_text(item.source_id + "\n", encoding="utf-8")
    if result.ok and result.entry_source and Path(result.entry_source).is_file():
        text = Path(result.entry_source).read_bytes()
        record["entry_sha256"] = hashlib.sha256(text).hexdigest()
        record["entry_name"] = Path(result.entry_source).name
        (destination / "entry.f").write_bytes(text)
    report = (result.out_dir / "transform_report.json") if result.out_dir else None
    if report and report.is_file():
        shutil.copy2(report, destination / "transform_report.json")
    shutil.rmtree(work, ignore_errors=True)
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--work-dir", type=Path,
                        default=Path("/tmp/reemit_work"))
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", default="")
    parser.add_argument("--all", dest="every", action="store_true")
    parser.add_argument(
        "--proposals", type=Path,
        default=REPO_ROOT / "paper_results/discovery/proposed_corpus_entries.json")
    args = parser.parse_args(argv)

    package = _assert_the_package_is_this_tree()
    print(f"  transforming with {package}")
    rows = select_work(read_work_list(args.triage), every=args.every,
                       only=args.only, limit=args.limit)
    proposals: dict = {}
    if args.proposals and Path(args.proposals).is_file():
        payload = json.loads(Path(args.proposals).read_text(encoding="utf-8"))
        entries = payload.get("entries") if isinstance(payload, dict) else payload
        for entry in (entries.values() if isinstance(entries, dict) else entries or []):
            repository = str(entry.get("repository") or "").replace("/", "__")
            identity = f"{repository}/{entry.get('source')}" if repository else ""
            if identity:
                proposals[identity] = entry
    plan = plan_work(rows, args.cache_dir, _NoStore(), force=True,
                     proposals=proposals)
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    work_root = Path(args.work_dir)
    work_root.mkdir(parents=True, exist_ok=True)

    records = []
    total = len(plan.todo)
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(_snapshot, item, work_root, out_root, True): item
                   for item in plan.todo}
        for done, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                records.append(future.result())
            except Exception as exc:  # noqa: BLE001
                records.append({"source_id": item.source_id, "ok": False,
                                "reason": f"snapshot crashed: {exc}",
                                "entry_sha256": "", "blockers": []})
            if done % 25 == 0 or done == total:
                print(f"  [{done}/{total}]", flush=True)
    records.sort(key=lambda r: r["source_id"])
    summary = {
        "transform_package": package,
        "selected": plan.selected,
        "transformed": sum(1 for r in records if r["ok"]),
        "failed": sum(1 for r in records if not r["ok"]),
        "compiled": sum(1 for r in records if r.get("compiled")),
        "records": records,
    }
    (out_root / "snapshot.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{summary['transformed']} transformed, {summary['failed']} failed, "
          f"{summary['compiled']} compiled -> {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
