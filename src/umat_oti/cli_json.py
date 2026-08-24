from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Any

from umat_oti.services.transformation import (
    TransformationOptions, run_transformation,
)


def run_config_transform(
    config_path: Path, out_dir: Path, *, compile_generated: bool = False
) -> tuple[dict[str, Any], int]:
    """Deprecated compatibility wrapper over the pure transformation service.

    Kept so existing callers keep working, but it is no longer an independent
    implementation: it delegates. New code should call
    :func:`umat_oti.services.transformation.run_transformation`, or better, run
    the pipeline, which is the single execution path.
    """
    warnings.warn(
        "umat_oti.cli_json.run_config_transform is deprecated; call "
        "umat_oti.services.transformation.run_transformation, or run the "
        "pipeline (umat_oti.pipeline), which is the single execution path.",
        DeprecationWarning, stacklevel=2,
    )
    return run_transformation(
        config_path, out_dir,
        TransformationOptions(compile_generated=compile_generated),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the single-config transform path from a compact JSON contract.")
    parser.add_argument("--config", type=Path, required=True, help="Path to the compact JSON file.")
    parser.add_argument(
        "--out",
        type=Path,
        help="Output directory. Defaults to ./umat_oti_workspace/new_user_runs/<config-stem>.",
    )
    parser.add_argument("--compile", action="store_true", help="Compile the generated Fortran units with gfortran.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = args.config.expanduser().resolve()
    out_dir = args.out.expanduser().resolve() if args.out is not None else (Path.cwd() / "umat_oti_workspace" / "new_user_runs" / config_path.stem)

    summary, exit_code = run_transformation(
        config_path, out_dir, TransformationOptions(compile_generated=args.compile)
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
