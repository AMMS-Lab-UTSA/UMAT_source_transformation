"""``umat-oti-pipeline`` -- run the canonical stage graph over one contract.

    umat-oti-pipeline --config examples/code_imp_actual_higher_order.json \\
                      --work-dir umat_oti_workspace/code_imp --compile

Every run writes ``run_manifest.json`` into the work directory. Re-running the
same contract reuses the stages whose inputs and artifacts are unchanged; pass
``--no-resume`` to force a cold run, or ``--only`` to run a subset.

The exit code reports *problems* -- failed or unsupported stages -- and not the
mere absence of results. A run in which everything was ``not_requested`` exits
zero because nothing went wrong, while a run blocked on missing external
software exits 3 so a caller can tell it apart from a real failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from umat_oti.pipeline.stages import canonical_engine
from umat_oti.pipeline.status import StageStatus

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_BLOCKED = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="umat-oti-pipeline", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # Not required=True: --list-stages must work without a contract.
    parser.add_argument("--config", type=Path,
                        help="contract JSON consumed by every front end")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--run-id", default="run")
    parser.add_argument("--compile", action="store_true",
                        help="compile the generated Fortran during transformation")
    parser.add_argument("--no-resume", action="store_true",
                        help="ignore any cached stage results")
    parser.add_argument("--only", nargs="+", metavar="STAGE",
                        help="run only these stages (dependencies still gate them)")
    parser.add_argument("--list-stages", action="store_true",
                        help="print the stage graph in dependency order and exit")
    parser.add_argument("--json", action="store_true",
                        help="print the run summary as JSON")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[3]
    engine = canonical_engine(repo_root)

    if args.list_stages:
        for index, stage in enumerate(engine.stages, start=1):
            requires = ", ".join(stage.requires) or "-"
            print(f"{index:2d}. {stage.name:34s} requires: {requires}")
        return EXIT_OK

    missing = [flag for flag, value in (("--config", args.config),
                                        ("--work-dir", args.work_dir)) if value is None]
    if missing:
        print(f"missing required argument(s): {', '.join(missing)}", file=sys.stderr)
        return EXIT_PROBLEM
    if not args.config.exists():
        print(f"contract not found: {args.config}", file=sys.stderr)
        return EXIT_PROBLEM

    contract = json.loads(args.config.read_text(encoding="utf-8"))
    # Relative source paths in a contract are relative to the contract itself.
    contract.setdefault("_base_dir", str(args.config.resolve().parent))

    manifest = engine.run(
        contract=contract, work_dir=args.work_dir, run_id=args.run_id,
        resume=not args.no_resume, only=args.only,
        options={"config_path": str(args.config.resolve()), "compile": args.compile},
    )

    summary = manifest.summary()
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        for stage in engine.stages:
            record = manifest.stages[stage.name]
            mark = " (cached)" if record.reused_from_cache else ""
            print(f"  {record.status.value:32s} {stage.name}{mark}")
            if record.reason:
                print(f"      {record.reason.splitlines()[0][:110]}")
        print(f"\nmanifest: {args.work_dir / 'run_manifest.json'}")
        print(f"summary : {json.dumps(summary['status_counts'], sort_keys=True)}")

    if summary["problems"]:
        return EXIT_PROBLEM
    blocked = any(r.status is StageStatus.BLOCKED_BY_EXTERNAL_DEPENDENCY
                  for r in manifest.stages.values())
    return EXIT_BLOCKED if blocked else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
