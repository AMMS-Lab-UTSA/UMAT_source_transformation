#!/usr/bin/env python3
"""Verify the illustrative example's consistent tangent and publish the evidence.

DDSDDE was the one derivative family the repository never checked numerically.
The Abaqus paired runs compare it between two builds that carry the same
tangent, and the higher-order study begins at order two, so a tangent that both
builds got wrong in the same way would have passed everything.

This runs the real transformation of the illustrative J2 UMAT, executes it, and
adjudicates every entry of the returned tangent against two references that
fail differently: the closed-form elastoplastic consistent tangent, and an
80-digit centred difference of an independent integrator.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from umat_oti.validation.actual_umat_higher_order import (  # noqa: E402
    run_actual_j2_higher_order_evidence,
)

DEFAULT_CONFIG = REPO_ROOT / "examples" / "j2_actual_higher_order.json"
DEFAULT_RESULTS = REPO_ROOT / "paper_results" / "actual_umat_higher_order" / "j2"
PUBLISHED = ("table2_ddsdde_illustrative.csv", "actual_umat_ddsdde.csv",
             "actual_umat_higher_order_evidence.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--work-dir", type=Path, required=True,
                        help="scratch directory for the build")
    parser.add_argument("--results-dir", type=Path, default=None,
                        help="where to publish; omit to leave the results in "
                             "the work directory only")
    args = parser.parse_args(argv)

    evidence = run_actual_j2_higher_order_evidence(args.config, args.work_dir)
    tangent = evidence["tangent"]
    print(f"  entries              {tangent['entries']}")
    print(f"  resolved             {tangent['resolved']}")
    print(f"  measured             {tangent['measured']}")
    print(f"  structural zeros     {tangent['structural_zeros']}"
          f" ({tangent['structural_zeros_disagreeing']} disagreeing)")
    print(f"  reference unresolved {tangent['reference_unresolved']}")
    print(f"  agreeing             {tangent['agreeing']}")
    print(f"  disagreeing          {tangent['disagreeing']}")
    print(f"  worst measured relative error "
          f"{tangent['worst_measured_relative_error']}")
    print(f"  references agree with each other to "
          f"{tangent['worst_reference_spread_relative_where_measured']}")

    if args.results_dir is not None:
        args.results_dir.mkdir(parents=True, exist_ok=True)
        for name in PUBLISHED:
            source = Path(args.work_dir) / name
            if source.is_file():
                shutil.copy2(source, args.results_dir / name)
        published = args.results_dir.resolve()
        try:
            published = published.relative_to(REPO_ROOT)
        except ValueError:
            pass
        print(f"  published to {published}")

    if tangent["disagreeing"]:
        print("FAILED: the tangent disagrees with its independent references")
        return 1
    if tangent["resolved"] == 0:
        print("FAILED: no entry was resolved by either reference")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
