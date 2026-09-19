#!/usr/bin/env python
"""Example 1: check the OTI tangent of a linear elastic UMAT against the exact answer.

Run from the repository root, after the transform step of the README:

    umat-oti jacobian parameter_sensitivity/models/m1_elastic/umat.for \
        --ntens 6 --out umat_oti_workspace/examples/01_elastic --compile
    python examples/01_elastic_tangent/run.py --jacobian-dir umat_oti_workspace/examples/01_elastic

What it does, in order:

1. compiles the drop-in UMAT written by ``umat-oti jacobian``
   (``umat_oti_combined.f90``) with a small material-point driver that prints
   STRESS and DDSDDE after every increment;
2. compiles the ORIGINAL, untransformed UMAT separately with the same driver;
3. for two sets of material constants, applies a two-increment strain path and
   compares
   - the OTI tangent with the analytic isotropic stiffness,
   - the transformed stress with the original stress (primal parity), and
   - centred finite differences of the original with the analytic stiffness,
     at three step sizes, to show what a finite-difference tangent costs.

Exit status 0 means every OTI tangent matched the analytic stiffness to
1e-12 (relative to its largest entry) and the stresses matched the original.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from umat_oti.validation.parameter_sensitivity_validation import (
    ABA_PARAM,
    build_original_driver,
    driver_source,
    replay,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = REPO_ROOT / "parameter_sensitivity" / "models" / "m1_elastic" / "umat.for"

NTENS, NSTATV = 6, 0
#: Two sets of (E, nu). The second shows the tangent is not hard-wired.
MATERIALS = ((210000.0, 0.3), (70000.0, 0.33))
#: Two strain increments (Voigt 11, 22, 33, 12, 13, 23; engineering shear).
PATH = np.array([
    [1.0e-3, -3.0e-4, -3.0e-4, 5.0e-4, 0.0, 2.0e-4],
    [-2.0e-4, 1.0e-4, 0.0, 0.0, 3.0e-4, 0.0],
])
FD_STEPS = (1.0e-4, 1.0e-6, 1.0e-8)
TOLERANCE = 1.0e-12


def analytic_stiffness(young: float, poisson: float) -> np.ndarray:
    """Isotropic small-strain stiffness in Voigt form with engineering shear."""
    lam = young * poisson / ((1.0 + poisson) * (1.0 - 2.0 * poisson))
    mu = young / (2.0 * (1.0 + poisson))
    stiffness = np.zeros((6, 6))
    stiffness[:3, :3] = lam
    stiffness[np.arange(3), np.arange(3)] += 2.0 * mu
    stiffness[np.arange(3, 6), np.arange(3, 6)] = mu
    return stiffness


def build_tangent_driver(source: Path, work: Path, nprops: int) -> Path:
    """Compile ``source`` with a driver that prints STRESS, STATEV and DDSDDE."""
    work.mkdir(parents=True, exist_ok=True)
    for name in ("aba_param.inc", "ABA_PARAM.INC"):
        (work / name).write_text(ABA_PARAM, encoding="utf-8")
    nsv = max(NSTATV, 1)
    driver = driver_source(ntens=NTENS, nstatv=NSTATV, nprops=nprops)
    old = f"WRITE(*,'({NTENS + nsv}(ES26.17E3,1X))') STRESS,STATEV"
    new = f"WRITE(*,'({NTENS + nsv + NTENS * NTENS}(ES26.17E3,1X))') STRESS,STATEV,DDSDDE"
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


def run_tangent_driver(executable: Path, props, path):
    """Stress (n, NTENS) and DDSDDE (n, NTENS, NTENS) after every increment."""
    payload = " ".join(f"{v:.17e}" for v in props) + f"\n{len(path)}\n"
    payload += "\n".join(" ".join(f"{v:.17e}" for v in row) for row in path) + "\n"
    done = subprocess.run([str(executable)], input=payload, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(done.stderr)
    width = NTENS + max(NSTATV, 1) + NTENS * NTENS
    rows = [list(map(float, line.split())) for line in done.stdout.splitlines()
            if len(line.split()) == width]
    data = np.asarray(rows)
    stress = data[:, :NTENS]
    # DDSDDE is written column by column (Fortran order).
    tangent = data[:, NTENS + max(NSTATV, 1):].reshape(len(path), NTENS, NTENS).transpose(0, 2, 1)
    return stress, tangent


def fd_tangent(reference: Path, props, path, step: float) -> np.ndarray:
    """Centred difference of the ORIGINAL stress w.r.t. each increment's DSTRAN."""
    tangent = np.zeros((len(path), NTENS, NTENS))
    for increment in range(len(path)):
        for component in range(NTENS):
            plus, minus = path[:increment + 1].copy(), path[:increment + 1].copy()
            plus[-1, component] += step
            minus[-1, component] -= step
            high = replay(reference, props, plus.tolist(), ntens=NTENS, nstatv=NSTATV).stress[-1]
            low = replay(reference, props, minus.tolist(), ntens=NTENS, nstatv=NSTATV).stress[-1]
            tangent[increment, :, component] = (np.asarray(high) - np.asarray(low)) / (2.0 * step)
    return tangent


def show(matrix: np.ndarray) -> str:
    return "\n".join("    " + " ".join(f"{v:13.6e}" for v in row) for row in matrix)


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

    transformed = build_tangent_driver(drop_in.resolve(), work / "transformed", nprops=2)
    reference = build_original_driver(ORIGINAL, work / "original", ntens=NTENS,
                                      nstatv=NSTATV, nprops=2)
    print("Example 1: consistent tangent of a linear elastic UMAT")
    print(f"  drop-in UMAT : {drop_in}")
    print(f"  original     : {ORIGINAL.relative_to(REPO_ROOT)}")
    print(f"  path         : {len(PATH)} strain increments\n")

    passed = True
    for young, poisson in MATERIALS:
        props = [young, poisson]
        stress, tangent = run_tangent_driver(transformed, props, PATH)
        original_stress = np.asarray(replay(reference, props, PATH.tolist(),
                                            ntens=NTENS, nstatv=NSTATV).stress)
        exact = analytic_stiffness(young, poisson)
        scale = np.max(np.abs(exact))
        oti_error = max(float(np.max(np.abs(t - exact))) / scale for t in tangent)
        parity = float(np.max(np.abs(stress - original_stress)))
        print(f"E = {young:g}, nu = {poisson:g}")
        if (young, poisson) == MATERIALS[0]:
            print("  DDSDDE from the OTI UMAT, last increment:")
            print(show(tangent[-1]))
            print("  analytic isotropic stiffness:")
            print(show(exact))
        print(f"  OTI tangent vs analytic       : max |diff| / max|C| = {oti_error:.3e}")
        print(f"  stress vs original UMAT       : max |diff| = {parity:.3e} "
              f"(stress scale {np.max(np.abs(original_stress)):.4g})")
        for step in FD_STEPS:
            fd = fd_tangent(reference, props, PATH, step)
            fd_error = max(float(np.max(np.abs(t - exact))) / scale for t in fd)
            print(f"  FD of original, step {step:7.0e}  : max |diff| / max|C| = {fd_error:.3e}")
        print()
        passed &= oti_error <= TOLERANCE and parity <= 1e-10 * np.max(np.abs(original_stress))

    print("RESULT:", "PASS" if passed else "FAIL",
          f"(OTI tangent equals the analytic stiffness to {TOLERANCE:g})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
