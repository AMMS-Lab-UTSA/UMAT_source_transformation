#!/usr/bin/env python
"""Freeze an immutable publication evidence snapshot tied to exact commits.

A figure or a table is only as trustworthy as the run behind it. This copies the
current evidence into a directory named for the commits that produced it,
records the environment it ran in, and hashes everything, so a number in the
manuscript can be traced to a file, a command and a commit rather than to a
memory of having run something.

Nothing is overwritten. Each freeze lands in its own directory; a second freeze
at the same commits is refused unless --force is given, because silently
replacing a snapshot that figures already cite is how a paper ends up with
numbers nobody can reproduce.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

RESULTS = REPO_ROOT / "paper_results"
FROZEN = RESULTS / "frozen"

#: Evidence files a publication figure or table may draw on.
EVIDENCE = (
    "parameter_sensitivity/parameter_sensitivity_round.json",
    "parameter_sensitivity/table6_parameter_sensitivity.csv",
    "parameter_sensitivity/table6_comparison_rows.csv",
    "internal_jacobians/internal_jacobian_round.json",
    "internal_jacobians/table3_internal_jacobians.csv",
    "corpus/corpus_round.json",
    "corpus/corpus_funnel.csv",
    "generality/generality_matrix.csv",
    "generality/generality_summary.json",
    "generality/source_identity.json",
    "generality/source_identity.csv",
    "arc_791506/table2_abaqus_paired.csv",
    "arc_791506/table2_abaqus_paired.json",
    # The illustrative example's own derivative evidence, which the tangent and
    # higher-order figures and tables are read from.
    "actual_umat_higher_order/j2/table2_ddsdde_illustrative.csv",
    "actual_umat_higher_order/j2/actual_umat_ddsdde.csv",
    "actual_umat_higher_order/j2/actual_umat_higher_order_comparison.csv",
    "actual_umat_higher_order/j2/table4_higher_order_actual_umat.csv",
    "actual_umat_higher_order/j2/actual_umat_higher_order_evidence.json",
    "higher_order_convergence/table4_reference_quality_summary.json",
    # The publication figures and tables, so a snapshot carries the artefacts a
    # reader actually sees and not only the files they were computed from.
    "figures/figure_gui_source.png",
    "figures/figure_gui_material.png",
    "figures/figure_gui_request.png",
    "figures/figure_gui_results.png",
    "figures/figure_gui_products.png",
    "figures/figure_tangent_verification.png",
    "figures/figure_higher_order_verification.png",
    "figures/figure_sensitivities.png",
    "figures/figure_collection_coverage.png",
    "figures/figure_verification_routes.png",
    "figures/gui_screenshots_provenance.json",
    "figures/figure_tangent_verification_provenance.json",
    "figures/figure_higher_order_verification_provenance.json",
    "figures/figure_sensitivities_provenance.json",
    "figures/figure_collection_coverage_provenance.json",
    "figures/figure_verification_routes_provenance.json",
    "tables/paper_tables.docx",
    "PAPER_READY_SUMMARY.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout.strip() or None) if proc.returncode == 0 else None


def repository_state(repo: Path) -> dict:
    """Branch, commit and whether anything uncommitted could affect the result.

    The snapshot directory this tool is in the middle of writing is excluded
    from the dirty check. Counting it would make every freeze report a dirty
    tree because of its own output, which says nothing about whether the code
    that produced the evidence was committed.
    """
    dirty_lines = (_git(repo, "status", "--porcelain") or "").splitlines()
    dirty_lines = [line for line in dirty_lines
                   if "paper_results/frozen/" not in line]
    dirty = "\n".join(dirty_lines)
    return {
        "path_name": repo.name,
        "url": _git(repo, "remote", "get-url", "origin"),
        "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "commit": _git(repo, "rev-parse", "HEAD"),
        "worktree_dirty": bool(dirty_lines),
        "dirty_paths": dirty_lines,
        "dirty_check_note": ("paper_results/frozen/ is excluded: it is this "
                             "tool's own output"),
    }


def _command_line(*command: str) -> str | None:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (proc.stdout or proc.stderr).strip()
    return text.splitlines()[0] if text else None


def environment() -> dict:
    from umat_oti.environment import detect_abaqus  # noqa: PLC0415

    abaqus = detect_abaqus()
    frozen_packages = _command_line(sys.executable, "-m", "pip", "freeze")
    try:
        proc = subprocess.run([sys.executable, "-m", "pip", "freeze"],
                              capture_output=True, text=True, timeout=120)
        packages = sorted(proc.stdout.strip().splitlines()) if proc.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        packages = []
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "operating_system": platform.platform(),
        "machine": platform.machine(),
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "fortran_compiler": _command_line("gfortran", "--version"),
        "fortran_flags": {
            "material_point_original": "-O1 -std=legacy -ffixed-form "
                                       "-ffixed-line-length-none",
            "oti_module_and_driver": "-O1 -std=legacy -ffree-line-length-none "
                                     "-fno-align-commons",
        },
        "make": _command_line("make", "--version"),
        "abaqus": abaqus.to_dict(),
        "dependency_lock": packages,
        "dependency_lock_note": (
            "pip freeze of the interpreter that produced this snapshot"
            if packages else "pip freeze was unavailable"),
        "_pip_freeze_first_line": frozen_packages,
    }


def tolerances() -> dict:
    """Every tolerance a verdict depends on, with why it is what it is."""
    return {
        "derivative_relative_tolerance": {
            "value": 1.0e-6,
            "applies_to": "OTI derivative against its independent reference",
            "justification": (
                "A centred difference at a well-chosen step resolves a smooth "
                "derivative to roughly 1e-8 relative; 1e-6 leaves two decades of "
                "margin for the reference's own truncation without admitting a "
                "genuine transformation error. It is never widened to recover a "
                "result: a row the reference cannot resolve at this tolerance is "
                "reported as unresolved, not as agreement."),
        },
        "primal_parity_relative_tolerance": {
            "value": 1.0e-9,
            "applies_to": "stress and state of the original vs transformed build",
            "justification": (
                "The two builds run the same algorithm in different arithmetic, "
                "so they should agree to near machine precision; 1e-9 catches a "
                "genuine divergence while tolerating reassociation. Measured "
                "values sit at 1e-14 to 1e-16, far inside it."),
        },
        "finite_difference_default_relative_step": {
            "value": 1.0e-4,
            "applies_to": "first-pass centred-difference reference",
            "justification": (
                "A first pass only. Where a row disagrees, the step is chosen "
                "from the method's own convergence over a ladder spanning 1e-2 "
                "to 1e-7 rather than fixed in advance, because a fixed step is a "
                "guess about the model's third derivative."),
        },
        "finite_difference_noise_floor": {
            "expression": "eps * max(|response_scale|, 1) / (2h)",
            "applies_to": "whether the reference can adjudicate a row at all",
            "justification": (
                "Models cancellation only. Truncation is handled separately by "
                "the step-convergence study, because the two dominate in "
                "opposite step regimes."),
        },
    }


def gates() -> list[dict]:
    return [
        {"gate": 1, "name": "source identity and dependency closure",
         "meaning": "the source is identified by content and its helper closure "
                    "resolves with no missing or ambiguous definitions"},
        {"gate": 2, "name": "transformation",
         "meaning": "the OTI source was generated"},
        {"gate": 3, "name": "compilation of both implementations",
         "meaning": "original and transformed compiled independently"},
        {"gate": 4, "name": "execution of both", "meaning": "both ran the path"},
        {"gate": 5, "name": "primal parity",
         "meaning": "stress and state agree, so the derivatives are comparable"},
        {"gate": 6, "name": "reference resolution",
         "meaning": "an independent reference can determine the value"},
        {"gate": 7, "name": "derivative comparison",
         "meaning": "the extracted derivative agrees with that reference"},
        {"_policy": "A case failing an earlier gate contributes no verified "
                    "derivative rows. Compilation is not verification."},
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-root", type=Path, default=FROZEN)
    parser.add_argument("--force", action="store_true",
                        help="overwrite a snapshot already frozen at these commits")
    parser.add_argument("--label", default=None)
    args = parser.parse_args(argv)

    umat = repository_state(REPO_ROOT)
    companion_path = REPO_ROOT.parent / "Residual_Assembler"
    companion = repository_state(companion_path) if companion_path.is_dir() else None

    short = (umat["commit"] or "unknown")[:12]
    name = args.label or f"umat-{short}"
    if companion and companion["commit"]:
        name += f"_ra-{companion['commit'][:12]}"
    destination = args.out_root / name
    if destination.exists() and not args.force:
        print(f"a snapshot for these commits already exists at "
              f"{destination.relative_to(REPO_ROOT)}. Refusing to overwrite it: "
              "figures and tables cite it by path. Pass --force only if you mean "
              "to replace it.", file=sys.stderr)
        return 3
    if destination.exists():
        shutil.rmtree(destination)
    (destination / "evidence").mkdir(parents=True)

    copied, missing = [], []
    for relative in EVIDENCE:
        source = RESULTS / relative
        if not source.is_file():
            missing.append(relative)
            continue
        target = destination / "evidence" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append({"path": relative, "sha256": sha256(target),
                       "bytes": target.stat().st_size})

    manifest = {
        "schema": "umat-oti-frozen-evidence/1",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_name": name,
        "repositories": {"umat_source_transformation": umat,
                         "residual_assembler": companion},
        "environment": environment(),
        "tolerances": tolerances(),
        "verification_gates": gates(),
        "evidence_files": copied,
        "evidence_files_absent": missing,
        "regeneration_commands": [
            "python tools/run_parameter_sensitivity_sweep.py",
            "python tools/run_internal_jacobian_round.py",
            "python tools/run_corpus_round.py",
            "python tools/build_source_identity_registry.py",
            "python tools/build_generality_matrix.py",
            "python tools/build_publication_reconciliation.py",
            "python tools/build_paper_summary.py",
            "python tools/freeze_publication_evidence.py",
        ],
        "policy": (
            "Every figure and table in the manuscript is generated from the "
            "files in this directory. A number that appears in the paper and "
            "not here has no provenance and must not be published."),
    }
    manifest_path = destination / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")

    checksums = destination / "SHA256SUMS"
    lines = [f"{entry['sha256']}  evidence/{entry['path']}" for entry in copied]
    lines.append(f"{sha256(manifest_path)}  MANIFEST.json")
    checksums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"froze {len(copied)} evidence files into "
          f"{destination.relative_to(REPO_ROOT)}")
    if missing:
        print(f"absent (recorded, not silently skipped): {', '.join(missing)}")
    print(f"umat  {umat['commit']}  dirty={umat['worktree_dirty']}")
    if companion:
        print(f"ra    {companion['commit']}  dirty={companion['worktree_dirty']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
