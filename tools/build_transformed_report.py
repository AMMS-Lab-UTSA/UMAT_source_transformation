"""Report on every discovered UMAT the transformer has put through, and what that means.

The triage says what happened to each source; the discovery manifests say
where each source came from and under what licence; the corpus-entry proposals
say whether a material vector was ever recovered for it. This joins the three
so that one row answers the whole question about one source, and so that the
answer carries its own limits.

Two limits are stated in every artefact this writes, because the count is
otherwise read as something it is not.

**"Transformed" means the generated Fortran compiles.** It is the strongest
claim available for these sources and it is not a claim about a derivative.
A UMAT is verified when its OTI tangent is compared against an independent
reference over a loading path, and that needs three things together: the
source must build, a material vector must be known, and a loading history must
be accepted by a reviewer. Compiling is one of the three.

**A source with no provenance row is reported as such.** The cache was
assembled by several discovery runs and a manifest describes one run, so a
source may be cached without an available manifest row. That is recorded as
"not in an available manifest" rather than filled in, because a licence
nobody read is not a licence that cleared.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRIAGE = REPO_ROOT / "paper_results" / "discovery" / "discovery_triage.csv"
DEFAULT_OUT = REPO_ROOT / "paper_results" / "discovery"

COLUMNS = (
    "source", "repository", "license_spdx", "commit", "found_by",
    "form", "kinematics", "lines", "bytes", "helper_routines",
    "ntens", "nstatv_hint", "declared_unsupported",
    "original_compiles", "compiled", "material_vector", "material_provenance",
    "verifiable_today", "seconds",
)


def provenance_index(manifest_paths: list[Path]) -> dict[str, dict[str, str]]:
    """Every admitted source's origin, keyed by its path inside the cache.

    A later manifest does not overwrite an earlier one: the first run that
    admitted a source is the one that read its licence and pinned its commit,
    and a re-run that skipped it as a duplicate has nothing to add.
    """
    index: dict[str, dict[str, str]] = {}
    for path in manifest_paths:
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    key = (row.get("cached_as") or "").strip()
                    if not key or key in index:
                        continue
                    if row.get("outcome") != "candidate":
                        continue
                    index[key] = {
                        "repository": row.get("repository", ""),
                        "license_spdx": row.get("license_spdx", ""),
                        "commit": (row.get("commit") or "")[:12],
                        "found_by": row.get("found_by", ""),
                    }
        except (OSError, csv.Error):
            continue
    return index


def material_index(proposals_path: Path | None) -> dict[str, dict[str, str]]:
    """Sources for which a material vector was read out of a shipped deck."""
    if not proposals_path or not proposals_path.is_file():
        return {}
    try:
        payload = json.loads(proposals_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = payload if isinstance(payload, list) else payload.get("entries", [])
    index: dict[str, dict[str, str]] = {}
    for entry in entries:
        if entry.get("status") != "proposed_needs_review":
            continue
        material = entry.get("material") or {}
        index[_cache_relative_source(entry)] = {
            "count": str(len(material.get("props") or [])),
            "provenance": str(material.get("provenance") or ""),
        }
    return index


def _cache_relative_source(entry: dict[str, Any]) -> str:
    """An entry's path within the discovery cache.

    Not its file name. Twenty-one transformed sources share a basename with
    another -- three separate projects ship a "umat.f" -- so a name key
    collapses them and reports one entry's material provenance against every
    source of that name. The same key was wrong in the verification harness and
    drove eighteen cases with the wrong project's constants; here it would
    print a deck from the wrong repository beside a correct result.
    """
    repository = str(entry.get("repository") or "").replace("/", "__")
    source = str(entry.get("source") or "")
    return f"{repository}/{source}" if repository else source


def rows_for(triage_path: Path, provenance: dict[str, dict[str, str]],
             materials: dict[str, dict[str, str]],
             stage: str = "transformed") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with triage_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if stage and row.get("stage") != stage:
                continue
            source = row.get("source", "")
            origin = provenance.get(source)
            material = materials.get(source, {})
            record = {name: row.get(name, "") for name in COLUMNS if name in row}
            record["source"] = source
            if origin:
                record.update(origin)
            else:
                record.update({"repository": row.get("repository", ""),
                               "license_spdx": "not in an available manifest",
                               "commit": "", "found_by": ""})
            record["material_vector"] = material.get("count", "")
            record["material_provenance"] = material.get("provenance", "")
            # Compiling is one of three things verification needs. This column
            # says which of them hold, never that the derivative is right.
            record["verifiable_today"] = (
                "needs an accepted loading path"
                if record["compiled"] == "yes" and material else
                "no material vector" if record["compiled"] == "yes" else "does not compile")
            out.append({name: record.get(name, "") for name in COLUMNS})
    return out


CAVEAT = (
    "Every row is a source whose generated Fortran COMPILES. That is the "
    "strongest claim available here and it is not a claim about a derivative: "
    "a UMAT is verified when its OTI tangent is compared against an "
    "independent reference over a loading path, which needs the source to "
    "build, a material vector to be known, and a loading history to be "
    "accepted by a reviewer. The verifiable_today column says which of those "
    "hold. No derivative in this report has been executed or compared. A "
    "licence recorded as 'not in an available manifest' was not read by any "
    "manifest reachable here and must not be treated as cleared."
)


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "transformed_sources": len(rows),
        "repositories": len({r["repository"] for r in rows if r["repository"]}),
        "by_licence": dict(Counter(r["license_spdx"] or "unrecorded" for r in rows).most_common()),
        "by_form": dict(Counter(r["form"] or "unknown" for r in rows).most_common()),
        "by_kinematics": dict(Counter(r["kinematics"] or "unknown" for r in rows).most_common()),
        "with_a_material_vector": sum(1 for r in rows if r["material_vector"]),
        "verifiable_today": dict(Counter(r["verifiable_today"] for r in rows).most_common()),
        "total_lines": sum(int(r["lines"] or 0) for r in rows),
        "found_by": dict(Counter(r["found_by"] or "unrecorded" for r in rows).most_common()),
        "caveat": CAVEAT,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE)
    parser.add_argument("--manifest", type=Path, action="append", default=None,
                        help="a discovered_sources.csv; repeatable. Earlier "
                             "runs win, because the run that admitted a source "
                             "is the one that read its licence.")
    parser.add_argument("--proposals", type=Path, default=None,
                        help="proposed_corpus_entries.json, for material vectors")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--stage", default="transformed")
    args = parser.parse_args(argv)

    manifests = args.manifest or [DEFAULT_OUT / "discovered_sources.csv"]
    provenance = provenance_index([Path(m) for m in manifests])
    materials = material_index(args.proposals)
    rows = rows_for(args.triage, provenance, materials, args.stage)
    summary = summarise(rows)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "transformed_sources.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    json_path = args.out_dir / "transformed_sources.json"
    json_path.write_text(json.dumps({"summary": summary, "sources": rows}, indent=2) + "\n",
                         encoding="utf-8")

    print(json.dumps({k: v for k, v in summary.items() if k != "caveat"}, indent=2))
    print(f"  provenance rows available: {len(provenance)}")
    print(f"  wrote {csv_path}")
    print(f"  wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
