"""Pure transformation service.

The transformation operation lives here, not in a CLI. Dependencies point one
way:

    pure transformation service      <- this module
            ^
    pipeline stages
            ^
    CLI / batch / Streamlit / corpus / evidence adapters

Nothing in this module imports a front end, so the pipeline can call it without
the core depending on argument parsing. ``umat_oti.cli_json.run_config_transform``
is now a thin compatibility wrapper over :func:`run_transformation`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from umat_oti.core.config_loader import load_project_config_json
from umat_oti.core.derivative_request import (
    KIND_PARAMETER_SENSITIVITY,
    KIND_STATE_SENSITIVITY,
    load_project_derivative_requests,
    validate_derivative_requests,
)
from umat_oti.core.transformation_anchors import (
    anchor_completion_status, merge_completed_anchors_into_config,
)
from umat_oti.reports.manifest import build_manifest, write_manifest
from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract,
    NonDifferentiableParameterPathError,
    transform_umat_for_parameter_sensitivity,
    validate_parameter_paths,
)
from umat_oti.transform.source_transform import transform_umat_to_oti_from_config


@dataclass(frozen=True)
class TransformationOptions:
    """Everything that changes what the transformation produces.

    These values belong in the cache key of any stage that runs the service: a
    run performed without compilation cannot satisfy a later request that needs
    objects, and a different compiler produces different objects from identical
    sources.
    """

    compile_generated: bool = False
    compiler: str = "gfortran"
    compiler_flags: tuple[str, ...] = ()
    backend: str = "otilib_static"
    validation_policy: str = "none"

    def cache_identity(self) -> dict[str, Any]:
        return {
            "compile_generated": self.compile_generated,
            "compiler": self.compiler,
            "compiler_flags": list(self.compiler_flags),
            "backend": self.backend,
            "validation_policy": self.validation_policy,
            "compiler_version": compiler_version_string(self.compiler),
        }


def compiler_version_string(compiler: str = "gfortran") -> str | None:
    """First line of ``<compiler> --version``, or None when it is absent.

    Absent is recorded as None rather than an empty string so that "no compiler
    here" is distinguishable from "a compiler that reported nothing".
    """
    if shutil.which(compiler) is None:
        return None
    try:
        out = subprocess.run([compiler, "--version"], capture_output=True,
                             text=True, timeout=30)
    except Exception:
        return None
    return (out.stdout.splitlines() or [None])[0]


def run_transformation(
    config_path: Path,
    out_dir: Path,
    options: TransformationOptions | None = None,
) -> tuple[dict[str, Any], int]:
    """Transform one contract into an artifact set. Returns (summary, exit_code)."""
    options = options or TransformationOptions()
    return _run_config_transform(config_path, out_dir,
                                 compile_generated=options.compile_generated)


def _run_config_transform(config_path: Path, out_dir: Path, *, compile_generated: bool = False) -> tuple[dict[str, Any], int]:
    config_path = config_path.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()

    try:
        config = load_project_config_json(config_path.read_bytes(), origin_path=config_path)
    except Exception as exc:
        return {"config": str(config_path), "error": f"{type(exc).__name__}: {exc}"}, 1

    source = config.get("source", {}) if isinstance(config.get("source"), dict) else {}
    source_path = Path(str(source.get("selected_umat_file", ""))).expanduser()
    if not source_path.is_file():
        return {"config": str(config_path), "error": f"Source file not found: {source_path}", "status_category": "source_not_found"}, 1

    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    config = merge_completed_anchors_into_config(config, source_text)
    derivative_requests = load_project_derivative_requests(config)
    request_errors = validate_derivative_requests(derivative_requests)
    if request_errors:
        return {"config": str(config_path), "errors": request_errors, "status_category": "invalid_derivative_request"}, 1
    parameter_requests = [
        request
        for request in derivative_requests
        if request.kind in {KIND_PARAMETER_SENSITIVITY, KIND_STATE_SENSITIVITY}
    ]
    if parameter_requests:
        parameter_map = tuple(dict.fromkeys(item for request in parameter_requests for item in request.parameter_map))
        try:
            validate_parameter_paths(source_text, parameter_map)
        except NonDifferentiableParameterPathError as exc:
            return {
                "config": str(config_path),
                "blockers": [{"code": exc.code, "message": str(exc), "suggested_patch": exc.suggested_patch}],
                "status_category": exc.code,
            }, 1
    completion = anchor_completion_status(config)
    settings = config.get("transformation_settings", {}) if isinstance(config.get("transformation_settings"), dict) else {}
    ntens = int(settings.get("ntens") or 0)
    summary: dict[str, Any] = {
        "config": str(config_path),
        "out_dir": str(out_dir),
        "source": str(source_path),
        "anchor_status": completion.get("status"),
        "completion_issues": completion.get("completion_issues", []),
        "ntens": ntens,
        "order": settings.get("order"),
        "derivative_requests": [request.to_dict() for request in derivative_requests],
    }
    if completion.get("status") == "needs_json_completion":
        summary["status_category"] = "needs_json_completion"
        return summary, 2

    out_dir.mkdir(parents=True, exist_ok=True)
    result = transform_umat_to_oti_from_config(source_text, config, out_dir, ntens)
    combined = _write_combined_source(out_dir, result.transformed_source_path) if result.success else None
    parameter_artifact: dict[str, Any] | None = None
    if result.success and parameter_requests:
        try:
            parameter_artifact = _generate_parameter_sensitivity_artifact(
                config=config,
                source_path=source_path,
                requests=parameter_requests,
                out_dir=out_dir / "parameter_sensitivity",
                ntens=ntens,
            )
        except NonDifferentiableParameterPathError as exc:
            summary.update(
                {
                    "transform_success": False,
                    "blockers": [{"code": exc.code, "message": str(exc), "suggested_patch": exc.suggested_patch}],
                    "status_category": exc.code,
                }
            )
            return summary, 1
        except (KeyError, TypeError, ValueError) as exc:
            summary.update(
                {
                    "transform_success": False,
                    "blockers": [{"code": "invalid_parameter_sensitivity_contract", "message": str(exc)}],
                    "status_category": "invalid_parameter_sensitivity_contract",
                }
            )
            return summary, 1
    manifest_path: Path | None = None
    compile_result: dict[str, Any] = {"status": "not_requested"}
    if result.success:
        compiler_name, compiler_version = _compiler_identity()
        if compile_generated:
            compile_result = _compile_generated_sources(out_dir, compiler_name)
        driver = config.get("material_point_driver") if isinstance(config.get("material_point_driver"), dict) else {}
        parameters = _indexed_names(config.get("parameters"), "props_index")
        state_variables = _indexed_names(config.get("state_variables"), "statev_index")
        manifest = build_manifest(
            source_path=source_path,
            entry_routine=str(source.get("selected_umat_name") or source.get("detected_umat_name") or "UMAT"),
            ntens=ntens,
            nstatv=int(driver.get("nstatv") or max((index for _, index in state_variables), default=0)),
            nprops=max((index for _, index in parameters), default=0),
            requests=derivative_requests,
            parameters=parameters,
            state_variables=state_variables,
            compiler_name=compiler_name,
            compiler_version=compiler_version,
            warnings=result.warnings,
            direction_count=int(result.report.get("oti_directions") or ntens),
            generated_files=[*result.generated_files, *([combined] if combined else [])],
            ntens_source=str(settings.get("ntens_source", "")),
            ntens_confidence=str(settings.get("ntens_confidence", "")),
            ntens_warning=str(settings.get("ntens_warning", "")),
            execution_status=str(compile_result["status"] if compile_generated else "generated_not_compiled"),
        )
        if compile_generated:
            manifest["execution"].update(compile_result)
        else:
            manifest["execution"]["compilation"] = compile_result
        manifest_path = write_manifest(manifest, out_dir / "derivative_manifest.json")
    summary.update(
        {
            "transform_success": result.success,
            "blockers": result.blockers,
            "warnings": result.warnings,
            "report_path": str(result.report_path or ""),
            "transformed_source": str(result.transformed_source_path or ""),
            "combined_source": str(combined or ""),
            "manifest": str(manifest_path or ""),
            "compilation": compile_result,
            "artifacts": {
                "abaqus_umat": {
                    "abi": "standard_real_umat",
                    "drop_in_abaqus_user_subroutine": True,
                    "source": str(combined or result.transformed_source_path or ""),
                },
                "parameter_sensitivity_driver": parameter_artifact,
            },
            "semantic_checks": result.report.get("semantic_checks", {}),
            "status_category": _classify_outcome(result),
        }
    )
    compiled_ok = not compile_generated or compile_result.get("status") == "compiled"
    return summary, 0 if result.success and compiled_ok else 1


def _indexed_names(raw: Any, index_key: str) -> list[tuple[str, int]]:
    if not isinstance(raw, list):
        return []
    return [
        (str(entry.get("name", "")).upper(), int(entry[index_key]))
        for entry in raw
        if isinstance(entry, dict) and str(entry.get("name", "")).strip() and entry.get(index_key) is not None
    ]


def _compiler_identity() -> tuple[str, str]:
    compiler = shutil.which("gfortran")
    if compiler is None:
        return "", ""
    result = subprocess.run([compiler, "--version"], check=False, capture_output=True, text=True)
    first_line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    return compiler, first_line


def _compile_generated_sources(out_dir: Path, compiler_name: str) -> dict[str, Any]:
    script = out_dir / "compile_hint.sh"
    command = [str(script)]
    if not compiler_name:
        return {"status": "compiler_unavailable", "command": command, "returncode": None}
    from umat_oti.corpus.cli import _write_aba_param_stub

    _write_aba_param_stub(out_dir)
    result = subprocess.run(command, cwd=out_dir, check=False, capture_output=True, text=True)
    return {
        "status": "compiled" if result.returncode == 0 else "compile_failed",
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _generate_parameter_sensitivity_artifact(
    *,
    config: dict[str, Any],
    source_path: Path,
    requests: list[Any],
    out_dir: Path,
    ntens: int,
) -> dict[str, Any]:
    parameters: list[tuple[str, int]] = []
    for request in requests:
        for item in request.parameter_map:
            if item not in parameters:
                parameters.append(item)
    if not parameters:
        raise ValueError("DSIGMA_DP/DSTATEV_DP requires a non-empty parameters mapping")
    parameter_entries = {
        str(entry.get("name", "")).upper(): entry
        for entry in config.get("parameters", [])
        if isinstance(entry, dict)
    }
    parameter_values = tuple(float(parameter_entries[name.upper()]["value"]) for name, _ in parameters)
    state_variables: list[tuple[str, int]] = []
    for request in requests:
        for item in request.state_map:
            if item not in state_variables:
                state_variables.append(item)
    driver = config.get("material_point_driver") if isinstance(config.get("material_point_driver"), dict) else {}
    nstatv = int(driver.get("nstatv") or max((index for _, index in state_variables), default=1))
    dstran = tuple(float(value) for value in driver.get("dstran_per_increment", []))
    if len(dstran) != ntens:
        raise ValueError(f"material_point_driver.dstran_per_increment must contain ntens={ntens} values")
    static_props = tuple(float(value) for value in driver.get("static_props", []))
    contract = GenericPSContract(
        name=str(config.get("case_name") or config.get("project", {}).get("name") or source_path.stem),
        umat_source_path=source_path,
        parameters=tuple(parameters),
        parameter_values=parameter_values,
        state_variables=tuple(state_variables),
        ntens=ntens,
        nstatv=nstatv,
        ndi=int(driver.get("ndi") or (3 if ntens >= 4 else ntens)),
        nshr=int(driver.get("nshr") if driver.get("nshr") is not None else max(ntens - 3, 0)),
        dstran_per_increment=dstran,
        n_increments=int(driver.get("n_increments") or 1),
        static_props=static_props,
    )
    layout = transform_umat_for_parameter_sensitivity(contract=contract, output_dir=out_dir)
    artifact = {
        "abi": "oti_material_point_driver",
        "drop_in_abaqus_user_subroutine": False,
        "root": str(layout.root),
        "driver": str(layout.driver),
        "lifted_umat": str(layout.lifted_umat),
        "makefile": str(layout.makefile),
        "oti_module": str(layout.otim_module),
        "parameters": [{"name": name, "props_index": index} for name, index in parameters],
        "state_variables": [{"name": name, "statev_index": index} for name, index in state_variables],
        "outputs": [request.target for request in requests],
    }
    manifest = out_dir / "artifact_manifest.json"
    manifest.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    artifact["manifest"] = str(manifest)
    return artifact


def _write_combined_source(out_dir: Path, transformed_source: Any) -> Path | None:
    """Write one Abaqus-submittable file: the OTI support modules followed by the
    transformed UMAT, all as free-form Fortran (the fixed-form UMAT is converted).

    Submit it directly with `abaqus job=... user=<name>_oti_combined.f90`.
    """
    if not transformed_source:
        return None
    transformed_source = Path(transformed_source)
    order_file = out_dir / "compile_order.txt"
    if not order_file.is_file():
        return None
    from umat_oti.validation.job_builder import _fixed_form_to_free_form

    chunks: list[str] = []
    for name in (line.strip() for line in order_file.read_text(encoding="utf-8").splitlines()):
        if not name:
            continue
        part = out_dir / name
        if not part.is_file():
            continue
        text = part.read_text(encoding="utf-8", errors="replace")
        if part.suffix.lower() in {".f", ".for", ".ftn"}:
            text = _fixed_form_to_free_form(text)
        chunks.append(f"! ===== {part.name} =====\n{text}\n")
    if not chunks:
        return None
    combined = out_dir / f"{transformed_source.stem}_combined.f90"
    combined.write_text("".join(chunks), encoding="utf-8")
    return combined


def _classify_outcome(result: Any) -> str:
    """Legible outcome category for the transform (robustness/triage aid)."""
    if not result.success:
        return "transform_blocked" if result.blockers else "transform_failed"
    semantic = result.report.get("semantic_checks", {}) if isinstance(result.report, dict) else {}
    if any(value is False for value in semantic.values()):
        return "succeeded_semantic_check_warnings"
    if result.warnings:
        # e.g. a helper passed through instead of OTI-lifted: derivatives may be
        # approximate on that path. Surface it rather than reporting clean success.
        return "succeeded_with_warnings"
    return "succeeded"
