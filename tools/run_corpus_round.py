#!/usr/bin/env python
"""Run the external UMAT corpus through the full funnel. Emits the corpus report.

Two modes, and the difference is honest rather than cosmetic:

``--mode offline``
    Replays the pinned snapshots already on disk. No network. This is the
    reproducible mode and the one CI and the paper profile use.

``--mode live``
    Would re-resolve each repository's refs over the network and re-pin. Not
    implemented; the runner says so and exits non-zero rather than reporting an
    external blocker for something nobody has built.

Every candidate stays in the denominator with the furthest stage it reached and
the exact blocker that stopped it. A source whose licence forbids redistribution
is classified and counted, never executed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.corpus.funnel import (  # noqa: E402
    STAGES, Candidate, MaterialData, run_funnel,
)

MANIFEST = REPO_ROOT / "parameter_sensitivity" / "corpus_snapshot.json"
RESULTS = REPO_ROOT / "paper_results" / "corpus"


def snapshot_root(manifest: dict, explicit: Path | None = None) -> Path:
    """Where the pinned sources live, in order of precedence.

    The default is a sibling checkout, which is convenient here and is not
    something a reviewer's layout has to match. An explicit --snapshot-root or
    the environment variable overrides it, and a missing root produces the exact
    command to obtain one rather than a confusing per-file error.
    """
    if explicit is not None:
        return Path(explicit).resolve()
    override = os.environ.get(manifest["snapshot_root_environment_variable"])
    if override:
        return Path(override).resolve()
    return (REPO_ROOT / manifest["default_snapshot_root"]).resolve()


def repository_base(root: Path, repository: dict) -> Path:
    """Locate a repository under either a submodule tree or an acquisition cache.

    Three layouts are legitimate snapshot roots and all are tried, so a reviewer
    is never required to reshape a tree to match one of them:

    ``permissive/<id>``          the Residual_Assembler submodule tree
    ``<id>``                     scripts/bootstrap_corpus.sh
    ``<id>/<sha12>``             the tools/acquire_corpus.py cache
    """
    for candidate in (root / repository["path"],
                      root / repository["id"],
                      root / repository["id"] / repository["commit_sha"][:12]):
        if candidate.is_dir():
            return candidate
    return root / repository["path"]


def build_candidate(entry: dict, repositories: dict, root: Path) -> Candidate | dict:
    repository = repositories[entry["repository"]]
    base = repository_base(root, repository)
    source = base / entry["source"]
    if repository.get("metadata_only"):
        return {"id": entry["id"], "bucket": "metadata_only",
                "reason": f"{repository['license_spdx']} does not permit "
                          "redistribution; recorded but never fetched or executed"}
    if not source.is_file():
        return {"id": entry["id"], "bucket": "snapshot_absent",
                "reason": (f"{entry['source']} is not present under {base}. The "
                           "pinned submodule is not checked out; run "
                           "scripts/init_permissive_sources.sh --all-permissive "
                           "in the Residual_Assembler checkout.")}
    material_spec = entry.get("material")
    material = None
    if material_spec:
        material = MaterialData(
            props=tuple(float(v) for v in material_spec["props"]),
            dstran_per_increment=tuple(material_spec["dstran_per_increment"]),
            n_increments=int(material_spec["n_increments"]),
            provenance=material_spec["provenance"],
            parameters=tuple((p["name"], int(p["props_index"]))
                             for p in material_spec.get("parameters", [])))
    return Candidate(
        id=entry["id"], source_path=source,
        repository_url=repository["url"], commit_sha=repository["commit_sha"],
        license_spdx=repository["license_spdx"],
        license_source=repository["license_source"],
        ntens=int(entry["ntens"]), nstatv=int(entry["nstatv"]),
        ndi=int(entry.get("ndi", 3)), nshr=int(entry.get("nshr", 1)),
        dependency_roots=tuple(base / r for r in entry.get("dependency_roots", [])),
        material=material,
        display_path=f"{repository['path']}/{entry['source']}",
        notes=entry.get("constitutive_class", ""),
        retrieved_at=f"pinned at {repository['commit_sha'][:12]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--candidate", action="append", dest="candidates")
    parser.add_argument("--work-dir", type=Path,
                        default=REPO_ROOT / "build" / "corpus")
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument(
        "--snapshot-root", type=Path, default=None,
        help=("directory holding the pinned sources: either a bootstrap "
              "submodule tree or a cache written by tools/acquire_corpus.py. "
              "Overrides the sibling-checkout default."))
    args = parser.parse_args(argv)

    if args.mode == "live":
        print("live corpus acquisition is not implemented. The pinned snapshots in "
              f"{MANIFEST.relative_to(REPO_ROOT)} are replayed by --mode offline; "
              "re-resolving refs over the network and re-pinning them has not been "
              "built. This is an unimplemented capability, not an external blocker.",
              file=sys.stderr)
        return 2

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    repositories = {r["id"]: r for r in manifest["repositories"]}
    root = snapshot_root(manifest, args.snapshot_root)
    if not root.is_dir():
        print(f"snapshot root {root} does not exist. Obtain the pinned sources "
              "with either:\n"
              "  scripts/bootstrap_corpus.sh            (clones both repositories "
              "at their pinned commits)\n"
              "  tools/acquire_corpus.py --allow-network --cache-root DIR\n"
              "then re-run with --snapshot-root DIR.", file=sys.stderr)
        return 2
    work = args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    results = args.results_dir
    if results is None:
        results = RESULTS if not args.candidates else work / "results"
    if results != RESULTS:
        print(f"partial or redirected round: writing to {results}", flush=True)

    wanted = set(args.candidates or [])
    records = []
    for entry in manifest["candidates"]:
        if wanted and entry["id"] not in wanted:
            continue
        print(f"[corpus] {entry['id']}", flush=True)
        candidate = build_candidate(entry, repositories, root)
        if isinstance(candidate, dict):
            candidate.update({
                "repository": entry["repository"],
                "constitutive_class": entry.get("constitutive_class"),
                "furthest_stage": ("license_classified"
                                   if candidate["bucket"] == "metadata_only"
                                   else "discovered"),
                "blocker": candidate.pop("reason"),
            })
            records.append(candidate)
            continue
        record = run_funnel(candidate, work / entry["id"], repo_root=REPO_ROOT,
                            snapshot_root=root)
        record["repository"] = entry["repository"]
        record["constitutive_class"] = entry.get("constitutive_class")
        if entry.get("material") is None and entry.get("material_blocker"):
            record["material_blocker"] = entry["material_blocker"]
        records.append(record)

    reached = {stage: 0 for stage in STAGES}
    for record in records:
        furthest = record.get("furthest_stage")
        if furthest in STAGES:
            for stage in STAGES[:STAGES.index(furthest) + 1]:
                reached[stage] += 1

    taxonomy: dict[str, list[str]] = {}
    for record in records:
        if record.get("furthest_stage") == "derivatives_verified":
            continue
        blocker = record.get("blocker") or "unknown"
        key = blocker.split(":", 1)[0].strip() or "unknown"
        taxonomy.setdefault(key, []).append(record["id"])

    payload = {
        "schema": "umat-oti-corpus-round/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "snapshot_manifest": str(MANIFEST.relative_to(REPO_ROOT)),
        "snapshot_root": {
            "declared_default": manifest["default_snapshot_root"],
            "environment_variable": manifest["snapshot_root_environment_variable"],
            "overridden": bool(os.environ.get(
                manifest["snapshot_root_environment_variable"])),
            "note": ("the absolute location is deliberately not recorded: it is "
                     "specific to the machine that ran the round and is not an "
                     "input any reader needs"),
        },
        "repositories": manifest["repositories"],
        "funnel": {
            "candidates": len(records),
            **{f"reached_{stage}": count for stage, count in reached.items()},
        },
        "failure_taxonomy": {k: sorted(v) for k, v in sorted(taxonomy.items())},
        "candidates": records,
    }
    results.mkdir(parents=True, exist_ok=True)
    (results / "corpus_round.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    import csv as _csv
    with (results / "corpus_funnel.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = _csv.writer(fh, lineterminator="\n")
        writer.writerow(["candidate", "repository", "commit_sha", "license",
                         "constitutive_class", "multi_file", "closure_size",
                         "furthest_stage", "primal_parity", "substantive_rows",
                         "worst_substantive_relative_error", "blocker"])
        for record in records:
            graph = record.get("dependency_graph") or {}
            comparison = record.get("comparison") or {}
            parity = (record.get("stages") or {}).get("primal_parity", {})
            writer.writerow([
                record["id"], record.get("repository", ""),
                (record.get("commit_sha") or "")[:12],
                record.get("license_spdx", ""),
                record.get("constitutive_class", ""),
                graph.get("multi_file", ""), len(graph.get("resolved", {})) or "",
                record.get("furthest_stage", ""),
                parity.get("worst_relative_difference", ""),
                comparison.get("substantive_rows", ""),
                comparison.get("worst_substantive_relative_error", ""),
                (record.get("blocker") or "")[:200],
            ])

    print("\n" + json.dumps(payload["funnel"], indent=2))
    print("\nfailure taxonomy:")
    for key, names in payload["failure_taxonomy"].items():
        print(f"  {key}: {len(names)} -> {', '.join(names)}")
    verified = reached["derivatives_verified"]
    print(f"\n{verified} of {len(records)} candidates numerically verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
