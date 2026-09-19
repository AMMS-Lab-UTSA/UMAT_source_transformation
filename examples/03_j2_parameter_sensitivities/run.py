#!/usr/bin/env python
"""Examples 3 and 4: read a provider package the way a collaborator would.

Run from the repository root on the --out directory of
``python -m umat_oti.provider.collaborator``:

    python examples/03_j2_parameter_sensitivities/run.py \
        --package umat_oti_workspace/examples/03_j2/package

It uses only the four hand-off files in ``<package>/collaborator/`` plus the
verifier's report in ``<package>/verification/``:

1. checks that ``OTI_UMAT.obj`` and ``REAL_UMAT.obj`` are the objects
   ``Mapping.json`` names (SHA-256);
2. calls ``OTI_UMAT.obj`` (entry point ``UMAT_OTI_EVAL``) along the verified
   loading path and prints stress, state and their parameter sensitivities
   DSIGMA_DP and DSTATEV_DP after every increment;
3. repeats an independent check with ``REAL_UMAT.obj`` alone: centred finite
   differences of the unchanged original over the whole path, at three
   relative steps, against DSIGMA_DP and DSTATEV_DP at the last increment;
4. counts the verifier's per-entry verdicts in ``verification_entries.csv``.

Exit status 0 means the objects match the mapping, the primal stress of both
objects agrees, and the finite-difference check agrees to 1e-6 at its best
step.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from umat_oti.validation.parameter_sensitivity_provider import ProviderLibrary
from umat_oti.validation.parameter_sensitivity_validation import ABA_PARAM, driver_source, replay

VOIGT = ("11", "22", "33", "12", "13", "23")
FD_STEPS = (1.0e-4, 1.0e-5, 1.0e-6)
FD_TOLERANCE = 1.0e-6


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def link_regular_object(regular: Path, work: Path, *, ntens: int, nstatv: int, nprops: int) -> Path:
    """REAL_UMAT.obj + the material-point driver -> an executable (no source needed)."""
    work.mkdir(parents=True, exist_ok=True)
    (work / "aba_param.inc").write_text(ABA_PARAM, encoding="utf-8")
    driver = work / "regular_driver.f90"
    driver.write_text(driver_source(ntens=ntens, nstatv=nstatv, nprops=nprops), encoding="utf-8")
    executable = work / "regular_driver"
    done = subprocess.run(["gfortran", "-O1", "-std=legacy", "-ffree-line-length-none",
                           str(driver), str(regular), "-o", str(executable)],
                          cwd=work, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"linking REAL_UMAT.obj failed:\n{done.stderr[-2000:]}")
    return executable


def history_table(names, stress, state, dsigma, dstate, *, component, slot, branches):
    """One line per increment: a stress component, a state slot and their sensitivities."""
    c, s = component - 1, slot - 1
    head = f"{'inc':>3} {'branch':>8} {'S' + VOIGT[c]:>11} " + " ".join(
        f"{'dS' + VOIGT[c] + '/d' + n:>13}" for n in names)
    lines = [head]
    for i in range(len(stress)):
        branch = branches[i] if branches else ""
        lines.append(f"{i + 1:>3} {branch:>8} {stress[i, c]:11.4f} "
                     + " ".join(f"{dsigma[i, c, k]:13.5e}" for k in range(len(names))))
    if state.shape[1]:
        lines.append("")
        lines.append(f"{'inc':>3} {'':>8} {'SDV' + str(slot):>11} "
                     + " ".join(f"{'dSDV' + str(slot) + '/d' + n:>13}" for n in names))
        for i in range(len(state)):
            lines.append(f"{i + 1:>3} {'':>8} {state[i, s]:11.4e} "
                         + " ".join(f"{dstate[i, s, k]:13.5e}" for k in range(len(names))))
    return "\n".join(lines)


def main(argv=None, *, default_component: int = 1, default_state: int = 1) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", type=Path, required=True,
                        help="the --out directory of umat_oti.provider.collaborator")
    parser.add_argument("--component", type=int, default=default_component,
                        help="stress component to tabulate, 1..6 (Voigt 11,22,33,12,13,23)")
    parser.add_argument("--state", type=int, default=default_state,
                        help="state variable (SDV) to tabulate, 1-based")
    args = parser.parse_args(argv)

    args.package = args.package.resolve()
    shared = args.package / "collaborator"
    report_path = args.package / "verification" / "verification.json"
    needed = [shared / name for name in ("OTI_UMAT.obj", "REAL_UMAT.obj", "Mapping.json",
                                         "transform_report.txt")] + [report_path]
    missing = [str(path) for path in needed if not path.is_file()]
    if missing:
        parser.error("not a complete package (run the collaborator command first): "
                     + ", ".join(missing))
    mapping = json.loads((shared / "Mapping.json").read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("passed"):
        print("The verifier did not pass this package:", report.get("error"))
        return 1
    dims = mapping["dimensions"]
    ntens, nstatv, nprops = dims["ntens"], dims["nstatev"], dims["nprops"]
    names = [p["name"] for p in mapping["parameters"]]
    slots = [p["props_index"] - 1 for p in mapping["parameters"]]
    props = np.asarray(report["props"], dtype=np.float64)
    path = np.asarray(report["path"], dtype=np.float64)

    print(f"Provider package: {args.package}")
    print(f"  model {mapping['model_id']}: NTENS={ntens} NPROPS={nprops} NSTATV={nstatv}, "
          f"{len(names)} parameters: {', '.join(names)}")
    print(f"  loading path: {len(path)} increments ({report.get('path_source')})")

    # 1. The two objects are the ones the mapping names.
    oti_ok = sha256(shared / "OTI_UMAT.obj") == mapping["object"]["sha256_full"]
    real_ok = sha256(shared / "REAL_UMAT.obj") == mapping["regular_object"]["sha256_full"]
    print(f"\n1. SHA-256 of OTI_UMAT.obj matches Mapping.json: {oti_ok}; "
          f"REAL_UMAT.obj: {real_ok}")

    # 2. Parameter sensitivities along the path, from the OTI object.
    work = args.package / "example_check"
    library = ProviderLibrary(shared / "OTI_UMAT.obj", mapping, work / "oti")
    stress, state, _tangent, dsigma, dstate = library.evaluate(props, path)
    print(f"\n2. OTI_UMAT.obj along the path (stress component {VOIGT[args.component - 1]}, "
          f"state SDV{args.state}):\n")
    print(history_table(names, stress, state, dsigma, dstate, component=args.component,
                        slot=args.state, branches=report.get("branches")))
    print(f"\n   DSIGMA_DP at the last increment (rows 11..23, columns = parameters):")
    print("   " + " " * 5 + " ".join(f"{n:>12}" for n in names))
    for row in range(ntens):
        print(f"   {VOIGT[row]:>4} " + " ".join(f"{dsigma[-1, row, k]:12.4e}" for k in range(len(names))))

    # 3. Independent check with REAL_UMAT.obj only.
    regular = link_regular_object(shared / "REAL_UMAT.obj", work / "regular",
                                  ntens=ntens, nstatv=nstatv, nprops=nprops)
    base = replay(regular, props, path, ntens=ntens, nstatv=nstatv)
    parity = float(np.max(np.abs(np.asarray(base.stress) - stress)))
    print(f"\n3. REAL_UMAT.obj alone: stress max |diff| to OTI_UMAT.obj = {parity:.3e}")
    print("   centred FD of REAL_UMAT.obj over the whole path, last increment, "
          "max |FD - OTI| / max|OTI| per parameter:")
    print(f"   {'parameter':>10} " + " ".join(f"{'h=' + format(h, '.0e'):>11}" for h in FD_STEPS)
          + f" {'best':>11}")
    worst_best = 0.0
    for name, slot, k in zip(names, slots, range(len(names))):
        oti_sigma, oti_state = dsigma[-1, :, k], dstate[-1, :nstatv, k]
        errors = []
        for relative in FD_STEPS:
            h = relative * (abs(props[slot]) or 1.0)
            up, down = props.copy(), props.copy()
            up[slot] += h
            down[slot] -= h
            high, low = (replay(regular, p, path, ntens=ntens, nstatv=nstatv) for p in (up, down))
            fd_sigma = (np.asarray(high.stress[-1]) - np.asarray(low.stress[-1])) / (2 * h)
            fd_state = (np.asarray(high.statev[-1][:nstatv]) - np.asarray(low.statev[-1][:nstatv])) / (2 * h)
            scale_sigma = max(float(np.max(np.abs(oti_sigma))), 1e-300)
            error = float(np.max(np.abs(fd_sigma - oti_sigma))) / scale_sigma
            if nstatv and np.max(np.abs(oti_state)) > 0:
                error = max(error, float(np.max(np.abs(fd_state - oti_state)))
                            / float(np.max(np.abs(oti_state))))
            errors.append(error)
        worst_best = max(worst_best, min(errors))
        print(f"   {name:>10} " + " ".join(f"{e:11.3e}" for e in errors) + f" {min(errors):11.3e}")

    # 4. The verifier's own per-entry verdicts.
    counts = collections.Counter()
    entries = Path(report["entries_csv"]).name
    with (args.package / "verification" / entries).open(newline="") as stream:
        for row in csv.DictReader(stream):
            counts[(row["array"], row["verdict"])] += 1
    print(f"\n4. Verifier verdict: {report['verdict']} "
          f"(per-entry verdicts from verification/{entries}):")
    verdicts = ("agrees", "consistent_with_zero", "reference_unresolved", "disagrees")
    print(f"   {'array':<20}" + "".join(f"{v:>22}" for v in verdicts))
    for array in dict.fromkeys(a for a, _ in counts):
        print(f"   {array:<20}" + "".join(f"{counts[(array, v)]:>22}" for v in verdicts))

    passed = oti_ok and real_ok and parity <= 1e-10 * max(1.0, float(np.max(np.abs(stress)))) \
        and worst_best <= FD_TOLERANCE
    print("\nRESULT:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
