#!/usr/bin/env python
"""Example 2: check the OTI consistent tangent of J2 plasticity against finite differences.

Run from the repository root, after the transform step of the README:

    umat-oti jacobian parameter_sensitivity/models/m3_j2/umat.for \
        --ntens 6 --out umat_oti_workspace/examples/02_j2 --compile
    python examples/02_j2_plasticity_tangent/run.py --jacobian-dir umat_oti_workspace/examples/02_j2

What it does, in order:

1. compiles the drop-in UMAT written by ``umat-oti jacobian``
   (``umat_oti_combined.f90``) with a material-point driver that prints
   STRESS, STATEV and DDSDDE after every increment;
2. compiles the ORIGINAL, untransformed UMAT separately with the same driver;
3. replays a seven-increment strain path that is elastic, elastic, plastic,
   plastic, elastic (unloading), plastic (reverse loading), elastic;
4. at every increment compares the OTI tangent with
   - centred finite differences of the original, at five strain steps
     (only the last increment of each path prefix is perturbed, so the
     incoming history is fixed, as in an Abaqus increment), and
   - the tangent the original source codes by hand.

Exit status 0 means primal stresses agree to round-off and, at every
increment, the finite-difference tangent at its best step agrees with the OTI
tangent to 1e-8 (relative to the increment's largest tangent entry).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from umat_oti.validation.parameter_sensitivity_validation import ABA_PARAM, driver_source

REPO_ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = REPO_ROOT / "parameter_sensitivity" / "models" / "m3_j2" / "umat.for"

NTENS, NSTATV = 6, 1
#: E, nu, initial yield stress SIGY0, linear hardening modulus H (MPa).
PROPS = (210000.0, 0.3, 250.0, 2000.0)
#: Strain increments (Voigt 11, 22, 33, 12, 13, 23; engineering shear). The same
#: path the provider verifier uses by default (docs/PROVIDER.md).
PATH = np.array([
    [0.0004, 0, 0, 0.0001, 0.00004, -0.00003],
    [0.0003, -0.00005, 0, 0, 0, 0],
    [0.0018, -0.0001, 0.00005, 0.0002, -0.0001, 0.0001],
    [0.0007, 0.0001, -0.0001, -0.0002, 0.0002, 0.00005],
    [-0.0004, 0.00004, 0, -0.00007, 0, 0],
    [-0.0032, 0.0002, -0.0001, -0.0002, 0.0001, -0.0001],
    [0.0002, 0, 0, 0, 0, 0],
])
FD_STEPS = (1.0e-5, 1.0e-6, 1.0e-7, 1.0e-8, 1.0e-9)
TOLERANCE = 1.0e-8


def build_tangent_driver(source: Path, work: Path) -> Path:
    """Compile ``source`` with a driver that prints STRESS, STATEV and DDSDDE."""
    work.mkdir(parents=True, exist_ok=True)
    for name in ("aba_param.inc", "ABA_PARAM.INC"):
        (work / name).write_text(ABA_PARAM, encoding="utf-8")
    driver = driver_source(ntens=NTENS, nstatv=NSTATV, nprops=len(PROPS))
    old = f"WRITE(*,'({NTENS + NSTATV}(ES26.17E3,1X))') STRESS,STATEV"
    new = f"WRITE(*,'({NTENS + NSTATV + NTENS * NTENS}(ES26.17E3,1X))') STRESS,STATEV,DDSDDE"
    if old not in driver:
        raise RuntimeError("the reference driver's output line changed; update this example")
    (work / "tangent_driver.f90").write_text(driver.replace(old, new), encoding="utf-8")
    form = (["-ffixed-form", "-ffixed-line-length-none"] if source.suffix.lower() in {".for", ".f"}
            else ["-ffree-form", "-ffree-line-length-none"])
    executable = work / "tangent_driver"
    for command in (
        ["gfortran", "-O1", "-std=legacy", *form, "-I", str(work), "-J", str(work),
         "-c", str(source), "-o", str(work / "umat.o")],
        ["gfortran", "-O1", "-std=legacy", "-ffree-line-length-none",
         str(work / "tangent_driver.f90"), str(work / "umat.o"), "-o", str(executable)],
    ):
        done = subprocess.run(command, cwd=work, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"compilation failed:\n{' '.join(command)}\n{done.stderr[-2000:]}")
    return executable


def run(executable: Path, path: np.ndarray):
    """Stress (n, 6), state (n, 1) and DDSDDE (n, 6, 6) after every increment."""
    payload = " ".join(f"{v:.17e}" for v in PROPS) + f"\n{len(path)}\n"
    payload += "\n".join(" ".join(f"{v:.17e}" for v in row) for row in path) + "\n"
    done = subprocess.run([str(executable)], input=payload, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr)
    width = NTENS + NSTATV + NTENS * NTENS
    data = np.asarray([list(map(float, line.split())) for line in done.stdout.splitlines()
                       if len(line.split()) == width])
    tangent = data[:, NTENS + NSTATV:].reshape(len(path), NTENS, NTENS).transpose(0, 2, 1)
    return data[:, :NTENS], data[:, NTENS:NTENS + NSTATV], tangent


def fd_tangent(executable: Path, increment: int, step: float) -> np.ndarray:
    """Centred difference of the stress after ``increment`` w.r.t. its own DSTRAN."""
    tangent = np.zeros((NTENS, NTENS))
    for component in range(NTENS):
        plus, minus = PATH[:increment + 1].copy(), PATH[:increment + 1].copy()
        plus[-1, component] += step
        minus[-1, component] -= step
        tangent[:, component] = (run(executable, plus)[0][-1] - run(executable, minus)[0][-1]) / (2 * step)
    return tangent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jacobian-dir", type=Path, required=True,
                        help="the --out directory of `umat-oti jacobian`")
    args = parser.parse_args(argv)
    jacobian_dir = args.jacobian_dir.resolve()
    drop_in = jacobian_dir / "umat_oti_combined.f90"
    if not drop_in.is_file():
        parser.error(f"{drop_in} not found: run `umat-oti jacobian ... --out {args.jacobian_dir}` first")
    work = jacobian_dir / "example_check"
    if work.exists():
        shutil.rmtree(work)
    transformed = build_tangent_driver(drop_in.resolve(), work / "transformed")
    original = build_tangent_driver(ORIGINAL, work / "original")

    stress, state, tangent = run(transformed, PATH)
    stress_ref, state_ref, hand_coded = run(original, PATH)
    parity = float(np.max(np.abs(stress - stress_ref)))
    plastic = np.diff(np.r_[0.0, state_ref[:, 0]]) > 1e-12

    print("Example 2: consistent tangent of J2 plasticity (radial return, linear hardening)")
    print(f"  drop-in UMAT : {drop_in}")
    print(f"  original     : {ORIGINAL.relative_to(REPO_ROOT)}")
    print(f"  PROPS        : E={PROPS[0]:g} nu={PROPS[1]:g} SIGY0={PROPS[2]:g} H={PROPS[3]:g}")
    print(f"  stress vs original UMAT: max |diff| = {parity:.3e} "
          f"(stress scale {np.max(np.abs(stress_ref)):.4g})\n")
    print("  Scaled error max|DDSDDE_OTI - reference| / max|reference| at each increment:")
    header = "  inc  branch   EQPLAS     " + "".join(f"FD h={h:<7.0e}" for h in FD_STEPS) \
        + "  best FD   hand-coded"
    print(header)
    worst_best = 0.0
    for increment in range(len(PATH)):
        errors = []
        for step in FD_STEPS:
            reference = fd_tangent(original, increment, step)
            scale = max(float(np.max(np.abs(reference))), 1e-12)
            errors.append(float(np.max(np.abs(tangent[increment] - reference))) / scale)
        hand = float(np.max(np.abs(tangent[increment] - hand_coded[increment]))) / \
            float(np.max(np.abs(hand_coded[increment])))
        worst_best = max(worst_best, min(errors))
        print(f"  {increment + 1:>3}  {'plastic' if plastic[increment] else 'elastic':<7}  "
              f"{state_ref[increment, 0]:.3e}  " + "".join(f"{e:<13.3e}" for e in errors)
              + f"{min(errors):<10.3e}{hand:.3e}")

    print("\n  DDSDDE from the OTI UMAT at increment 3 (plastic), MPa:")
    for row in tangent[2]:
        print("    " + " ".join(f"{v:12.1f}" for v in row))

    passed = parity <= 1e-10 * float(np.max(np.abs(stress_ref))) and worst_best <= TOLERANCE
    print("\nRESULT:", "PASS" if passed else "FAIL",
          f"(best-step FD agrees with the OTI tangent to {worst_best:.1e}; tolerance {TOLERANCE:g})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
