"""Compile the original UMAT and current generic lift into one PIC object."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def _abaqus_make(abaqus: str, source: Path, work: Path, target: Path) -> dict:
    """Compile ``source`` with ``abaqus make``; copy its object to ``target``.

    Runs in its own directory on the bare file name, so the object records no
    directory of the developer's.
    """
    work.mkdir()
    shutil.copy2(source, work / source.name)
    completed = subprocess.run([abaqus, "make", f"library={source.name}", "directory=."],
                               cwd=work, text=True, capture_output=True)
    log = completed.stdout + completed.stderr
    (work / "abaqus_make.log").write_text(log, encoding="utf-8")
    produced = work / f"{source.stem}-std.o"
    if completed.returncode or not produced.is_file():
        raise ProviderBuildError(f"abaqus make failed ({completed.returncode}):\n{log[-3000:]}")
    shutil.copy2(produced, target)
    compilers = [line.strip() for line in log.splitlines() if "Fortran" in line and "Version" in line]
    return {"toolchain": "abaqus make",
            "compiler": compilers[0] if compilers else None,
            "abaqus_make_log": "abaqus_make/abaqus_make.log in the build directory"}


def build_provider(contract_path: Path | str, output_dir: Path | str, *,
                   compiler: str = "gfortran", regular_object: str | None = None,
                   abaqus_toolchain: bool = False, abaqus: str = "abaqus") -> dict:
    """Build the OTI provider; optionally also publish the regular object.

    ``regular_object`` names a second output: the ORIGINAL UMAT compiled
    unchanged from the same source, as the regular driver for production
    analyses. By default it is the very object bundled into the provider
    (same compiler, same flags). With ``abaqus_toolchain`` it is built instead
    the way Abaqus builds user subroutines -- ``abaqus make``, i.e. the
    compiler and flags of the Abaqus site environment (ifort on Linux) -- so
    that it links into an Abaqus job against the Fortran runtime Abaqus ships,
    rather than referring to a gfortran runtime Abaqus does not load. Its
    SHA-256 is recorded in the completed contract (``regular_object``) so a
    collaborator can check that the two objects they were given are a
    matched pair. Without ``regular_object`` the build and the contract are
    exactly as before.
    """
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
    if regular_object is not None:
        regular_object = _filename(regular_object, ".obj")
        if regular_object == object_name:
            raise ProviderBuildError("the regular object needs a name different from the OTI object")
    if abaqus_toolchain and regular_object is None:
        raise ProviderBuildError("--abaqus-toolchain builds the regular object; name it with --regular-object")
    abaqus_executable = shutil.which(abaqus) if abaqus_toolchain else None
    if abaqus_toolchain and abaqus_executable is None:
        raise ProviderBuildError(f"Abaqus executable {abaqus!r} not on PATH; the Abaqus toolchain "
                                 "is `abaqus make`")
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
    # Every compile runs inside the build directory on relative file names.
    # gfortran writes the file name it was given into each bounds-check
    # message ("At line N of file ..."), and gfortran 9 does not apply
    # -ffile-prefix-map to those, so an absolute name would ship the
    # developer's directory names inside the object. The original source is
    # compiled from a copy under original/ for the same reason; the prefix map
    # is kept for anything else a newer compiler or -g would record.
    flags = [executable, "-O1", "-fPIC", "-std=legacy", "-ffree-line-length-none", "-fcheck=bounds",
             f"-ffile-prefix-map={build_dir}=."]
    recorded_flags = [Path(executable).name, *flags[1:-1], "-ffile-prefix-map=<build>=."]
    sources = [layout.master_parameters, layout.real_utils, layout.otim_module,
               build_dir / "oti_intrinsics.f90", layout.lifted_umat,
               build_dir / "abaqus_stubs.f90", wrapper]
    objects = []
    for generated_source in sources:
        relative = os.path.relpath(generated_source, build_dir)
        obj = str(Path(relative).with_suffix(".o"))
        _run([*flags, "-c", relative, "-o", obj], build_dir)
        objects.append(obj)
    original_copy = build_dir / "original" / source.name
    original_copy.parent.mkdir()
    shutil.copy2(source, original_copy)
    original_object = build_dir / "original_umat.o"
    form = detect_source_form(source, source.read_text(encoding="utf-8"))
    form_flags = ["-ffixed-form", "-ffixed-line-length-none"] if form == "fixed" else ["-ffree-form"]
    original_command = [*flags, *form_flags, "-I", ".", "-c", f"original/{source.name}",
                        "-o", original_object.name]
    _run(original_command, build_dir)
    objects.append(original_object.name)
    bundled_object = build_dir / object_name
    _run([executable, "-nostdlib", "-r", *objects, "-o", object_name], build_dir)
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
    if regular_object is not None:
        staged_regular = build_dir / regular_object
        if abaqus_toolchain:
            toolchain = _abaqus_make(abaqus_executable, original_copy, build_dir / "abaqus_make",
                                     staged_regular)
            role = ("ORIGINAL UMAT compiled unchanged by `abaqus make` (the Abaqus site "
                    "environment's compiler and flags); the OTI provider bundles its own "
                    f"{Path(executable).name} build of the same source")
            command = [Path(abaqus_executable).name, "make", f"library={source.name}"]
        else:
            shutil.copy2(original_object, staged_regular)
            toolchain = {"toolchain": "provider", "compiler": None}
            role = "ORIGINAL UMAT compiled unchanged; the same object is bundled in the OTI provider"
            command = [*recorded_flags, *form_flags, "-I", ".", "-c", f"original/{source.name}"]
        metadata["regular_object"] = {
            "file": regular_object,
            "sha256_full": hashlib.sha256(staged_regular.read_bytes()).hexdigest(),
            "role": role,
            "source_sha256_full": hashlib.sha256(source.read_bytes()).hexdigest(),
            "compile_command": command,
            **toolchain,
        }
    staged_json = build_dir / json_name
    staged_json.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(bundled_object, output_dir / object_name)
    shutil.copy2(staged_json, output_dir / json_name)
    result = {"object": str(output_dir / object_name), "contract": str(output_dir / json_name),
              "build_dir": str(build_dir)}
    if regular_object is not None:
        shutil.copy2(build_dir / regular_object, output_dir / regular_object)
        result["regular_object"] = str(output_dir / regular_object)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build a relocatable provider from a v2 contract")
    build.add_argument("contract", type=Path)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--compiler", default="gfortran")
    build.add_argument("--regular-object", metavar="NAME.obj",
                       help="also publish the ORIGINAL UMAT compiled unchanged (same compiler, "
                            "flags and source) under this name; its SHA-256 goes into the contract")
    build.add_argument("--abaqus-toolchain", action="store_true",
                       help="build the regular object with `abaqus make` (the Abaqus site "
                            "compiler and flags) instead of the provider's compiler")
    build.add_argument("--abaqus", default="abaqus", help="Abaqus command for --abaqus-toolchain")
    args = parser.parse_args(argv)
    try:
        result = build_provider(args.contract, args.out, compiler=args.compiler,
                                regular_object=args.regular_object,
                                abaqus_toolchain=args.abaqus_toolchain, abaqus=args.abaqus)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"provider build failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0