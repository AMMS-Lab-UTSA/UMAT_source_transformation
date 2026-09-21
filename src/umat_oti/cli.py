from __future__ import annotations

import argparse
import json
from pathlib import Path

from umat_oti.services.jacobian_request import (
    DEFAULT_RESPONSE, DEFAULT_SEED, DEFAULT_TARGET, run_jacobian_transform,
)
from umat_oti.services.transformation import TransformationOptions, run_transformation
from umat_oti.core.pipeline import transform_umat
from umat_oti.validation.material_point import load_material_point_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="umat-oti")
    subparsers = parser.add_subparsers(dest="command", required=True)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
        print(json.dumps({**run.summary, "contract": str(run.contract_path)},
                         indent=2, sort_keys=True))
        return run.exit_code
    parser.error(f"Unhandled command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
