#!/usr/bin/env python3
"""Run a UMAT through Abaqus from a verification manifest, and record what it did.

One command per build. Given the same manifest and the original and transformed
sources, it produces two histories that :mod:`umat_oti.abaqus.compare` can be
asked whether they agree.

It never decides that a job succeeded from its exit code. Abaqus 2021 on this
machine aborts during post-analysis wrap-up -- with no user subroutine at all --
after writing that the analysis completed, so the exit code is preserved as a
warning and the outcome is read from the records Abaqus wrote.

  tools/run_abaqus_verification.py --manifest m.json --source u.for --job orig
  tools/run_abaqus_verification.py --manifest m.json --source u_oti.for \
      --job tx --support-dir transform_out/

Nothing here knows the name of any model. Everything model-specific is in the
manifest, including where its material constants came from -- a manifest that
cannot say is refused rather than run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from umat_oti.abaqus.compare import compare_primal          # noqa: E402
from umat_oti.abaqus.deck import generate_deck, total_increments  # noqa: E402
from umat_oti.abaqus.manifest import (                      # noqa: E402
    LoadingSegment, VerificationManifest)
from umat_oti.abaqus.probe import (                          # noqa: E402
    converged_only, instrument, parse_probe)
from umat_oti.abaqus.runner import run_job                   # noqa: E402
from umat_oti.abaqus.support import (                        # noqa: E402
    build_support, compile_order, install_support)


def load_manifest(path: Path) -> tuple[VerificationManifest, tuple[str, ...]]:
    """A manifest from JSON, with its loading rebuilt as segments.

    Returns the manifest and the names of any keys it carried that the manifest
    does not declare. Those are dropped -- a manifest may hold diagnostics that
    are not inputs -- but they are handed back rather than discarded, because a
    misspelled field would otherwise take a real setting out of the run without
    anything saying so.
    """
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    declared = set(VerificationManifest.__dataclass_fields__)
    ignored = tuple(sorted(set(record) - declared - {"loading"}))
    for name in ignored:
        record.pop(name)
    loading = tuple(LoadingSegment(**dict(segment, strain=tuple(segment["strain"])))
                    for segment in record.pop("loading", []))
    for name in ("props", "initial_statev", "fd_steps", "bundle",
                 "outputs", "perturbation_components"):
        if name in record and record[name] is not None:
            record[name] = tuple(record[name])
    if record.get("orientation") is not None:
        record["orientation"] = tuple(record["orientation"])
    record["source"] = Path(record["source"])
    record["bundle"] = tuple(Path(p) for p in record.get("bundle", ()))
    return VerificationManifest(loading=loading, **record), ignored


def run_one(manifest: VerificationManifest, source: Path, job: str,
            work_dir: Path, support_dir: Path | None, timeout: int) -> dict:
    """One build, through the deck the manifest describes."""
    work_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"job": job, "source": str(source), "support": None}

    if support_dir is not None:
        # The transformed UMAT is last in the order because that is when it
        # compiles, but `abaqus user=` builds it itself. Building it here too
        # defines every routine in the file twice.
        build = build_support(compile_order(support_dir, exclude=source), work_dir)
        report["support"] = build.as_dict()
        if not build.ok:
            report["log"] = build.log[-4000:]
            return report
        install_support(build, work_dir)

    text, instrumented = instrument(Path(source).read_text(errors="replace"), job)
    probed = work_dir / f"{job}_probed.for"
    probed.write_text(text, encoding="utf-8")
    report["instrumented"] = instrumented
    if not instrumented:
        # Without the probe the job still runs, but its stress is only readable
        # from the ODB at single precision -- not enough for a difference.
        report["warning"] = ("the probe found no call site, so this run records "
                             "no full-precision history")

    result = run_job(work_dir, job, generate_deck(manifest), user_source=probed,
                     expected_increments=total_increments(manifest.loading),
                     timeout=timeout)
    records = converged_only(parse_probe(work_dir / f"{job}_probe.txt"))
    (work_dir / f"{job}_history.json").write_text(json.dumps(records), encoding="utf-8")
    report.update({
        "completed": result.status.analysis_completed,
        "reasons": list(result.status.reasons),
        "warnings": list(result.status.warnings),
        "increments": result.status.increments,
        "converged_records": len(records),
        "console": "" if result.status.analysis_completed else result.console[-2000:],
    })
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--job", required=True)
    parser.add_argument("--work-dir", type=Path,
                        help="default: a directory named for the job")
    parser.add_argument("--support-dir", type=Path,
                        help="the transform's output, holding compile_order.txt")
    parser.add_argument("--against", type=Path,
                        help="a history JSON to compare this run's against")
    parser.add_argument("--timeout", type=int, default=20000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    manifest, ignored = load_manifest(args.manifest)
    missing = manifest.missing_requirements()
    if missing:
        print(json.dumps({"job": args.job, "refused": list(missing)}, indent=1))
        return 2

    work = args.work_dir or Path(args.job)
    report = run_one(manifest, args.source, args.job, work,
                     args.support_dir, args.timeout)
    if ignored:
        report["manifest_keys_ignored"] = list(ignored)

    if args.against and report.get("completed"):
        reference = json.loads(Path(args.against).read_text(encoding="utf-8"))
        history = json.loads((work / f"{args.job}_history.json").read_text())
        comparison = compare_primal(reference, history,
                                    tolerance=manifest.primal_tolerance,
                                    near_zero_fraction=manifest.near_zero_fraction)
        report["primal"] = comparison.as_dict()

    print(json.dumps(report, indent=1))
    return 0 if report.get("completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
