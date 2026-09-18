"""Run the joint working-tree wheel gate owned by Residual Assembler."""

import argparse
from pathlib import Path
import runpy
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--ra-repo", type=Path, required=True)
    args, remaining = parser.parse_known_args()
    script = args.ra_repo.resolve() / "scripts/clean_install_gate.py"
    if not script.is_file():
        parser.error(f"joint gate not found: {script}")
    sys.argv = [str(script), "--ra-repo", str(args.ra_repo.resolve()),
                "--umat-repo", str(Path(__file__).resolve().parents[1]), *remaining]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()