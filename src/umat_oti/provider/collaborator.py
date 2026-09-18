"""The developer's hand-off: the four files the IMQCAM presentation names.

Slide 11 has the material developer share, and keep the source private:

``REAL_UMAT.obj``
    the regular driver -- the ORIGINAL UMAT compiled unchanged;
``OTI_UMAT.obj``
    the OTI-enabled driver for residual sensitivities -- the original routine
    plus the differentiated one, returning ``DSIGMA_DP`` and ``DSTATEV_DP``;
``Mapping.json``
    the completed parameter and derivative mapping -- the provider's own
    generated contract, copied unchanged (it names both objects' SHA-256);
``transform_report.txt``
    build, validation and diagnostic results.

Nothing here builds or verifies anything itself. It runs the two existing
commands as subprocesses and keeps their real exit codes:

1. ``python -m umat_oti.provider build CONTRACT --out BUILD --regular-object REAL_UMAT.obj``
2. ``python -m umat_oti.validation.parameter_sensitivity_provider CONTRACT --out VERIFY``
   (the independent check: primal parity against the separately compiled
   ORIGINAL, and centred finite differences of the ORIGINAL over a step sweep).

The verification builds its own copy of the provider. The build compiles on
relative file names, so a rebuild reproduces the object byte for byte and the
copies are compared as bytes; independently, both are loaded through the
verifier's own ABI client and evaluated on the verification's properties and
path, and every returned array is compared.

Used by the GUI screen "Parameter Sensitivities" (``streamlit run
scripts/app.py``) and by ``python -m umat_oti.provider.collaborator``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

#: The names the presentation gives the shared files.
OTI_OBJECT = "OTI_UMAT.obj"
REAL_OBJECT = "REAL_UMAT.obj"
MAPPING = "Mapping.json"
REPORT = "transform_report.txt"
SHARED_FILES = (REAL_OBJECT, OTI_OBJECT, MAPPING, REPORT)

#: The provider accepts three-dimensional, first-order STRESS-wrt-PROPS
#: contracts only (see docs/PROVIDER.md); the screen does not offer others.
PROVIDER_NTENS = 6

REPO_ROOT = Path(__file__).resolve().parents[3]
LOADING_PATHS = REPO_ROOT / "parameter_sensitivity" / "loading_paths.json"

#: Material-point paths the independent check can replay (the contract's
#: ``validation.check_path``). Each is strain increments in Voigt order with
#: engineering shear, one unit time step each.
CHECK_PATHS = {
    "provider": "the provider's seven-increment J2 path (docs/PROVIDER.md): elastic, "
                "plastic, unloading and reverse-plastic increments",
    "uniaxial": "uniaxial strain, the parameter-sensitivity sweep's declared default "
                "(parameter_sensitivity/loading_paths.json): 20 increments of 1e-4 in 11",
    "tension_shear": "tension with shear: 20 increments of 1e-4 in 11 and 1e-4 engineering "
                     "shear in 12, so that shear stiffness enters the response",
}


def check_path_spec(key: str) -> dict[str, Any] | None:
    """The ``validation.check_path`` entry for a named path (None: provider default)."""
    if key == "provider":
        return None
    if key == "uniaxial":
        default = json.loads(LOADING_PATHS.read_text(encoding="utf-8"))["default"]
        return {"dstran_per_increment": list(default["dstran_per_increment"]),
                "n_increments": int(default["n_increments"]),
                "source": "parameter_sensitivity/loading_paths.json default: " + default["rationale"]}
    if key == "tension_shear":
        return {"dstran_per_increment": [1e-4, 0.0, 0.0, 1e-4, 0.0, 0.0], "n_increments": 20,
                "source": CHECK_PATHS["tension_shear"]}
    raise ValueError(f"unknown check path {key!r}; choose one of {sorted(CHECK_PATHS)}")


@dataclass(frozen=True)
class Parameter:
    name: str
    props_index: int
    value: float


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model_name(text: str) -> str:
    """A filename-safe model name: letters, digits and underscores."""
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")
    return cleaned or "model"


def _blank(cell: Any) -> bool:
    """None, an empty string, NaN, or a missing-value marker (pandas.NA)."""
    if cell is None:
        return True
    if isinstance(cell, str):
        return not cell.strip()
    try:
        return bool(cell != cell)
    except TypeError:  # pandas.NA refuses a truth value; it is a missing cell
        return True


def parse_parameters(rows: Sequence[dict[str, Any]]) -> list[Parameter]:
    """The screen's table rows -> parameters, refusing anything ambiguous.

    A row with every cell empty is ignored (the editor's blank trailing row).
    Every other row needs a name, a positive integer PROPS index and a finite
    value; names and indices must be unique.
    """
    parameters: list[Parameter] = []
    for number, row in enumerate(rows, start=1):
        name = "" if _blank(row.get("parameter")) else str(row.get("parameter")).strip()
        index, value = row.get("PROPS index"), row.get("value")
        blank = [_blank(cell) for cell in (index, value)]
        if not name and all(blank):
            continue
        if not name or any(blank):
            raise ValueError(f"row {number}: every parameter needs a name, a PROPS index and a value")
        try:
            slot, number_value = int(index), float(value)
        except (TypeError, ValueError):
            raise ValueError(f"row {number}: PROPS index must be an integer and value a number") from None
        if slot != float(index) or slot < 1:
            raise ValueError(f"row {number}: PROPS index must be a positive integer, not {index!r}")
        if not math.isfinite(number_value):
            raise ValueError(f"row {number}: value must be finite")
        parameters.append(Parameter(name, slot, number_value))
    if not parameters:
        raise ValueError("list at least one parameter")
    if len({p.name for p in parameters}) != len(parameters):
        raise ValueError("parameter names must be unique")
    if len({p.props_index for p in parameters}) != len(parameters):
        raise ValueError("PROPS indices must be unique")
    return parameters


def provider_contract(source_name: str, *, name: str, nstatev: int,
                      parameters: Sequence[Parameter], stress: bool = True,
                      state: bool = True, check_path: str = "provider") -> dict[str, Any]:
    """The provider's input contract (``resasm_umat_transform_v2``) for the screen.

    NPROPS is the largest listed index, and every slot up to it must be listed:
    the independent check replays the ORIGINAL routine, which needs a value in
    every PROPS slot. The two derivative requests map onto what the provider
    can return. ``DSIGMA_DP`` is the provider's one derivative request, so it
    cannot be switched off. ``DSTATEV_DP`` is carried across increments
    whenever the routine has state (``history.path_dependent``), so with
    NSTATV > 0 it cannot be switched off either; with NSTATV = 0 ticking it
    selects the path-marching form that still carries incoming derivatives.
    """
    if not stress:
        raise ValueError("the provider returns DSIGMA_DP = dSTRESS/dPROPS; it is the request "
                         "being built and cannot be switched off")
    nstatev = int(nstatev)
    if nstatev < 0:
        raise ValueError("NSTATV cannot be negative")
    if nstatev and not state:
        raise ValueError("with NSTATV > 0 the state derivatives DSTATEV_DP are carried "
                         "(history.path_dependent); untick nothing or set NSTATV = 0")
    nprops = max(p.props_index for p in parameters)
    missing = sorted(set(range(1, nprops + 1)) - {p.props_index for p in parameters})
    if missing:
        raise ValueError(f"PROPS slot(s) {missing} have no row: the check replays the original "
                         "routine and needs a value for every slot up to NPROPS")
    values = [0.0] * nprops
    for parameter in parameters:
        values[parameter.props_index - 1] = parameter.value
    stem = f"umat_{model_name(name)}_oti"
    validation: dict[str, Any] = {"props_values": values}
    path = check_path_spec(check_path)
    if path is not None:
        validation["check_path"] = path
    return {
        "schema": "resasm_umat_transform_v2",
        "source": {"main_file": source_name},
        "kinematics": "small_strain",
        "dimensions": {"ntens": PROVIDER_NTENS, "nprops": nprops, "nstatev": nstatev},
        "parameters": [{"name": p.name, "props_index": p.props_index} for p in parameters],
        "derivative": {"of": "STRESS", "wrt": "PROPS", "order": 1},
        "history": {"path_dependent": bool(nstatev or state)},
        "output": {"object": f"{stem}.obj", "contract": f"{stem}.json"},
        "validation": validation,
    }


def stage_model(source: Path, model_dir: Path, contract: dict[str, Any]) -> Path:
    """Copy the source beside a fresh contract; the provider reads both from there."""
    model_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, model_dir / contract["source"]["main_file"])
    path = model_dir / "contract_v2.json"
    path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return path


def _command(arguments: list[str], log: Path) -> dict[str, Any]:
    completed = subprocess.run(arguments, capture_output=True, text=True)
    log.write_text(f"$ {' '.join(arguments)}\n--- stdout\n{completed.stdout}"
                   f"--- stderr\n{completed.stderr}exit code {completed.returncode}\n",
                   encoding="utf-8")
    return {"command": arguments, "exit_code": completed.returncode,
            "stdout": completed.stdout, "stderr": completed.stderr, "log": str(log)}


def _generated_sources(build_dir: Path) -> dict[str, str]:
    return {path.name: _sha256(path) for path in sorted(build_dir.iterdir())
            if path.suffix in {".f90", ".f", ".for"} and path.is_file()}


def _tie_shipped_to_verified(shipped: dict[str, Any], verification: dict[str, Any],
                             work: Path) -> dict[str, Any]:
    """Evaluate both objects through the verifier's ABI client and compare."""
    import numpy as np

    from umat_oti.validation.parameter_sensitivity_provider import ProviderLibrary

    verified = verification["provider"]
    props = np.asarray(verification["props"], dtype=np.float64)
    path = np.asarray(verification["path"], dtype=np.float64)
    arrays = []
    for label, built in (("shipped", shipped), ("verified", verified)):
        contract = json.loads(Path(built["contract"]).read_text(encoding="utf-8"))
        library = ProviderLibrary(Path(built["object"]), contract, work / f"abi_{label}")
        arrays.append(library.evaluate(props, path) + library.march(props, path))
    names = ("stress", "statev", "ddsdde", "dsigma_dp", "dstatev_dp",
             "march_stress", "march_dsigma_dp", "march_ddsdde")
    differences = {name: float(np.max(np.abs(a - b))) if np.size(a) else 0.0
                   for name, a, b in zip(names, arrays[0], arrays[1])}
    shipped_sources = _generated_sources(Path(shipped["build_dir"]))
    verified_sources = _generated_sources(Path(verified["build_dir"]))
    return {"objects_byte_identical":
                Path(shipped["object"]).read_bytes() == Path(verified["object"]).read_bytes(),
            "max_abs_difference": differences,
            "identical_outputs": all(value == 0.0 for value in differences.values()),
            "generated_sources_identical": shipped_sources == verified_sources,
            "generated_sources": shipped_sources}


def package(contract_path: Path | str, out_dir: Path | str, *, verify: bool = True,
            require_j2_branches: bool = False, abaqus_toolchain: bool = False,
            abaqus: str = "abaqus", python: str = sys.executable) -> dict[str, Any]:
    """Build, verify and publish the four shared files. Never raises for a failed step."""
    contract_path, out_dir = Path(contract_path).resolve(), Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    logs = out_dir / "logs"
    logs.mkdir(exist_ok=True)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    summary: dict[str, Any] = {
        "schema": "umat_oti_collaborator_package_v1", "contract": str(contract_path),
        "model": contract_path.parent.name, "parameters": contract.get("parameters", []),
        "props_values": (contract.get("validation") or {}).get("props_values"),
        "dimensions": contract.get("dimensions"),
        "history": contract.get("history"), "verification_requested": verify,
        "check_path": (contract.get("validation") or {}).get("check_path"),
        "require_j2_branches": require_j2_branches,
    }
    build_dir = out_dir / "build"
    build = _command([python, "-m", "umat_oti.provider", "build", str(contract_path),
                      "--out", str(build_dir), "--regular-object", REAL_OBJECT,
                      *(["--abaqus-toolchain", "--abaqus", abaqus] if abaqus_toolchain else [])],
                     logs / "provider_build.log")
    summary["build"] = {key: build[key] for key in ("command", "exit_code", "log")}
    built: dict[str, Any] = {}
    if build["exit_code"] == 0:
        built = json.loads(build["stdout"])
        summary["build"]["outputs"] = built
    else:
        summary["build"]["diagnostic"] = (build["stderr"] or build["stdout"]).strip()[-2000:]

    if built and verify:
        verify_dir = out_dir / "verification"
        arguments = [python, "-m", "umat_oti.validation.parameter_sensitivity_provider",
                     str(contract_path), "--out", str(verify_dir)]
        if not require_j2_branches:
            arguments.append("--elastic")
        checked = _command(arguments, logs / "provider_verification.log")
        report_path = verify_dir / "verification.json"
        report = json.loads(report_path.read_text()) if report_path.is_file() else {}
        summary["verification"] = {"command": checked["command"], "exit_code": checked["exit_code"],
                                   "log": checked["log"], "report": str(report_path),
                                   "passed": bool(report.get("passed")) and checked["exit_code"] == 0,
                                   "result": report}
        if summary["verification"]["passed"]:
            try:
                summary["tie"] = _tie_shipped_to_verified(built, report, out_dir / "tie")
            except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
                summary["tie"] = {"identical_outputs": False, "error": str(error)}

    summary["exit_code"] = package_exit_code(summary)
    if built:
        shared = out_dir / "collaborator"
        shared.mkdir(exist_ok=True)
        shutil.copy2(built["object"], shared / OTI_OBJECT)
        shutil.copy2(built["regular_object"], shared / REAL_OBJECT)
        shutil.copy2(built["contract"], shared / MAPPING)
        summary["canonical"] = {"object": built["object"], "contract": built["contract"]}
        summary["regular_object"] = json.loads(Path(built["contract"]).read_text()).get("regular_object")
        summary["shared"] = {name: {"path": str(shared / name), "sha256": _sha256(shared / name)}
                             for name in SHARED_FILES if name != REPORT}
        # The report lists the other three files' digests, so it is written
        # after them and its own digest is added last.
        (shared / REPORT).write_text(render_report(summary), encoding="utf-8")
        summary["shared"][REPORT] = {"path": str(shared / REPORT), "sha256": _sha256(shared / REPORT)}
    (out_dir / "package.json").write_text(json.dumps(summary, indent=2, default=str) + "\n",
                                          encoding="utf-8")
    return summary


def package_exit_code(summary: dict[str, Any]) -> int:
    """0 built (and verified, when asked); 1 built but not verified; 2 not built."""
    if summary.get("build", {}).get("exit_code") != 0:
        return 2
    if not summary.get("verification_requested"):
        return 0
    verification = summary.get("verification") or {}
    tie = summary.get("tie") or {}
    return 0 if verification.get("passed") and tie.get("identical_outputs") else 1


def headline_errors(result: dict[str, Any]) -> dict[str, float]:
    """Worst relative error among the verified entries of each array (verification.json)."""
    arrays = result.get("arrays") or {}
    return {f"{name} vs finite diff.": (arrays.get(name) or {}).get("worst_relative_error_agreeing",
                                                                   math.nan)
            for name in ("DSIGMA_DP", "DSTATEV_DP", "DDSDDE")}


def render_report(summary: dict[str, Any]) -> str:
    """transform_report.txt: what was built, how it was checked, what it measured."""
    lines = ["UMAT-OTI collaborator package -- build, validation and diagnostic results",
             "=" * 76, ""]
    dimensions = summary.get("dimensions") or {}
    lines += [f"Model            : {summary.get('model')}",
              f"Dimensions       : NTENS={dimensions.get('ntens')} NPROPS={dimensions.get('nprops')} "
              f"NSTATV={dimensions.get('nstatev')}",
              f"Path dependent   : {(summary.get('history') or {}).get('path_dependent')}",
              "Parameters (name, PROPS index, value at which the check was run):"]
    values = summary.get("props_values") or []
    for parameter in summary.get("parameters") or []:
        index = parameter.get("props_index")
        value = values[index - 1] if isinstance(index, int) and 0 < index <= len(values) else "?"
        lines.append(f"  {parameter.get('name'):<12} PROPS({index})  {value}")
    build = summary.get("build") or {}
    lines += ["", "Build", "-----", "$ " + " ".join(build.get("command") or []),
              f"exit code {build.get('exit_code')}"]
    if build.get("diagnostic"):
        lines += ["diagnostic:", build["diagnostic"]]
    shared = summary.get("shared") or {}
    if shared:
        lines.append("Shared files (the source is not among them):")
        for name, entry in shared.items():
            if name != REPORT:
                lines.append(f"  {name:<22} sha256 {entry['sha256']}")
        regular = summary.get("regular_object") or {}
        if regular:
            lines.append(f"REAL_UMAT.obj    : {regular.get('toolchain')}; {regular.get('compiler') or ''}".rstrip("; "))
            lines.append("  (Abaqus on Linux takes a precompiled user object only with the .o "
                         "extension: copy it to REAL_UMAT.o and pass user=REAL_UMAT.o)")
    verification = summary.get("verification")
    lines += ["", "Validation", "----------"]
    if not summary.get("verification_requested"):
        lines.append("NOT RUN (not requested). The objects are built, not verified.")
    elif verification is None:
        lines.append("NOT RUN: the build failed.")
    else:
        lines += ["$ " + " ".join(verification.get("command") or []),
                  f"exit code {verification.get('exit_code')}"]
        result = verification.get("result") or {}
        if verification.get("passed"):
            criterion = result.get("criterion") or {}
            lines += [f"Verdict          : {result.get('verdict')}",
                      f"Reference        : {result.get('reference')}",
                      f"Check path       : {result.get('increments')} increments; {result.get('path_source')}",
                      f"J2 branches      : {', '.join(result.get('branches') or []) or 'not required'}",
                      f"Largest state    : {result.get('state_growth'):.6g} at the end of the path",
                      f"Primal parity    : stress max |diff| {result.get('primal_stress_max_abs'):.3e}, "
                      f"state max |diff| {result.get('primal_state_max_abs'):.3e}",
                      f"Tolerance        : relative {criterion.get('relative_tolerance')} per entry, where "
                      "the reference determines the entry to within it",
                      f"Reference value  : {criterion.get('reference_value')}",
                      f"Uncertainty      : {criterion.get('reference_uncertainty')}",
                      f"Verdicts         : {criterion.get('verdicts')}",
                      "", "Array                 columns agree/unresolved   entries agree   zero   "
                      "unresolved   worst rel. error (agreeing)"]
            for name, array in (result.get("arrays") or {}).items():
                lines.append(f"  {name:<20} {array['columns']:>4} {array['agreeing_columns']:>6}/"
                             f"{array['unresolved_columns']:<10} {array['agrees']:>12} "
                             f"{array['consistent_with_zero']:>6} {array['reference_unresolved']:>12}   "
                             f"{array['worst_relative_error_agreeing']:.3e}")
            unresolved = result.get("unresolved_columns") or []
            lines.append("Unresolved columns: " + ("none" if not unresolved else ""))
            for column in unresolved:
                lines.append(f"  {column['array']} {column['column']}: {column['reason']}")
            comparisons = result.get("comparisons") or {}
            lines.append(f"Entries          : {comparisons}")
            lines.append(f"Every entry      : {Path(str(result.get('entries_csv'))).name} in the "
                         "verification directory")
            tie = summary.get("tie") or {}
            lines.append("Shipped object   : "
                         + ("byte-identical to the verified build" if tie.get("objects_byte_identical")
                            else "not byte-identical to the verified build")
                         + ("; returns bit-identical arrays to it on the check path"
                            if tie.get("identical_outputs") else
                            f"; NOT tied to the verified build: {tie}"))
            lines.append("Generated sources identical to the verified build: "
                         f"{tie.get('generated_sources_identical')}")
        else:
            lines += ["FAILED -- the verifier's diagnostic:",
                      str(result.get("error") or verification.get("log"))]
    lines += ["", f"Package exit code: {summary.get('exit_code')}", "",
              "Limits: 3D small-strain first-order STRESS/PROPS providers only (docs/PROVIDER.md)."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("contract", type=Path, help="provider contract (resasm_umat_transform_v2)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-verify", action="store_true", help="build only")
    parser.add_argument("--abaqus-toolchain", action="store_true",
                        help="build REAL_UMAT.obj with `abaqus make` (the Abaqus site compiler)")
    parser.add_argument("--j2-branches", action="store_true",
                        help="require the check path to cross elastic, plastic and unloading increments")
    args = parser.parse_args(argv)
    summary = package(args.contract, args.out, verify=not args.no_verify,
                      require_j2_branches=args.j2_branches, abaqus_toolchain=args.abaqus_toolchain)
    print(json.dumps({key: summary.get(key) for key in ("exit_code", "shared", "canonical")},
                     indent=2, default=str))
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
