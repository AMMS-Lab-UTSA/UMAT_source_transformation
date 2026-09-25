from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from umat_oti.services.jacobian_request import (
    DEFAULT_RESPONSE, DEFAULT_SEED, DEFAULT_TARGET, run_jacobian_transform,
)
from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.core.pipeline import transform_umat
from umat_oti.validation.material_point import load_material_point_config
from umat_oti.validation.job_builder import DEFAULT_ABAQUS_MODULES, DEFAULT_ABAQUS_RUN_PREFIX


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="umat-oti")
    subparsers = parser.add_subparsers(dest="command", required=True)
    complete = subparsers.add_parser(
        "all", help="Discover dependencies, compile the tangent, and build and verify parameter sensitivities.")
    complete.add_argument("source", type=Path)
    complete.add_argument("--material-config", type=Path,
                          help="Optional material-settings override; otherwise discover and generate it automatically.")
    complete.add_argument("--material-discovery-root", type=Path,
                          help="Directory to search for associated material data; defaults to the source directory.")
    complete.add_argument("--out", type=Path, required=True, help="New or empty output directory.")
    complete.add_argument("--dependency-root", type=Path, action="append", default=[],
                          help="Additional helper source directory or file (repeatable).")
    complete_modes = complete.add_mutually_exclusive_group()
    complete_modes.add_argument("--abaqus", action="store_true",
                                help="After Jacobian and sensitivity verification, run an Abaqus analysis trial.")
    complete_modes.add_argument("--abaqus-smoke", action="store_true",
                                help="After Jacobian and sensitivity verification, build with Abaqus only.")
    complete.add_argument("--abaqus-input", type=Path,
                          help="Existing deck override; implies --abaqus.")
    complete.add_argument("--abaqus-experiment", type=Path,
                          help="Experiment settings override; otherwise generate from --material-config. Implies --abaqus.")
    complete.add_argument("--abaqus-command", default="abaqus")
    complete.add_argument("--abaqus-modules", default=DEFAULT_ABAQUS_MODULES)
    complete.add_argument("--abaqus-run-prefix", default=DEFAULT_ABAQUS_RUN_PREFIX)
    transform = subparsers.add_parser("transform", help="Generate an OTIS-enabled UMAT.")
    transform.add_argument("source", type=Path, help="Path to the source UMAT.")
    transform.add_argument("--out", type=Path, required=True, help="Output directory for generated files.")
    transform.add_argument("--config", type=Path, help="Optional material_point.json validation config.")
    transform.add_argument("--no-validation", action="store_true", help="Generate files without running validation.")
    config = subparsers.add_parser("config", help="Generate artifacts from a canonical UMAT-OTI JSON contract.")
    config.add_argument("config", type=Path, help="Path to a schema 1.1 or legacy project contract.")
    config.add_argument("--out", type=Path, required=True, help="Output directory for generated files.")
    config.add_argument("--compile", action="store_true", help="Compile the generated Fortran units with gfortran.")
    jacobian = subparsers.add_parser(
        "jacobian",
        help="Constitutive Jacobian from four fields: source, NTENS and seed/response/target. "
             "The tangent block is located by the transformer; no contract is written by hand.")
    jacobian.add_argument("source", type=Path, help="Path to the UMAT source (.for/.f/.f90).")
    jacobian.add_argument("--ntens", type=int, required=True, help="Number of stress components (3, 4 or 6).")
    jacobian.add_argument("--seed", default=DEFAULT_SEED, help="Differentiate with respect to (default DSTRAN).")
    jacobian.add_argument("--response", default=DEFAULT_RESPONSE, help="Output to differentiate (default STRESS).")
    jacobian.add_argument("--target", default=DEFAULT_TARGET, help="Where the derivative is written (default DDSDDE).")
    jacobian.add_argument("--order", type=int, default=1, help="Derivative order (default 1).")
    jacobian.add_argument("--out", type=Path, required=True, help="Output directory for generated files.")
    jacobian.add_argument("--compile", action="store_true", help="Compile the generated Fortran units with gfortran.")
    jacobian.add_argument(
        "--discover-dependencies", action="store_true",
        help="Search the source directory recursively for helper routines and lift their dependencies.")
    jacobian.add_argument(
        "--dependency-root", type=Path, action="append", default=[], metavar="PATH",
        help="Additional helper source directory or file to search (repeatable).")
    jacobian.add_argument("--abaqus", action="store_true",
                          help="Try the candidate in Abaqus, generating a deck from experiment settings by default (not verification).")
    jacobian.add_argument("--abaqus-smoke", action="store_true",
                          help="Compile/link with abaqus make only; no deck or material settings, no solver execution.")
    jacobian.add_argument("--abaqus-experiment", type=Path, metavar="SETTINGS.json",
                          help="Experiment settings for deck generation; defaults to SOURCE with suffix .abaqus.json. Implies --abaqus.")
    jacobian.add_argument("--abaqus-discovery-root", type=Path, metavar="PATH",
                          help="Search this model directory for material decks when settings are absent/incomplete; defaults to source directory.")
    jacobian.add_argument("--abaqus-input", type=Path, metavar="DECK.inp",
                          help="Override deck generation with an existing Abaqus input deck. Implies --abaqus.")
    jacobian.add_argument("--abaqus-allow-semantic-failures", action="store_true",
                          help="Allow an unverified Abaqus trial despite failed semantic checks; requires an Abaqus trial request.")
    jacobian.add_argument("--abaqus-command", default="abaqus")
    jacobian.add_argument("--abaqus-modules", default=DEFAULT_ABAQUS_MODULES)
    jacobian.add_argument("--abaqus-run-prefix", default=DEFAULT_ABAQUS_RUN_PREFIX,
                          help="Scheduler command prefix; use an empty string when already on a compute node.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "all":
        from umat_oti.services.complete_workflow import CompleteAbaqusOptions, run_complete_workflow

        if args.abaqus_smoke and (args.abaqus_input is not None or args.abaqus_experiment is not None):
            parser.error("--abaqus-smoke cannot be combined with --abaqus-input or --abaqus-experiment")
        options = None
        if args.abaqus or args.abaqus_smoke or args.abaqus_input is not None or args.abaqus_experiment is not None:
            options = CompleteAbaqusOptions(
                input_deck=args.abaqus_input, experiment=args.abaqus_experiment,
                smoke=args.abaqus_smoke, command=args.abaqus_command,
                modules=args.abaqus_modules, run_prefix=args.abaqus_run_prefix)
        summary = run_complete_workflow(args.source, args.material_config, args.out,
                                        dependency_roots=args.dependency_root, abaqus_options=options,
                                        material_discovery_root=args.material_discovery_root)
        print(json.dumps(summary, indent=2, default=str))
        return int(summary["exit_code"])
    if args.command == "transform":
        material_point = None
        if args.config is not None:
            material_point = load_material_point_config(args.config.parent)
        result = transform_umat(
            args.source,
            args.out,
            material_point=material_point,
            run_validation=not args.no_validation,
        )
        print(
            json.dumps(
                {
                    "generated_files": result.generated_files,
                    "output_dir": str(result.output_dir),
                    "validation_status": result.validation_report.get("status"),
                    "validation_pass": result.validation_report.get("pass"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if result.validation_report.get("status") != "failed" else 1
    if args.command == "config":
        summary, exit_code = run_transformation(
            args.config, args.out,
            TransformationOptions(compile_generated=args.compile))
        print(json.dumps(summary, indent=2, sort_keys=True))
        return exit_code
    if args.command == "jacobian":
        abaqus_requested = args.abaqus or args.abaqus_smoke or args.abaqus_input is not None or args.abaqus_experiment is not None
        if args.abaqus_smoke and (args.abaqus or args.abaqus_input is not None or args.abaqus_experiment is not None):
            parser.error("--abaqus-smoke cannot be combined with an Abaqus analysis trial request")
        if args.abaqus_allow_semantic_failures and not abaqus_requested:
            parser.error("--abaqus-allow-semantic-failures requires --abaqus, --abaqus-smoke or --abaqus-input")
        if args.abaqus_input is not None and not args.abaqus_input.is_file():
            parser.error(f"Abaqus input deck not found: {args.abaqus_input}")
        if abaqus_requested and not args.abaqus_smoke and args.abaqus_input is None:
            settings = args.abaqus_experiment or args.source.with_suffix(".abaqus.json")
            if args.abaqus_experiment is not None and not settings.is_file():
                parser.error(f"Abaqus experiment settings not found: {settings}. "
                             "Omit --abaqus-experiment to use automatic discovery.")
            generator_options = ["--settings", str(settings.resolve())] if settings.is_file() else []
            if args.abaqus_discovery_root is not None:
                generator_options += ["--discovery-root", str(args.abaqus_discovery_root.resolve())]
            generated = subprocess.run(
                [sys.executable, "-m", "umat_oti.abaqus.trial_deck", *generator_options,
                 "--source", str(args.source.resolve()), "--ntens", str(args.ntens),
                 "--out", str(args.out.resolve())], capture_output=True, text=True, check=False)
            if generated.returncode:
                parser.error("Abaqus deck generation failed: " + (generated.stderr or generated.stdout).strip()
                             + f"\nDiscovery details, if attempted: {args.out / 'abaqus_discovery.json'}")
            args.abaqus_input = args.out.resolve() / "abaqus_trial.inp"
        try:
            run = run_jacobian_transform(
                args.source, args.out, ntens=args.ntens, seed=args.seed,
                response=args.response, target=args.target, order=args.order,
                compile_generated=args.compile,
                discover_dependencies=args.discover_dependencies,
                dependency_roots=args.dependency_root)
        except (ValueError, OSError) as error:
            print(f"jacobian request refused: {error}")
            return 2
        exit_code = run.exit_code
        if abaqus_requested:
            from umat_oti.services.abaqus_trial import run_abaqus_trial

            trial = run_abaqus_trial(
                run, args.abaqus_input,
                smoke=args.abaqus_smoke,
                allow_semantic_failures=args.abaqus_allow_semantic_failures,
                abaqus_command=args.abaqus_command, abaqus_modules=args.abaqus_modules,
                run_prefix=args.abaqus_run_prefix)
            run.summary["abaqus_trial"] = trial
            if trial["status"] != ("built" if args.abaqus_smoke else "completed"):
                exit_code = exit_code or 1
        print(json.dumps({**run.summary, "contract": str(run.contract_path)},
                         indent=2, sort_keys=True))
        return exit_code
    parser.error(f"Unhandled command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
