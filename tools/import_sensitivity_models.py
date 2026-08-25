#!/usr/bin/env python3
"""Import the parameter-sensitivity model set from a discovered local copy.

Data only. Contracts and Fortran sources are copied; build directories, ``.obj``,
``.o``, ``.mod`` files, executables and previously generated numerical results
are deliberately **not** imported. Old outputs are somebody else's run: they
would enter this repository as evidence without provenance, and they would be
indistinguishable from results this pipeline produced. Everything numerical must
be regenerated here.

Every imported model records where it came from, what it hashed to, and whether
the source file was tracked in the origin repository, so the import is auditable
after the source copy is gone.

    python tools/import_sensitivity_models.py --dry-run
    python tools/import_sensitivity_models.py
    python tools/import_sensitivity_models.py --check   # verify nothing drifted
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
#: Where the authors' working tree of models lives. There is no portable
#: default -- it is a location on whoever's machine performed the import -- so
#: it comes from the environment or --source and the tool refuses to guess.
SOURCE_ENV = "UMAT_OTI_MODEL_IMPORT_SOURCE"
DEST = REPO_ROOT / "parameter_sensitivity" / "models"
MANIFEST = REPO_ROOT / "parameter_sensitivity" / "IMPORT_PROVENANCE.json"

#: The 18 the SoftwareX Table 6 requirement names.
REQUIRED = (
    "m1_elastic", "m2_cubic", "m3_j2", "m5_cpflow", "m6_fcc",
    "sweep_aniso_ortho", "sweep_damage_elastic", "sweep_eco",
    "sweep_j2_bilinear", "sweep_j2_combined", "sweep_j2_kinematic",
    "sweep_lame_elastic", "sweep_maxwell_ve", "sweep_mooney_small",
    "sweep_real_ECL_TEMP", "sweep_real_PCO", "sweep_thermoelastic",
    "sweep_transiso",
)
#: Present in the source copy but not part of the Table 6 requirement. Imported
#: and labelled, because a model that exists is worth having; excluded from the
#: Table 6 denominator, because padding a denominator is how counts stop meaning
#: anything.
ADDITIONAL = ("m2_elastic3d", "sweep_drucker_prager", "sweep_perzyna_linear")

CONTRACT_NAMES = ("contract.json", "transform_contract_v2.json")
SOURCE_NAME = "umat.for"

#: Never imported: these are build outputs and prior numerical results.
EXCLUDED_SUFFIXES = {".obj", ".o", ".mod", ".exe", ".a", ".so", ".dat"}
EXCLUDED_DIRS = {"build", "__pycache__", "dist"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or None
    except Exception:
        return None


def describe_origin(source_repo: Path, rel: Path) -> dict:
    """Where this file came from, and whether the origin tracked it."""
    tracked = subprocess.run(
        ["git", "-C", str(source_repo), "ls-files", "--error-unmatch", str(rel)],
        capture_output=True, text=True).returncode == 0
    blob = git(source_repo, "rev-parse", f"HEAD:{rel}") if tracked else None
    return {
        "tracked_in_origin": tracked,
        "origin_blob_sha": blob,
        # An untracked file has no commit that vouches for it; that has to be
        # visible rather than implied by a missing field.
        "origin_provenance_note": (
            "tracked at origin HEAD" if tracked else
            "UNTRACKED in the origin worktree: no commit vouches for this content; "
            "it is preserved only by the file hash recorded here and by the "
            "divergent-repository backup"),
    }


def collect(source_root: Path) -> tuple[list[dict], list[str]]:
    materials = source_root / "oti_provider" / "materials"
    if not materials.is_dir():
        raise SystemExit(f"no materials directory at {materials}")
    head = git(source_root, "rev-parse", "HEAD")
    remote = git(source_root, "remote", "get-url", "origin")

    records, problems = [], []
    for name in (*REQUIRED, *ADDITIONAL):
        model_dir = materials / name
        if not model_dir.is_dir():
            problems.append(f"{name}: directory absent at {model_dir}")
            continue
        contract = next((model_dir / c for c in CONTRACT_NAMES if (model_dir / c).is_file()), None)
        source = model_dir / SOURCE_NAME
        if contract is None:
            problems.append(f"{name}: no contract file ({' or '.join(CONTRACT_NAMES)})")
        if not source.is_file():
            problems.append(f"{name}: no {SOURCE_NAME}")
        if contract is None or not source.is_file():
            continue

        payload = json.loads(contract.read_text(encoding="utf-8"))
        records.append({
            "model": name,
            "required_for_table6": name in REQUIRED,
            "origin_repo": str(source_root),
            "origin_remote": remote,
            "origin_head": head,
            "contract": {
                "origin_absolute_path": str(contract),
                "filename": contract.name,
                "sha256": sha256_file(contract),
                "schema": payload.get("schema"),
                **describe_origin(source_root, contract.relative_to(source_root)),
            },
            "source": {
                "origin_absolute_path": str(source),
                "filename": source.name,
                "sha256": sha256_file(source),
                "bytes": source.stat().st_size,
                **describe_origin(source_root, source.relative_to(source_root)),
            },
            "ownership": (
                "first-party: purpose-written for this project. Headers describe "
                "self-contained reformulations authored for the OTI provider, not "
                "third-party redistributed code."),
            "excluded_from_import": sorted(
                {p.name for p in model_dir.rglob("*")
                 if p.is_file() and (p.suffix in EXCLUDED_SUFFIXES
                                     or set(p.relative_to(model_dir).parts) & EXCLUDED_DIRS)}),
            "manual_corrections": [],
        })
    return records, problems


def write(records: list[dict], *, dry_run: bool) -> None:
    for record in records:
        target = DEST / record["model"]
        if not dry_run:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(record["source"]["origin_absolute_path"], target / SOURCE_NAME)
            # Preserve the original contract verbatim under a name that says what
            # schema it is; the canonical contract is generated, not hand-edited.
            shutil.copy2(record["contract"]["origin_absolute_path"],
                         target / "contract_v2.json")
        record["imported_to"] = {
            "source": str((target / SOURCE_NAME).relative_to(REPO_ROOT)),
            "contract_v2": str((target / "contract_v2.json").relative_to(REPO_ROOT)),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source", type=Path, default=None,
        help=(f"the working tree to import models from; defaults to ${SOURCE_ENV}. "
              "There is no portable default: this is a path on the machine that "
              "holds the authors' model tree."))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="verify imported files still match the recorded hashes")
    args = parser.parse_args(argv)

    if args.check:
        if not MANIFEST.exists():
            print("no import manifest; nothing to check", file=sys.stderr)
            return 2
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        bad = []
        for record in manifest["models"]:
            for key in ("source", "contract"):
                rel = record["imported_to"]["source" if key == "source" else "contract_v2"]
                path = REPO_ROOT / rel
                if not path.exists():
                    bad.append(f"{record['model']}: {rel} missing")
                elif sha256_file(path) != record[key]["sha256"]:
                    bad.append(f"{record['model']}: {rel} content changed since import")
        if bad:
            print("\n".join(bad), file=sys.stderr)
            return 1
        print(f"all {len(manifest['models'])} imported models match their recorded hashes")
        return 0

    source = args.source or (
        Path(os.environ[SOURCE_ENV]) if os.environ.get(SOURCE_ENV) else None)
    if source is None:
        parser.error(
            f"no import source: pass --source or set {SOURCE_ENV}. This tool "
            "copies models out of the authors' working tree, whose location is "
            "specific to the machine holding it.")
    args.source = source
    records, problems = collect(args.source)
    write(records, dry_run=args.dry_run)

    required = [r for r in records if r["required_for_table6"]]
    manifest = {
        "schema": "umat-oti-model-import/1",
        "policy": (
            "Data only. Build directories, .obj/.o/.mod files, executables and "
            "previously generated numerical results were not imported: they are a "
            "different run's output and would enter this repository as evidence "
            "without provenance. All numbers must be regenerated by this pipeline."
        ),
        "origin": {
            "path": str(args.source),
            "remote": git(args.source, "remote", "get-url", "origin"),
            "head": git(args.source, "rev-parse", "HEAD"),
            "branch": git(args.source, "rev-parse", "--abbrev-ref", "HEAD"),
            "backup": "see softwarex_work/backups/divergent_*/ for the full snapshot",
        },
        "counts": {
            "required_for_table6": len(REQUIRED),
            "required_imported": len(required),
            "additional_imported": len(records) - len(required),
            "problems": len(problems),
        },
        "problems": problems,
        "models": records,
    }
    if not args.dry_run:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")

    print(f"{'DRY RUN: ' if args.dry_run else ''}imported "
          f"{len(required)}/{len(REQUIRED)} required + {len(records) - len(required)} additional")
    for problem in problems:
        print(f"  PROBLEM {problem}")
    schemas = {r["contract"]["schema"] for r in records}
    print(f"  contract schemas seen: {sorted(s for s in schemas if s)}")
    untracked = [r["model"] for r in records if not r["source"]["tracked_in_origin"]]
    print(f"  sources untracked at origin ({len(untracked)}): {', '.join(untracked)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
