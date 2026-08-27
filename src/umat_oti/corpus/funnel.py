"""One funnel for every externally sourced UMAT, curated or not.

The corpus pipeline and the multi-file work are the same problem seen twice: a
Fortran file someone else wrote, a licence that may or may not permit
redistribution, dependencies that may live in sibling files, and material data
that may or may not exist. Giving each its own path would mean dependency
resolution worked for one and not the other, so both run through here.

Every candidate keeps its place in the denominator. A candidate that stops at
compilation is recorded as having stopped at compilation, with the exact
blocker, and is never quietly dropped or counted as a success. Compilation is
not verification: a candidate is only ``derivatives_verified`` when the original
and transformed builds were compiled independently, replayed over the same
loading history, agreed on stress and state, and their derivatives matched a
reference that could actually resolve them.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from umat_oti.corpus.identity import closure_identity, content_identity
from umat_oti.transform.dependency_resolution import (
    DependencyResolutionError,
    combined_source,
    infer_minimum_dimensions,
    resolve_closure,
)
from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract,
    transform_umat_for_parameter_sensitivity,
)
from umat_oti.validation.parameter_sensitivity_validation import (
    build_original_driver,
    centered_fd,
    compare,
    primal_parity,
    read_oti_csv,
    replay_reproducibly,
)
from umat_oti.validation.reference_resolution import (
    converged_value,
    measure_reference_resolution,
)

__all__ = ["FunnelStage", "STAGES", "Candidate", "MaterialData", "run_funnel"]

#: The funnel, in order. A candidate's furthest stage is the last one it passed.
STAGES = (
    "discovered",
    "license_classified",
    "entry_detected",
    "dependencies_resolved",
    "contract_constructed",
    "original_compiled",
    "transformed",
    "generated_compiled",
    "original_executed",
    "transformed_executed",
    "primal_parity",
    "reference_resolved",
    "derivatives_verified",
)

#: Licence identifiers that permit redistribution of the source itself.
REDISTRIBUTABLE_LICENSES = frozenset({
    "MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "Zlib",
    "GPL-3.0-only", "GPL-3.0-or-later", "LGPL-3.0-only", "AGPL-3.0-only",
})

#: Wall-clock ceiling for any single build or execution of third-party code.
DEFAULT_TIMEOUT_SECONDS = 300


@dataclass
class MaterialData:
    """Material properties and a loading history, with where they came from."""

    props: tuple[float, ...]
    dstran_per_increment: tuple[float, ...]
    n_increments: int
    provenance: str
    parameters: tuple[tuple[str, int], ...] = ()
    is_physical: bool = True
    #: Row-major 3x3 added to the deformation gradient each increment. Required
    #: by a finite-strain UMAT; absent for a small-strain one.
    deformation_gradient_increment: tuple[float, ...] = ()

    @property
    def finite_strain(self) -> bool:
        return bool(self.deformation_gradient_increment)

    def as_dict(self) -> dict:
        return {
            "props": list(self.props),
            "dstran_per_increment": list(self.dstran_per_increment),
            "n_increments": self.n_increments,
            "finite_strain": self.finite_strain,
            "deformation_gradient_increment":
                list(self.deformation_gradient_increment),
            "provenance": self.provenance,
            "parameters": [{"name": n, "props_index": i} for n, i in self.parameters],
            "material_is_physical": self.is_physical,
        }


@dataclass
class Candidate:
    """One externally sourced UMAT and everything known about it."""

    id: str
    source_path: Path
    repository_url: str
    commit_sha: str
    license_spdx: str
    license_source: str
    ntens: int
    nstatv: int
    ndi: int = 3
    nshr: int = 1
    entry: str = "UMAT"
    dependency_roots: tuple[Path, ...] = ()
    material: Optional[MaterialData] = None
    retrieved_at: str = ""
    notes: str = ""
    #: Absolute paths to numerical libraries the closure needs at link time.
    #: These are mathematics, not glue: DGETRF and friends are used as-is rather
    #: than stubbed, because a stub would silently change the results.
    link_libraries: tuple[str, ...] = ()
    exclude_path_fragments: tuple[str, ...] = ()
    #: Path as it should appear in evidence: relative to the pinned snapshot
    #: root, not to this machine. The snapshot lives in a sibling checkout, so
    #: an absolute path here would make every generated artefact
    #: machine-specific.
    display_path: str = ""

    @property
    def redistributable(self) -> bool:
        return self.license_spdx in REDISTRIBUTABLE_LICENSES

    def content_sha256(self) -> str:
        return hashlib.sha256(self.source_path.read_bytes()).hexdigest()

    def provenance(self, *, relative_to: Optional[Path] = None) -> dict:
        path = self.display_path or str(self.source_path)
        if not self.display_path and relative_to is not None:
            try:
                path = str(self.source_path.relative_to(relative_to))
            except ValueError:
                pass
        return {
            "id": self.id,
            "repository_url": self.repository_url,
            "commit_sha": self.commit_sha,
            "source_path": path,
            "content_sha256": self.content_sha256(),
            "license_spdx": self.license_spdx,
            "license_source": self.license_source,
            "redistribution_permitted": self.redistributable,
            "retrieved_at": self.retrieved_at,
            "entry_routine": self.entry,
            "notes": self.notes,
        }


@dataclass
class FunnelStage:
    name: str
    status: str
    reason: Optional[str] = None
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        payload = {"status": self.status}
        if self.reason:
            payload["reason"] = self.reason
        payload.update(self.detail)
        return payload


class _Record:
    def __init__(self, candidate: Candidate, repo_root: Optional[Path]):
        self.candidate = candidate
        self.repo_root = repo_root
        self.stages: dict[str, FunnelStage] = {}
        self.furthest = None
        self.blocker: Optional[str] = None
        self.extra: dict[str, Any] = {}
        # Wall clock since the previous stage closed. Reported so a reader can
        # see which stage a run spends its time in; a stage that took no
        # measurable time reports 0.0 rather than being omitted.
        self._since = time.perf_counter()

    def _elapsed(self) -> float:
        now = time.perf_counter()
        seconds = now - self._since
        self._since = now
        return round(seconds, 3)

    def passed(self, name: str, **detail) -> None:
        self.stages[name] = FunnelStage(name, "succeeded",
                                        detail={"seconds": self._elapsed(), **detail})
        self.furthest = name

    def stopped(self, name: str, reason: str, status: str = "failed", **detail):
        self.stages[name] = FunnelStage(name, status, reason=reason,
                                        detail={"seconds": self._elapsed(), **detail})
        self.blocker = f"{name}: {reason}"

    def as_dict(self) -> dict:
        return {
            **self.candidate.provenance(relative_to=self.repo_root),
            "stages": {n: s.as_dict() for n, s in self.stages.items()},
            "furthest_stage": self.furthest,
            "blocker": self.blocker,
            **self.extra,
        }


def _statev_terms(dimensions: dict) -> list[tuple[int, int]]:
    terms = []
    for text in dimensions.get("statev_terms", []):
        left, _, right = text.partition("*NTENS+")
        try:
            terms.append((int(left), int(right)))
        except ValueError:
            continue
    return terms


def _run(command: Sequence[str], cwd: Path, timeout: int) -> tuple[int, str]:
    """Run third-party build/execute steps under a wall-clock ceiling."""
    try:
        proc = subprocess.run(list(command), cwd=str(cwd), capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_funnel(candidate: Candidate, work_dir: Path, *,
               repo_root: Optional[Path] = None,
               snapshot_root: Optional[Path] = None,
               timeout: int = DEFAULT_TIMEOUT_SECONDS,
               relative_tolerance: float = 1.0e-6) -> dict:
    """Advance one candidate as far through the funnel as it can go."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    record = _Record(candidate, repo_root)

    record.passed("discovered", content_sha256=candidate.content_sha256())

    record.stages["license_classified"] = FunnelStage(
        "license_classified", "succeeded",
        detail={"license_spdx": candidate.license_spdx,
                "license_source": candidate.license_source,
                "redistribution_permitted": candidate.redistributable})
    record.furthest = "license_classified"
    if not candidate.redistributable:
        record.stopped(
            "entry_detected",
            f"licence {candidate.license_spdx!r} does not permit redistribution; "
            "this source is recorded as metadata only and is not executed",
            status="blocked_by_license")
        return record.as_dict()

    # --- entry + dependency closure --------------------------------------
    try:
        graph = resolve_closure(candidate.source_path, entry=candidate.entry,
                                roots=candidate.dependency_roots,
                                exclude=candidate.exclude_path_fragments)
    except DependencyResolutionError as exc:
        record.stopped("entry_detected", exc.detail, code=exc.code)
        return record.as_dict()
    record.passed("entry_detected", entry=candidate.entry)
    # The closure lives in the pinned snapshot, which is a sibling checkout.
    # Rendering those paths relative to the snapshot root keeps the evidence
    # machine-independent; rendering them relative to this repository would
    # leave absolute paths in every generated artefact.
    record.extra["dependency_graph"] = graph.as_dict(
        relative_to=snapshot_root or repo_root)

    if graph.missing:
        record.stopped(
            "dependencies_resolved",
            "; ".join(m.as_dict(relative_to=snapshot_root or repo_root)["diagnostic"]
                      for m in graph.missing[:4]),
            status="failed", missing=[m.symbol for m in graph.missing])
        return record.as_dict()
    if graph.conflicts:
        record.stopped(
            "dependencies_resolved",
            "these helpers have differing definitions in different files and none "
            "is local, so choosing one would change the numerics: "
            + ", ".join(d.symbol for d in graph.conflicts),
            status="failed", ambiguous=[d.symbol for d in graph.conflicts])
        return record.as_dict()
    record.passed("dependencies_resolved",
                  closure_size=len(graph.resolved),
                  multi_file=graph.is_multi_file,
                  external_files=sorted({
                      str(d.path.name) for d in graph.external_definitions}))

    # Identity is recorded here, where the resolved closure is available. A
    # multi-file source must hash as its closure everywhere it appears, or the
    # same implementation registers once as a closure and once as a single file
    # and is counted twice.
    identity = (closure_identity(graph) if graph.is_multi_file
                else content_identity(candidate.source_path))
    record.extra["identity"] = identity.as_dict()
    record.extra["canonical_source_id"] = identity.canonical_source_id

    prepared = work_dir / f"{candidate.id}_resolved.for"
    prepared.write_text(combined_source(graph), encoding="utf-8")

    # Declared dimensions must cover what the source actually addresses. A UMAT
    # driven with too small an NSTATV reads past the end of the array; the real
    # part it finds there is often zero, so primal parity passes while the
    # imaginary parts are uninitialised and the derivatives come back around
    # 1e222. That looked exactly like a transformation defect and was not one.
    dimensions = infer_minimum_dimensions([prepared])
    record.extra["inferred_dimensions"] = dimensions
    required_ntens = dimensions.get("minimum_ntens") or 0
    required_nstatv = max(
        dimensions.get("literal_statev_index") or 0,
        max((a * candidate.ntens + b
             for a, b in _statev_terms(dimensions)), default=0))
    if candidate.ntens < required_ntens or candidate.nstatv < required_nstatv:
        record.stopped(
            "contract_constructed",
            f"the declared dimensions are too small for what this source "
            f"addresses: it needs NTENS >= {required_ntens} and, at NTENS="
            f"{candidate.ntens}, NSTATV >= {required_nstatv}, but the contract "
            f"declares NTENS={candidate.ntens} and NSTATV={candidate.nstatv}. "
            "Running it would read or write outside the driver's arrays",
            status="dimension_inference_conflict",
            required_ntens=required_ntens, required_nstatv=required_nstatv)
        return record.as_dict()

    material = candidate.material
    if material is None:
        record.stopped(
            "contract_constructed",
            "no material property vector or loading history is available for this "
            "source; upstream provides none and none may be invented",
            status="blocked_by_missing_material_data")
        return record.as_dict()
    parameters = material.parameters or tuple(
        (f"P{i}", i) for i in range(1, len(material.props) + 1))
    record.passed("contract_constructed",
                  nprops=len(material.props), ntens=candidate.ntens,
                  nstatv=candidate.nstatv,
                  parameters=[n for n, _ in parameters],
                  material=material.as_dict())

    path = [list(material.dstran_per_increment) for _ in range(material.n_increments)]

    # --- original build ---------------------------------------------------
    reference_dir = work_dir / "original"
    try:
        executable = build_original_driver(
            prepared, reference_dir, ntens=candidate.ntens,
            nstatv=candidate.nstatv, nprops=len(material.props),
            finite_strain=material.finite_strain,
            link_libraries=candidate.link_libraries)
    except RuntimeError as exc:
        record.stopped("original_compiled", str(exc)[:600])
        return record.as_dict()
    record.passed("original_compiled")

    # --- transform + OTI build -------------------------------------------
    ps_dir = work_dir / "oti"
    contract = GenericPSContract(
        name=candidate.id, umat_source_path=prepared,
        parameters=parameters,
        parameter_values=tuple(material.props[i - 1] for _, i in parameters),
        state_variables=tuple((f"SDV{i}", i)
                              for i in range(1, candidate.nstatv + 1)),
        ntens=candidate.ntens, nstatv=candidate.nstatv,
        ndi=candidate.ndi, nshr=candidate.nshr,
        dstran_per_increment=tuple(material.dstran_per_increment),
        n_increments=material.n_increments,
        static_props=tuple(material.props),
        deformation_gradient_increment=tuple(
            material.deformation_gradient_increment))
    try:
        transform_umat_for_parameter_sensitivity(contract=contract, output_dir=ps_dir)
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        record.stopped("transformed", f"{type(exc).__name__}: {exc}"[:600])
        return record.as_dict()
    record.passed("transformed")

    code, output = _run(["make"], ps_dir, timeout)
    if code != 0 or not (ps_dir / "ps_driver").exists():
        record.stopped("generated_compiled",
                       f"OTI build failed (rc={code}): {output[-600:]}")
        return record.as_dict()
    record.passed("generated_compiled")

    # --- execute both -----------------------------------------------------
    # The unperturbed replay, run twice. Every later stage reads this build as
    # a function of PROPS -- parity compares one evaluation against the other
    # build's, and the reference divides the gap between two evaluations by a
    # step of order 1e-5 -- so a build that answers differently each time
    # cannot support any of it. Asking once cannot tell the difference, because
    # a run that reads uninitialised memory still returns a full set of
    # plausible numbers.
    try:
        original = replay_reproducibly(
            executable, list(material.props), path,
            ntens=candidate.ntens, nstatv=candidate.nstatv,
            deformation_gradient_increment=(
                list(material.deformation_gradient_increment)
                if material.finite_strain else None))
    except RuntimeError as exc:
        # The run-specific divergence goes to the operator, not into the
        # frozen artefact: it differs on every run by definition.
        detail = getattr(exc, "detail", "")
        if detail:
            print(f"    [{candidate.id}] first divergence: {detail}", flush=True)
        record.stopped("original_executed", str(exc)[:600])
        return record.as_dict()
    record.passed("original_executed", increments=original.increments)

    code, output = _run([str(ps_dir / "ps_driver")], ps_dir, timeout)
    if code != 0:
        record.stopped("transformed_executed",
                       f"OTI driver failed (rc={code}): {output[-600:]}")
        return record.as_dict()
    record.passed("transformed_executed")

    # --- primal parity gates the derivatives ------------------------------
    try:
        parity = primal_parity(original, ps_dir / "primal_stress_state_OTI.csv",
                               ntens=candidate.ntens, nstatv=candidate.nstatv)
    except (OSError, KeyError, ValueError) as exc:
        record.stopped("primal_parity", str(exc)[:400])
        return record.as_dict()
    worst = max((p["max_relative_difference"] for p in parity["per_increment"]),
                default=0.0)
    if not parity["agrees"]:
        record.stopped(
            "primal_parity",
            "the original and transformed builds compute different responses along "
            f"the same path (worst relative difference {worst:.3e}), so their "
            "derivatives are not comparable quantities",
            worst_relative_difference=worst)
        return record.as_dict()
    record.passed("primal_parity", worst_relative_difference=worst)

    # --- independent reference -------------------------------------------
    indices = [i for _, i in parameters]
    try:
        reference = centered_fd(
            executable, list(material.props), path,
            ntens=candidate.ntens, nstatv=candidate.nstatv,
            props_indices=indices,
            deformation_gradient_increment=(
                list(material.deformation_gradient_increment)
                if material.finite_strain else None))
    except RuntimeError as exc:
        record.stopped("reference_resolved", str(exc)[:400])
        return record.as_dict()
    record.passed("reference_resolved")

    branches = ["inelastic" if (sv and abs(sv[0]) > 1e-12) else "elastic"
                for sv in original.statev]
    stress_scale = max((abs(v) for row in original.stress for v in row), default=1.0)
    rows = []
    for array, csv_name in (("DSIGMA_DP", "DSIGMA_DP_OTI.csv"),
                            ("DSTATEV_DP", "DSTATEV_DP_OTI.csv")):
        source_csv = ps_dir / csv_name
        if not source_csv.is_file():
            continue
        if array == "DSTATEV_DP" and candidate.nstatv == 0:
            continue
        rows += compare(read_oti_csv(source_csv), reference, array=array,
                        parameters=[{"name": n, "props_index": i}
                                    for n, i in parameters],
                        branches=branches, response_scale=stress_scale)
    if not rows:
        record.stopped("derivatives_verified", "no comparable derivative rows")
        return record.as_dict()

    rows = _readjudicate(
        rows, executable=executable, props=list(material.props), path=path,
        candidate=candidate, parameters=parameters, ps_dir=ps_dir,
        tolerance=relative_tolerance,
        gradient=(list(material.deformation_gradient_increment)
                  if material.finite_strain else None))
    agreeing = [r for r in rows if r.agrees is True]
    disagreeing = [r for r in rows if r.agrees is False]
    unresolved = [r for r in rows if r.agrees is None]
    # The worst relative error is only meaningful over rows the relative test
    # actually judged. A row that agreed because its absolute difference sat
    # below the reference's noise floor can carry a relative error near 1 -- a
    # 1e-16 quantity against a 1e-13 reference -- and reporting that as the
    # headline number would suggest a disagreement where the reference simply
    # cannot resolve anything. This matches the sweep's convention.
    substantive = [r for r in rows if r.judged_by
                   and r.judged_by.startswith("relative")]
    by_judgement: dict[str, int] = {}
    for row in rows:
        by_judgement[row.judged_by] = by_judgement.get(row.judged_by, 0) + 1
    record.extra["comparison"] = {
        "rows": len(rows), "agreeing": len(agreeing),
        "disagreeing": len(disagreeing), "reference_unresolved": len(unresolved),
        "substantive_rows": len(substantive),
        "rows_by_judgement": dict(sorted(by_judgement.items())),
        "worst_substantive_relative_error": max(
            (r.relative_error for r in substantive if r.relative_error is not None),
            default=None),
    }
    if disagreeing:
        record.stopped(
            "derivatives_verified",
            f"{len(disagreeing)} of {len(rows)} rows disagree with a reference that "
            "can resolve them")
    elif unresolved:
        record.stopped(
            "derivatives_verified",
            f"no row disagrees; {len(unresolved)} of {len(rows)} sit below what "
            "centred differences can resolve, so those directions are withheld",
            status="unresolved")
    else:
        record.passed("derivatives_verified", rows=len(rows))
    return record.as_dict()


def _readjudicate(rows, *, executable, props, path, candidate, parameters,
                  ps_dir, tolerance, gradient=None):
    """Re-judge disagreeing rows against a converged step, as the sweep does."""
    failing = [r for r in rows if r.agrees is False]
    if not failing:
        return rows
    by_name = {n: i for n, i in parameters}
    csv_for = {"DSIGMA_DP": "DSIGMA_DP_OTI.csv", "DSTATEV_DP": "DSTATEV_DP_OTI.csv"}
    replacements: dict = {}
    for parameter_name, array in sorted({(r.parameter, r.array) for r in failing}):
        index = by_name.get(parameter_name)
        source_csv = ps_dir / csv_for.get(array, "")
        if index is None or not source_csv.is_file():
            continue
        ladder = measure_reference_resolution(
            executable, props, path, ntens=candidate.ntens,
            nstatv=candidate.nstatv, props_index=index, array=array,
            deformation_gradient_increment=gradient)
        table = read_oti_csv(source_csv)
        for row in failing:
            if (row.parameter, row.array) != (parameter_name, array):
                continue
            best = converged_value(ladder, row.increment, row.component)
            if best is None:
                continue
            value, step, uncertainty = best
            entry = table.get((row.increment, row.component)) or {}
            oti_value = entry.get(parameter_name.upper(), entry.get(parameter_name))
            if oti_value is None:
                continue
            magnitude = max(abs(oti_value), abs(value))
            absolute = abs(oti_value - value)
            relative = absolute / magnitude if magnitude else 0.0
            if relative <= tolerance:
                agrees: Optional[bool] = True
            elif absolute <= uncertainty:
                agrees = None
            else:
                agrees = False
            replacements[(row.array, row.parameter, row.increment, row.component)] = (
                value, step, absolute, relative, agrees)
    for row in rows:
        key = (row.array, row.parameter, row.increment, row.component)
        replacement = replacements.get(key)
        if replacement is None or row.agrees is not False:
            continue
        value, step, absolute, relative, agrees = replacement
        row.reference, row.absolute_error, row.relative_error = value, absolute, relative
        row.agrees = agrees
        row.judged_by = (f"reference_unresolved_at_converged_step_{step:g}"
                         if agrees is None else f"relative_at_converged_step_{step:g}")
    return rows
