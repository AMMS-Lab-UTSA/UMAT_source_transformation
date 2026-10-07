#!/usr/bin/env python3
"""Build the corpus manifest (JSON + flat CSV + JSON Schema).

Offline: reads the registry and discovery inventory in this repository, the
acquisition cache, the transform store and the verification pass results that
sit beside the repository. Nothing is fetched.

    PYTHONPATH=src python tools/build_corpus_manifest.py
    PYTHONPATH=src python tools/build_corpus_manifest.py \
        --merge results.jsonl            # merge feature results, then write
    PYTHONPATH=src python tools/build_corpus_manifest.py \
        --merge-ra ../corpus_campaign/batches/B1/noether/records.jsonl

Roots default to the workspace layout (siblings of the repository) and can be
overridden by flags or by UMAT_OTI_DISCOVERY_CACHE, UMAT_OTI_TRANSFORM_STORE
and UMAT_OTI_CORPUS_RUN.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from umat_oti.corpus_features.manifest import (  # noqa: E402
    ManifestInputs,
    build_manifest,
    expand_roots,
    merge_feature_results,
    ra_records_to_cells,
    write_outputs,
)


def _root(flag: str | None, env: str, default: Path) -> Path:
    return Path(flag or os.environ.get(env) or default).resolve()


#: Acquisition manifests whose licence source the rows quote: the two corpus
#: waves plus every discovery round tools/ingest_discovery_round.py added to
#: the inventory. The same list as tools/build_corpus_registry.py's
#: DEFAULT_ACQUISITION (a test holds them equal). Set here, not in the package
#: default, so the harness fingerprint does not move for a data path.
ACQUISITION_MANIFESTS = ("paper_results/corpus/companions.json",
                         "paper_results/corpus/companions_wave2.json",
                         "paper_results/discovery/family_round_2026-10-02/companions.json",
                         "paper_results/discovery/family_round_2026-10-06/companions.json")


def main(argv=None) -> int:
    ws = REPO.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--discovery-cache")
    ap.add_argument("--transform-store")
    ap.add_argument("--corpus-run")
    ap.add_argument("--families", help="reviewed family classification "
                    "(default corpus_run/material_families_checked_E.json)")
    ap.add_argument("--families-second-pass", help="second-pass classification "
                    "carried per row but not used for family figures "
                    "(default corpus_run/material_families_checked_v2.json)")
    ap.add_argument("--families-reporting", help="D-11 reporting classification "
                    "(default ../corpus_campaign/batches/B3/scout/"
                    "families_reviewed_B3.json; rows it lacks fall back to --families)")
    ap.add_argument("--earlier-registry-rev", default="f0f0731",
                    help="git revision whose registry eligible set the summary "
                         "compares against ('' to skip)")
    ap.add_argument("--current-pass", default="pass16")
    ap.add_argument("--later-pass", default="pass17")
    ap.add_argument("--out-dir", default=str(REPO / "paper_results/corpus/manifest"))
    ap.add_argument("--campaign", help="campaign root (evidence root `campaign`; "
                    "default ../corpus_campaign)")
    ap.add_argument("--ra-repo", help="Residual Assembler checkout (evidence root "
                    "`ra`; default ../final-ra)")
    ap.add_argument("--primal-ddsdde-cells", help="D-18: routine-level cells of the "
                    "primal+ddsdde run; primal_stress_state and ddsdde come only from "
                    "here (requires --feature-cells)")
    ap.add_argument("--feature-cells", help="D-18: routine-level cells of the "
                    "full-feature run; every feature except primal_stress_state and "
                    "ddsdde comes from here (requires --primal-ddsdde-cells)")
    ap.add_argument("--merge", action="append", default=[],
                    help="feature-results JSONL to merge (repeatable)")
    ap.add_argument("--merge-ra", action="append", default=[],
                    help="Residual Assembler records (ra-corpus-residual/1) to fold "
                         "and merge into the provider-build block (repeatable)")
    args = ap.parse_args(argv)
    if bool(args.primal_ddsdde_cells) != bool(args.feature_cells):
        ap.error("--primal-ddsdde-cells and --feature-cells go together (decision D-18)")

    corpus_run = _root(args.corpus_run, "UMAT_OTI_CORPUS_RUN", ws / "corpus_run")
    campaign = _root(args.campaign, "UMAT_OTI_CAMPAIGN", ws / "corpus_campaign")
    inp = ManifestInputs(
        repo=REPO,
        discovery_cache=_root(args.discovery_cache, "UMAT_OTI_DISCOVERY_CACHE",
                              ws / "discovery_cache"),
        transform_store=_root(args.transform_store, "UMAT_OTI_TRANSFORM_STORE",
                              ws / "transform_store"),
        corpus_run=corpus_run,
        families=Path(args.families or corpus_run / "material_families_checked_E.json"),
        families_second_pass=Path(args.families_second_pass or
                                  corpus_run / "material_families_checked_v2.json"),
        current_pass=args.current_pass,
        later_pass=args.later_pass or None,
        families_reporting=Path(args.families_reporting or campaign / "batches/B3/scout"
                                / "families_reviewed_B3.json"),
        earlier_registry_rev=args.earlier_registry_rev or None,
        campaign=campaign,
        ra_repo=_root(args.ra_repo, "UMAT_OTI_RA_REPO", ws / "final-ra"),
        companions=ACQUISITION_MANIFESTS,
    )
    for label, p in (("discovery cache", inp.discovery_cache),
                     ("corpus_run", inp.corpus_run), ("families", inp.families),
                     ("reporting families (D-11)", inp.families_reporting)):
        if not p.exists():
            print(f"error: {label} not found at {p}", file=sys.stderr)
            return 2
    t0 = time.time()
    manifest = build_manifest(inp)
    def show(path, report):
        print(f"merged {path}: " + json.dumps(
            {k: (len(v) if isinstance(v, list) else v) for k, v in report.items()}))
        for r in report["rejected"][:20]:
            print(f"  rejected line {r['line']} {r['source_id']} {r['feature']}: "
                  f"{'; '.join(r['problems'])}")

    if args.primal_ddsdde_cells:
        from umat_oti.corpus_features.manifest import merge_d18
        d18 = merge_d18(manifest, args.primal_ddsdde_cells, args.feature_cells)
        show(args.primal_ddsdde_cells, d18["primal_ddsdde_run"])
        show(args.feature_cells, d18["full_feature_run"])
        print(f"D-18 guard withheld {len(d18['guarded'])} verified primal/ddsdde cell(s)")
    for path in args.merge:
        show(path, merge_feature_results(manifest, path))
    for path in args.merge_ra:
        cells, ra_report = ra_records_to_cells(path, roots=expand_roots(manifest["roots"]))
        print(f"RA records {path}: {json.dumps({k: v for k, v in ra_report.items() if k != 'mismatches'})}")
        for what, n in ra_report["mismatches"].items():
            print(f"  contract mismatch x{n}: {what}")
        from umat_oti.corpus_features.manifest import to_locator
        label = to_locator(str(Path(path).resolve()), expand_roots(manifest["roots"]))
        report = merge_feature_results(manifest, cells, producer="noether/B1",
                                       label=label)
        manifest["merges"][-1]["ra_adapter"] = ra_report
        show(path, report)
    paths = write_outputs(manifest, Path(args.out_dir))
    s = manifest["summary"]
    print(f"rows: {len(manifest['rows'])} "
          f"(D1 acquired {s['denominators']['D1_acquired']['count']}, "
          f"D2 eligible {s['denominators']['D2_eligible']['count']}, "
          f"discovered not acquired "
          f"{s['denominators']['discovered_not_acquired']['count']})")
    for name, f in s["funnel"].items():
        print(f"  funnel {name}: " + ", ".join(f"{k}={v}" for k, v in f.items()))
    print(f"  ddsdde legacy gate (not counted): "
          f"{ {k: v for k, v in s['ddsdde_legacy_gate'].items() if k != 'what'} }")
    print(f"  lifted/provider builds (separate): "
          f"{ {k: v for k, v in s['features_other_builds'].items() if k != 'what'} }")
    print(f"data quality: {manifest['data_quality']['by_code']}")
    for k, p in paths.items():
        print(f"wrote {k}: {p}")
    print(f"seconds: {time.time() - t0:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
