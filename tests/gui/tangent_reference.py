"""An independent check of a transformed UMAT's DDSDDE, for the GUI tests.

The value under test is what the generated drop-in UMAT writes into DDSDDE when
called through the standard Abaqus interface. The reference is a centred finite
difference of the ORIGINAL source, compiled on its own by the provider
verifier's reference-driver builder and replayed in ordinary real arithmetic;
the two share no code path. Each tangent is taken at fixed incoming history:
only the last increment of each path prefix is perturbed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from umat_oti.validation.parameter_sensitivity_validation import (
    ABA_PARAM, build_original_driver, driver_source, replay,
)


def build_transformed_driver(drop_in: Path, work: Path, *, ntens: int, nstatv: int,
                             nprops: int) -> Path:
    """Compile the drop-in UMAT with a driver that also prints DDSDDE."""
    work.mkdir(parents=True, exist_ok=True)
    for name in ("aba_param.inc", "ABA_PARAM.INC"):
        (work / name).write_text(ABA_PARAM, encoding="utf-8")
    source = driver_source(ntens=ntens, nstatv=nstatv, nprops=nprops)
    nsv = max(nstatv, 1)
    old = f"WRITE(*,'({ntens + nsv}(ES26.17E3,1X))') STRESS,STATEV"
    assert old in source, "the reference driver's output line changed"
    source = source.replace(
        old, f"WRITE(*,'({ntens + nsv + ntens * ntens}(ES26.17E3,1X))') STRESS,STATEV,DDSDDE")
    source = source.replace("PROGRAM original_reference_driver", "PROGRAM transformed_driver")
    source = source.replace("END PROGRAM original_reference_driver", "END PROGRAM transformed_driver")
    driver = work / "transformed_driver.f90"
    driver.write_text(source, encoding="utf-8")
    executable = work / "transformed_driver"
    for arguments in (
        ["gfortran", "-O1", "-std=legacy", "-ffree-form", "-ffree-line-length-none",
         "-I", str(work), "-J", str(work), "-c", str(drop_in), "-o", str(work / "umat.o")],
        ["gfortran", "-O1", "-std=legacy", "-ffree-line-length-none", str(driver),
         str(work / "umat.o"), "-o", str(executable)],
    ):
        completed = subprocess.run(arguments, cwd=work, capture_output=True, text=True)
        assert completed.returncode == 0, completed.stderr[-3000:]
    return executable


def run_transformed(executable: Path, props, path, *, ntens: int, nstatv: int):
    """(stress, ddsdde) per increment from the transformed build."""
    payload = " ".join(f"{v:.17e}" for v in props) + f"\n{len(path)}\n"
    payload += "\n".join(" ".join(f"{v:.17e}" for v in row) for row in path) + "\n"
    completed = subprocess.run([str(executable)], input=payload, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    nsv = max(nstatv, 1)
    rows = [list(map(float, line.split())) for line in completed.stdout.splitlines()
            if len(line.split()) == ntens + nsv + ntens * ntens]
    assert len(rows) == len(path), completed.stdout[-2000:]
    data = np.asarray(rows)
    stress = data[:, :ntens]
    # DDSDDE was written column by column (Fortran order).
    tangent = data[:, ntens + nsv:].reshape(len(path), ntens, ntens).transpose(0, 2, 1)
    return stress, tangent


def fd_tangent(reference: Path, props, path, *, ntens: int, nstatv: int, step: float):
    """Centred difference of the ORIGINAL stress w.r.t. each increment's DSTRAN."""
    path = np.asarray(path, dtype=float)
    tangent = np.zeros((len(path), ntens, ntens))
    for increment in range(len(path)):
        for component in range(ntens):
            plus, minus = path[:increment + 1].copy(), path[:increment + 1].copy()
            plus[-1, component] += step
            minus[-1, component] -= step
            high = np.asarray(replay(reference, props, plus.tolist(), ntens=ntens, nstatv=nstatv).stress)
            low = np.asarray(replay(reference, props, minus.tolist(), ntens=ntens, nstatv=nstatv).stress)
            tangent[increment, :, component] = (high[-1] - low[-1]) / (2 * step)
    return tangent


def compare_with_original(drop_in: Path, original: Path, work: Path, *, props, path,
                          ntens: int, nstatv: int, steps=(1e-6, 1e-7, 1e-8)) -> dict:
    """Primal parity and scaled tangent errors at every step of the sweep."""
    executable = build_transformed_driver(drop_in, work / "transformed", ntens=ntens,
                                          nstatv=nstatv, nprops=len(props))
    reference = build_original_driver(original, work / "original", ntens=ntens,
                                      nstatv=nstatv, nprops=len(props))
    stress, tangent = run_transformed(executable, props, path, ntens=ntens, nstatv=nstatv)
    original_stress = np.asarray(replay(reference, props, np.asarray(path).tolist(),
                                        ntens=ntens, nstatv=nstatv).stress)
    errors = []
    for step in steps:
        reference_tangent = fd_tangent(reference, props, path, ntens=ntens, nstatv=nstatv, step=step)
        scale = np.maximum(np.max(np.abs(reference_tangent), axis=(1, 2), keepdims=True), 1e-12)
        errors.append(float(np.max(np.abs(tangent - reference_tangent) / scale)))
    return {"primal_max_abs": float(np.max(np.abs(stress - original_stress))),
            "stress_scale": float(np.max(np.abs(original_stress))),
            "tangent_scaled_errors": errors, "tangent": tangent}
