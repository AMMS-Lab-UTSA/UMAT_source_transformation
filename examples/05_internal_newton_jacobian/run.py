#!/usr/bin/env python
"""Example 5: extract the internal (local Newton) Jacobian of a viscoplastic damage UMAT.

Run from the repository root:

    python examples/05_internal_newton_jacobian/run.py --out umat_oti_workspace/examples/05_vpdco

The UMAT is ``UMATs/UMATs/ICP/UMAT_VPDCO.for``: rate-dependent plasticity
coupled with continuum damage. Inside every increment it solves a scalar
equation FGAM(GAM_PAR) = 0 for the plastic multiplier GAM_PAR by Newton's
method, ``GAM_PAR = GAM_PAR - FGAM/FJAC``, where FJAC is the hand-coded
derivative dFGAM/dGAM_PAR. This script

1. resolves the helper routines the UMAT calls (some live in
   ``UMAT_ECL_TEMP.for`` in the same folder) into one source file;
2. finds the Newton update in the source automatically;
3. runs the original UMAT along a uniaxial strain path and records the
   converged GAM_PAR;
4. seeds GAM_PAR with an OTI direction at that converged value and reads
   dFGAM/dGAM_PAR out of the transformed, compiled UMAT;
5. computes the same derivative by centred finite differences of the separately
   compiled original over a ladder of steps, and
6. compares both with the value of FJAC the source computes by hand.

Exit status 0 means the OTI value agrees with the converged finite-difference
reference to 1e-8. The hand-coded FJAC is reported, never used as the reference.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from umat_oti.transform.dependency_resolution import combined_source, resolve_closure
from umat_oti.transform.internal_jacobian import discover_local_solves
from umat_oti.validation.internal_jacobian_validation import (
    InternalJacobianCase,
    verify_internal_jacobian,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "UMATs" / "UMATs" / "ICP" / "UMAT_VPDCO.for"

#: The 26 material constants of the sample material input distributed with this
#: UMAT, in the order SUBROUTINE VSPRATE reads them: TETA, E0, E1, G0, G1, SIGY0,
#: SIGY1, CTE, H', GAMMA, R0, R1, C, A, D0, b, k, d, p, n, Q, R, N0, ms, l, Ga.
PROPS = (295.15, 62.0, -0.067, 24.28, -0.029, 76.944, -0.1883, 5.7e-06, 13.6, 457.9,
         37.47, -0.0748, 383.3, 45000000.0, 48.8, 3.18e-07, 1.38e-20, 0.015, 3.34, 1.67,
         44700000.0, 8314.0, 6.023e+23, 20140.0, 0.0003, 10.0)
#: Uniaxial strain: 20 increments of 1e-4 in component 11.
DSTRAN = (1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0)
N_INCREMENTS = 20
NTENS, NSTATV = 6, 22
TOLERANCE = 1.0e-8


def relative(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-300)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="a new directory for the results")
    args = parser.parse_args(argv)
    args.out = args.out.resolve()
    if args.out.exists():
        parser.error("--out must be a new directory; earlier results are kept")
    args.out.mkdir(parents=True)

    # 1. One self-contained source: the UMAT plus every helper it calls.
    graph = resolve_closure(SOURCE, entry="UMAT", roots=[SOURCE.parent])
    if graph.missing:
        print("helper routines not found:", [m.symbol for m in graph.missing])
        return 2
    resolved = args.out / "UMAT_VPDCO_resolved.for"
    resolved.write_text(combined_source(graph), encoding="utf-8")
    helpers = sorted(set(graph.resolved) - {"UMAT"})

    # 2. The local Newton solve, found by a syntactic scan of the source.
    solve = discover_local_solves(resolved.read_text(encoding="utf-8"))[0]

    print("Example 5: internal (local Newton) Jacobian of a viscoplastic damage UMAT")
    print(f"  source       : {SOURCE.relative_to(REPO_ROOT)} + {len(helpers)} helper routines")
    print(f"  Newton update: {solve.iterate} = {solve.iterate} "
          f"{solve.sign} {solve.residual}/{solve.jacobian} "
          f"(resolved source, line {solve.update_line})")
    print(f"  derivative   : d{solve.residual}/d{solve.iterate} "
          f"(hand-coded in the source as {solve.jacobian})")
    print(f"  loading      : {N_INCREMENTS} increments of DSTRAN11 = {DSTRAN[0]:g}\n")

    # 3-6. Probe, seed, extract, and compare with the independent reference.
    case = InternalJacobianCase(
        model="UMAT_VPDCO", source_path=resolved.resolve(), props=PROPS,
        dstran_per_increment=DSTRAN, n_increments=N_INCREMENTS,
        ntens=NTENS, nstatv=NSTATV, ndi=3, nshr=3)
    record = verify_internal_jacobian(case, args.out / "verification")
    (args.out / "verification.json").write_text(json.dumps(record, indent=2, default=str) + "\n",
                                                encoding="utf-8")
    stages = record.get("stages", {})
    for name, stage in stages.items():
        print(f"  stage {name:<30} {stage.get('status')}"
              + (f"  ({stage['reason']})" if stage.get("reason") else ""))
    extracted = record.get("extracted")
    if not extracted:
        print("\nRESULT: FAIL (no Jacobian was extracted; see verification.json)")
        return 1

    convergence = record["reference_convergence"]
    oti, hand = extracted["oti"], extracted["hand_coded"]
    fd = convergence.get("converged_reference", extracted["finite_difference"])
    print(f"\n  increment {record['target_increment']}, converged "
          f"{solve.iterate} = {record['converged_iterate']:.10e}")
    print("\n  Centred finite differences of the original over the step ladder")
    print("  (the reference is the flattest three-step window, Richardson-extrapolated")
    print("  where that is tighter):")
    print("    relative step        dFGAM/dGAM_PAR")
    for step, value in zip(convergence["relative_steps"], convergence["values"]):
        marker = "  <- reference taken here" if step == convergence.get("converged_relative_step") else ""
        print(f"    {step:13.3e}   {value:22.15e}{marker}")

    print(f"\n  OTI (transformed UMAT)        : {oti:22.15e}")
    print(f"  finite-difference reference   : {fd:22.15e}")
    print(f"  hand-coded {solve.jacobian:<19}: {hand:22.15e}")
    oti_error, hand_error = relative(oti, fd), relative(hand, fd)
    print(f"\n  |OTI - FD| / |FD|             : {oti_error:.3e}")
    print(f"  |hand-coded - FD| / |FD|      : {hand_error:.3e}")

    passed = stages.get("jacobian_verified", {}).get("status") == "succeeded" and oti_error <= TOLERANCE
    print("\nRESULT:", "PASS" if passed else "FAIL",
          f"(OTI agrees with finite differences to {oti_error:.1e}; tolerance {TOLERANCE:g})")
    if hand_error > 1e-6:
        print(f"NOTE: the hand-coded {solve.jacobian} differs from the finite-difference "
              f"reference by {hand_error:.1e}; the OTI value does not.")
    print(f"Full record: {args.out / 'verification.json'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
