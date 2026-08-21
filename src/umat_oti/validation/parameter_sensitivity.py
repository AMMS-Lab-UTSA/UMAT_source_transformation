"""Parameter-sensitivity material-point driver for the SoftwareX J2 case.

This module produces the paper's ``DSIGMA_DP`` and ``DSTATEV_DP`` outputs
using a *history-consistent* centered finite-difference replay: for every
requested parameter, the entire loading history is re-integrated with the
parameter perturbed positive and negative from the operating point, and the
central difference is taken **at each increment**. This is exactly the
verification protocol the SoftwareX task spec calls for:

> Across a multi-increment path:
> - seed the material parameters once
> - propagate the OTI state through every increment
> - do not discard the imaginary coefficients of STATEV
> - extract DSTATEV_DP at each increment
> - use the updated OTI state as the starting state of the following increment
>
> For finite-difference verification, every positive and negative parameter
> perturbation must replay the complete loading history from the same initial
> state. Do not perturb only the final increment.

We provide two backends for computing the sensitivities:

* ``"centered_fd"`` — deterministic reference implementation using the
  pure-Python J2 model in :mod:`umat_oti.validation.j2_reference`. Always
  available; used both as the ground truth and as the OTI-unavailable
  fallback.
* ``"oti"`` — placeholder that documents where the compiled OTI-seeded UMAT
  path would be plugged in; raises :class:`OtilibUnavailable` when a real
  OTI runtime is not present on ``PATH``. This preserves the "no false
  success" rule from the spec while leaving the code path visible for when
  OTIlib is installed.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional, Sequence

from umat_oti.validation.j2_reference import (
    NTENS,
    PARAM_NAMES,
    STATE_NAMES,
    IncrementRecord,
    J2Parameters,
    LoadingPath,
    build_softwarex_j2_path,
    run_path,
)


class OtilibUnavailable(RuntimeError):
    """Raised when the OTI backend is requested but no runtime is available."""


@dataclass(frozen=True)
class ParameterMap:
    """Mapping between parameter names and 1-based PROPS indices."""

    entries: tuple[tuple[str, int], ...]

    @classmethod
    def softwarex_default(cls) -> "ParameterMap":
        return cls(entries=(("E", 1), ("NU", 2), ("SIGY0", 3), ("H", 4)))

    def names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.entries)

    def indices(self) -> tuple[int, ...]:
        return tuple(idx for _, idx in self.entries)


@dataclass(frozen=True)
class StateMap:
    entries: tuple[tuple[str, int], ...]

    @classmethod
    def softwarex_default(cls) -> "StateMap":
        return cls(entries=(("EQPLAS", 1),))

    def names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.entries)


@dataclass
class IncrementSensitivity:
    """Sensitivities at a single increment."""

    increment: int
    dsigma_dp: tuple[tuple[float, ...], ...]     # NTENS x NPARAM
    dstatev_dp: tuple[tuple[float, ...], ...]    # NSTATV x NPARAM
    stress: tuple[float, ...]
    statev: tuple[float, ...]
    yielded: bool


@dataclass
class SensitivityRun:
    """Complete sensitivity result over a loading path."""

    backend: str
    parameters: ParameterMap
    state: StateMap
    path_name: str
    fd_step_relative: float
    increments: list[IncrementSensitivity] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def compute_j2_parameter_sensitivities(
    *,
    params: J2Parameters,
    path: LoadingPath,
    parameter_map: Optional[ParameterMap] = None,
    state_map: Optional[StateMap] = None,
    backend: str = "centered_fd",
    fd_step_relative: float = 1.0e-6,
) -> SensitivityRun:
    """Compute ``DSIGMA_DP`` and ``DSTATEV_DP`` at every increment.

    Parameters
    ----------
    params, path
        Operating point (material parameters) and deterministic strain path.
    parameter_map
        Selection of PROPS entries to differentiate against. Defaults to the
        four SoftwareX parameters (E, NU, SIGY0, H).
    state_map
        Selection of STATEV entries to export. Defaults to (EQPLAS,).
    backend
        Either ``"centered_fd"`` (always available) or ``"oti"`` (raises
        :class:`OtilibUnavailable` when no OTI runtime is on ``PATH``).
    fd_step_relative
        Relative FD step ``h`` used per parameter. The centered FD applies
        ``p*(1+h)`` and ``p*(1-h)`` (and falls back to an absolute step of
        ``h`` when ``|p|`` is smaller than one).
    """
    parameter_map = parameter_map or ParameterMap.softwarex_default()
    state_map = state_map or StateMap.softwarex_default()

    if backend == "centered_fd":
        return _sensitivity_centered_fd(params, path, parameter_map, state_map, fd_step_relative)
    if backend == "oti":
        if not _oti_available():
            raise OtilibUnavailable(
                "OTI backend requested but no OTI runtime was detected on PATH. "
                "Install OTIlib (see scripts/setup_otilib.sh in the Residual "
                "Assembler repo) or rerun with backend='centered_fd'."
            )
        # If a real OTI runtime becomes available in the future, this branch
        # would compile the transformed UMAT with PROPS-seeded OTI directions
        # and read DSIGMA_DP / DSTATEV_DP directly. Until then, we refuse to
        # produce a number rather than fabricate one.
        raise OtilibUnavailable(
            "OTI backend detected but no compiled UMAT harness is wired in "
            "this build. Use backend='centered_fd' for the reference values."
        )
    raise ValueError(f"unknown backend {backend!r}; expected 'centered_fd' or 'oti'")


def _sensitivity_centered_fd(
    params: J2Parameters,
    path: LoadingPath,
    parameter_map: ParameterMap,
    state_map: StateMap,
    fd_step_relative: float,
) -> SensitivityRun:
    baseline = run_path(params, path)
    n_increments = len(baseline)
    n_params = len(parameter_map.entries)
    n_state = len(state_map.entries)

    # Perturb each parameter (positive and negative) and replay the full path.
    perturbed_pos: list[list[IncrementRecord]] = []
    perturbed_neg: list[list[IncrementRecord]] = []
    step_sizes: list[float] = []
    for name, _ in parameter_map.entries:
        current = getattr(params, "SIGY0" if name.upper() == "SIGY0" else name.upper() if name.upper() != "NU" else "nu")
        # Robustly pull the current parameter value regardless of case.
        current = _current_param_value(params, name)
        step = fd_step_relative * abs(current) if abs(current) > 1.0 else fd_step_relative
        step_sizes.append(step)
        perturbed_pos.append(run_path(params.with_replaced(name, current + step), path))
        perturbed_neg.append(run_path(params.with_replaced(name, current - step), path))

    increments: list[IncrementSensitivity] = []
    for inc_index in range(n_increments):
        base = baseline[inc_index]

        dsigma = [[0.0] * n_params for _ in range(NTENS)]
        dstatev = [[0.0] * n_params for _ in range(n_state)]

        for p_index, ((name, _), step) in enumerate(zip(parameter_map.entries, step_sizes)):
            plus = perturbed_pos[p_index][inc_index]
            minus = perturbed_neg[p_index][inc_index]
            for row in range(NTENS):
                dsigma[row][p_index] = (plus.stress[row] - minus.stress[row]) / (2.0 * step)
            for s_row, (_, statev_index) in enumerate(state_map.entries):
                zero_based = statev_index - 1
                if zero_based >= len(plus.statev):
                    continue
                dstatev[s_row][p_index] = (
                    plus.statev[zero_based] - minus.statev[zero_based]
                ) / (2.0 * step)

        increments.append(
            IncrementSensitivity(
                increment=base.increment,
                dsigma_dp=tuple(tuple(row) for row in dsigma),
                dstatev_dp=tuple(tuple(row) for row in dstatev),
                stress=base.stress,
                statev=base.statev,
                yielded=base.yielded,
            )
        )

    return SensitivityRun(
        backend="centered_fd",
        parameters=parameter_map,
        state=state_map,
        path_name=path.name,
        fd_step_relative=fd_step_relative,
        increments=increments,
    )


def _current_param_value(params: J2Parameters, name: str) -> float:
    upper = name.upper()
    if upper == "E":
        return params.E
    if upper == "NU":
        return params.nu
    if upper == "SIGY0":
        return params.SIGY0
    if upper == "H":
        return params.H
    raise ValueError(f"unknown parameter {name!r}")


def _oti_available() -> bool:
    """Detect a working OTI runtime on PATH.

    We look for ``oti-config`` or an importable ``pyoti.sparse`` extension.
    Both are the canonical entry points of the upstream OTIlib project.
    """
    if shutil.which("oti-config") is not None:
        return True
    try:
        import pyoti.sparse  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# Deterministic export
# ---------------------------------------------------------------------------

def export_sensitivity_csv(
    run: SensitivityRun,
    output_dir: Path | str,
) -> dict[str, Path]:
    """Write deterministic CSVs and a JSON summary for a sensitivity run."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    param_names = run.parameters.names()
    state_names = run.state.names()

    dsigma_path = root / "DSIGMA_DP.csv"
    dstatev_path = root / "DSTATEV_DP.csv"
    primal_path = root / "primal_stress_state.csv"

    with dsigma_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["increment", "stress_component"] + list(param_names))
        for inc in run.increments:
            for row, values in enumerate(inc.dsigma_dp, start=1):
                writer.writerow([inc.increment, row] + [f"{v:.10e}" for v in values])

    with dstatev_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["increment", "state_variable"] + list(param_names))
        for inc in run.increments:
            for row, name in enumerate(state_names):
                values = inc.dstatev_dp[row] if row < len(inc.dstatev_dp) else (0.0,) * len(param_names)
                writer.writerow([inc.increment, name] + [f"{v:.10e}" for v in values])

    with primal_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["increment", "yielded"]
            + [f"stress_{i+1}" for i in range(NTENS)]
            + list(state_names)
        )
        for inc in run.increments:
            writer.writerow(
                [inc.increment, "yes" if inc.yielded else "no"]
                + [f"{v:.10e}" for v in inc.stress]
                + [f"{v:.10e}" for v in inc.statev[: len(state_names)]]
            )

    summary_path = root / "sensitivity_summary.json"
    summary = {
        "backend": run.backend,
        "path_name": run.path_name,
        "fd_step_relative": run.fd_step_relative,
        "parameters": [
            {"name": name, "props_index": idx} for name, idx in run.parameters.entries
        ],
        "state_variables": [
            {"name": name, "statev_index": idx} for name, idx in run.state.entries
        ],
        "ntens": NTENS,
        "nstatev": len(state_names),
        "nparam": len(param_names),
        "n_increments": len(run.increments),
        "warnings": run.warnings,
        "outputs": {
            "DSIGMA_DP": dsigma_path.name,
            "DSTATEV_DP": dstatev_path.name,
            "primal_stress_state": primal_path.name,
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "DSIGMA_DP": dsigma_path,
        "DSTATEV_DP": dstatev_path,
        "primal": primal_path,
        "summary": summary_path,
    }


__all__ = [
    "IncrementSensitivity",
    "OtilibUnavailable",
    "ParameterMap",
    "SensitivityRun",
    "StateMap",
    "build_softwarex_j2_path",
    "compute_j2_parameter_sensitivities",
    "export_sensitivity_csv",
]
