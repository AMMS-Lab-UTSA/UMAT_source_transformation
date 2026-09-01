"""Verify the tangent of every discovered UMAT that can be verified, in one batch.

Compiling is not verification. This is the step that earns the word: for each
source it builds the transformed file AND the untransformed original, drives
both over the same path, checks their stresses agree, and then compares the
OTI tangent against a centred difference taken from the original -- ordinary
real arithmetic, no shared code path with the value under test. Each entry is
swept over a step ladder and adjudicated by how tightly the difference pins
the value down; where the ladder cannot decide, the entry is reported
unresolved rather than counted as agreement.

Three things are needed and only two of them can be read off a repository.

**The material vector is real.** Constants come from an ``.inp`` deck the
source's own author shipped, named per entry in ``material_provenance``. None
is invented; a source with no matching deck is not verified here, it is
reported as not verifiable and left alone.

**The loading path is a declared probe, and says so.** It is chosen here, not
read from the deck, because a deck describes a whole finite-element job and
not the strain history of one material point. That makes every result in this
report a statement about the transformer -- does the OTI tangent equal the
derivative of this source's own stress -- and not a statement about the
model's behaviour under its author's intended loading. The probe is recorded
beside every row so a reader can see exactly what was driven.

A disagreement here is a real finding either way: it is the transformed build
and the original disagreeing about a derivative of the same source.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_discovery_triage import without_machine_paths  # noqa: E402
from umat_oti.validation.tangent_validation import (  # noqa: E402
    sdvini_initial_state,
    STAGE_ORDER, TangentCase, verify_tangent,
)

DEFAULT_CACHE = Path(os.environ.get("UMAT_OTI_DISCOVERY_CACHE")
                     or REPO_ROOT.parent / "discovery_cache")
DEFAULT_OUT = REPO_ROOT / "paper_results" / "discovery"

#: The probe. A uniaxial ramp with a multiaxial step, small enough to stay in
#: the elastic range of most models and large enough that a centred difference
#: over it is not pure round-off. It is a probe and nothing more: it is not
#: read from any deck and is not any source's own loading history.
PROBE_INCREMENT = (1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0)
PROBE_INCREMENTS = 8
PROBE_PROVENANCE = (
    "declared probe, chosen by the verification harness; not read from a deck "
    "and not this source's own loading history"
)
#: Where the driver places the material point. Declared here for the same
#: reason the loading path is: it is a choice this harness makes, and a reader
#: has to be able to see it. The origin is not a neutral choice -- a model that
#: reads a fibre direction off the position divides by a zero radius there.
PROBE_COORDS = (1.0, 1.0, 1.0)

COLUMNS = (
    "name", "source", "repository", "kinematics", "nstatv", "ntens",
    "props_count", "material_provenance", "loading_probe",
    "furthest_stage", "primal_parity", "rows_total", "rows_agreeing",
    "rows_disagreeing", "rows_unresolved", "structural_zeros",
    "worst_relative_error", "driven_through", "reference_perturbation",
    "blocker",
)


def _cache_relative_source(entry: dict[str, Any]) -> str:
    """An entry's path within the discovery cache.

    A proposal names its source relative to the repository and names the
    repository as "owner/name"; the cache holds it under "owner__name". Putting
    the two together is what makes an entry identify one file rather than one
    filename.
    """
    repository = str(entry.get("repository") or "").replace("/", "__")
    source = str(entry.get("source") or "")
    return f"{repository}/{source}" if repository else source


def cases_from(triage_csv: Path, proposals_json: Path, cache: Path,
               limit: int = 0, kinematics: str = "") -> list[dict[str, Any]]:
    """One entry per transformed source that has a material vector."""
    payload = json.loads(proposals_json.read_text(encoding="utf-8"))
    entries = payload if isinstance(payload, list) else payload.get("entries", [])
    # Keyed by the path within the cache, not by the file's name. Twenty-one
    # transformed sources share a basename with another -- three separate
    # projects ship a "umat.f" -- so a basename key silently collapsed them and
    # handed whichever entry happened to be last to all of them. Eighteen cases
    # were driven with another project's material constants, and two of those
    # reached "verified": the tangent agreed with a derivative of a stress that
    # was never the one its author meant to compute.
    material: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry.get("status") != "proposed_needs_review":
            continue
        material[_cache_relative_source(entry)] = entry

    out: list[dict[str, Any]] = []
    with triage_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("stage") != "transformed":
                continue
            entry = material.get(row["source"])
            if not entry:
                continue
            if kinematics and row.get("kinematics") != kinematics:
                continue
            out.append({"row": row, "entry": entry, "path": cache / row["source"]})
            if limit and len(out) >= limit:
                break
    return out


def _source_text(path: Path) -> str:
    """The source, or empty when it cannot be read.

    An unreadable source is a real outcome for this harness -- the verify step
    reports it with the compiler's own words a moment later -- so reading it
    here to look for an SDVINI must not be what ends the run.
    """
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _case(item: dict[str, Any]) -> TangentCase:
    row, entry = item["row"], item["entry"]
    props = tuple(float(v) for v in (entry.get("material") or {}).get("props") or ())
    nstatv = int(row.get("nstatv_hint") or 0) or 1
    return TangentCase(
        name=Path(row["source"]).stem,
        source_path=item["path"],
        props=props,
        dstran_per_increment=PROBE_INCREMENT,
        n_increments=PROBE_INCREMENTS,
        coords=PROBE_COORDS,
        ntens=int(row.get("ntens") or 6),
        nstatv=nstatv,
        # Read from this source's own SDVINI, not chosen here. A growth model
        # whose multipliers start at zero divides by zero, which is why both
        # builds returned NaN rather than only the transformed one.
        initial_statev=sdvini_initial_state(_source_text(item["path"]), nstatv),
    )


def run(items: list[dict[str, Any]], work_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        row, entry = item["row"], item["entry"]
        name = Path(row["source"]).stem
        print(f"[{index}/{len(items)}] {row['source'][:70]}", flush=True)
        record = {key: "" for key in COLUMNS}
        record.update({
            "name": name,
            "source": row["source"],
            "repository": row.get("repository", ""),
            "kinematics": row.get("kinematics", ""),
            "nstatv": row.get("nstatv_hint", ""),
            "ntens": row.get("ntens", ""),
            "props_count": len((entry.get("material") or {}).get("props") or ()),
            "material_provenance": (entry.get("material") or {}).get("provenance", ""),
            "loading_probe": PROBE_PROVENANCE,
        })
        work = work_root / name
        try:
            result = verify_tangent(_case(item), work)
        except Exception as error:  # noqa: BLE001 - a crash is a finding
            record.update(furthest_stage="harness_error",
                          blocker=without_machine_paths(
                              f"{type(error).__name__}: {error}", work_root)[:220])
            record["traceback"] = traceback.format_exc()[-300:]
            rows.append(record)
            print(f"    harness_error  {type(error).__name__}", flush=True)
            continue
        summary = result.summary or {}
        total = int(summary.get("entries") or len(result.rows or ()))
        agreeing = int(summary.get("agreeing") or 0)
        unresolved = int(summary.get("unresolved") or 0)
        record.update({
            "furthest_stage": result.furthest_stage or "",
            "primal_parity": (result.stages.get("primal_parity") or {}).get(
                "worst_relative", "") if isinstance(result.stages, dict) else "",
            "rows_total": total,
            "rows_agreeing": agreeing,
            "rows_disagreeing": int(summary.get("disagreeing") or 0),
            "rows_unresolved": unresolved,
            "structural_zeros": int(summary.get("structural_zeros") or 0),
            "worst_relative_error": summary.get("worst_measured_relative_error", ""),
            # Which inputs were actually perturbed, carried per row rather than
            # left in a per-case summary. A finite-strain row and a
            # small-strain row establish derivatives with respect to different
            # things, and a reader scanning the table has to be able to see
            # which without going back to the module docstring.
            "driven_through": summary.get("driven_through", ""),
            "reference_perturbation": summary.get("reference_perturbation", ""),
            "blocker": (result.blocker or "")[:220],
        })
        # A blocker quotes whatever the compiler or the runtime said, and both
        # name the absolute path of every file they were handed. Those paths
        # are a property of the machine that ran this, not of the failure, and
        # they were reaching the published table.
        for key, value in record.items():
            if isinstance(value, str):
                record[key] = without_machine_paths(value, work_root)
        rows.append(record)
        print(f"    {result.furthest_stage or 'no stage'}  "
              f"rows {agreeing}/{total} agreeing, {unresolved} unresolved",
              flush=True)
    return rows


CAVEAT = (
    "The tangent under test comes from the transformed build; the reference "
    "comes from the untransformed original compiled on its own and replayed "
    "with a perturbed strain increment, so the two sides share no code path. "
    "Material constants are read from a deck the source's author shipped and "
    "are never invented. The LOADING PATH IS A DECLARED PROBE chosen by this "
    "harness -- it is not read from any deck and is not the source's own "
    "loading history -- so a verified row says the OTI tangent equals the "
    "derivative of this source's own stress along that probe, and says "
    "nothing about the model under its author's intended loading. Entries the "
    "step ladder cannot pin down are reported unresolved, never as agreement."
)


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reached = Counter(r["furthest_stage"] for r in rows if r["furthest_stage"])
    verified = [r for r in rows if r["furthest_stage"] == "tangent_verified"]
    return {
        "cases": len(rows),
        "reached_tangent_verified": len(verified),
        "by_furthest_stage": dict(reached.most_common()),
        "rows_total": sum(int(r["rows_total"] or 0) for r in rows),
        "rows_agreeing": sum(int(r["rows_agreeing"] or 0) for r in rows),
        "rows_disagreeing": sum(int(r.get("rows_disagreeing") or 0) for r in rows),
        "rows_unresolved": sum(int(r["rows_unresolved"] or 0) for r in rows),
        "structural_zeros": sum(int(r.get("structural_zeros") or 0) for r in rows),
        "loading_probe": {"dstran_per_increment": list(PROBE_INCREMENT),
                          "n_increments": PROBE_INCREMENTS,
                          "coords": list(PROBE_COORDS),
                          "provenance": PROBE_PROVENANCE},
        "caveat": CAVEAT,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triage", type=Path,
                        default=DEFAULT_OUT / "discovery_triage.csv")
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--kinematics", default="",
                        help="restrict to 'small strain' or 'finite'")
    args = parser.parse_args(argv)

    items = cases_from(args.triage, args.proposals, args.cache_dir,
                       args.limit, args.kinematics)
    print(f"  {len(items)} transformed sources carry a material vector")
    if not items:
        print("  nothing to verify")
        return 0
    args.work_dir.mkdir(parents=True, exist_ok=True)
    rows = run(items, args.work_dir)
    summary = summarise(rows)
    print(json.dumps({k: v for k, v in summary.items() if k != "caveat"}, indent=2))

    if args.results_dir:
        args.results_dir.mkdir(parents=True, exist_ok=True)
        csv_path = args.results_dir / "discovered_tangent_verification.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(COLUMNS))
            writer.writeheader()
            writer.writerows({k: r.get(k, "") for k in COLUMNS} for r in rows)
        (args.results_dir / "discovered_tangent_verification.json").write_text(
            json.dumps({"summary": summary, "cases": rows}, indent=2) + "\n",
            encoding="utf-8")
        print(f"  wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
