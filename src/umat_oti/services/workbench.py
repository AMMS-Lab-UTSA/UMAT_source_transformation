"""One request, one backend, for every front end.

The interface a user drives and the pipeline a paper cites must run the same
code, or a screenshot stops being evidence. This module is that code: it takes a
single request describing a UMAT and the derivative products wanted from it, and
returns per-product outcomes with the stage evidence behind them.

Nothing here is interface-specific and nothing numerical lives above it. The
Streamlit app builds a :class:`WorkbenchRequest`, calls :func:`run_workbench`,
and renders what comes back; it never computes a derivative, never decides a
verdict, and never has its own tolerance.

Two rules the outcome vocabulary exists to enforce:

*Compilation is not verification.* A product whose source transformed and
compiled is ``compiled``, never ``verified``. ``verified`` requires that both
implementations ran, agreed on the primal response, and that the derivative
matched a reference able to resolve it.

*Primal parity gates everything.* If the two builds disagree on stress or state
they are not solving the same problem, and their derivatives are not comparable
quantities. Every derivative product below such a failure is ``blocked``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from umat_oti.corpus.funnel import Candidate, MaterialData, run_funnel
from umat_oti.corpus.identity import closure_identity, content_identity
from umat_oti.transform.dependency_resolution import (
    DependencyResolutionError, infer_minimum_dimensions, resolve_closure,
)
from umat_oti.transform.internal_jacobian import discover_local_solves

__all__ = [
    "PRODUCTS",
    "OUTCOMES",
    "LoadingHistory",
    "WorkbenchRequest",
    "ProductOutcome",
    "WorkbenchResult",
    "analyse_source",
    "run_workbench",
]

#: The derivative products a request may ask for.
PRODUCTS = (
    "DDSDDE",
    "INTERNAL_JACOBIAN",
    "HIGHER_ORDER_STRESS",
    "DSIGMA_DP",
    "DSTATEV_DP",
)

#: Every outcome a product can have. "compiled" is deliberately distinct from
#: "verified", and "not_requested" is distinct from "blocked".
OUTCOMES = (
    "verified",
    "failed",
    "unresolved",
    "blocked",
    "unsupported",
    "not_requested",
    "compiled",
)


@dataclass
class LoadingHistory:
    """The path a material point is driven along."""

    dstran_per_increment: tuple[float, ...]
    n_increments: int
    deformation_gradient_increment: tuple[float, ...] = ()
    label: str = ""
    provenance: str = "declared in the request"

    @property
    def finite_strain(self) -> bool:
        return bool(self.deformation_gradient_increment)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "dstran_per_increment": list(self.dstran_per_increment),
            "n_increments": self.n_increments,
            "finite_strain": self.finite_strain,
            "deformation_gradient_increment":
                list(self.deformation_gradient_increment),
            "provenance": self.provenance,
        }


@dataclass
class WorkbenchRequest:
    """Everything the backend needs, and nothing about how it is displayed."""

    name: str
    source_path: Path
    ntens: int
    nstatv: int
    props: tuple[float, ...]
    loading: LoadingHistory
    dependency_roots: tuple[Path, ...] = ()
    exclude_path_fragments: tuple[str, ...] = ()
    ndi: int = 3
    nshr: int = 3
    entry: str = "UMAT"
    parameters: tuple[tuple[str, int], ...] = ()
    state_names: tuple[str, ...] = ()
    products: tuple[str, ...] = ("DSIGMA_DP",)
    higher_order_max: int = 4
    material_provenance: str = ""

    def validate(self) -> list[str]:
        """Every problem with the request, not just the first one."""
        problems: list[str] = []
        if not self.name.strip():
            problems.append("the request needs a name")
        if not Path(self.source_path).is_file():
            problems.append(f"source file not found: {self.source_path}")
        if self.ntens <= 0:
            problems.append("NTENS must be positive")
        if self.nstatv < 0:
            problems.append("NSTATV cannot be negative")
        if self.ndi + self.nshr != self.ntens:
            problems.append(
                f"NDI + NSHR must equal NTENS ({self.ndi} + {self.nshr} "
                f"!= {self.ntens})")
        if not self.props:
            problems.append("no material properties were given")
        for name, index in self.parameters:
            if not 1 <= index <= len(self.props):
                problems.append(
                    f"parameter {name!r} maps to PROPS({index}), outside the "
                    f"{len(self.props)} properties supplied")
        unknown = [p for p in self.products if p not in PRODUCTS]
        if unknown:
            problems.append(f"unknown derivative products: {', '.join(unknown)}")
        if not self.products:
            problems.append("no derivative product was requested")
        if self.loading.n_increments <= 0:
            problems.append("the loading history needs at least one increment")
        if (not self.loading.finite_strain
                and len(self.loading.dstran_per_increment) != self.ntens):
            problems.append(
                f"the strain increment has {len(self.loading.dstran_per_increment)} "
                f"components but NTENS is {self.ntens}")
        if self.loading.finite_strain and \
                len(self.loading.deformation_gradient_increment) != 9:
            problems.append(
                "a deformation-gradient increment needs nine row-major values")
        if "DSTATEV_DP" in self.products and self.nstatv <= 0:
            problems.append(
                "DSTATEV_DP was requested but the model declares no state variables")
        return problems

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "source": Path(self.source_path).name,
            "dependency_roots": [str(Path(r).name) for r in self.dependency_roots],
            "entry_routine": self.entry,
            "ntens": self.ntens, "ndi": self.ndi, "nshr": self.nshr,
            "nstatv": self.nstatv,
            "props": list(self.props),
            "parameters": [{"name": n, "props_index": i} for n, i in self.parameters],
            "state_names": list(self.state_names),
            "products": list(self.products),
            "loading": self.loading.as_dict(),
            "material_provenance": self.material_provenance,
        }


@dataclass
class ProductOutcome:
    product: str
    status: str
    reason: Optional[str] = None
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        payload = {"product": self.product, "status": self.status}
        if self.reason:
            payload["reason"] = self.reason
        payload.update(self.detail)
        return payload


@dataclass
class WorkbenchResult:
    request: dict
    analysis: dict
    stages: dict = field(default_factory=dict)
    products: dict[str, ProductOutcome] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    primal_parity: dict = field(default_factory=dict)
    comparison: dict = field(default_factory=dict)
    dependency_graph: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "request": self.request,
            "analysis": self.analysis,
            "dependency_graph": self.dependency_graph,
            "stages": self.stages,
            "primal_parity": self.primal_parity,
            "comparison": self.comparison,
            "products": {k: v.as_dict() for k, v in sorted(self.products.items())},
            "artifacts": self.artifacts,
            "errors": self.errors,
        }


def analyse_source(source: Path, roots: Sequence[Path] = (),
                   entry: str = "UMAT",
                   exclude: Sequence[str] = ()) -> dict:
    """Read a source and report what it is, before anything is transformed.

    This is what the interface shows a user after they pick a file: the entry
    routine, the helper closure and where each helper came from, what the source
    needs from a library or the Abaqus runtime, and the smallest dimensions it
    can legally be driven with.
    """
    source = Path(source)
    text = source.read_text(encoding="utf-8", errors="replace")
    fixed = source.suffix.lower() in {".for", ".f", ".f77"}
    analysis: dict[str, Any] = {
        "source": source.name,
        "source_form": "fixed" if fixed else "free",
        "lines": text.count("\n") + 1,
        "entry_routine": entry,
        "defines_entry": f"SUBROUTINE {entry.upper()}" in text.upper(),
    }
    try:
        graph = resolve_closure(source, entry=entry, roots=roots, exclude=exclude)
    except DependencyResolutionError as exc:
        analysis["dependency_error"] = exc.detail
        analysis["dependency_error_code"] = exc.code
        return analysis

    identity = (closure_identity(graph) if graph.is_multi_file
                else content_identity(source))
    analysis.update({
        "identity": identity.as_dict(),
        "helper_routines": sorted(n for n in graph.resolved if n != entry.upper()),
        "closure_size": len(graph.resolved),
        "multi_file": graph.is_multi_file,
        "external_files": sorted({d.path.name for d in graph.external_definitions}),
        "missing_symbols": [m.as_dict() for m in graph.missing],
        "ambiguous_symbols": [d.symbol for d in graph.conflicts],
        "abaqus_runtime_calls": list(graph.runtime_calls),
        "external_library_calls": dict(graph.library_calls),
        "dimensions": infer_minimum_dimensions([source]),
        "local_solves": [s.as_dict() for s in discover_local_solves(text)],
    })
    analysis["graph"] = graph.as_dict()
    return analysis


def _blocked(products: Sequence[str], reason: str) -> dict[str, ProductOutcome]:
    return {p: ProductOutcome(p, "blocked", reason) for p in products}


def run_workbench(request: WorkbenchRequest, work_dir: Path) -> WorkbenchResult:
    """Run a request through the canonical pipeline and report per product."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    problems = request.validate()
    if problems:
        return WorkbenchResult(request=request.as_dict(), analysis={},
                               errors=problems)

    analysis = analyse_source(request.source_path, request.dependency_roots,
                              request.entry, request.exclude_path_fragments)
    result = WorkbenchResult(request=request.as_dict(), analysis=analysis)
    result.dependency_graph = analysis.get("graph", {})

    requested = tuple(request.products)
    for product in PRODUCTS:
        if product not in requested:
            result.products[product] = ProductOutcome(
                product, "not_requested",
                "this product was not asked for in the request")

    if analysis.get("dependency_error"):
        result.products.update(_blocked(requested, analysis["dependency_error"]))
        return result
    if analysis.get("missing_symbols"):
        symbols = ", ".join(m["symbol"] for m in analysis["missing_symbols"])
        result.products.update(_blocked(
            requested, f"the helper closure is incomplete: {symbols} could not be "
                       "resolved from the declared dependency roots"))
        return result
    if analysis.get("ambiguous_symbols"):
        result.products.update(_blocked(
            requested,
            "these helpers have differing definitions in different files and none "
            "is local, so choosing one would change the numerics: "
            + ", ".join(analysis["ambiguous_symbols"])))
        return result

    # The parameter-sensitivity products run through the corpus funnel, which is
    # the same path the published rounds use.
    sensitivity = [p for p in requested if p in ("DSIGMA_DP", "DSTATEV_DP")]
    candidate = Candidate(
        id=request.name, source_path=Path(request.source_path),
        repository_url="(local)", commit_sha="0" * 40,
        license_spdx="MIT", license_source="supplied by the caller",
        ntens=request.ntens, nstatv=request.nstatv, ndi=request.ndi,
        nshr=request.nshr, entry=request.entry,
        dependency_roots=tuple(request.dependency_roots),
        exclude_path_fragments=tuple(request.exclude_path_fragments),
        material=MaterialData(
            props=tuple(request.props),
            dstran_per_increment=tuple(request.loading.dstran_per_increment),
            n_increments=request.loading.n_increments,
            provenance=(request.material_provenance
                        or request.loading.provenance),
            parameters=tuple(request.parameters),
            deformation_gradient_increment=tuple(
                request.loading.deformation_gradient_increment)))

    record = run_funnel(candidate, work_dir / "pipeline")
    result.stages = record.get("stages", {})
    result.comparison = record.get("comparison", {})
    result.primal_parity = result.stages.get("primal_parity", {})

    for name, relative in (
            ("resolved_source", f"pipeline/{request.name}_resolved.for"),
            ("transformed_source", "pipeline/oti/umat_oti_lifted.f90"),
            ("oti_module", "pipeline/oti/ps_driver.f90"),
            ("dsigma_csv", "pipeline/oti/DSIGMA_DP_OTI.csv"),
            ("dstatev_csv", "pipeline/oti/DSTATEV_DP_OTI.csv"),
            ("primal_csv", "pipeline/oti/primal_stress_state_OTI.csv")):
        candidate_path = work_dir / relative
        if candidate_path.is_file():
            result.artifacts[name] = str(candidate_path)

    furthest = record.get("furthest_stage")
    blocker = record.get("blocker")
    parity_ok = result.primal_parity.get("status") == "succeeded"
    verdict = result.stages.get("derivatives_verified", {})

    for product in sensitivity:
        if verdict.get("status") == "succeeded":
            outcome = ProductOutcome(
                product, "verified",
                detail={"rows": result.comparison.get("rows"),
                        "substantive_rows": result.comparison.get("substantive_rows"),
                        "worst_substantive_relative_error":
                            result.comparison.get("worst_substantive_relative_error")})
        elif verdict.get("status") == "unresolved":
            outcome = ProductOutcome(
                product, "unresolved", verdict.get("reason"),
                detail={"reference_unresolved":
                        result.comparison.get("reference_unresolved")})
        elif verdict.get("status") == "failed":
            outcome = ProductOutcome(product, "failed", verdict.get("reason"))
        elif not parity_ok and furthest in ("generated_compiled", "transformed",
                                            "original_compiled",
                                            "original_executed",
                                            "transformed_executed"):
            reached_compile = furthest in (
                "generated_compiled", "original_executed", "transformed_executed")
            outcome = ProductOutcome(
                product, "compiled" if reached_compile else "failed",
                (blocker or "the run stopped before the derivative comparison") +
                ". Compiling is not verification: nothing has been checked "
                "numerically.")
        else:
            outcome = ProductOutcome(product, "blocked", blocker)
        result.products[product] = outcome

    if "INTERNAL_JACOBIAN" in requested:
        result.products["INTERNAL_JACOBIAN"] = _internal_jacobian(
            request, analysis, work_dir, parity_ok, blocker)

    if "DDSDDE" in requested:
        result.products["DDSDDE"] = _consistent_tangent(request, work_dir)

    if "HIGHER_ORDER_STRESS" in requested:
        result.products["HIGHER_ORDER_STRESS"] = ProductOutcome(
            "HIGHER_ORDER_STRESS", "unsupported",
            "stress derivatives of order two and above are produced by the "
            "contract pipeline (umat_oti.services.transformation) and are not "
            "yet wired into this request; asking for them here reports "
            "unsupported rather than silently returning nothing.")

    manifest = work_dir / "workbench_result.json"
    manifest.write_text(json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    result.artifacts["result_manifest"] = str(manifest)
    return result


def _consistent_tangent(request: WorkbenchRequest, work_dir: Path) -> ProductOutcome:
    """Check the tangent the OTI build returns against the original build.

    This runs its own strain-seeded transformation. The parameter-sensitivity
    build seeds PROPS, so the DDSDDE it returns is whatever the source
    hand-coded rather than an OTI result; seeding DSTRAN is what makes the
    tangent a derivative the transformation produced.
    """
    from umat_oti.validation.tangent_validation import (  # noqa: PLC0415
        TangentCase, verify_tangent, write_tangent_evidence,
    )

    case = TangentCase(
        name=request.name, source_path=Path(request.source_path),
        props=tuple(request.props),
        dstran_per_increment=tuple(request.loading.dstran_per_increment),
        n_increments=request.loading.n_increments,
        ntens=request.ntens, nstatv=request.nstatv,
        ndi=request.ndi, nshr=request.nshr, entry=request.entry,
        parameters=tuple(request.parameters),
        state_names=tuple(request.state_names))
    out_dir = work_dir / "tangent"
    try:
        outcome = verify_tangent(case, out_dir)
    except Exception as error:  # noqa: BLE001 - reported, never swallowed
        return ProductOutcome("DDSDDE", "failed",
                              f"{type(error).__name__}: {error}"[:400])
    write_tangent_evidence(outcome, out_dir)

    stages = outcome.stages
    if stages.get("tangent_verified", {}).get("status") == "succeeded":
        return ProductOutcome("DDSDDE", "verified", detail=outcome.summary)
    if stages.get("tangent_verified", {}).get("status") == "failed":
        return ProductOutcome("DDSDDE", "failed", outcome.blocker,
                              detail=outcome.summary)
    if stages.get("reference_resolved", {}).get("status") == "failed":
        return ProductOutcome("DDSDDE", "unresolved", outcome.blocker,
                              detail=outcome.summary)
    reached = outcome.furthest_stage
    if reached in ("generated_compiled", "transformed_executed",
                   "original_executed", "original_compiled"):
        return ProductOutcome(
            "DDSDDE", "compiled",
            (outcome.blocker or "the run stopped before the tangent comparison")
            + ". Compiling is not verification: nothing has been checked "
              "numerically.")
    return ProductOutcome("DDSDDE", "blocked", outcome.blocker)


def _internal_jacobian(request: WorkbenchRequest, analysis: dict, work_dir: Path,
                       parity_ok: bool, blocker: Optional[str]) -> ProductOutcome:
    from umat_oti.validation.internal_jacobian_validation import (  # noqa: PLC0415
        InternalJacobianCase, verify_internal_jacobian,
    )

    solves = analysis.get("local_solves") or []
    if not solves:
        return ProductOutcome(
            "INTERNAL_JACOBIAN", "unsupported",
            "this model integrates its constitutive law without a local Newton "
            "iteration, so it has no internal Jacobian to extract")

    case = InternalJacobianCase(
        model=request.name, source_path=Path(request.source_path),
        props=tuple(request.props),
        dstran_per_increment=tuple(request.loading.dstran_per_increment),
        n_increments=request.loading.n_increments,
        ntens=request.ntens, nstatv=request.nstatv,
        ndi=request.ndi, nshr=request.nshr,
        state_names=tuple(request.state_names))
    record = verify_internal_jacobian(case, work_dir / "internal_jacobian")
    verdict = record.get("stages", {}).get("jacobian_verified", {})
    extracted = record.get("extracted")
    if verdict.get("status") == "succeeded" and extracted:
        return ProductOutcome(
            "INTERNAL_JACOBIAN", "verified",
            detail={"iterate": solves[0].get("iteration_variable"),
                    "residual": solves[0].get("residual_variable"),
                    "hand_coded_variable":
                        solves[0].get("hand_coded_jacobian_variable"),
                    "extracted": extracted,
                    "hand_coded_audit": record.get("hand_coded_audit"),
                    "reference_convergence": record.get("reference_convergence")})
    if verdict.get("status") == "blocked_by_external_dependency":
        return ProductOutcome("INTERNAL_JACOBIAN", "unresolved", verdict.get("reason"))
    return ProductOutcome(
        "INTERNAL_JACOBIAN", "blocked" if not parity_ok else "failed",
        record.get("stages", {}).get(record.get("furthest_stage") or "", {})
        .get("reason") or blocker
        or "the extraction did not reach a numerical comparison")
