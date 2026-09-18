"""Read-only compatibility experiment with the original Program 2 replay.

Exports the old residual_core Python package into the validation output
directory. Neither repository is checked out or modified. No constitutive
core is replaced: the legacy client loads the compiled provider object.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from umat_oti.validation.parameter_sensitivity_provider import FD_TOLERANCE, _relative_error


def check_exported(report_path: Path) -> dict:
    from residual_core.replay.path_material import PathMaterial

    report = json.loads(report_path.read_text())
    completed = json.loads(Path(report["provider"]["contract"]).read_text())
    material = PathMaterial(report["provider"]["object"], completed,
                            workdir=str(report_path.parent / "legacy_link"))
    if not material.has_march:
        raise AssertionError("legacy replay fell back instead of linking UMAT_OTI_MARCH")
    props, path = np.array(report["props"]), np.array(report["path"])
    times = np.ones(len(path))
    evaluated = material.march_oti(props, path, times)
    marched = material.march_fast(props, path, times)
    original = material.march_regular(props, path, times)

    def values(rows, key):
        return np.array([row[key] for row in rows])

    for key in ("stress", "statev"):
        np.testing.assert_allclose(values(evaluated, key), values(original, key), rtol=1e-12, atol=1e-10)
    fd_stress = np.zeros_like(values(evaluated, "dsigma_dp"))
    fd_state = np.zeros_like(values(evaluated, "dstatev_dp"))
    for column, parameter in enumerate(completed["parameters"]):
        slot = parameter["props_index"] - 1
        step = 1.0e-5 * max(abs(props[slot]), 1.0)
        plus, minus = props.copy(), props.copy()
        plus[slot] += step
        minus[slot] -= step
        high, low = material.march_regular(plus, path, times), material.march_regular(minus, path, times)
        fd_stress[:, :, column] = (values(high, "stress") - values(low, "stress")) / (2 * step)
        fd_state[:, :, column] = (values(high, "statev") - values(low, "statev")) / (2 * step)
    fd_tangent = np.zeros_like(values(evaluated, "ddsdde"))
    for increment in range(len(path)):
        for component in range(material.ntens):
            plus, minus = path[:increment + 1].copy(), path[:increment + 1].copy()
            plus[-1, component] += 1e-7
            minus[-1, component] -= 1e-7
            high = material.march_regular(props, plus, times[:increment + 1])[-1]["stress"]
            low = material.march_regular(props, minus, times[:increment + 1])[-1]["stress"]
            fd_tangent[increment, :, component] = (high - low) / 2e-7
    errors = {
        "eval_stress_parameter": _relative_error(values(evaluated, "dsigma_dp"), fd_stress, (0, 1)),
        "march_stress_parameter": _relative_error(values(marched, "dsigma_dp"), fd_stress, (0, 1)),
        "eval_state_parameter": _relative_error(values(evaluated, "dstatev_dp"), fd_state, (0, 1)),
        "eval_tangent": _relative_error(values(evaluated, "ddsdde"), fd_tangent, (1, 2)),
        "march_tangent": _relative_error(values(marched, "ddsdde"), fd_tangent, (1, 2)),
    }
    if max(errors.values()) > FD_TOLERANCE:
        raise AssertionError(f"legacy replay vs ORIGINAL FD failed: {errors}")
    result = {"passed": True, "consumer": "original PathMaterial.march_oti/march_fast/march_regular",
              "has_march": material.has_march, "scaled_errors": errors,
              "derivative_comparisons": int(2 * fd_stress.size + fd_state.size + 2 * fd_tangent.size),
              "reference": "centered FD of bundled ORIGINAL UMAT through original replay client"}
    (report_path.parent / "legacy_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def verify_legacy(report_path: Path, repository: Path, ref: str) -> dict:
    report_path, repository = report_path.resolve(), repository.resolve()
    legacy = report_path.parent / "legacy_source"
    prefix = "residual-assembler/"
    listed = subprocess.run(
        ["git", "-C", str(repository), "ls-tree", "-r", "--name-only", ref,
         prefix + "residual_core"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    for source_path in listed:
        if not source_path.endswith(".py"):
            continue
        contents = subprocess.run(["git", "-C", str(repository), "show", f"{ref}:{source_path}"],
                                  check=True, capture_output=True).stdout
        target = legacy / source_path.removeprefix(prefix)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
    if not (legacy / "residual_core/replay/path_material.py").is_file():
        raise ValueError(f"{ref} does not contain the original replay PathMaterial")
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(legacy), str(Path(__file__).resolve().parents[2])])}
    subprocess.run(
        [sys.executable, "-c", "from pathlib import Path; import sys; "
         "from umat_oti.provider.legacy_check import check_exported; check_exported(Path(sys.argv[1]))",
         str(report_path)], env=environment, cwd=legacy, check=True,
    )
    result_path = report_path.parent / "legacy_verification.json"
    result = json.loads(result_path.read_text())
    result["ref"] = ref
    result["commit"] = subprocess.run(["git", "-C", str(repository), "rev-parse", ref],
                                      check=True, capture_output=True, text=True).stdout.strip()
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--ref", default="origin/cross-platform-hardening")
    args = parser.parse_args()
    print(json.dumps(verify_legacy(args.report, args.repo, args.ref), indent=2))


if __name__ == "__main__":
    main()