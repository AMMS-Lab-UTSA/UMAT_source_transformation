"""Experimental source-port audit; compilation is not derivative verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from umat_oti.fortran.parser import parse_fortran_file
from umat_oti.oti.module_generator import generate_otilib_module
from umat_oti.transform.dependency_resolution import index_sources
from umat_oti.transform.helper_lifting import lift_helper_set_source, wrap_free_form
from umat_oti.transform.parameter_sensitivity_transform import _emit_intrinsic_extensions


REFERENCE_COMMIT = "6ec7f2bc4ecf4c4a93496aa2fa519575bc0e39ca"
REFERENCE_TAG = "v3.12.1"
REFERENCE_URL = "https://github.com/Reference-LAPACK/lapack.git"


def _filter_overloaded_intrinsics(source: str, overloaded: set[str]) -> tuple[str, list[str]]:
    lines, removed = [], []
    for line in source.splitlines():
        declaration = re.fullmatch(r"\s*INTRINSIC\s+(?:::)?\s*(.+)", line, re.IGNORECASE)
        if declaration is None:
            lines.append(line)
            continue
        names = [name.strip() for name in declaration.group(1).split(",")]
        kept = [name for name in names if name.upper() not in overloaded]
        removed.extend(name for name in names if name.upper() in overloaded)
        if kept:
            lines.append("    intrinsic :: " + ", ".join(kept))
    adjustments = ["Use OTI overload instead of INTRINSIC declaration: " + name for name in removed]
    return "\n".join(lines) + "\n", adjustments


def _preserve_scale_derivatives(name: str, source: str) -> tuple[str, list[str]]:
    shortcuts = {
        "DAXPY": ("IF (REAL(DA).EQ.0.0d0) RETURN", ""),
        "DSCAL": ("IF (N.LE.0 .OR. INCX.LE.0 .OR. REAL(DA).EQ.ONE) RETURN",
                  "IF (N.LE.0 .OR. INCX.LE.0) RETURN"),
    }
    if name not in shortcuts:
        return source, []
    old, new = shortcuts[name]
    lines = source.splitlines()
    if sum(line.strip() == old for line in lines) != 1:
        raise ValueError(f"{name}: expected pinned-reference scalar shortcut not found exactly once")
    rewritten = ["    " + new if line.strip() == old else line for line in lines]
    return "\n".join(rewritten) + "\n", ["Removed primal-only scale shortcut to preserve scale derivatives"]


def port_reference(source_root: Path, out_dir: Path, *, routines: list[str] | None = None,
                   directions: int = 2, order: int = 1, compile_generated: bool = False,
                   compiler: str = "gfortran") -> dict:
    source_root, out_dir = source_root.resolve(), out_dir.resolve()
    if source_root == out_dir or source_root in out_dir.parents:
        raise ValueError("Output must be outside the reference source tree")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Use a new or empty output directory")
    if not (source_root / "LICENSE").is_file():
        raise ValueError("Reference tree must contain its upstream LICENSE")
    roots = [source_root / "SRC", source_root / "BLAS" / "SRC", source_root / "INSTALL"]
    if not all(root.is_dir() for root in roots):
        raise ValueError("Reference tree needs SRC, BLAS/SRC and INSTALL directories")
    revision = subprocess.run(["git", "-C", str(source_root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    if revision != REFERENCE_COMMIT:
        raise ValueError(f"Expected Reference LAPACK {REFERENCE_TAG} at {REFERENCE_COMMIT}")
    status = subprocess.run(["git", "-C", str(source_root), "status", "--porcelain", "--untracked-files=normal"],
                            capture_output=True, text=True, check=True).stdout.strip()
    if status:
        raise ValueError("Reference checkout must be clean, including untracked files")
    if directions < 1 or order < 1:
        raise ValueError("Directions and order must be positive integers")
    executable = shutil.which(compiler) if compile_generated else None
    if compile_generated and executable is None:
        raise ValueError(f"Compiler not found: {compiler}")
    index = index_sources(roots)
    indexed_paths = {item.path for definitions in index.definitions.values() for item in definitions}
    selected = sorted(index.definitions) if routines is None else sorted(set(name.upper() for name in routines))
    if not selected:
        raise ValueError("Select at least one routine")
    unknown = set(selected) - index.definitions.keys()
    if unknown:
        raise ValueError(f"Unknown reference routines: {sorted(unknown)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root / "LICENSE", out_dir / "LAPACK_LICENSE.txt")
    module = generate_otilib_module(output_dir=out_dir, ntens=directions, order=order)
    extensions = out_dir / "oti_intrinsics.f90"
    extensions.write_text(_emit_intrinsic_extensions(module.module_name, module.type_name), encoding="utf-8")
    overloaded = set(re.findall(r"^\s*INTERFACE\s+([A-Z_]\w*)\s*$",
                                module.module_path.read_text() + "\n" + extensions.read_text(),
                                flags=re.IGNORECASE | re.MULTILINE))
    overloaded = {name.upper() for name in overloaded}
    report = {"schema": "umat_oti_lapack_port_audit_v1", "reference_url": REFERENCE_URL,
              "reference_tag": REFERENCE_TAG, "reference_commit": revision,
              "source_root": str(source_root), "directions": directions, "order": order,
              "inventory_count": len(index.definitions), "selected_count": len(selected),
              "scanned_file_count": len(index.files),
              "files_without_indexed_routines": [str(path.relative_to(source_root)) for path in index.files
                                                 if path not in indexed_paths],
              "supported_library": False, "numerically_verified": False,
              "scope": "Per-routine emission/compilation only; no closed-library link or numerical guarantee",
              "routines": {}, "support_build": None, "compiler": executable}
    if compile_generated:
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, check=True)
        report["compiler_version"] = version.stdout.splitlines()[0]
        built = subprocess.run([executable, "-c", "-ffree-line-length-none",
                                module.master_parameters_path.name, module.real_utils_path.name,
                                module.module_path.name, extensions.name], cwd=out_dir,
                               capture_output=True, text=True)
        report["support_build"] = {"returncode": built.returncode,
                                   "diagnostic": built.stdout + built.stderr}
    cache = {}
    for name in selected:
        candidates = index.get(name)
        canonical = [item for item in candidates if item.path.parent in roots]
        preferred = {"LSAME": source_root / "INSTALL" / "lsame.f",
                 "XERBLA": source_root / "SRC" / "xerbla.f",
                 "XERBLA_ARRAY": source_root / "SRC" / "xerbla_array.f",
                 "DLAMCH": source_root / "INSTALL" / "dlamch.f",
                 "DLAMC3": source_root / "INSTALL" / "dlamch.f",
                 "SLAMCH": source_root / "INSTALL" / "slamch.f",
                 "SLAMC3": source_root / "INSTALL" / "slamch.f",
                 "DISNAN": source_root / "SRC" / "disnan.f",
                 "DLAISNAN": source_root / "SRC" / "dlaisnan.f",
                 "SISNAN": source_root / "SRC" / "sisnan.f",
                 "SLAISNAN": source_root / "SRC" / "slaisnan.f"}
        if name in preferred:
            canonical = [item for item in canonical if item.path == preferred[name]]
        record = {"candidates": [str(item.path.relative_to(source_root)) for item in candidates],
                  "numerically_verified": False}
        report["routines"][name] = record
        if not canonical or len({item.body_sha256 for item in canonical}) != 1:
            record.update(status="source_selection_required")
            continue
        definition = canonical[0]
        record.update(source=str(definition.path.relative_to(source_root)),
                      source_sha256=hashlib.sha256(definition.path.read_bytes()).hexdigest())
        retained = out_dir / "reference_sources" / definition.path.relative_to(source_root)
        retained.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(definition.path, retained)
        try:
            if definition.path not in cache:
                cache[definition.path] = parse_fortran_file(definition.path)
            parsed = cache[definition.path]
            lifted = lift_helper_set_source(parsed, [name], module_name=module.module_name,
                                             type_name=module.type_name)
            generated = out_dir / f"{name.lower()}_oti.f90"
            source, adjustments = _preserve_scale_derivatives(name, lifted.source)
            source, intrinsic_adjustments = _filter_overloaded_intrinsics(source, overloaded)
            adjustments.extend(intrinsic_adjustments)
            generated.write_text(wrap_free_form(source), encoding="utf-8")
            record.update(status="emitted_unverified", generated=generated.name, adjustments=adjustments)
            if compile_generated:
                if report["support_build"]["returncode"]:
                    record.update(status="support_compile_failed")
                    continue
                built = subprocess.run([executable, "-c", "-ffree-line-length-none", generated.name],
                                       cwd=out_dir, capture_output=True, text=True)
                record.update(status="compiled_unverified" if built.returncode == 0 else "compile_failed",
                              returncode=built.returncode, diagnostic=built.stdout + built.stderr)
        except Exception as error:
            record.update(status="emission_failed", diagnostic=f"{type(error).__name__}: {error}")
    report["counts"] = dict(Counter(row["status"] for row in report["routines"].values()))
    (out_dir / "port_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--routines", nargs="+", help="Default: inventory and attempt every indexed name")
    parser.add_argument("--directions", type=int, default=2)
    parser.add_argument("--order", type=int, default=1)
    parser.add_argument("--compile", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = port_reference(args.source_root, args.out, routines=args.routines,
                                directions=args.directions, order=args.order,
                                compile_generated=args.compile)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error), "supported_library": False}))
        return 1
    print(json.dumps({key: report[key] for key in ("inventory_count", "selected_count", "counts",
                                                  "supported_library", "numerically_verified")}, indent=2))
    return 0 if all(row["status"] in {"emitted_unverified", "compiled_unverified"}
                    for row in report["routines"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())