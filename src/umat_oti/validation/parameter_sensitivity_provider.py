"""Independent compiled-provider checks against finite differences of ORIGINAL.

Run with ``python -m umat_oti.validation.parameter_sensitivity_provider CONTRACT
--out DIR``. This bounded material-point check never invokes Abaqus.

The path is the contract's ``validation.check_path`` (the provider's J2 path
when it declares none). Primal parity is exact to round-off. Every derivative
entry -- DSIGMA_DP, DSTATEV_DP and DDSDDE, from EVAL and from MARCH -- is judged
against centred differences of the separately compiled ORIGINAL over a ladder
of steps, and gets one of four verdicts: agrees, consistent with zero,
reference unresolved, disagrees. See ``_adjudicate``.
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
from umat_oti.validation.reference_resolution import DEFAULT_LADDER, ResolutionLadder, converged_value


J2_PATH = np.array([
    [0.0004, 0, 0, 0.0001, 0.00004, -0.00003],
    [0.0003, -0.00005, 0, 0, 0, 0],
    [0.0018, -0.0001, 0.00005, 0.0002, -0.0001, 0.0001],
    [0.0007, 0.0001, -0.0001, -0.0002, 0.0002, 0.00005],
    [-0.0004, 0.00004, 0, -0.00007, 0, 0],
    [-0.0032, 0.0002, -0.0001, -0.0002, 0.0001, -0.0001],
    [0.0002, 0, 0, 0, 0, 0],
], dtype=np.float64)
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


#: Relative tolerance on one entry, where the reference pins the entry down to
#: better than this. It is the provider's documented limit, now applied entry by
#: entry against the entry's own magnitude instead of against its column's
#: largest entry.
RELATIVE_TOLERANCE = FD_TOLERANCE

#: Parameter steps are these fractions of the parameter's own value (an
#: absolute step where the value is zero); strain steps are these fractions of
#: the increment's largest strain component. Half a decade apart, from
#: truncation- to cancellation-dominated: the ladder the rest of the project
#: uses (umat_oti.validation.reference_resolution.DEFAULT_LADDER).
STEP_LADDER = DEFAULT_LADDER

#: The seven-increment path used when a contract declares none. It crosses
#: elastic, plastic, unloading and reverse-plastic increments of the J2 model.
DEFAULT_PATH_SOURCE = "provider default: the seven-increment J2 path of docs/PROVIDER.md"


class CheckPathError(ValueError):
    """The contract's check path cannot be used."""


def check_path(raw: dict, ntens: int) -> tuple[np.ndarray, str]:
    """The material-point path the check replays, and where it came from.

    ``validation.check_path`` in the provider contract names it, either as
    explicit increments ``{"increments": [[...], ...]}`` or as a repeated one
    ``{"dstran_per_increment": [...], "n_increments": N}`` -- the form
    ``parameter_sensitivity/loading_paths.json`` uses. Every increment is a
    strain increment in Voigt order with engineering shear, applied over a unit
    time step. Without the field the provider's J2 path is used, so existing
    contracts are checked exactly as before.
    """
    spec = (raw.get("validation") or {}).get("check_path")
    if spec is None:
        return J2_PATH.copy(), DEFAULT_PATH_SOURCE
    if not isinstance(spec, dict):
        raise CheckPathError("validation.check_path must be an object")
    if "increments" in spec:
        rows = spec["increments"]
    elif "dstran_per_increment" in spec:
        count = spec.get("n_increments")
        if type(count) is not int or count < 1:
            raise CheckPathError("validation.check_path.n_increments must be a positive integer")
        rows = [spec["dstran_per_increment"]] * count
    else:
        raise CheckPathError("validation.check_path needs increments or dstran_per_increment")
    try:
        path = np.asarray(rows, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise CheckPathError(f"validation.check_path is not numeric: {error}") from None
    if path.ndim != 2 or path.shape[1] != ntens or not len(path) or not np.all(np.isfinite(path)):
        raise CheckPathError(f"validation.check_path must be finite rows of {ntens} strain components")
    if not np.any(path):
        raise CheckPathError("validation.check_path does not deform the material point")
    source = str(spec.get("source") or spec.get("description") or "declared in the contract")
    return path, source


def _noise_floor(response: np.ndarray, step: float) -> np.ndarray:
    """Cancellation floor of a centred difference, per increment: eps*|f|/(2h).

    ``|f|`` is the largest magnitude of the differenced response at that
    increment, over all its components: rounding in one component of an
    update is set by the size of the update, not by the component's own value.
    Measured from the response itself, with no unit-dependent floor.
    """
    scale = np.max(np.abs(response), axis=-1) if response.size else np.zeros(len(response))
    return np.finfo(np.float64).eps * scale / (2.0 * step)


def _adjudicate(value: float, series: tuple, steps: tuple, noise: tuple,
                tolerance: float) -> dict:
    """One entry: agrees, consistent with zero, reference unresolved, or disagrees.

    The reference is a centred difference of the ORIGINAL over the step ladder,
    read the way the rest of the project reads one
    (``reference_resolution.converged_value``): the centre of the flattest
    three-step window, or its Richardson extrapolation where that pins the
    value down more tightly, with the remaining spread as the method's own
    residual. The reference's uncertainty is the largest of the window's
    spread, that residual, the next finer step's distance from the estimate
    and the cancellation floor at the step used. Then:

    - the value differs from the estimate by more than the reference's
      uncertainty and by more than the relative tolerance: **disagrees**;
    - the reference pins the entry down to within the tolerance and the value
      is within it: **agrees**;
    - the entry is no larger than the reference's uncertainty, on both sides:
      **consistent with zero** -- the reference says only that it is zero to
      within its resolution, and the value is too;
    - otherwise the value lies within the reference's own uncertainty but that
      uncertainty is wider than the tolerance: **reference unresolved**. The
      reference cannot say whether the value is right. It is never counted as
      agreement.
    """
    ladder = ResolutionLadder(props_index=0, array="", steps=tuple(steps))
    ladder.values[(1, 1)] = tuple(series)
    bounds = ladder.window(1, 1)
    if bounds is None:
        return {"verdict": "reference_unresolved", "judged_by": "no_admissible_steps",
                "reference": None, "uncertainty": None, "relative_error": None,
                "reason": "fewer than two admissible steps"}
    estimate, used_step, residual = converged_value(ladder, 1, 1)
    # Richardson may sharpen the estimate, but its residual measures only how
    # far two extrapolations moved; the plain window's spread is what the
    # differences themselves scatter by near the plateau. Three steps can also
    # agree by coincidence, so the next finer step -- where cancellation shows
    # first -- is included too: its distance from the estimate is the noise the
    # reference actually has there, which the one-ulp model below understates
    # for an update of many operations. The uncertainty is never taken smaller
    # than any of these, nor than the cancellation floor.
    spread = max(residual, ladder.resolution(1, 1))
    if bounds[1] < len(series):
        spread = max(spread, abs(series[bounds[1]] - estimate))
    floor = noise[steps.index(used_step)]
    uncertainty = max(spread, floor)
    gap = abs(value - estimate)
    magnitude = max(abs(value), abs(estimate))
    relative = gap / magnitude if magnitude else 0.0
    row = {"reference": estimate, "uncertainty": uncertainty, "window_spread": spread,
           "noise_floor": floor, "step": used_step, "relative_error": relative}
    within = gap <= uncertainty or bool(ladder.brackets(1, 1, value))
    if not within and relative > tolerance:
        row.update(verdict="disagrees", judged_by="relative",
                   reason=f"gap {gap:.3e} exceeds the reference's uncertainty "
                          f"{uncertainty:.3e} and the relative tolerance")
    elif uncertainty <= tolerance * magnitude:
        row.update(verdict="agrees", judged_by="relative" if not within else "within_resolution",
                   reason="the reference determines the entry to within the tolerance")
    elif magnitude <= uncertainty:
        row.update(verdict="consistent_with_zero", judged_by="zero_within_resolution",
                   reason=f"both values are within the reference's uncertainty "
                          f"{uncertainty:.3e} of zero")
    else:
        row.update(verdict="reference_unresolved", judged_by="reference_residual",
                   reason=f"the reference's uncertainty {uncertainty:.3e} is wider than "
                          f"the tolerance on this entry ({tolerance * magnitude:.3e})")
    return row


def _column_verdict(rows: list[dict]) -> tuple[str, str]:
    counts = {verdict: sum(1 for row in rows if row["verdict"] == verdict)
              for verdict in ("agrees", "consistent_with_zero", "reference_unresolved", "disagrees")}
    if counts["disagrees"]:
        return "disagrees", f"{counts['disagrees']} entries disagree with the reference"
    if counts["agrees"]:
        return "agrees", (f"{counts['agrees']} entries agree"
                          + (f"; {counts['reference_unresolved']} entries the reference cannot "
                             f"resolve to the tolerance" if counts["reference_unresolved"] else ""))
    if counts["reference_unresolved"]:
        return "unresolved", ("no entry is determined to the tolerance: the reference's own "
                              "uncertainty is wider than the tolerance wherever the "
                              "derivative is non-zero")
    return "unresolved", ("every entry is zero to within the reference's resolution: on this "
                          "path the derivative is smaller than a centred difference of the "
                          "response can resolve")


def _ladder_arrays(evaluate, base: float, steps: tuple, *, admissible) -> tuple[list, list, list]:
    """Centred differences at each step; skipped where the step is inadmissible."""
    kept, differences, responses = [], [], []
    for relative in steps:
        step = relative * (abs(base) if base else 1.0)
        try:
            high, low = evaluate(+step), evaluate(-step)
        except RuntimeError:
            continue  # a step the model cannot run contributes nothing, never a zero
        if not admissible(high) or not admissible(low):
            continue
        kept.append((relative, step))
        differences.append(tuple((h - l) / (2.0 * step) for h, l in zip(high[:2], low[:2])))
        responses.append(high[:2])
    return kept, differences, responses


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
    path, path_source = check_path(raw, ntens)
    library = ProviderLibrary(Path(built["object"]), completed, output_dir / "abi_check")
    original = build_original_driver(
        contract_path.parent / raw["source"]["main_file"], output_dir / "original_reference",
        ntens=ntens, nstatv=nstatev, nprops=nprops,
    )

    def reference(properties, increments):
        result = replay(original, properties, increments, ntens=ntens, nstatv=nstatev)
        return np.asarray(result.stress), np.asarray(result.statev)[:, :nstatev]

    expected_stress, expected_state = reference(props, path)
    stress, state, tangent, dsigma, dstate = library.evaluate(props, path)
    march_stress, march_dsigma, march_tangent = library.march(props, path)
    for array in (stress, state, tangent, dsigma, dstate, march_stress, march_dsigma, march_tangent):
        if not np.all(np.isfinite(array)):
            raise AssertionError("provider returned nonfinite values on the check path")
    np.testing.assert_allclose(stress, expected_stress, rtol=1e-12, atol=1e-10)
    np.testing.assert_allclose(state, expected_state, rtol=1e-12, atol=1e-14)
    np.testing.assert_allclose(march_stress, expected_stress[-1], rtol=1e-12, atol=1e-10)

    def branches(states):
        return np.diff(np.r_[0.0, states[:, 0]]) > 1.0e-10

    branch_labels, plastic = [], None
    if require_j2_branches:
        plastic = branches(expected_state)
        if not (plastic.any() and (~plastic).any() and np.any(~plastic[np.flatnonzero(plastic)[0]:])):
            raise AssertionError("J2 check must exercise elastic, plastic, and unloading increments")
        branch_labels = ["plastic" if value else "elastic" for value in plastic]

    def admissible_for(prefix):
        # A perturbation that moves any increment onto another branch measures
        # a secant across the kink, not the derivative; that step is left out.
        if plastic is None:
            return lambda result: True
        return lambda result: bool(np.array_equal(branches(result[1]), plastic[:prefix]))

    entries: list[dict] = []
    columns: list[dict] = []
    stress_noise_scale, state_noise_scale = expected_stress, expected_state

    # Parameter derivatives: one ladder per parameter serves DSIGMA_DP and
    # DSTATEV_DP, for EVAL and for MARCH.
    for column, parameter in enumerate(completed["parameters"]):
        slot = parameter["props_index"] - 1

        def perturbed(step, slot=slot):
            moved = props.copy()
            moved[slot] += step
            return reference(moved, path)

        kept, differences, _ = _ladder_arrays(perturbed, props[slot], STEP_LADDER,
                                              admissible=admissible_for(len(path)))
        steps = tuple(relative for relative, _ in kept)
        for array, index, values, response in (
                ("DSIGMA_DP", 0, dsigma[:, :, column], stress_noise_scale),
                ("DSTATEV_DP", 1, dstate[:, :, column], state_noise_scale),
                ("DSIGMA_DP (MARCH)", 0, march_dsigma[:, :, column], stress_noise_scale)):
            if values.shape[1] == 0:
                continue
            noise = [_noise_floor(response, step) for _, step in kept]
            rows = []
            for increment in range(values.shape[0]):
                for component in range(values.shape[1]):
                    series = tuple(table[index][increment, component] for table in differences)
                    row = _adjudicate(float(values[increment, component]), series, steps,
                                      tuple(level[increment] for level in noise), RELATIVE_TOLERANCE)
                    row.update(array=array, column=parameter["name"], increment=increment + 1,
                               component=component + 1, oti=float(values[increment, component]))
                    rows.append(row)
            verdict, reason = _column_verdict(rows)
            columns.append(_column_record(array, parameter["name"], rows, verdict, reason, steps))
            entries.extend(rows)

    # The tangent, at fixed incoming history: only the last increment of each
    # prefix of the path is perturbed, one strain component at a time.
    for strain in range(ntens):
        rows_eval, rows_march, steps_seen = [], [], set()
        for increment in range(len(path)):
            magnitude = float(np.max(np.abs(path[increment]))) or 1.0e-4

            def perturbed(step, increment=increment, strain=strain):
                moved = path[:increment + 1].copy()
                moved[-1, strain] += step
                high_stress, high_state = reference(props, moved)
                return high_stress[-1:], high_state
            kept, differences, _ = [], [], []
            for relative in STEP_LADDER:
                step = relative * magnitude
                try:
                    high, low = perturbed(step), perturbed(-step)
                except RuntimeError:
                    continue
                if not (admissible_for(increment + 1)((None, high[1]))
                        and admissible_for(increment + 1)((None, low[1]))):
                    continue
                kept.append((relative, step))
                differences.append((high[0][0] - low[0][0]) / (2.0 * step))
            steps = tuple(relative for relative, _ in kept)
            steps_seen.add(steps)
            noise = tuple(float(_noise_floor(expected_stress[increment:increment + 1], step)[0])
                          for _, step in kept)
            for row_index in range(ntens):
                series = tuple(table[row_index] for table in differences)
                for values, rows in ((tangent, rows_eval), (march_tangent, rows_march)):
                    row = _adjudicate(float(values[increment, row_index, strain]), series, steps,
                                      noise, RELATIVE_TOLERANCE)
                    row.update(increment=increment + 1, component=row_index + 1,
                               oti=float(values[increment, row_index, strain]))
                    rows.append(row)
        for array, rows in (("DDSDDE", rows_eval), ("DDSDDE (MARCH)", rows_march)):
            name = f"dDSTRAN({strain + 1})"
            for row in rows:
                row.update(array=array, column=name)
            verdict, reason = _column_verdict(rows)
            columns.append(_column_record(array, name, rows, verdict, reason,
                                          sorted(steps_seen, key=len)[-1] if steps_seen else ()))
            entries.extend(rows)

    carry_difference = float(np.max(np.abs(library.evaluate(props, path, carry=False)[3] - dsigma)))
    if require_j2_branches and carry_difference < 1.0e-4:
        raise AssertionError("J2 path did not discriminate missing incoming sensitivities")

    by_array: dict[str, dict] = {}
    for record in columns:
        summary = by_array.setdefault(record["array"], {
            "columns": 0, "agreeing_columns": 0, "unresolved_columns": 0, "disagreeing_columns": 0,
            "agrees": 0, "consistent_with_zero": 0, "reference_unresolved": 0, "disagrees": 0,
            "worst_relative_error_agreeing": 0.0})
        summary["columns"] += 1
        summary[{"agrees": "agreeing_columns", "unresolved": "unresolved_columns",
                 "disagrees": "disagreeing_columns"}[record["verdict"]]] += 1
        for key in ("agrees", "consistent_with_zero", "reference_unresolved", "disagrees"):
            summary[key] += record["counts"][key]
        summary["worst_relative_error_agreeing"] = max(
            summary["worst_relative_error_agreeing"], record["worst_relative_error_agreeing"] or 0.0)
    disagreeing = [record for record in columns if record["verdict"] == "disagrees"]
    unresolved = [record for record in columns if record["verdict"] == "unresolved"]
    nontrivial = all(summary["agreeing_columns"] for summary in by_array.values())
    if disagreeing:
        raise AssertionError("derivatives disagree with the ORIGINAL's centred differences: "
                             + "; ".join(f"{r['array']} {r['column']}: {r['reason']}" for r in disagreeing))
    if not nontrivial:
        raise AssertionError("an array has no column the reference resolves: "
                             + ", ".join(name for name, s in by_array.items() if not s["agreeing_columns"]))
    _write_entries(output_dir / "verification_entries.csv", entries)
    report = {
        "passed": True,
        "verdict": "verified" if not unresolved else "verified_with_unresolved_columns",
        "reference": "separately compiled ORIGINAL UMAT; centred finite differences over a step ladder",
        "provider": built, "source_hash": completed["regular_source_hash"],
        "object_sha256_full": hashlib.sha256(Path(built["object"]).read_bytes()).hexdigest(),
        "props": props.tolist(), "path": path.tolist(), "path_source": path_source,
        "increments": len(path), "branches": branch_labels,
        "criterion": {
            "relative_tolerance": RELATIVE_TOLERANCE,
            "parameter_steps": "relative to the parameter's value: " + ", ".join(f"{s:.3g}" for s in STEP_LADDER),
            "strain_steps": "relative to the increment's largest strain component: "
                            + ", ".join(f"{s:.3g}" for s in STEP_LADDER),
            "reference_value": ("reference_resolution.converged_value: centre of the flattest "
                                "three-step window, or its Richardson extrapolation where tighter"),
            "reference_uncertainty": ("max(flattest-window spread, Richardson residual, distance "
                                      "of the next finer step from the estimate, "
                                      "eps*|response|/(2h) at the step used)"),
            "within_reference": "gap <= uncertainty, or the flattest window's values straddle the value",
            "verdicts": "agrees | consistent_with_zero | reference_unresolved | disagrees; "
                        "only 'agrees' counts as verified",
            "branch_rule": ("steps that move any increment onto another J2 branch are left out"
                            if require_j2_branches else "no branch rule"),
        },
        "primal_stress_max_abs": float(np.max(np.abs(stress - expected_stress))),
        "primal_state_max_abs": float(np.max(np.abs(state - expected_state))) if nstatev else 0.0,
        "carry_reset_stress_derivative_difference": carry_difference,
        "state_growth": float(np.max(np.abs(expected_state[-1]))) if nstatev else 0.0,
        "arrays": by_array,
        "columns": [{key: value for key, value in record.items() if key != "rows"} for record in columns],
        "unresolved_columns": [{"array": r["array"], "column": r["column"], "reason": r["reason"]}
                               for r in unresolved],
        "comparisons": {"eval_primal": int(stress.size + state.size), "march_final_primal": ntens,
                        "verified_entries": sum(s["agrees"] for s in by_array.values()),
                        "consistent_with_zero": sum(s["consistent_with_zero"] for s in by_array.values()),
                        "reference_unresolved": sum(s["reference_unresolved"] for s in by_array.values()),
                        "disagreeing": 0},
        "entries_csv": str(output_dir / "verification_entries.csv"),
        "clean_install_verified": False,
    }
    (output_dir / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def _column_record(array: str, name: str, rows: list[dict], verdict: str, reason: str,
                   steps: tuple) -> dict:
    agreeing = [row for row in rows if row["verdict"] == "agrees"]
    return {"array": array, "column": name, "verdict": verdict, "reason": reason,
            "counts": {key: sum(1 for row in rows if row["verdict"] == key)
                       for key in ("agrees", "consistent_with_zero", "reference_unresolved", "disagrees")},
            "worst_relative_error_agreeing": max((row["relative_error"] for row in agreeing), default=None),
            "largest_entry": max((abs(row["oti"]) for row in rows), default=0.0),
            "admissible_relative_steps": list(steps)}


def _write_entries(path: Path, entries: list[dict]) -> None:
    import csv

    fields = ["array", "column", "increment", "component", "oti", "reference", "uncertainty",
              "window_spread", "noise_floor", "step", "relative_error", "verdict", "judged_by", "reason"]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(entries)


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