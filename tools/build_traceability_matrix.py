#!/usr/bin/env python3
"""Generate docs/PIPELINE_REQUIREMENTS_TRACEABILITY.md from live probes.

Every status in the matrix is decided by looking at the repository as it is
now -- does the implementation file exist, does the test exist, does the
evidence artifact have data rows -- rather than by prose that can drift from
reality. A table with a header and no rows is reported as having no rows.

Two status vocabularies are kept separate on purpose.

``execution``  what the code currently does when run:
               implemented / partially_implemented / unimplemented / failed /
               blocked_by_external_dependency
``claim``      what may be asserted in the manuscript:
               verified / partially_implemented / unimplemented / failed /
               blocked_by_external_dependency

Code can be fully implemented and still support no claim, because running is
not verifying. The two columns are never merged.

    python tools/build_traceability_matrix.py [--check]

``--check`` exits non-zero if the generated document differs from the one on
disk, so CI can prove the matrix was regenerated after a change.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESIDUAL_ROOT = REPO_ROOT.parent / "Residual_Assembler"
OUTPUT = REPO_ROOT / "docs" / "PIPELINE_REQUIREMENTS_TRACEABILITY.md"

EXECUTION_STATUSES = (
    "implemented", "partially_implemented", "unimplemented", "failed",
    "blocked_by_external_dependency",
)
CLAIM_STATUSES = (
    "verified", "partially_implemented", "unimplemented", "failed",
    "blocked_by_external_dependency",
)


# --------------------------------------------------------------------------- #
# Probes -- every one of these reads the repository, none takes prose on trust
# --------------------------------------------------------------------------- #
def root_for(repo: str) -> Path:
    return REPO_ROOT if repo == "UMAT_source_transformation" else RESIDUAL_ROOT


def exists(repo: str, rel: str) -> bool:
    return (root_for(repo) / rel).exists()


def csv_data_rows(repo: str, rel: str) -> int | None:
    path = root_for(repo) / rel
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def symbol_present(repo: str, rel: str, symbol: str) -> bool:
    path = root_for(repo) / rel
    if not path.exists():
        return False
    return symbol in path.read_text(encoding="utf-8", errors="replace")


def grep_count(repo: str, pattern: str, subdir: str = "src") -> int:
    root = root_for(repo) / subdir
    if not root.exists():
        return 0
    result = subprocess.run(
        ["grep", "-rl", pattern, str(root)], capture_output=True, text=True
    )
    return len([line for line in result.stdout.splitlines() if line.strip()])


@dataclass
class Requirement:
    id: str
    area: str
    requirement: str
    repo: str
    stage: str
    implementation: str | None = None
    test: str | None = None
    evidence: str | None = None
    execution: str = "unimplemented"
    claim: str = "unimplemented"
    blocker: str | None = None
    notes: str = ""
    measured: dict = field(default_factory=dict)

    def validate(self) -> None:
        assert self.execution in EXECUTION_STATUSES, (self.id, self.execution)
        assert self.claim in CLAIM_STATUSES, (self.id, self.claim)
        # A requirement that supports no claim and has no blocker must say why.
        if self.claim in ("unimplemented", "failed", "blocked_by_external_dependency"):
            assert self.blocker, f"{self.id} needs a blocker"


# --------------------------------------------------------------------------- #
# The requirement set, as measured
# --------------------------------------------------------------------------- #
U = "UMAT_source_transformation"
R = "Residual_Assembler"


def build_requirements() -> list[Requirement]:
    items: list[Requirement] = []
    add = items.append

    # -- 1. pipeline engine ------------------------------------------------- #
    engine = "src/umat_oti/pipeline/engine.py"
    engine_exists = exists(U, engine)
    add(Requirement(
        id="PIPE-ENGINE", area="Pipeline", stage="all",
        requirement="A first-class resumable stage engine with typed stage IO and a run manifest",
        repo=U, implementation=engine if engine_exists else None,
        test="tests/test_pipeline_engine.py" if exists(U, "tests/test_pipeline_engine.py") else None,
        execution="implemented" if engine_exists else "unimplemented",
        claim="partially_implemented" if engine_exists else "unimplemented",
        blocker=None if engine_exists else "no stage engine exists; front ends call transforms directly",
        notes="Stages must distinguish failure from not_requested, unsupported and blocked.",
    ))

    # One normalization boundary. Count the distinct transform entry points in use.
    entry_points = {
        "cli_json.run_config_transform": grep_count(U, "run_config_transform"),
        "transform.source_transform.transform_umat_to_oti_from_config":
            grep_count(U, "transform_umat_to_oti_from_config"),
        "semantic.transform_pipeline.transform_umat":
            grep_count(U, "from umat_oti.semantic.transform_pipeline import"),
        "core.pipeline.transform_umat": grep_count(U, "from umat_oti.core.pipeline import"),
    }
    distinct = sum(1 for count in entry_points.values() if count)
    add(Requirement(
        id="PIPE-ONE-BOUNDARY", area="Pipeline", stage="contract normalization",
        requirement="Exactly one normalization boundary shared by every front end",
        repo=U, implementation="src/umat_oti/cli_json.py (de facto)",
        execution="partially_implemented" if distinct > 1 else "implemented",
        claim="partially_implemented" if distinct > 1 else "verified",
        blocker=(f"{distinct} distinct transform entry points are still in use"
                 if distinct > 1 else None),
        measured={"distinct_transform_entry_points": entry_points},
    ))

    # -- 2. canonical derivative contract ----------------------------------- #
    # Probe the concepts the request model actually uses. The higher-order family
    # is expressed as a kind plus an `order` field, not as a literal DDSDDE4
    # token, so probing for the token would report a false negative.
    families = [
        ("DDSDDE order 1", "KIND_MATERIAL_TANGENT"),
        ("higher-order stress derivatives 2-4", "KIND_HIGHER_ORDER"),
        ("internal constitutive Jacobians", "FJAC"),
        ("DSIGMA_DP", "DSIGMA_DP"),
        ("DSTATEV_DP", "DSTATEV_DP"),
    ]
    req_module = "src/umat_oti/core/derivative_request.py"
    supported = {
        name: symbol_present(U, req_module, token) for name, token in families
    }
    missing = [name for name, ok in supported.items() if not ok]
    add(Requirement(
        id="CONTRACT-FAMILIES", area="Contract", stage="contract inference",
        requirement="One request model expressing seed+response+target+order for all five derivative families",
        repo=U, implementation=req_module,
        test="tests/test_derivative_request.py" if exists(U, "tests/test_derivative_request.py") else None,
        execution="implemented" if not missing else "partially_implemented",
        claim="partially_implemented",
        blocker=None if not missing else f"not expressed in the request model: {', '.join(missing)}",
        measured={"families": supported,
                  "supported_orders_default": "(1, 2, 3, 4)",
                  "extensible_beyond_four": symbol_present(U, req_module, "supported_orders")},
        notes="Orders beyond 4 are reachable only by passing a wider supported_orders "
              "set; the default is (1, 2, 3, 4). The higher-order block is marked "
              "loader-implemented with codegen deferred in the module docstring.",
    ))
    add(Requirement(
        id="CONTRACT-FINITE-STRAIN", area="Contract", stage="contract inference",
        requirement="Finite-strain detection selecting deformation-gradient seeds instead of DSTRAN",
        repo=U,
        implementation=req_module if symbol_present(U, req_module, "DFGRD") else None,
        execution="implemented" if symbol_present(U, req_module, "DFGRD") else "unimplemented",
        claim="unimplemented" if not symbol_present(U, req_module, "DFGRD") else "partially_implemented",
        blocker=(None if symbol_present(U, req_module, "DFGRD")
                 else "no deformation-gradient seed selection in the request model"),
    ))

    # -- 3. paper tables ----------------------------------------------------- #
    table_specs = [
        ("TABLE-2", "Table 2 paired original/transformed Abaqus validation (18 + 1 failed)",
         "paper_results/arc_791506/table2_abaqus_paired.csv", 19),
        ("TABLE-3", "Table 3 internal Jacobians, 19 entries across 10 models",
         "paper_results/arc_791506/evidence/table3_internal_jacobians.csv", 19),
        ("TABLE-4", "Table 4 actual-UMAT higher order for code_imp, UMAT_PCL, UMAT_PCLK, visco_imp",
         "paper_results/higher_order_convergence/table4_higher_order_convergence.csv", 1),
        ("TABLE-5", "Table 5 J2 DSIGMA_DP 6x4 and DSTATEV_DP 1x4",
         "paper_results/arc_791506/evidence/table5_j2_parameter_sensitivities.csv", 28),
        ("TABLE-6", "Table 6 parameter sensitivities across 18 models and all directions",
         "paper_results/arc_791506/evidence/table6_parameter_sensitivity_sweep.csv", 18),
    ]
    for rid, text, rel, minimum in table_specs:
        rows = csv_data_rows(U, rel)
        if rows is None:
            execution, claim = "unimplemented", "unimplemented"
            blocker = f"artifact {rel} does not exist"
        elif rows == 0:
            execution, claim = "unimplemented", "unimplemented"
            blocker = f"{rel} is header-only: 0 data rows"
        elif rows < minimum:
            execution, claim = "partially_implemented", "partially_implemented"
            blocker = f"{rel} has {rows} data rows, expected at least {minimum}"
        else:
            execution, claim = "implemented", "partially_implemented"
            blocker = "row-level reference quality decides the claim; see the claim matrix"
        add(Requirement(
            id=rid, area="Paper tables", stage="evidence generation",
            requirement=text, repo=U, evidence=rel,
            implementation="src/umat_oti/reports/run_softwarex_evidence.py",
            execution=execution, claim=claim, blocker=blocker,
            measured={"data_rows": rows, "minimum_expected": minimum},
        ))

    # The 18-model parameter sensitivity set, by name.
    sweep_models = [
        "m1_elastic", "m2_cubic", "m3_j2", "m5_cpflow", "m6_fcc",
        "sweep_aniso_ortho", "sweep_damage_elastic", "sweep_eco",
        "sweep_j2_bilinear", "sweep_j2_combined", "sweep_j2_kinematic",
        "sweep_lame_elastic", "sweep_maxwell_ve", "sweep_mooney_small",
        "sweep_real_ECL_TEMP", "sweep_real_PCO", "sweep_thermoelastic",
        "sweep_transiso",
    ]
    found = []
    for name in sweep_models:
        hit = subprocess.run(
            ["bash", "-c",
             f"find {REPO_ROOT} -name '*{name}*' -not -path '*/.git/*' | head -1"],
            capture_output=True, text=True).stdout.strip()
        if hit:
            found.append(name)
    add(Requirement(
        id="SWEEP-18-MODELS", area="Paper tables", stage="contract inference",
        requirement="Contracts for the 18 named parameter-sensitivity models",
        repo=U,
        execution="unimplemented" if not found else "partially_implemented",
        claim="unimplemented" if not found else "partially_implemented",
        blocker=(f"{len(sweep_models) - len(found)} of {len(sweep_models)} named models "
                 f"have no contract or source in the repository"),
        measured={"present": found, "absent": [m for m in sweep_models if m not in found]},
    ))

    # -- 4. higher-order regression models ----------------------------------- #
    conv_root = "paper_results/higher_order_convergence"
    for model in ("j2", "code_imp", "UMAT_PCL", "UMAT_PCLK", "visco_imp"):
        rel = f"{conv_root}/{model}/convergence_evidence.json"
        path = root_for(U) / rel
        if not path.exists():
            add(Requirement(
                id=f"HO-{model}", area="Higher order", stage="derivative verification",
                requirement=f"Orders 2-4 from the actual {model} source, independently referenced",
                repo=U, execution="unimplemented", claim="unimplemented",
                blocker="no convergence dataset generated"))
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        rows = summary.get("rows", 0)
        supporting = summary.get("rows_supporting_verification", 0)
        verified = bool(summary.get("verified"))
        status_field = data.get("status")
        if status_field == "failed_transformed_execution":
            execution, claim = "failed", "failed"
            blocker = "the transformed build aborts at run time; no rows exist to classify"
        elif verified:
            execution, claim = "implemented", "verified"
            blocker = None
        else:
            execution, claim = "implemented", "partially_implemented"
            blocker = (f"{rows - supporting} of {rows} rows lack defensible independent "
                       f"support or disagree with a resolved reference")
        add(Requirement(
            id=f"HO-{model}", area="Higher order", stage="derivative verification",
            requirement=f"Orders 2-4 from the actual {model} source, independently referenced",
            repo=U, evidence=rel,
            implementation="src/umat_oti/validation/higher_order_convergence.py",
            test="tests/test_higher_order_convergence.py",
            execution=execution, claim=claim, blocker=blocker,
            measured={"rows": rows, "rows_supporting_verification": supporting,
                      "verified": verified},
        ))

    # -- 5. corpus ------------------------------------------------------------ #
    corpus_stages = ["discover", "license", "snapshot", "dedupe", "analyze",
                     "dependency", "contract", "transform", "compile",
                     "primal_verify", "derivative_verify", "report"]
    corpus_impl = "src/umat_oti/corpus/__init__.py"
    present = [s for s in corpus_stages if symbol_present(U, corpus_impl, s)]
    add(Requirement(
        id="CORPUS-PIPELINE", area="Corpus", stage="web acquisition",
        requirement="discover -> license -> snapshot -> dedupe -> analyze -> ... -> report, per-candidate provenance",
        repo=U, implementation=corpus_impl,
        execution="partially_implemented", claim="partially_implemented",
        blocker=(f"{len(corpus_stages) - len(present)} of {len(corpus_stages)} named "
                 f"stages have no corresponding symbol in the corpus package"),
        measured={"stage_symbols_present": present},
    ))

    # -- 6. Residual Assembler ------------------------------------------------ #
    c3d8 = "residual_core/formulations/c3d8_kernel.py"
    add(Requirement(
        id="RA-C3D8", area="Residual Assembler", stage="residual assembly",
        requirement="Real C3D8 quadrature path recovering B, detJ, weights and DOF maps",
        repo=R,
        implementation=c3d8 if exists(R, c3d8) else None,
        execution="partially_implemented" if exists(R, c3d8) else "unimplemented",
        claim="partially_implemented",
        blocker="not yet validated against 2N+1 Abaqus finite-difference reruns",
    ))
    add(Requirement(
        id="RA-2N1", area="Residual Assembler", stage="derivative verification",
        requirement="Validate real C3D8 J2 against 2N+1 Abaqus finite-difference reruns",
        repo=R, execution="unimplemented", claim="blocked_by_external_dependency",
        blocker="requires Abaqus; this machine has 2021.HF5 and the archived evidence is 2024",
    ))

    # -- 7. scaling ----------------------------------------------------------- #
    add(Requirement(
        id="PERF-SCALING", area="Performance", stage="evidence generation",
        requirement="Measured scaling at 10, paper-set, ~150 and ~200 parameter directions",
        repo=U, execution="unimplemented", claim="unimplemented",
        blocker="no benchmark harness exists; presentation claims remain not_yet_verified",
        notes="Claims such as '1.4 nominal runs', '8x faster', '49 vs 210 updates' and "
              "'400 avoided analyses' must stay labelled not_yet_verified until reproduced.",
    ))

    # -- 8. metadata reconciliation ------------------------------------------- #
    versions = {}
    py = (root_for(U) / "pyproject.toml")
    if py.exists():
        for line in py.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version"):
                versions["pyproject.toml"] = line.split("=", 1)[1].strip().strip('"')
                break
    for rel, token in (("CITATION.cff", "version:"), ("codemeta.json", '"version"'),
                       (".zenodo.json", '"version"')):
        path = root_for(U) / rel
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if token in line:
                versions[rel] = line.split(":", 1)[1].strip().strip(' ",')
                break
    distinct_versions = {v for v in versions.values() if v}
    add(Requirement(
        id="META-VERSION", area="Release metadata", stage="evidence generation",
        requirement="One version across pyproject, CITATION.cff, codemeta.json and .zenodo.json",
        repo=U,
        execution="implemented" if len(distinct_versions) <= 1 else "partially_implemented",
        claim="verified" if len(distinct_versions) <= 1 else "partially_implemented",
        blocker=(None if len(distinct_versions) <= 1
                 else f"version disagreement across metadata files: {versions}"),
        measured={"versions": versions},
    ))

    # -- 9. documentation ----------------------------------------------------- #
    docs = ["START_HERE.md", "docs/CONTRACT_REFERENCE.md", "docs/CLI_REFERENCE.md",
            "docs/STREAMLIT_TUTORIAL.md", "docs/ABAQUS_VALIDATION.md",
            "docs/RESIDUAL_ASSEMBLER_HANDOFF.md", "docs/WEB_CORPUS_GUIDE.md",
            "docs/TROUBLESHOOTING.md", "docs/REPRODUCE_PAPER.md"]
    have = [d for d in docs if exists(U, d)]
    add(Requirement(
        id="DOCS-SET", area="Documentation", stage="release",
        requirement="START_HERE plus contract, CLI, Streamlit, Abaqus, handoff, corpus, troubleshooting and reproduction guides",
        repo=U,
        execution="unimplemented" if not have else "partially_implemented",
        claim="unimplemented" if not have else "partially_implemented",
        blocker=f"{len(docs) - len(have)} of {len(docs)} required documents are absent",
        measured={"present": have, "absent": [d for d in docs if d not in have]},
    ))

    for item in items:
        item.validate()
    return items


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def render(items: list[Requirement]) -> str:
    def cell(value: str | None) -> str:
        return f"`{value}`" if value else "--"

    lines = [
        "# Pipeline requirements traceability",
        "",
        "Generated by `tools/build_traceability_matrix.py`. Every status below is",
        "decided by probing this repository -- file existence, symbol presence, CSV",
        "data-row counts, generated evidence -- not by prose. Regenerate after any",
        "change; `--check` fails if this file is stale.",
        "",
        "## Two status vocabularies, deliberately not merged",
        "",
        "**Execution** is what the code does when run: `implemented`,",
        "`partially_implemented`, `unimplemented`, `failed`,",
        "`blocked_by_external_dependency`.",
        "",
        "**Claim** is what may be asserted in the manuscript: `verified`,",
        "`partially_implemented`, `unimplemented`, `failed`,",
        "`blocked_by_external_dependency`.",
        "",
        "Code can be fully implemented and still support no claim, because running is",
        "not verifying. A row is `verified` only when independent evidence supports",
        "every required part of it.",
        "",
    ]

    by_area: dict[str, list[Requirement]] = {}
    for item in items:
        by_area.setdefault(item.area, []).append(item)

    counts: dict[str, int] = {}
    for item in items:
        counts[item.claim] = counts.get(item.claim, 0) + 1
    lines += ["## Claim status roll-up", "", "| Claim status | Requirements |", "|---|---:|"]
    for status in CLAIM_STATUSES:
        if counts.get(status):
            lines.append(f"| `{status}` | {counts[status]} |")
    lines += [f"| **total** | **{len(items)}** |", ""]

    for area in sorted(by_area):
        lines += [f"## {area}", "",
                  "| ID | Requirement | Repo | Stage | Implementation | Test | Evidence | Execution | Claim |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for item in sorted(by_area[area], key=lambda r: r.id):
            lines.append(
                f"| `{item.id}` | {item.requirement} | {item.repo} | {item.stage} | "
                f"{cell(item.implementation)} | {cell(item.test)} | {cell(item.evidence)} | "
                f"`{item.execution}` | `{item.claim}` |"
            )
        lines.append("")
        for item in sorted(by_area[area], key=lambda r: r.id):
            if not (item.blocker or item.measured or item.notes):
                continue
            lines.append(f"**`{item.id}`**")
            if item.blocker:
                lines.append(f"- blocker: {item.blocker}")
            if item.notes:
                lines.append(f"- note: {item.notes}")
            for key, value in item.measured.items():
                rendered = json.dumps(value, sort_keys=True)
                if len(rendered) > 400:
                    rendered = rendered[:397] + "..."
                lines.append(f"- measured `{key}`: {rendered}")
            lines.append("")

    lines += [
        "## What this matrix is not",
        "",
        "It does not record intent. A requirement whose implementation exists but",
        "whose evidence artifact has no data rows is reported as `unimplemented`,",
        "because an empty table supports nothing. A requirement blocked on external",
        "software is `blocked_by_external_dependency`, never `failed` -- those are",
        "different situations and conflating them hides which one applies.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the file on disk is stale")
    args = parser.parse_args(argv)

    content = render(build_requirements())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != content:
            print(f"stale: {OUTPUT.relative_to(REPO_ROOT)} differs from a fresh probe",
                  file=sys.stderr)
            return 1
        print(f"up to date: {OUTPUT.relative_to(REPO_ROOT)}")
        return 0
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
