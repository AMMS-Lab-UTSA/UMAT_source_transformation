#!/usr/bin/env python
"""Reconcile every UMAT appearance to one canonical implementation identity.

The same Fortran is reachable from several places at once: the curated
parameter-sensitivity set, the UMATs/ICP archive, the higher-order fixtures, the
archived Abaqus campaign, and the pinned external corpus. Every one of the twelve
ICP UMATs is normalised-identical to a file in the upstream jgomezc1/ABAQUS-US
snapshot, differing only in line endings, so counting appearances would report
one implementation validated several ways as several implementations.

This walks all of them, computes a canonical identity from the code, and reports
counts that are about implementations rather than appearances.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.corpus.identity import (  # noqa: E402
    IdentityRegistry, SourceIdentity, closure_identity, content_identity,
)
from umat_oti.transform.dependency_resolution import (  # noqa: E402
    DependencyResolutionError, resolve_closure,
)

RESULTS = REPO_ROOT / "paper_results"
MODELS = REPO_ROOT / "parameter_sensitivity" / "models"
ARCHIVE = REPO_ROOT / "UMATs"
SNAPSHOT = REPO_ROOT / "parameter_sensitivity" / "corpus_snapshot.json"
OUT = RESULTS / "generality"

FORTRAN = (".for", ".f", ".f90", ".f77")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _identity_for(source: Path, roots):
    """Closure identity when the source needs siblings, content identity otherwise."""
    try:
        graph = resolve_closure(source, entry="UMAT", roots=roots)
    except DependencyResolutionError:
        return content_identity(source), None
    if graph.missing or not graph.is_multi_file:
        return content_identity(source), graph
    return closure_identity(graph), graph


def build() -> tuple[IdentityRegistry, int]:
    registry = IdentityRegistry()
    raw = 0

    sweep = _load(RESULTS / "parameter_sensitivity" / "parameter_sensitivity_round.json")
    sweep_status = {m["model"]: m["stages"].get("derivatives_verified", {}).get("status")
                    for m in sweep.get("models", [])}
    classification = _load(
        REPO_ROOT / "parameter_sensitivity" / "benchmark_classification.json"
    ).get("models", {})

    for directory in sorted(MODELS.iterdir()):
        source = directory / "umat.for"
        if not source.is_file():
            continue
        raw += 1
        identity, _ = _identity_for(source, [directory])
        status = sweep_status.get(directory.name)
        registry.record(
            identity, origin="parameter_sensitivity benchmark set",
            label=directory.name,
            validation_event="TABLE-6 parameter sensitivity" if status else None,
            constitutive_model=(classification.get(directory.name, {})
                                .get("constitutive_class")),
            source_structure="single_file",
            execution_environment="local gfortran material-point driver",
            verified=(status == "succeeded") if status else None)

    for source in sorted(p for p in ARCHIVE.rglob("*") if p.suffix.lower() in FORTRAN):
        text = source.read_text(encoding="utf-8", errors="replace")
        if "SUBROUTINE UMAT" not in text.upper():
            continue
        raw += 1
        identity, graph = _identity_for(source, [source.parent])
        registry.record(
            identity, origin="UMATs archive (in-repository copy)",
            label=source.stem,
            source_structure=("dependency_closure"
                              if graph and graph.is_multi_file else "single_file"))

    jac = _load(RESULTS / "internal_jacobians" / "internal_jacobian_round.json")
    higher = {d.name for d in (RESULTS / "higher_order_convergence").glob("*/")
              if (d / "convergence_evidence.json").is_file()}

    snapshot = _load(SNAPSHOT)
    repositories = {r["id"]: r for r in snapshot.get("repositories", [])}
    root = (REPO_ROOT / snapshot.get("default_snapshot_root", "")).resolve() \
        if snapshot else None
    corpus = _load(RESULTS / "corpus" / "corpus_round.json")
    corpus_status = {c["id"]: c.get("furthest_stage") for c in corpus.get("candidates", [])}

    for entry in snapshot.get("candidates", []):
        repository = repositories.get(entry["repository"], {})
        if repository.get("metadata_only"):
            continue
        source = root / repository["path"] / entry["source"] if root else None
        if not source or not source.is_file():
            continue
        raw += 1
        roots = [root / repository["path"] / r for r in entry.get("dependency_roots", [])]
        identity, graph = _identity_for(source, roots)
        registry.record(
            identity,
            origin=f"external corpus: {repository['url']}@{repository['commit_sha'][:12]}",
            label=entry["id"],
            validation_event="CORPUS offline round",
            constitutive_model=entry.get("constitutive_class"),
            source_structure=("dependency_closure"
                              if graph and graph.is_multi_file else "single_file"),
            execution_environment="local gfortran material-point driver",
            upstream_repository=repository["url"],
            verified=corpus_status.get(entry["id"]) == "derivatives_verified")

    # The round records its own canonical identity, so nothing is re-derived
    # from a path here. That matters: the executed source for a multi-file
    # candidate is a generated closure file, and hashing that instead of the
    # upstream original would invent a new implementation on every run.
    for record in jac.get("records", []):
        identity_payload = record.get("identity")
        if not identity_payload:
            continue
        identity = SourceIdentity(
            canonical_source_id=identity_payload["canonical_source_id"],
            kind=identity_payload["identity_kind"],
            entry_routine=identity_payload["entry_routine"],
            content_sha256=identity_payload["normalised_content_sha256"],
            code_only_sha256=identity_payload["code_only_sha256"],
            closure_size=identity_payload.get("closure_size", 1))
        registry.record(
            identity, origin=f"internal-Jacobian round ({record.get('origin','')})",
            label=record["id"],
            validation_event="TABLE-3 internal Jacobian",
            execution_environment="local gfortran material-point driver",
            verified=record.get("bucket") == "verified")

    for name in sorted(higher):
        evidence = _load(RESULTS / "higher_order_convergence" / name / "convergence_evidence.json")
        source_path = (evidence.get("source") or {}).get("path")
        if not source_path:
            continue
        source = REPO_ROOT / source_path
        if not source.is_file():
            continue
        identity, _ = _identity_for(source, [source.parent])
        registry.record(
            identity, origin="higher-order convergence study", label=name,
            validation_event="TABLE-4 higher order",
            execution_environment="local gfortran material-point driver")

    for table2 in sorted(RESULTS.glob("arc_*/table2_abaqus_paired.json")):
        payload = _load(table2)
        for row in payload.get("rows", []):
            case = row.get("case_name")
            matches = [p for p in ARCHIVE.rglob(f"{case}.*")
                       if p.suffix.lower() in FORTRAN]
            if not matches:
                continue
            identity, _ = _identity_for(matches[0], [matches[0].parent])
            registry.record(
                identity, origin="archived paired Abaqus campaign", label=case,
                validation_event="TABLE-2 paired Abaqus",
                execution_environment=(
                    f"Slurm job {row.get('slurm_job_id')} on {row.get('hostname')} "
                    f"with {row.get('compiler')}; Abaqus version not recorded"),
                verified=row.get("status") == "passed")
    return registry, raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args(argv)

    registry, raw = build()
    payload = {
        "schema": "umat-oti-source-identity/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": (
            "Identity is computed from normalised source content (single file) or "
            "from the resolved routine closure (multi-file). Paths are excluded: "
            "the same closure lives at different relative paths in different "
            "origins, and hashing layout would make identical code hash "
            "differently."),
        **registry.as_dict(raw_discovered=raw),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "source_identity.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with (args.out_dir / "source_identity.csv").open("w", newline="",
                                                     encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["canonical_source_id", "identity_kind", "labels",
                         "origins", "validation_events", "verified_by",
                         "constitutive_models", "closure_size"])
        for source_id, entry in sorted(registry.by_id.items()):
            writer.writerow([
                source_id, entry["identity_kind"], ";".join(entry["labels"]),
                ";".join(entry["origins"]),
                ";".join(sorted({e["event"] for e in entry["validation_events"]})),
                ";".join(entry["verified_by"]),
                ";".join(entry["constitutive_models"]), entry["closure_size"],
            ])

    print(json.dumps(payload["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
