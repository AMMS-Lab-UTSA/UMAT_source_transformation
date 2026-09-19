"""Reproduce the bundled m5_cpflow local-Jacobian verification without Abaqus."""

import argparse
import json
from pathlib import Path

from umat_oti.validation.internal_jacobian_validation import (
    InternalJacobianCase,
    verify_internal_jacobian,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    # the build runs in its own directory, so a relative --out must be made
    # absolute here or the include path handed to the compiler points nowhere
    args.out = args.out.resolve()
    if args.out.exists():
        parser.error("--out must be a new directory; existing evidence is preserved")
    args.out.mkdir(parents=True)
    case = InternalJacobianCase(
        model="m5_cpflow",
        source_path=Path(__file__).resolve().parents[1]
        / "parameter_sensitivity/models/m5_cpflow/umat.for",
        props=(200000.0, 0.3, 1500.0, 25.0, 0.4, 1.6, 0.1, 60000.0),
        dstran_per_increment=(1.0e-4, 0.0, 0.0, 0.0, 0.0, 0.0),
        n_increments=20, ntens=6, nstatv=1, ndi=3, nshr=3,
        state_names=("EQPLAS",),
    )
    try:
        record = verify_internal_jacobian(case, args.out)
        reference = record.get("extracted", {}).get("finite_difference", 0.0)
        extracted = record.get("extracted", {}).get("oti", 0.0)
        relative_error = abs(extracted - reference) / abs(reference) if reference else None
        recording = record.get("stages", {}).get("recording_is_non_perturbing", {})
        passed = (
            record.get("furthest_stage") == "jacobian_verified"
            and record["stages"]["jacobian_verified"]["status"] == "succeeded"
            and recording.get("max_stress_drift") == 0.0
            and relative_error is not None and relative_error < 1e-8
            and record.get("hand_coded_audit", {}).get("relative_difference", 1.0) < 1e-8
        )
        record.update(passed=passed, example_relative_error=relative_error,
                      example_tolerance=1e-8, clean_install_verified=False)
    except (OSError, RuntimeError, ValueError) as exc:
        record = {"passed": False, "diagnostic": str(exc), "clean_install_verified": False}
    (args.out / "verification.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"passed": record["passed"], "report": str(args.out / "verification.json")}))
    return 0 if record["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())