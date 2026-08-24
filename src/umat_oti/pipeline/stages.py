"""The canonical UMAT-OTI stage graph.

The stage names and their order are the pipeline's public shape:

    source_acquisition -> source_inventory -> license_classification
    -> entry_routine_detection -> dependency_closure -> contract_inference
    -> derivative_request_normalization -> source_transformation
    -> oti_support_generation -> compilation -> material_point_execution
    -> primal_parity -> derivative_verification -> abaqus_validation
    -> evidence_generation -> distributable_package

Stages that are not yet implemented are *registered anyway*, reporting
``unsupported`` with the reason. Leaving them out would make a partial run look
complete; naming them makes the gap legible in every run manifest.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from umat_oti.pipeline.engine import FunctionStage, RunContext, StageOutcome
from umat_oti.pipeline.manifest import Artifact, sha256_file
from umat_oti.pipeline.status import StageStatus, require

def _resolve_declared_sources(ctx: RunContext) -> list[Path]:
    """Resolve the contract's declared sources without running the stage.

    Shared by the stage and by its cache key so the two cannot disagree about
    which files matter.
    """
    declared = ctx.contract.get("sources") or (
        [ctx.contract["source"]] if ctx.contract.get("source") else []
    )
    base = Path(ctx.contract.get("_base_dir") or ctx.repo_root)
    resolved = []
    for entry in declared:
        path = Path(entry)
        resolved.append((path if path.is_absolute() else base / path).resolve())
    return resolved


def _hash_paths(paths) -> dict[str, str | None]:
    """SHA256 per path; ``None`` for a path that does not exist.

    A missing file hashing to None rather than being omitted means that deleting
    a dependency changes the key, which is exactly what must invalidate a cache.
    """
    out: dict[str, str | None] = {}
    for path in sorted({str(Path(p)) for p in paths}):
        candidate = Path(path)
        out[path] = sha256_file(candidate) if candidate.is_file() else None
    return out


def _referenced_files(paths) -> list[Path]:
    """INCLUDE targets reachable from the given sources, resolved next to them."""
    found: list[Path] = []
    for entry in paths:
        path = Path(entry)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in _INCLUDE.findall(text):
            candidate = (path.parent / name)
            found.append(candidate.resolve() if candidate.exists() else Path(name))
    return found


def _acquisition_cache_inputs(ctx: RunContext) -> dict:
    """Paths *and contents*.

    Keying on paths alone was a correctness bug: editing a Fortran source
    without touching the contract left every downstream stage reusing artifacts
    built from the previous text.
    """
    sources = _resolve_declared_sources(ctx)
    return {
        "declared": [str(p) for p in sources],
        "source_hashes": _hash_paths(sources),
        # Included files are dependencies even though the contract never names
        # them, so adding, editing or deleting one has to invalidate the run.
        "included_hashes": _hash_paths(_referenced_files(sources)),
    }


def _closure_cache_inputs(ctx: RunContext) -> dict:
    """Hash every file the dependency closure actually reached."""
    inventory = ctx.results.get("source_inventory") or {}
    files = [item["path"] for item in inventory.get("files", [])]
    return {"closure_candidates": _hash_paths(files + [str(p) for p in _referenced_files(files)])}


def _transformation_cache_inputs(ctx: RunContext) -> dict:
    """Options and every input file the transform reads."""
    closure = ctx.results.get("dependency_closure") or {}
    inventory = ctx.results.get("source_inventory") or {}
    files = closure.get("files_in_closure") or [i["path"] for i in inventory.get("files", [])]
    config_path = ctx.options.get("config_path")
    return {
        "options": transformation_options(ctx).cache_identity(),
        "inputs": _hash_paths(files + [str(p) for p in _referenced_files(files)]),
        # The contract's *contents*, independent of where the file lives.
        "contract_file": (sha256_file(Path(config_path))
                          if config_path and Path(config_path).is_file() else None),
    }


def _compilation_cache_inputs(ctx: RunContext) -> dict:
    """Compiler identity decides the objects as much as the sources do."""
    from umat_oti.services.transformation import compiler_version_string

    compiler = str(ctx.options.get("compiler", "gfortran"))
    return {
        "compiler": compiler,
        "compiler_version": compiler_version_string(compiler),
        "compiler_flags": list(ctx.options.get("compiler_flags", ()) or ()),
        "compile_requested": bool(ctx.options.get("compile", False)),
    }


def _derivative_verification_cache_inputs(ctx: RunContext) -> dict:
    """Parity is not a declared dependency, so it must enter the key explicitly.

    Without this, changing the parity verdict would leave a cached derivative
    result standing and the parity gate would never be applied.
    """
    record = ctx.manifest.stages.get("primal_parity")
    block = ctx.contract.get("validation") or {}
    return {
        "primal_parity_status": record.status.value if record else None,
        "primal_parity_cache_key": record.cache_key if record else None,
        "reference_kind": str(block.get("reference_kind", "compiled_original")),
        "base_step": block.get("base_step"),
        "order": block.get("order"),
    }


def _material_point_cache_inputs(ctx: RunContext) -> dict:
    """The load path and driver settings decide the execution."""
    block = ctx.contract.get("validation")
    return {"validation": block, "compiler": str(ctx.options.get("compiler", "gfortran"))}


def transformation_options(ctx: RunContext):
    """Build the service options from the run's options mapping.

    Defined once so the stage that *runs* the transformation and the cache key
    that *describes* it cannot drift apart.
    """
    from umat_oti.services.transformation import TransformationOptions

    return TransformationOptions(
        compile_generated=bool(ctx.options.get("compile", False)),
        compiler=str(ctx.options.get("compiler", "gfortran")),
        compiler_flags=tuple(ctx.options.get("compiler_flags", ()) or ()),
        backend=str(ctx.options.get("backend", "otilib_static")),
        validation_policy=str(ctx.options.get("validation_policy", "none")),
    )


FIXED_FORM_SUFFIXES = {".f", ".for", ".f77", ".fpp"}
FREE_FORM_SUFFIXES = {".f90", ".f95", ".f03", ".f08"}

#: SPDX-ish tokens mapped to the tiers the project already uses.
LICENSE_TIERS = {
    "MIT": "permissive", "BSD-3-CLAUSE": "permissive", "BSD-2-CLAUSE": "permissive",
    "APACHE-2.0": "permissive", "GPL-3.0": "copyleft", "GPL-2.0": "copyleft",
    "AGPL-3.0": "copyleft", "LGPL-3.0": "copyleft",
}


# --------------------------------------------------------------------------- #
# 1. source acquisition
# --------------------------------------------------------------------------- #
def _source_acquisition(ctx: RunContext) -> StageOutcome:
    """Resolve the contract's declared sources to files that exist."""
    declared = ctx.contract.get("sources") or (
        [ctx.contract["source"]] if ctx.contract.get("source") else []
    )
    if not declared:
        return StageOutcome.failed(
            "the contract declares no source: set 'source' or 'sources'")

    base = Path(ctx.contract.get("_base_dir") or ctx.repo_root)
    resolved, missing = [], []
    for entry in declared:
        path = Path(entry)
        candidate = path if path.is_absolute() else (base / path)
        candidate = candidate.resolve()
        (resolved if candidate.exists() else missing).append(str(candidate))

    if missing:
        return StageOutcome.failed(
            "declared sources do not exist on this machine: " + ", ".join(missing))
    return StageOutcome.ok(sources=resolved, base_dir=str(base))


# --------------------------------------------------------------------------- #
# 2. source inventory
# --------------------------------------------------------------------------- #
def _detect_form(path: Path) -> tuple[str, str]:
    """(form, how it was decided). Suffix first, then content."""
    suffix = path.suffix.lower()
    if suffix in FREE_FORM_SUFFIXES:
        return "free", f"suffix {suffix}"
    if suffix in FIXED_FORM_SUFFIXES:
        return "fixed", f"suffix {suffix}"
    text = path.read_text(encoding="utf-8", errors="replace")
    # A continuation character in column 6 is decisive for fixed form.
    for line in text.splitlines():
        if len(line) > 5 and line[5] not in " 0" and not line.lstrip().startswith("!"):
            return "fixed", "a continuation character in column 6"
    if re.search(r"^\s*\w+\s*&\s*$", text, re.M):
        return "free", "a trailing & continuation"
    return "fixed", "no free-form marker found; defaulting to fixed for a Fortran source"


def _source_inventory(ctx: RunContext) -> StageOutcome:
    sources = require(ctx.output_of("source_acquisition"), "sources",
                      context="source_inventory")
    files = []
    for entry in sources:
        path = Path(entry)
        form, reason = _detect_form(path)
        files.append({
            "path": str(path),
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "source_form": form,
            "source_form_evidence": reason,
        })
    forms = sorted({f["source_form"] for f in files})
    return StageOutcome.ok(files=files, file_count=len(files), source_forms=forms,
                           mixed_form=len(forms) > 1)


# --------------------------------------------------------------------------- #
# 3. license classification
# --------------------------------------------------------------------------- #
def _license_classification(ctx: RunContext) -> StageOutcome:
    files = require(ctx.output_of("source_inventory"), "files",
                    context="license_classification")
    findings = []
    for entry in files:
        path = Path(entry["path"])
        spdx = None
        head = "\n".join(
            path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]).upper()
        match = re.search(r"SPDX-LICENSE-IDENTIFIER:\s*([A-Z0-9.\-+]+)", head)
        if match:
            spdx = match.group(1)
        license_file = None
        for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING"):
            candidate = path.parent / name
            if candidate.exists():
                license_file = str(candidate)
                break
        tier = LICENSE_TIERS.get((spdx or "").upper())
        findings.append({
            "path": entry["path"],
            "spdx": spdx,
            "license_file": license_file,
            "tier": tier,
            # No licence found is *not* permissive. It is unknown, and unknown
            # means all rights reserved until someone establishes otherwise.
            "redistributable_as_fixture": tier == "permissive",
            "classification_reason": (
                f"SPDX header {spdx}" if spdx else
                f"no SPDX header; nearest licence file {license_file}" if license_file
                else "no SPDX header and no licence file found"),
        })
    unknown = [f for f in findings if f["tier"] is None]
    return StageOutcome(
        status=StageOutcome.ok().status,
        outputs={"licenses": findings, "unknown_count": len(unknown)},
        diagnostics=(
            [] if not unknown else
            [f"{len(unknown)} of {len(findings)} sources have no determinable licence; "
             f"they must not be redistributed as fixtures"]),
    )


# --------------------------------------------------------------------------- #
# 4. entry-routine detection
# --------------------------------------------------------------------------- #
_SUBROUTINE = re.compile(r"^\s*(?:\d+\s+)?SUBROUTINE\s+([A-Z_]\w*)", re.I | re.M)


def _entry_routine_detection(ctx: RunContext) -> StageOutcome:
    files = require(ctx.output_of("source_inventory"), "files",
                    context="entry_routine_detection")
    declared = ctx.contract.get("entry_routine")
    routines: dict[str, list[str]] = {}
    for entry in files:
        text = Path(entry["path"]).read_text(encoding="utf-8", errors="replace")
        for name in _SUBROUTINE.findall(text):
            routines.setdefault(name.upper(), []).append(entry["path"])

    if declared:
        chosen = declared.upper()
        if chosen not in routines:
            return StageOutcome.failed(
                f"the contract names entry routine {declared!r}, which is not defined "
                f"in the declared sources. Found: {', '.join(sorted(routines)) or 'none'}")
        how = "declared in the contract"
    else:
        candidates = [name for name in routines if name == "UMAT"]
        if not candidates:
            return StageOutcome.unsupported(
                "no UMAT entry routine found and none declared; entry-routine "
                f"selection cannot be inferred from {', '.join(sorted(routines)) or 'no subroutines'}")
        chosen = candidates[0]
        how = "inferred: a subroutine named UMAT"
    return StageOutcome.ok(entry_routine=chosen, entry_files=routines[chosen],
                           how_selected=how,
                           all_subroutines=sorted(routines))


# --------------------------------------------------------------------------- #
# 5. dependency closure
# --------------------------------------------------------------------------- #
_CALL = re.compile(r"\bCALL\s+([A-Z_]\w*)", re.I)
_INCLUDE = re.compile(r"^\s*INCLUDE\s+['\"]([^'\"]+)['\"]", re.I | re.M)
_USE = re.compile(r"^\s*USE\s+([A-Z_]\w*)", re.I | re.M)


def _dependency_closure(ctx: RunContext) -> StageOutcome:
    inventory = ctx.output_of("source_inventory")
    entry = ctx.output_of("entry_routine_detection")
    defined: dict[str, str] = {}
    texts: dict[str, str] = {}
    for item in inventory["files"]:
        text = Path(item["path"]).read_text(encoding="utf-8", errors="replace")
        texts[item["path"]] = text
        for name in _SUBROUTINE.findall(text):
            defined.setdefault(name.upper(), item["path"])

    reached: set[str] = set()
    frontier = [entry["entry_routine"]]
    edges: list[dict[str, str]] = []
    while frontier:
        current = frontier.pop()
        if current in reached:
            continue
        reached.add(current)
        path = defined.get(current)
        if path is None:
            continue
        for callee in {c.upper() for c in _CALL.findall(texts[path])}:
            edges.append({"caller": current, "callee": callee})
            if callee not in reached:
                frontier.append(callee)

    external = sorted({e["callee"] for e in edges} - set(defined))
    includes, modules = set(), set()
    for text in texts.values():
        includes.update(_INCLUDE.findall(text))
        modules.update(name.upper() for name in _USE.findall(text))

    return StageOutcome.ok(
        reached_routines=sorted(reached),
        call_edges=edges,
        files_in_closure=sorted({defined[r] for r in reached if r in defined}),
        include_files=sorted(includes),
        used_modules=sorted(modules),
        # Named, not hidden: these are supplied by Abaqus at run time and must be
        # provided or stubbed for any offline build.
        external_routines=external,
    )


# --------------------------------------------------------------------------- #
# 6. contract inference
# --------------------------------------------------------------------------- #
def _max_subscript(text: str, name: str) -> int | None:
    hits = [int(m) for m in re.findall(rf"\b{name}\s*\(\s*(\d+)\s*\)", text, re.I)]
    return max(hits) if hits else None


def _contract_inference(ctx: RunContext) -> StageOutcome:
    inventory = ctx.output_of("source_inventory")
    closure = ctx.output_of("dependency_closure")
    text = "\n".join(
        Path(p).read_text(encoding="utf-8", errors="replace")
        for p in (closure["files_in_closure"] or [f["path"] for f in inventory["files"]])
    )
    inferred: dict[str, Any] = {}
    for key, name in (("nstatv", "STATEV"), ("nprops", "PROPS")):
        value = _max_subscript(text, name)
        inferred[key] = {
            "value": value,
            "evidence": (f"largest literal {name} subscript in the closure" if value
                         else None),
            "unavailable_reason": (None if value else
                                   f"no literal {name}(n) subscript found; declare it "
                                   f"explicitly in the contract"),
        }
    declared = {k: ctx.contract.get(k) for k in ("ntens", "nstatv", "nprops")}
    resolved, conflicts = {}, []
    for key in ("nstatv", "nprops"):
        if declared.get(key) is not None:
            resolved[key] = declared[key]
            if inferred[key]["value"] not in (None, declared[key]):
                conflicts.append(
                    f"{key}: contract declares {declared[key]}, source suggests "
                    f"{inferred[key]['value']}; the contract wins and the conflict is recorded")
        else:
            resolved[key] = inferred[key]["value"]
    # NTENS is a solver-side choice, never inferable from the source alone.
    resolved["ntens"] = declared.get("ntens")
    return StageOutcome(
        status=StageOutcome.ok().status,
        outputs={"inferred": inferred, "declared": declared, "resolved": resolved,
                 "conflicts": conflicts,
                 "ntens_note": ("NTENS comes from the element/solver, not the source; "
                                "it is taken from the contract or left null")},
        diagnostics=conflicts,
    )


# --------------------------------------------------------------------------- #
# 7. derivative-request normalization -- the single normalization boundary
# --------------------------------------------------------------------------- #
def _derivative_request_normalization(ctx: RunContext) -> StageOutcome:
    """Normalize every requested derivative to seed + response + target + order.

    This is the one boundary. Every front end reaches the transform through this
    stage, so CLI, JSON, batch, Streamlit, corpus and evidence generation cannot
    develop separate readings of the same contract.
    """
    from umat_oti.core.derivative_request import (
        load_project_derivative_requests, validate_derivative_requests,
    )

    try:
        requests = load_project_derivative_requests(ctx.contract,
                                                    emit_deprecations=False)
    except Exception as exc:  # noqa: BLE001 -- surfaced as a stage failure
        return StageOutcome.failed(f"could not normalize derivative requests: {exc}")

    if not requests:
        return StageOutcome.not_requested(
            "the contract expresses no derivative request in any recognized shape")

    errors = validate_derivative_requests(requests)
    if errors:
        return StageOutcome.failed(
            "the normalized requests are invalid: " + "; ".join(errors))

    normalized = [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in requests]
    orders = sorted({int(r.get("order", 1) or 1) for r in normalized})
    kinds = sorted({str(r.get("kind")) for r in normalized})
    return StageOutcome.ok(requests=normalized, count=len(normalized),
                           orders=orders, kinds=kinds)


# --------------------------------------------------------------------------- #
# 8-10. transformation, OTI support generation, compilation
# --------------------------------------------------------------------------- #
def _source_transformation(ctx: RunContext) -> StageOutcome:
    """Run the canonical transform, writing into this stage's directory.

    Calls the pure service. The pipeline must never reach into a CLI: that would
    make the core depend on argument parsing and give the same operation two
    implementations.
    """
    from umat_oti.services.transformation import run_transformation

    config_path = ctx.options.get("config_path")
    if not config_path:
        return StageOutcome.unsupported(
            "the engine currently drives the transform from a contract file on disk; "
            "pass options['config_path']")
    out_dir = ctx.stage_dir("source_transformation")
    summary, exit_code = run_transformation(
        Path(config_path), out_dir, transformation_options(ctx))
    if exit_code != 0:
        return StageOutcome.failed(
            f"transform returned {exit_code}: {summary.get('error') or summary}")
    artifacts = []
    for role, key in (("transformed_source", "transformed_source"),
                      ("manifest", "manifest")):
        value = summary.get(key)
        if value and Path(value).exists():
            artifacts.append(Artifact.of(Path(value), role, root=ctx.work_dir))
    return StageOutcome(
        status=StageOutcome.ok().status,
        outputs={"summary_keys": sorted(summary), "out_dir": str(out_dir),
                 "transformed_source": summary.get("transformed_source"),
                 "warnings": summary.get("warnings") or []},
        artifacts=artifacts,
        diagnostics=list(summary.get("warnings") or []),
    )


def _oti_support_generation(ctx: RunContext) -> StageOutcome:
    out_dir = Path(ctx.output_of("source_transformation")["out_dir"])
    order_file = out_dir / "compile_order.txt"
    if not order_file.exists():
        return StageOutcome.failed(
            "the transform produced no compile_order.txt, so the generated OTI "
            "support units cannot be identified")
    units = [line.strip() for line in order_file.read_text().splitlines() if line.strip()]
    artifacts = [Artifact.of(out_dir / u, "generated_source", root=ctx.work_dir)
                 for u in units if (out_dir / u).exists()]
    return StageOutcome(status=StageOutcome.ok().status,
                        outputs={"compile_order": units},
                        artifacts=artifacts)


def _compilation(ctx: RunContext) -> StageOutcome:
    """Four distinct outcomes, never collapsed into one.

    Not asking for objects is not a failure to produce them, and a missing
    compiler is not a defect in this repository.
    """
    compiler = str(ctx.options.get("compiler", "gfortran"))
    if not ctx.options.get("compile", False):
        return StageOutcome.not_requested(
            "compilation was not requested; pass --compile to build the generated "
            "Fortran. No objects exist, and none are claimed to")
    if not shutil.which(compiler):
        return StageOutcome.blocked(
            f"{compiler} is not on PATH; the generated Fortran cannot be compiled here")
    out_dir = Path(ctx.output_of("source_transformation")["out_dir"])
    units = ctx.output_of("oti_support_generation")["compile_order"]
    objects = []
    for unit in units:
        stem = Path(unit).stem
        for candidate in (out_dir / f"{stem}.o", out_dir / "transformed_umat.o"):
            if candidate.exists():
                objects.append(str(candidate))
                break
    if not objects:
        return StageOutcome.failed(
            "compilation was requested but produced no object files")
    return StageOutcome(
        status=StageOutcome.ok().status,
        outputs={"objects": objects, "object_count": len(objects)},
        artifacts=[Artifact.of(Path(o), "object", root=ctx.work_dir) for o in objects],
    )



# --------------------------------------------------------------------------- #
# 11-13. material-point execution, primal parity, derivative verification
# --------------------------------------------------------------------------- #
def _model_spec(ctx: RunContext):
    """Build the validation spec from the contract, or say why we cannot."""
    from umat_oti.validation.actual_umat_higher_order_generic import ModelSpec

    config_path = Path(ctx.options.get("config_path") or "")
    key = str(ctx.contract.get("name") or config_path.stem or "model")
    sources = ctx.output_of("source_acquisition")["sources"]
    return ModelSpec.from_contract(
        ctx.contract, key=key,
        config=str(config_path), source=str(sources[0]) if sources else "")


def _reference_kind(ctx: RunContext) -> str:
    """How the contract says its independent reference is obtained."""
    block = ctx.contract.get("validation")
    if not isinstance(block, dict):
        return "none"
    return str(block.get("reference_kind", "compiled_original"))


def _material_point_execution(ctx: RunContext) -> StageOutcome:
    """Build and run the material-point driver over the contract's load path.

    Executes the *actual transformed source*, carrying OTI-valued STRESS and
    STATEV between increments. A Python re-implementation is never substituted
    here: the claim this stage supports is about compiled transformed Fortran,
    so only compiled transformed Fortran can support it.
    """
    from umat_oti.validation import actual_umat_higher_order_generic as generic

    if not shutil.which(str(ctx.options.get("compiler", "gfortran"))):
        return StageOutcome.blocked("no Fortran compiler on PATH")
    kind = _reference_kind(ctx)
    if kind == "extended_precision_model":
        return _extended_precision_execution(ctx)
    try:
        spec = _model_spec(ctx)
    except ValueError as exc:
        return StageOutcome.not_requested(str(exc))

    work = ctx.stage_dir("material_point_execution") / "build"
    try:
        artifacts = generic.build_model_artifacts(spec, work)
    except RuntimeError as exc:
        return StageOutcome.failed(str(exc))

    history_path = ctx.stage_dir("material_point_execution") / "loading_history.json"
    history_path.write_text(json.dumps({
        "increments": [list(v) for v in spec.increments],
        "props": list(spec.props),
        "nstatv": spec.nstatv,
        "branch_history": artifacts["branch_history"],
        "primal_check": artifacts["primal_check"],
    }, indent=2, sort_keys=True), encoding="utf-8")

    recorded = []
    for role, path in (("transformed_driver", work / f"{spec.key}_higher_order_driver.f90"),
                       ("reference_driver", work / f"{spec.key}_reference_driver.f90"),
                       ("oti_output", work / "oti_hjac.dat")):
        if Path(path).exists():
            recorded.append(Artifact.of(Path(path), role, root=ctx.work_dir))
    recorded.append(Artifact.of(history_path, "loading_history", root=ctx.work_dir))

    return StageOutcome(
        status=StageOutcome.ok().status,
        outputs={
            "model_key": spec.key,
            "build_dir": str(work),
            "increments": [list(v) for v in spec.increments],
            "branch_history": artifacts["branch_history"],
            "primal_check": artifacts["primal_check"],
            "primal_agrees": artifacts["primal_agrees"],
            "hashes": artifacts["hashes"],
            "oti_value_count": len(artifacts["oti_values"]),
            "compiler": str(ctx.options.get("compiler", "gfortran")),
        },
        artifacts=recorded,
    )


def _extended_precision_execution(ctx: RunContext) -> StageOutcome:
    """Run the transformed source against an extended-precision reference model.

    The transformed Fortran is still compiled and executed here; what differs is
    that the reference is an independent high-precision implementation rather
    than a second build of the same file.
    """
    from umat_oti.validation.actual_umat_higher_order import (
        run_actual_j2_higher_order_evidence,
    )

    config_path = Path(ctx.options.get("config_path") or "")
    out = ctx.stage_dir("material_point_execution") / "evidence"
    try:
        evidence = run_actual_j2_higher_order_evidence(config_path, out)
    except RuntimeError as exc:
        return StageOutcome.failed(str(exc))
    artifacts = []
    for record in evidence.get("artifacts", []):
        path = Path(record["path"])
        if path.exists() and path.suffix in (".f90", ".csv", ".dat", ".json"):
            artifacts.append(Artifact.of(path, "material_point_output", root=ctx.work_dir))
    return StageOutcome(
        status=StageOutcome.ok().status,
        outputs={
            "model_key": str(ctx.contract.get("validation", {}).get("study") or "j2"),
            "reference_kind": "extended_precision_model",
            "branch_history": evidence.get("branch_history", []),
            "source_sha256": evidence.get("source", {}).get("sha256"),
            "compiler": str(ctx.options.get("compiler", "gfortran")),
        },
        artifacts=artifacts,
    )


def _primal_parity(ctx: RunContext) -> StageOutcome:
    """Compare original and transformed primal responses before any derivative.

    Two kinds of divergence must not be conflated.

    A divergence within an order of magnitude of the model's *own* local Newton
    tolerance means the two builds stopped at different admissible points. That
    is a property of the model, not a defect in the transformation -- but it
    still bounds what can be verified on the affected branch, so those branches
    are named and carried forward rather than waved through.

    A divergence far beyond that tolerance cannot be explained by convergence.
    That is a transformation defect, and it fails the stage: derivatives from a
    build that computes a different stress are not statements about
    differentiation.
    """
    from umat_oti.validation.actual_umat_higher_order_generic import (
        SOLVER_TOLERANCE_MARGIN,
    )

    if _reference_kind(ctx) == "extended_precision_model":
        return StageOutcome.not_requested(
            "this contract's reference is an independent extended-precision model "
            "rather than a second compiled build of the same source, so build-to-build "
            "primal parity does not apply. The reference's independence comes from "
            "being a different implementation, not a different build.")

    execution = ctx.output_of("material_point_execution")
    checks = execution["primal_check"]
    diverging = [c for c in checks if not c["agrees"]]
    ratios = [c.get("divergence_over_model_solver_tolerance") for c in diverging]
    known = [r for r in ratios if r is not None]
    worst = max(known) if known else None
    unexplained = [c for c in diverging
                   if c.get("divergence_over_model_solver_tolerance") is None
                   or c["divergence_over_model_solver_tolerance"] > SOLVER_TOLERANCE_MARGIN]
    limited_branches = sorted({c["branch"] for c in diverging})

    outputs = {
        "agrees": not diverging,
        "per_increment": checks,
        "diverging_increments": [c["increment"] for c in diverging],
        "worst_divergence_over_solver_tolerance": worst,
        "solver_tolerance_margin": SOLVER_TOLERANCE_MARGIN,
        "model_solver_tolerance": (checks[0].get("model_solver_tolerance")
                                   if checks else None),
        # Branches whose derivatives cannot be verified, even when the stage
        # succeeds, because the two builds do not agree there.
        "parity_limited_branches": limited_branches,
        "unexplained_increments": [c["increment"] for c in unexplained],
    }

    if not diverging:
        return StageOutcome(status=StageOutcome.ok().status, outputs=outputs)

    if unexplained:
        return StageOutcome(
            status=StageOutcome.failed("x").status,
            reason=(
                f"primal divergence on increment(s) {[c['increment'] for c in unexplained]} "
                f"is beyond what the model's own local Newton tolerance can explain"
                + (f" (worst {worst:.3g}x that tolerance)" if worst is not None else "")
                + ". This is a transformation defect: derivatives from a build that "
                  "computes a different stress are not statements about differentiation."),
            outputs=outputs)

    return StageOutcome(
        status=StageOutcome.ok().status,
        outputs=outputs,
        diagnostics=[
            f"the transformed and original builds differ on increment(s) "
            f"{[c['increment'] for c in diverging]} by up to {worst:.3g} times the "
            f"model's own local Newton tolerance. They are not solving to the same "
            f"state, so derivatives on branch(es) {limited_branches} are bounded by "
            f"that and cannot be verified beyond it."],
    )


def _derivative_verification(ctx: RunContext) -> StageOutcome:
    """Run the convergence study behind the stage, on the parity-checked build."""
    from umat_oti.validation.higher_order_convergence_study import (
        run_generic_convergence, run_j2_convergence,
    )

    limited: list[str] = []
    if _reference_kind(ctx) == "extended_precision_model":
        out_dir = ctx.stage_dir("derivative_verification")
        dataset = run_j2_convergence(out_dir, lambda message: None)
        summary = dataset["summary"]
        return StageOutcome(
            status=StageOutcome.ok().status,
            outputs={
                "rows": summary["rows"],
                "rows_supporting_verification": summary["rows_supporting_verification"],
                "classification_counts": summary["classification_counts"],
                "verified": summary["verified"],
                "reference_kind": "extended_precision_model",
                "parity_limited_branches": [],
            },
            artifacts=[Artifact.of(Path(dataset["dataset_path"]),
                                   "convergence_evidence", root=ctx.work_dir)],
        )

    # Consult parity from the manifest rather than as a hard dependency: a
    # contract whose reference is an independent implementation has no
    # build-to-build parity, but where parity DID run and fail, no row here may
    # count. The study still runs, because knowing how the rows classify is
    # useful; what it may not do is call any of them verified.
    parity_record = ctx.manifest.stages.get("primal_parity")
    parity = ctx.results.get("primal_parity") or (
        parity_record.outputs if parity_record else {})
    limited = parity.get("parity_limited_branches") or []
    parity_failed = (parity_record is not None
                     and parity_record.status is not StageStatus.SUCCEEDED
                     and parity_record.status is not StageStatus.NOT_REQUESTED)
    try:
        spec = _model_spec(ctx)
    except ValueError as exc:
        return StageOutcome.not_requested(str(exc))
    out_dir = ctx.stage_dir("derivative_verification")
    dataset = run_generic_convergence(spec, out_dir, lambda message: None)
    summary = dataset["summary"]
    artifacts = [
        Artifact.of(Path(dataset["dataset_path"]), "convergence_evidence", root=ctx.work_dir)
    ]
    for name in ("convergence_rows.csv", "convergence_sweep.csv"):
        path = out_dir / name
        if path.exists():
            artifacts.append(Artifact.of(path, "derivative_rows", root=ctx.work_dir))
    return StageOutcome(
        status=StageOutcome.ok().status,
        outputs={
            "rows": summary["rows"],
            "rows_supporting_verification": (
                0 if parity_failed else summary["rows_supporting_verification"]),
            "rows_supporting_verification_before_parity_gate": (
                summary["rows_supporting_verification"] if parity_failed else None),
            "classification_counts": summary["classification_counts"],
            # Parity failing overrides every row-level result: the two builds do
            # not compute the same stress, so their derivatives are not
            # comparable no matter how cleanly the reference resolved them.
            "verified": False if parity_failed else summary["verified"],
            "parity_failed": parity_failed,
            "parity_gate": (
                None if not parity_failed else
                "primal parity failed, so no row counts as verified regardless of its "
                "own classification: " + (parity_record.reason or "")),
            "parity_limited_branches": limited,
            "parity_limitation": (
                None if not limited else
                f"the primal responses differ on branch(es) {limited}; rows there are "
                f"bounded by that disagreement regardless of their own classification"),
            # Executing is not verifying. This stage succeeding means the study
            # ran; whether the model is verified is the 'verified' flag above.
            "stage_success_is_not_verification": (
                "this stage succeeded because the study executed; the scientific "
                "outcome is the 'verified' field and the per-row classifications"),
        },
        artifacts=artifacts,
    )


# --------------------------------------------------------------------------- #
# 14-16. registered, not yet implemented
# --------------------------------------------------------------------------- #
def _unsupported(reason: str):
    def run(ctx: RunContext) -> StageOutcome:
        return StageOutcome.unsupported(reason)
    return run


CANONICAL_STAGES: tuple[FunctionStage, ...] = (
    FunctionStage("source_acquisition", _source_acquisition,
                  cache_inputs_fn=_acquisition_cache_inputs),
    FunctionStage("source_inventory", _source_inventory, ("source_acquisition",)),
    FunctionStage("license_classification", _license_classification, ("source_inventory",)),
    FunctionStage("entry_routine_detection", _entry_routine_detection, ("source_inventory",)),
    FunctionStage("dependency_closure", _dependency_closure,
                  ("source_inventory", "entry_routine_detection"),
                  cache_inputs_fn=_closure_cache_inputs),
    FunctionStage("contract_inference", _contract_inference,
                  ("source_inventory", "dependency_closure")),
    FunctionStage("derivative_request_normalization", _derivative_request_normalization,
                  ("contract_inference",)),
    FunctionStage("source_transformation", _source_transformation,
                  ("derivative_request_normalization",),
                  cache_inputs_fn=_transformation_cache_inputs),
    FunctionStage("oti_support_generation", _oti_support_generation,
                  ("source_transformation",)),
    FunctionStage("compilation", _compilation,
                  ("oti_support_generation",),
                  cache_inputs_fn=_compilation_cache_inputs),
    FunctionStage("material_point_execution", _material_point_execution,
                  ("compilation",), cache_inputs_fn=_material_point_cache_inputs),
    FunctionStage("primal_parity", _primal_parity, ("material_point_execution",)),
    # Depends on the *execution*, not on parity: a contract whose reference is an
    # independent implementation has no build-to-build parity to wait for. Parity,
    # where it applies, is consulted inside the stage and carried into its result.
    FunctionStage("derivative_verification", _derivative_verification,
                  ("material_point_execution",), version="2",
                  cache_inputs_fn=_derivative_verification_cache_inputs),
    FunctionStage("abaqus_validation",
                  _unsupported("Abaqus validation is not yet routed through the engine"),
                  ("compilation",)),
    FunctionStage("evidence_generation",
                  _unsupported("evidence generation is in reports.run_softwarex_evidence "
                               "and is not yet routed through the engine"),
                  ("derivative_verification",)),
    FunctionStage("distributable_package",
                  _unsupported("packaging of the artifact bundle is not implemented"),
                  ("evidence_generation",)),
)


def canonical_engine(repo_root: Path):
    from umat_oti.pipeline.engine import PipelineEngine
    return PipelineEngine(list(CANONICAL_STAGES), repo_root=repo_root)
