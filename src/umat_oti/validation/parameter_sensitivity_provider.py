"""Independent compiled-provider checks against finite differences of ORIGINAL.

Run with ``python -m umat_oti.validation.parameter_sensitivity_provider CONTRACT
--out DIR``. This bounded material-point check never invokes Abaqus.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from umat_oti.provider import build_provider
from umat_oti.validation.parameter_sensitivity_validation import build_original_driver, replay


J2_PATH = np.array([
    [0.0004, 0, 0, 0.0001, 0.00004, -0.00003],
    [0.0003, -0.00005, 0, 0, 0, 0],
    [0.0018, -0.0001, 0.00005, 0.0002, -0.0001, 0.0001],
    [0.0007, 0.0001, -0.0001, -0.0002, 0.0002, 0.00005],
    [-0.0004, 0.00004, 0, -0.00007, 0, 0],
    [-0.0032, 0.0002, -0.0001, -0.0002, 0.0001, -0.0001],
    [0.0002, 0, 0, 0, 0, 0],
], dtype=np.float64)
PARAMETER_STEPS = (1.0e-4, 3.0e-5, 1.0e-5)
STRAIN_STEPS = (1.0e-6, 1.0e-7, 1.0e-8)
FD_TOLERANCE = 2.0e-6


def _pointer(array):
    return array.ctypes.data_as(ctypes.POINTER(ctypes.c_double))


class ProviderLibrary:
    """A direct Fortran ABI client used only by the independent validator."""

    def __init__(self, object_path: Path, contract: dict, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        shared = directory / "provider.so"
        subprocess.run(["gfortran", "-shared", "-Wl,--no-undefined", str(object_path),
                        "-o", str(shared)], check=True, capture_output=True, text=True)
        self.library = ctypes.CDLL(str(shared))
        self.contract = contract
        self.dimensions = contract["dimensions"]
        double_pointer = ctypes.POINTER(ctypes.c_double)
        integer_pointer = ctypes.POINTER(ctypes.c_int)
        self.library.umat_oti_eval_.restype = None
        self.library.umat_oti_eval_.argtypes = (
            [double_pointer] * 10 + [integer_pointer] * 4 + [double_pointer] *
            (4 if contract["history"]["path_dependent"] else 2)
        )
        self.library.umat_oti_march_.restype = None
        self.library.umat_oti_march_.argtypes = [
            double_pointer, integer_pointer, double_pointer, integer_pointer, double_pointer,
            integer_pointer, integer_pointer, integer_pointer, double_pointer,
            double_pointer, double_pointer,
        ]

    def evaluate(self, props, path, *, carry=True):
        ntens, nstatev, nparam = (self.dimensions[key] for key in ("ntens", "nstatev", "nparam"))
        props = np.asfortranarray(props, dtype=np.float64)
        stress, state, strain = np.zeros(ntens), np.zeros(nstatev), np.zeros(ntens)
        dsigma = np.zeros((ntens, nparam), order="F")
        dstate = np.zeros((nstatev, nparam), order="F")
        tangent = np.zeros((ntens, ntens), order="F")
        sizes = [ctypes.c_int(self.dimensions[key]) for key in ("nprops", "ntens", "nstatev", "nparam")]
        rows = []
        for increment, delta in enumerate(path):
            previous_sigma = dsigma.copy(order="F") if carry else np.zeros_like(dsigma)
            previous_state = dstate.copy(order="F") if carry else np.zeros_like(dstate)
            delta = np.ascontiguousarray(delta, dtype=np.float64)
            strain_argument = strain
            if not self.contract["history"]["path_dependent"]:
                stress.fill(0.0)
                state.fill(0.0)
                delta = strain + delta
                strain_argument = np.zeros(ntens)
            time = np.array([increment, increment], dtype=np.float64)
            scalars = [ctypes.c_double(value) for value in (1.0, 293.15, 0.0)]
            arguments = [_pointer(value) for value in (stress, state, tangent, strain_argument, delta, time)]
            arguments += [ctypes.byref(value) for value in scalars] + [_pointer(props)]
            arguments += [ctypes.byref(value) for value in sizes]
            arguments += [_pointer(dsigma), _pointer(dstate)]
            if self.contract["history"]["path_dependent"]:
                arguments += [_pointer(previous_sigma), _pointer(previous_state)]
            self.library.umat_oti_eval_(*arguments)
            rows.append(tuple(value.copy() for value in (stress, state, tangent, dsigma, dstate)))
            strain += path[increment]
        return tuple(np.array([row[index] for row in rows]) for index in range(5))

    def march(self, props, path):
        ntens, nstatev, nparam = (self.dimensions[key] for key in ("ntens", "nstatev", "nparam"))
        props = np.asfortranarray(props, dtype=np.float64)
        path_fortran = np.asfortranarray(np.asarray(path).T)
        increments = len(path)
        times = np.ones(increments)
        dsigma = np.zeros((ntens, nparam, increments), order="F")
        stress = np.zeros(ntens)
        tangent = np.zeros((ntens, ntens, increments), order="F")
        sizes = [ctypes.c_int(value) for value in (len(props), increments, ntens, nstatev, nparam)]
        self.library.umat_oti_march_(
            _pointer(props), ctypes.byref(sizes[0]), _pointer(path_fortran), ctypes.byref(sizes[1]),
            _pointer(times), *[ctypes.byref(value) for value in sizes[2:]],
            _pointer(dsigma), _pointer(stress), _pointer(tangent),
        )
        return stress, dsigma.transpose(2, 0, 1), tangent.transpose(2, 0, 1)


def _relative_error(actual, reference, axes):
    if not np.all(np.isfinite(actual)) or not np.all(np.isfinite(reference)):
        raise AssertionError("provider/reference contains nonfinite values")
    scale = np.maximum(np.max(np.abs(reference), axis=axes, keepdims=True), 1.0e-12)
    return float(np.max(np.abs(actual - reference) / scale))


def verify_provider(contract_path: Path, output_dir: Path, *, require_j2_branches=True) -> dict:
    contract_path, output_dir = Path(contract_path).resolve(), Path(output_dir).resolve()
    raw = json.loads(contract_path.read_text())
    props = np.asarray(raw["validation"]["props_values"], dtype=np.float64)
    built = build_provider(contract_path, output_dir)
    completed = json.loads(Path(built["contract"]).read_text())
    dimensions = completed["dimensions"]
    ntens, nstatev, nprops = (dimensions[key] for key in ("ntens", "nstatev", "nprops"))
    if props.shape != (nprops,) or not np.all(np.isfinite(props)):
        raise ValueError("validation.props_values must contain one finite value per PROPS slot")
    library = ProviderLibrary(Path(built["object"]), completed, output_dir / "abi_check")
    original = build_original_driver(
        contract_path.parent / raw["source"]["main_file"], output_dir / "original_reference",
        ntens=ntens, nstatv=nstatev, nprops=nprops,
    )

    def reference(properties, path):
        result = replay(original, properties, path, ntens=ntens, nstatv=nstatev)
        return np.asarray(result.stress), np.asarray(result.statev)[:, :nstatev]

    path = J2_PATH.copy()
    expected_stress, expected_state = reference(props, path)
    stress, state, tangent, dsigma, dstate = library.evaluate(props, path)
    march_stress, march_dsigma, march_tangent = library.march(props, path)
    np.testing.assert_allclose(stress, expected_stress, rtol=1e-12, atol=1e-10)
    np.testing.assert_allclose(state, expected_state, rtol=1e-12, atol=1e-14)
    np.testing.assert_allclose(march_stress, expected_stress[-1], rtol=1e-12, atol=1e-10)

    def branches(states):
        return np.diff(np.r_[0.0, states[:, 0]]) > 1.0e-10

    branch_labels = []
    if require_j2_branches:
        plastic = branches(expected_state)
        if not (plastic.any() and (~plastic).any() and np.any(~plastic[np.flatnonzero(plastic)[0]:])):
            raise AssertionError("J2 check must exercise elastic, plastic, and unloading increments")
        branch_labels = ["plastic" if value else "elastic" for value in plastic]

    parameter_errors, parameter_references = [], []
    for relative_step in PARAMETER_STEPS:
        fd_sigma, fd_state = np.zeros_like(dsigma), np.zeros_like(dstate)
        for column, parameter in enumerate(completed["parameters"]):
            slot = parameter["props_index"] - 1
            step = relative_step * max(abs(props[slot]), 1.0)
            plus, minus = props.copy(), props.copy()
            plus[slot] += step
            minus[slot] -= step
            high_stress, high_state = reference(plus, path)
            low_stress, low_state = reference(minus, path)
            if require_j2_branches:
                np.testing.assert_array_equal(branches(high_state), plastic)
                np.testing.assert_array_equal(branches(low_state), plastic)
            fd_sigma[:, :, column] = (high_stress - low_stress) / (2 * step)
            fd_state[:, :, column] = (high_state - low_state) / (2 * step)
        errors = {"relative_step": relative_step,
                  "eval_stress": _relative_error(dsigma, fd_sigma, (0, 1)),
                  "march_stress": _relative_error(march_dsigma, fd_sigma, (0, 1)),
                  "eval_state": _relative_error(dstate, fd_state, (0, 1)) if nstatev else 0.0}
        if max(errors[key] for key in ("eval_stress", "march_stress", "eval_state")) > FD_TOLERANCE:
            raise AssertionError(f"parameter FD failed: {errors}")
        parameter_errors.append(errors)
        parameter_references.append((fd_sigma, fd_state))
    parameter_plateau = _relative_error(parameter_references[-1][0], parameter_references[-2][0], (0, 1))
    state_plateau = (_relative_error(parameter_references[-1][1], parameter_references[-2][1], (0, 1))
                     if nstatev else 0.0)
    if max(parameter_plateau, state_plateau) > FD_TOLERANCE:
        raise AssertionError("parameter FD sweep has no stable plateau")

    tangent_errors, tangent_references = [], []
    for step in STRAIN_STEPS:
        fd_tangent = np.zeros_like(tangent)
        for increment in range(len(path)):
            for component in range(ntens):
                plus, minus = path[:increment + 1].copy(), path[:increment + 1].copy()
                plus[-1, component] += step
                minus[-1, component] -= step
                high_stress, high_state = reference(props, plus)
                low_stress, low_state = reference(props, minus)
                if require_j2_branches:
                    np.testing.assert_array_equal(branches(high_state), plastic[:increment + 1])
                    np.testing.assert_array_equal(branches(low_state), plastic[:increment + 1])
                fd_tangent[increment, :, component] = (high_stress[-1] - low_stress[-1]) / (2 * step)
        errors = {"absolute_step": step, "eval": _relative_error(tangent, fd_tangent, (1, 2)),
                  "march": _relative_error(march_tangent, fd_tangent, (1, 2))}
        if max(errors["eval"], errors["march"]) > FD_TOLERANCE:
            raise AssertionError(f"tangent FD failed: {errors}")
        tangent_errors.append(errors)
        tangent_references.append(fd_tangent)
    tangent_plateau = _relative_error(tangent_references[-1], tangent_references[-2], (1, 2))
    if tangent_plateau > FD_TOLERANCE:
        raise AssertionError("tangent FD sweep has no stable plateau")
    carry_difference = float(np.max(np.abs(library.evaluate(props, path, carry=False)[3] - dsigma)))
    if require_j2_branches and carry_difference < 1.0e-4:
        raise AssertionError("J2 path did not discriminate missing incoming sensitivities")
    report = {
        "passed": True, "reference": "separately compiled ORIGINAL UMAT; centered finite differences",
        "provider": built, "source_hash": completed["regular_source_hash"],
        "object_sha256_full": hashlib.sha256(Path(built["object"]).read_bytes()).hexdigest(),
        "props": props.tolist(), "path": path.tolist(), "increments": len(path), "branches": branch_labels,
        "parameter_steps": parameter_errors, "tangent_steps": tangent_errors,
        "fd_plateau": {"stress": parameter_plateau, "state": state_plateau, "tangent": tangent_plateau},
        "scaled_max_error_tolerance": FD_TOLERANCE,
        "scaling": "parameter: max per column over path/components; tangent: max per increment; floor 1e-12",
        "primal_stress_max_abs": float(np.max(np.abs(stress - expected_stress))),
        "primal_state_max_abs": float(np.max(np.abs(state - expected_state))) if nstatev else 0.0,
        "carry_reset_stress_derivative_difference": carry_difference,
        "comparisons": {"eval_primal": int(stress.size + state.size), "march_final_primal": ntens,
                        "eval_parameter_fd": int(dsigma.size + dstate.size) * len(PARAMETER_STEPS),
                        "march_parameter_fd": int(dsigma.size) * len(PARAMETER_STEPS),
                        "eval_tangent_fd": int(tangent.size) * len(STRAIN_STEPS),
                        "march_tangent_fd": int(tangent.size) * len(STRAIN_STEPS)},
        "clean_install_verified": False,
    }
    (output_dir / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--elastic", action="store_true", help="do not require the J2 branch sequence")
    args = parser.parse_args(argv)
    try:
        report = verify_provider(args.contract, args.out, require_j2_branches=not args.elastic)
    except (AssertionError, ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        args.out.mkdir(parents=True, exist_ok=True)
        report = {"passed": False, "contract": str(args.contract), "error": str(error)}
        (args.out / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
        parser.exit(2, json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()