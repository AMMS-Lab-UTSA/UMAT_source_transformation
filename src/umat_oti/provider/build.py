"""Compile the original UMAT and current generic lift into one PIC object."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from umat_oti.fortran.normalize import detect_source_form
from umat_oti.transform.parameter_sensitivity_transform import (
    GenericPSContract,
    transform_umat_for_parameter_sensitivity,
)
from umat_oti.validation.parameter_sensitivity_validation import ABA_PARAM

from .emit import CARRY_SIGNATURE, EVAL_SIGNATURE, MARCH_SIGNATURE, TOTAL_SIGNATURE, emit_wrappers


class ProviderBuildError(ValueError):
    """A contract or compiler failure prevents publishing a provider."""


def _run(arguments: list[str], directory: Path) -> str:
    result = subprocess.run(arguments, cwd=directory, text=True, capture_output=True)
    if result.returncode:
        raise ProviderBuildError(
            f"provider command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def _filename(value: str, suffix: str) -> str:
    if not isinstance(value, str) or Path(value).name != value or not value.endswith(suffix):
        raise ProviderBuildError(f"output must be a plain {suffix} filename: {value!r}")
    return value


def build_provider(contract_path: Path | str, output_dir: Path | str, *,
                   compiler: str = "gfortran") -> dict:
    contract_path = Path(contract_path).resolve()
    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    if raw.get("schema") != "resasm_umat_transform_v2":
        raise ProviderBuildError("expected schema resasm_umat_transform_v2")
    if raw.get("kinematics") != "small_strain":
        raise ProviderBuildError("provider supports only small_strain, not deformation-gradient kinematics")
    dimensions = raw.get("dimensions", {})
    for name in ("ntens", "nprops", "nstatev"):
        if type(dimensions.get(name)) is not int or dimensions[name] < 0:
            raise ProviderBuildError(f"dimensions.{name} must be a nonnegative integer")
    ntens, nprops, nstatev = (dimensions[key] for key in ("ntens", "nprops", "nstatev"))
    if ntens != 6 or nprops < 1:
        raise ProviderBuildError("provider supports 3D NTENS=6 with NPROPS >= 1 only")
    derivative = raw.get("derivative", {})
    if (raw.get("derivative_requests") or derivative.get("order", 1) != 1
            or derivative.get("of", derivative.get("response", "STRESS")) != "STRESS"
            or derivative.get("wrt", "PROPS") != "PROPS"
            or derivative.get("export", "DSIGMA_DP") != "DSIGMA_DP"
            or not derivative):
        raise ProviderBuildError("provider requires first-order STRESS wrt PROPS (DSIGMA_DP)")
    entries = raw.get("parameters", [])
    parameters = []
    for entry in entries:
        name, slot = entry.get("name"), entry.get("props_index")
        if not isinstance(name, str) or not name or type(slot) is not int or not 1 <= slot <= nprops:
            raise ProviderBuildError(f"invalid parameter name or PROPS index: {entry!r}")
        parameters.append((name, slot))
    if (not parameters or len({name for name, _ in parameters}) != len(parameters)
            or len({slot for _, slot in parameters}) != len(parameters)):
        raise ProviderBuildError("parameters must have unique names and unique PROPS indices")
    history = raw.get("history", {})
    path_dependent = history.get("path_dependent", nstatev > 0)
    if type(path_dependent) is not bool or (nstatev and not path_dependent):
        raise ProviderBuildError("physical STATEV requires history.path_dependent=true")
    source_spec = raw.get("source", {})
    if ("main_file" not in source_spec or set(source_spec) - {"main_file", "entry_point"}
            or source_spec.get("entry_point", "UMAT").upper() != "UMAT"):
        raise ProviderBuildError("provider source supports main_file and entry_point=UMAT only; includes/extra sources are not supported")
    source = (contract_path.parent / source_spec["main_file"]).resolve(strict=True)
    output = raw.get("output", {})
    object_name = _filename(output.get("object", f"umat_{contract_path.parent.name}_oti.obj"), ".obj")
    json_name = _filename(output.get("contract", f"{Path(object_name).stem}.json"), ".json")
    executable = shutil.which(compiler)
    if executable is None:
        raise ProviderBuildError(f"compiler {compiler!r} not on PATH")
    output_dir = Path(output_dir).resolve()
    if output_dir == source.parent or source.parent in output_dir.parents:
        raise ProviderBuildError("output directory must be outside the original model directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    build_dir = Path(tempfile.mkdtemp(prefix="build-", dir=output_dir))
    contract = GenericPSContract(
        name=Path(object_name).stem, umat_source_path=source, parameters=tuple(parameters),
        parameter_values=(0.0,) * len(parameters), state_variables=(), ntens=ntens,
        nstatv=nstatev, ndi=3, nshr=3, dstran_per_increment=(0.0,) * ntens,
        n_increments=1, static_props=(0.0,) * nprops,
    )
    layout = transform_umat_for_parameter_sensitivity(
        contract=contract, output_dir=build_dir, extra_directions=ntens,
    )
    wrapper = build_dir / "provider_wrappers.f90"
    wrapper.write_text(emit_wrappers(
        layout, ntens=ntens, nprops=nprops, nstatev=nstatev,
        parameters=tuple(parameters), path_dependent=path_dependent,
    ), encoding="utf-8")
    for include in ("ABA_PARAM.INC", "aba_param.inc", "ABA_PARAM.inc", "aba_param.INC"):
        (build_dir / include).write_text(ABA_PARAM, encoding="utf-8")
    flags = [executable, "-O1", "-fPIC", "-std=legacy", "-ffree-line-length-none", "-fcheck=bounds"]
    sources = [layout.master_parameters, layout.real_utils, layout.otim_module,
               build_dir / "oti_intrinsics.f90", layout.lifted_umat,
               build_dir / "abaqus_stubs.f90", wrapper]
    objects = []
    for generated_source in sources:
        obj = generated_source.with_suffix(".o")
        _run([*flags, "-c", str(generated_source), "-o", str(obj)], build_dir)
        objects.append(str(obj))
    original_object = build_dir / "original_umat.o"
    form = detect_source_form(source, source.read_text(encoding="utf-8"))
    form_flags = ["-ffixed-form", "-ffixed-line-length-none"] if form == "fixed" else ["-ffree-form"]
    _run([*flags, *form_flags, "-I", str(build_dir), "-c", str(source),
          "-o", str(original_object)], build_dir)
    objects.append(str(original_object))
    bundled_object = build_dir / object_name
    _run([executable, "-r", *objects, "-o", str(bundled_object)], build_dir)
    _run([executable, "-shared", "-Wl,--no-undefined", str(bundled_object),
          "-o", str(build_dir / "provider_link_check.so")], build_dir)
    metadata = {
        "schema": "resasm_umat_oti_contract_v1", "model_id": Path(object_name).stem,
        "kinematics": "small_strain", "dimensions": {**dimensions, "nparam": len(parameters)},
        "symbols": {"regular_umat": "umat", "oti_internal": "umat_oti_internal",
                    "oti_eval": "umat_oti_eval_", "oti_eval_signature":
                    EVAL_SIGNATURE + (CARRY_SIGNATURE if path_dependent else []),
                    "oti_eval_total": "umat_oti_eval_total_",
                    "oti_eval_total_signature": TOTAL_SIGNATURE},
        "replay": {"mode": "path_marching" if path_dependent else "stateless",
                   "carry": ["DSIGMA_DP", "DSTATEV_DP"] if path_dependent else []},
        "march": {"symbol": "umat_oti_march_", "directions": len(parameters) + ntens,
                  "signature": MARCH_SIGNATURE},
        "layouts": {"DSIGMA_DP": "fortran(NTENS,NPARAM)",
                    "DSTATEV_DP": "fortran(NSTATV,NPARAM)",
                    "DDSDDE": "fortran(NTENS,NTENS)",
                    "voigt": ["11", "22", "33", "12", "13", "23"]},
        "parameters": [{"name": name, "props_index": slot, "oti_direction": direction}
                       for direction, (name, slot) in enumerate(parameters, 1)],
        "history": {"path_dependent": path_dependent, "dstatev_dp": "returned"},
        "object": {"file": object_name,
               "sha256": hashlib.sha256(bundled_object.read_bytes()).hexdigest()[:16],
               "sha256_full": hashlib.sha256(bundled_object.read_bytes()).hexdigest()},
        "regular_source_hash": hashlib.sha256(source.read_bytes()).hexdigest()[:16],
        "validation": {"status": "not_run", "passed": False},
        "build": {"compiler": _run([executable, "--version"], build_dir).splitlines()[0],
                  "transformer": "transform_umat_for_parameter_sensitivity",
                  "sources": build_dir.name, "tangent": "dSTRESS_dDSTRAN_at_fixed_incoming_history"},
    }
    staged_json = build_dir / json_name
    staged_json.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(bundled_object, output_dir / object_name)
    shutil.copy2(staged_json, output_dir / json_name)
    return {"object": str(output_dir / object_name), "contract": str(output_dir / json_name),
            "build_dir": str(build_dir)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build a relocatable provider from a v2 contract")
    build.add_argument("contract", type=Path)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--compiler", default="gfortran")
    args = parser.parse_args(argv)
    try:
        result = build_provider(args.contract, args.out, compiler=args.compiler)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"provider build failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0