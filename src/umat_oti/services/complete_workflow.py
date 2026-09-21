"""Dependency discovery, tangent generation and verified parameter sensitivities."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Sequence

from umat_oti.fortran.literals import mask_character_literals
from umat_oti.fortran.parser import parse_declaration_line, parse_fortran_file
from umat_oti.provider.collaborator import Parameter, package, provider_contract, stage_model
from umat_oti.services.jacobian_request import jacobian_contract, run_jacobian_transform
from umat_oti.services.transformation import _payload_with_resolved_closure
from umat_oti.validation.parameter_sensitivity_provider import check_path


def _material_settings(path: Path) -> dict[str, Any]:
    settings = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(settings, dict) or settings.get("kinematics") != "small_strain":
        raise ValueError("kinematics must explicitly be small_strain; finite strain is not supported")
    allowed = {"kinematics", "ntens", "nstatev", "props_values", "check_path", "parameters"}
    if set(settings) - allowed:
        raise ValueError(f"Unknown material settings: {sorted(set(settings) - allowed)}")
    if type(settings.get("ntens", 6)) is not int or settings.get("ntens", 6) != 6:
        raise ValueError("The sensitivity provider requires ntens=6")
    if type(settings.get("nstatev")) is not int or settings["nstatev"] < 0:
        raise ValueError("nstatev must be an explicit nonnegative integer")
    values = settings.get("props_values")
    if not isinstance(values, list) or not values or any(
        type(value) not in (int, float) or not math.isfinite(value) for value in values
    ):
        raise ValueError("props_values must provide finite numeric values for every PROPS slot")
    if not isinstance(settings.get("check_path"), dict):
        raise ValueError("check_path must explicitly describe the strain-increment history")
    check_path({"validation": {"check_path": settings["check_path"]}}, 6)
    return settings


def _parameters(source: Path, settings: dict[str, Any]) -> list[Parameter]:
    values = settings["props_values"]
    aliases: dict[int, set[str]] = {}
    parsed = parse_fortran_file(source)
    dynamic = False
    for line in parsed.logical_lines:
        text, _ = mask_character_literals(line.text)
        if parse_declaration_line(text) is not None or re.match(r"\s*DIMENSION\b", text, re.IGNORECASE):
            continue
        assignment = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*=\s*PROPS\(\s*(\d+)\s*\)\s*",
                                  text, re.IGNORECASE)
        if assignment:
            aliases.setdefault(int(assignment.group(2)), set()).add(assignment.group(1).upper())
        for reference in re.finditer(r"\bPROPS\s*\(([^()]*)\)", text, re.IGNORECASE):
            index = reference.group(1).strip()
            if index.isdigit():
                if not 1 <= int(index) <= len(values):
                    raise ValueError(f"PROPS({index}) exceeds the supplied props_values")
            else:
                dynamic = True
    explicit = settings.get("parameters")
    if explicit is None:
        if dynamic:
            raise ValueError("Dynamic PROPS indexing requires an explicit parameters list")
        entries = [{"name": next(iter(aliases[index])) if len(aliases.get(index, ())) == 1
                    else f"PROPS_{index}", "props_index": index}
                   for index in range(1, len(values) + 1)]
    else:
        if not isinstance(explicit, list) or not explicit:
            raise ValueError("parameters must be a nonempty list of names and PROPS indices")
        entries = explicit
    parameters = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each parameter needs name and props_index")
        name, index = entry.get("name"), entry.get("props_index")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise ValueError("Parameter names must be identifiers")
        if type(index) is not int or not 1 <= index <= len(values):
            raise ValueError(f"Invalid PROPS index for parameter {name}")
        parameters.append(Parameter(name, index, float(values[index - 1])))
    if len({item.name.upper() for item in parameters}) != len(parameters):
        raise ValueError("Ambiguous parameter names; provide unique names in parameters")
    if len({item.props_index for item in parameters}) != len(parameters):
        raise ValueError("parameters must have unique PROPS indices")
    return parameters


def run_complete_workflow(source: Path, material_config: Path, out_dir: Path, *,
                          dependency_roots: Sequence[Path] = ()) -> dict[str, Any]:
    source, out_dir = source.expanduser().resolve(), out_dir.expanduser().resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        return {"exit_code": 2, "failed_stage": "output", "error":
                "Use a new or empty output directory so stale artifacts cannot appear successful"}
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"exit_code": 1, "stages": {}, "out_dir": str(out_dir)}
    stage = "material_settings"
    try:
        settings = _material_settings(material_config.expanduser().resolve())
        summary["stages"][stage] = {"status": "succeeded"}
        stage = "dependencies"
        discovery = out_dir / "discovery"
        discovery.mkdir()
        contract = jacobian_contract(source, ntens=6, discover_dependencies=True,
                                     dependency_roots=list(dependency_roots))
        request = discovery / "jacobian_contract.json"
        request.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        payload, closure = _payload_with_resolved_closure(request, discovery)
        resolved = Path(json.loads(payload)["source"])
        summary["stages"][stage] = {"status": "succeeded", "closure": closure}
        if closure and closure.get("entry_routine") != "UMAT":
            raise ValueError("The sensitivity provider currently requires entry routine UMAT")
        stage = "parameters"
        parameters = _parameters(resolved, settings)
        parameter_report = {"selection": "explicit" if settings.get("parameters") else "all_props_slots",
                            "parameters": [vars(item) for item in parameters],
                            "notice": "PROPS slots may include discrete flags; explicitly select only continuous parameters"}
        (out_dir / "parameters.json").write_text(
            json.dumps(parameter_report, indent=2) + "\n", encoding="utf-8")
        summary["stages"][stage] = {"status": "succeeded", **parameter_report}
        stage = "jacobian"
        tangent = run_jacobian_transform(resolved, out_dir / "jacobian", ntens=6,
                                         compile_generated=True)
        summary["stages"][stage] = tangent.summary
        if not tangent.succeeded:
            raise ValueError("Tangent transformation or compilation failed; see jacobian diagnostics")
        stage = "sensitivities"
        all_slots = [Parameter(f"PROPS_{index}", index, value)
                     for index, value in enumerate(settings["props_values"], start=1)]
        provider = provider_contract(resolved.name, name=source.stem,
                                     nstatev=settings["nstatev"], parameters=all_slots)
        provider["parameters"] = [{"name": item.name, "props_index": item.props_index}
                                  for item in parameters]
        provider["validation"]["check_path"] = settings["check_path"]
        staged = stage_model(resolved, out_dir / "model", provider)
        result = package(staged, out_dir / "sensitivities", verify=True)
        summary["stages"][stage] = result
        if result["exit_code"]:
            raise ValueError("Sensitivity build or verification failed; see sensitivities/package.json")
        summary["exit_code"] = 0
    except (ValueError, OSError, RuntimeError) as error:
        summary.update(failed_stage=stage, error=str(error))
    (out_dir / "workflow_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    return summary