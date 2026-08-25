"""Extract and verify a UMAT's internal constitutive Jacobian.

The quantity of interest is ``dF/dg``: the derivative of a local Newton solve's
residual with respect to its iterate, evaluated at the converged iterate of one
increment.  Abaqus UMATs normally carry this coefficient as hand-written code
(``FJAC``, ``DF``, ...).  This module obtains it three independent ways:

===================  =====================================================
``oti``              coefficient extracted by the OTI-lifted build
``finite_difference``  centred differences of the *untransformed* build
``hand_coded``       the value the original source computes for itself
===================  =====================================================

The finite-difference column is the reference.  ``oti`` is the quantity being
verified against it.  ``hand_coded`` is a third, *audited* column: a UMAT whose
own Jacobian disagrees with the finite-difference reference has a defective (or
deliberately approximate) tangent, which is a finding about that source, not
evidence about the transformation.  The hand-coded value is never used as the
reference for the OTI value.

All three observe the same local state by construction: the two builds compile
the *same* injected source, and seeding is confined to a single increment so no
history contamination enters the extracted coefficient.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from umat_oti.transform.internal_jacobian import LocalSolve, discover_local_solves
from umat_oti.transform.local_jacobian_probe import (
    ProbeInjectionError,
    inject_local_solve_probe,
    plan_probe_slots,
)
from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract,
    transform_umat_for_parameter_sensitivity,
)
from umat_oti.validation.parameter_sensitivity_validation import (
    DEFAULT_REL_STEP,
    build_original_driver,
    centered_fd,
    compare,
    primal_parity,
    read_oti_csv,
    replay,
)

__all__ = [
    "InternalJacobianCase",
    "verify_internal_jacobian",
    "STAGE_ORDER",
]

#: The funnel an internal-Jacobian case walks.  A case reports the furthest
#: stage it reached; every stage carries its own status and reason.
STAGE_ORDER = (
    "solve_discovered",
    "probe_injected",
    "recording_is_non_perturbing",
    "converged_iterate_located",
    "compiled_original_probe",
    "compiled_oti_probe",
    "primal_parity",
    "fd_reference_resolved",
    "jacobian_extracted",
    "jacobian_verified",
)

SEED_NAME = "GSEED"


@dataclass
class InternalJacobianCase:
    """Inputs describing one local solve to extract and verify."""

    model: str
    source_path: Path
    props: tuple[float, ...]
    dstran_per_increment: tuple[float, ...]
    n_increments: int
    ntens: int
    nstatv: int
    ndi: int
    nshr: int
    target_increment: Optional[int] = None
    solve_index: int = 0
    rel_step: float = DEFAULT_REL_STEP
    state_names: tuple[str, ...] = field(default_factory=tuple)

    @property
    def nprops(self) -> int:
        return len(self.props)

    @property
    def path(self) -> list[list[float]]:
        return [list(self.dstran_per_increment) for _ in range(self.n_increments)]


def _stage(record: dict, name: str, status: str, **extra: Any) -> None:
    entry = {"status": status}
    entry.update(extra)
    record["stages"][name] = entry
    if status == "succeeded":
        record["furthest_stage"] = name


def verify_internal_jacobian(case: InternalJacobianCase, out_dir: Path) -> dict:
    """Run the full extract-and-verify funnel for one local solve."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "model": case.model,
        "source": case.source_path.name,
        "stages": {},
        "furthest_stage": None,
        "rows": [],
    }

    text = case.source_path.read_text(encoding="utf-8", errors="replace")
    solves = discover_local_solves(text)
    if len(solves) <= case.solve_index:
        _stage(record, "solve_discovered", "unsupported",
               reason="no local Newton solve was discovered in this source")
        return record
    solve: LocalSolve = solves[case.solve_index]
    record["solve"] = solve.as_dict()
    _stage(record, "solve_discovered", "succeeded")

    slots = plan_probe_slots(nstatv=case.nstatv, nprops=case.nprops)
    record["slots"] = slots.as_dict()

    # ---- inject: an observing pass and a seeding pass ---------------------
    try:
        observe = inject_local_solve_probe(
            text, solve, slots, target_increment=1, override_iterate=False)
    except ProbeInjectionError as exc:
        _stage(record, "probe_injected", "unsupported", reason=exc.detail, code=exc.code)
        return record
    observe_path = out_dir / "umat_probe_observe.for"
    observe_path.write_text(observe.source, encoding="utf-8")

    # ---- control: recording must not change the primal response -----------
    reference_dir = out_dir / "original_reference"
    try:
        plain_exe = build_original_driver(
            case.source_path, reference_dir / "plain", ntens=case.ntens,
            nstatv=case.nstatv, nprops=case.nprops)
        plain = replay(plain_exe, case.props, case.path,
                       ntens=case.ntens, nstatv=case.nstatv)
        observe_exe = build_original_driver(
            observe_path, reference_dir / "observe", ntens=case.ntens,
            nstatv=slots.nstatv, nprops=slots.nprops)
        observed = replay(observe_exe, list(case.props) + [0.0], case.path,
                          ntens=case.ntens, nstatv=slots.nstatv)
    except RuntimeError as exc:
        _stage(record, "probe_injected", "failed", reason=str(exc)[:400])
        return record
    _stage(record, "probe_injected", "succeeded")

    drift = max(
        (abs(a - b) for ra, rb in zip(plain.stress, observed.stress)
         for a, b in zip(ra, rb)),
        default=0.0)
    state_drift = max(
        (abs(ra[i] - rb[i]) for ra, rb in zip(plain.statev, observed.statev)
         for i in range(case.nstatv)),
        default=0.0)
    non_perturbing = drift == 0.0 and state_drift == 0.0
    _stage(record, "recording_is_non_perturbing",
           "succeeded" if non_perturbing else "failed",
           max_stress_drift=drift, max_state_drift=state_drift,
           reason=None if non_perturbing else (
               "adding the recording assignments changed the primal response, so "
               "the recorded residual is not the original source's residual"))
    if not non_perturbing:
        return record

    # ---- locate the converged iterate to probe about ----------------------
    iterates = [row[slots.iterate - 1] for row in observed.statev]
    residuals = [row[slots.residual - 1] for row in observed.statev]
    hand_coded = [row[slots.jacobian - 1] for row in observed.statev]
    if case.target_increment is not None:
        target = case.target_increment
    else:
        entered = [(abs(v), i + 1) for i, v in enumerate(iterates) if v != 0.0]
        target = max(entered)[1] if entered else 0
    if not 1 <= target <= len(iterates) or iterates[target - 1] == 0.0:
        _stage(record, "converged_iterate_located", "unsupported",
               reason=("the local solve was never entered with a non-zero iterate "
                       "along this loading path, so there is no converged iterate "
                       "to differentiate about"),
               iterates=iterates)
        return record
    gamma = iterates[target - 1]
    record["target_increment"] = target
    record["converged_iterate"] = gamma
    record["residual_at_iterate"] = residuals[target - 1]
    record["hand_coded_jacobian"] = hand_coded[target - 1]
    _stage(record, "converged_iterate_located", "succeeded",
           increment=target, iterate=gamma, residual=residuals[target - 1])

    # ---- seeding pass: the loop becomes an evaluator of F(g) --------------
    try:
        seeded = inject_local_solve_probe(
            text, solve, slots, target_increment=target, override_iterate=True)
    except ProbeInjectionError as exc:
        _stage(record, "compiled_original_probe", "unsupported",
               reason=exc.detail, code=exc.code)
        return record
    seeded_path = out_dir / "umat_probe_seeded.for"
    seeded_path.write_text(seeded.source, encoding="utf-8")
    record["injection"] = seeded.as_dict()

    probe_props = list(case.props) + [gamma]
    try:
        seeded_exe = build_original_driver(
            seeded_path, reference_dir / "seeded", ntens=case.ntens,
            nstatv=slots.nstatv, nprops=slots.nprops)
        seeded_run = replay(seeded_exe, probe_props, case.path,
                            ntens=case.ntens, nstatv=slots.nstatv)
    except RuntimeError as exc:
        _stage(record, "compiled_original_probe", "failed", reason=str(exc)[:400])
        return record
    _stage(record, "compiled_original_probe", "succeeded")

    # The seeded build must reproduce the observing build at the converged
    # iterate: forcing the iterate to the value it already converged to is a
    # no-op if the probe really does replace the update rather than the physics.
    probe_residual = seeded_run.statev[target - 1][slots.residual - 1]
    probe_jacobian = seeded_run.statev[target - 1][slots.jacobian - 1]
    record["probe_residual_at_iterate"] = probe_residual
    record["probe_hand_coded_jacobian"] = probe_jacobian

    # ---- OTI build of the same injected source ----------------------------
    ps_dir = out_dir / "oti_probe"
    state_names = tuple(
        case.state_names[i] if i < len(case.state_names) else f"SDV{i + 1}"
        for i in range(slots.nstatv))
    contract = GenericPSContract(
        name=f"{case.model}_internal_jacobian",
        umat_source_path=seeded_path,
        parameters=((SEED_NAME, slots.seed_props),),
        parameter_values=(gamma,),
        state_variables=tuple((name, i + 1) for i, name in enumerate(state_names)),
        ntens=case.ntens,
        nstatv=slots.nstatv,
        ndi=case.ndi,
        nshr=case.nshr,
        dstran_per_increment=tuple(case.dstran_per_increment),
        n_increments=case.n_increments,
        static_props=tuple(probe_props),
    )
    try:
        transform_umat_for_parameter_sensitivity(contract=contract, output_dir=ps_dir)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        _stage(record, "compiled_oti_probe", "failed",
               reason=f"{type(exc).__name__}: {exc}"[:400])
        return record
    build = subprocess.run(["make"], cwd=ps_dir, capture_output=True, text=True)
    if build.returncode != 0 or not (ps_dir / "ps_driver").exists():
        _stage(record, "compiled_oti_probe", "failed",
               reason=f"OTI probe build failed: {build.stderr[:400]}")
        return record
    run = subprocess.run([str(ps_dir / "ps_driver")], cwd=ps_dir,
                         capture_output=True, text=True)
    if run.returncode != 0:
        _stage(record, "compiled_oti_probe", "failed",
               reason=f"OTI probe run failed (rc={run.returncode}): {run.stderr[:400]}")
        return record
    _stage(record, "compiled_oti_probe", "succeeded")

    try:
        parity = primal_parity(seeded_run, ps_dir / "primal_stress_state_OTI.csv",
                               ntens=case.ntens, nstatv=slots.nstatv)
    except (OSError, KeyError, ValueError) as exc:
        _stage(record, "primal_parity", "failed", reason=str(exc)[:300])
        return record
    worst = max((p["max_relative_difference"] for p in parity["per_increment"]),
                default=0.0)
    _stage(record, "primal_parity", "succeeded" if parity["agrees"] else "failed",
           worst_relative_difference=worst,
           reason=None if parity["agrees"] else (
               "the original and OTI builds of the injected source compute different "
               "responses, so their residual derivatives are not comparable"))
    if not parity["agrees"]:
        return record

    # ---- independent reference: centred FD of the untransformed build -----
    try:
        reference = centered_fd(
            seeded_exe, probe_props, case.path, ntens=case.ntens,
            nstatv=slots.nstatv, props_indices=[slots.seed_props],
            rel_step=case.rel_step)
    except RuntimeError as exc:
        _stage(record, "fd_reference_resolved", "failed", reason=str(exc)[:400])
        return record
    fd_value = reference[slots.seed_props]["dstatev"][target - 1][slots.residual - 1]
    _stage(record, "fd_reference_resolved", "succeeded",
           step=reference[slots.seed_props]["step"], value=fd_value)

    oti_csv = ps_dir / "DSTATEV_DP_OTI.csv"
    if not oti_csv.exists():
        _stage(record, "jacobian_extracted", "failed",
               reason="the OTI probe build produced no DSTATEV_DP output")
        return record
    oti_table = read_oti_csv(oti_csv)
    entry = oti_table.get((target, slots.residual))
    if entry is None:
        _stage(record, "jacobian_extracted", "failed",
               reason=f"no OTI row for increment {target}, state slot {slots.residual}")
        return record
    oti_value = entry.get(SEED_NAME, entry.get(SEED_NAME.lower()))
    if oti_value is None:
        _stage(record, "jacobian_extracted", "failed",
               reason=f"the OTI output carries no {SEED_NAME} direction")
        return record
    record["extracted"] = {
        "oti": oti_value,
        "finite_difference": fd_value,
        "hand_coded": probe_jacobian,
    }
    _stage(record, "jacobian_extracted", "succeeded", value=oti_value)

    # ---- verdict: OTI vs FD (verified), hand-coded vs FD (audited) --------
    stress_scale = max((abs(v) for row in seeded_run.stress for v in row), default=1.0)
    parameter = {"name": SEED_NAME, "props_index": slots.seed_props}
    branches = ["local_solve"] * case.n_increments
    rows = [
        row for row in compare(
            {(target, slots.residual): {SEED_NAME: oti_value}},
            reference, array="DSTATEV_DP", parameters=[parameter],
            branches=branches, response_scale=stress_scale)
    ]
    record["rows"] = [r.as_dict() if hasattr(r, "as_dict") else vars(r) for r in rows]
    verdicts = {r.agrees for r in rows}
    if verdicts == {True}:
        status, reason = "succeeded", None
    elif None in verdicts and False not in verdicts:
        status, reason = "blocked_by_external_dependency", (
            "the centred-difference reference could not resolve a value of this "
            "magnitude, so it cannot adjudicate the extracted coefficient")
    else:
        status, reason = "failed", (
            "the extracted coefficient disagrees with the centred-difference "
            "reference beyond its resolution")
    audit_absolute = abs(probe_jacobian - fd_value)
    audit_relative = audit_absolute / max(abs(fd_value), 1e-300)
    record["hand_coded_audit"] = {
        "absolute_difference": audit_absolute,
        "relative_difference": audit_relative,
        "note": ("the source's own Jacobian is audited against the same reference; "
                 "it is never used as the reference for the extracted value"),
    }
    _stage(record, "jacobian_verified", status, reason=reason)
    return record
