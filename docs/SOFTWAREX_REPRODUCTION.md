# Reproducing the published results

This document is for a reviewer who has the repository and wants to check what
it claims. It says what runs without a licence, what does not, what each command
produces, and how pass and fail are decided.

## 1. What the software does

UMAT-OTI rewrites Abaqus UMAT Fortran so that derivatives are computed by
order-truncated imaginary (OTI) automatic differentiation rather than by hand or
by finite differences. It covers the consistent tangent `DDSDDE`, higher-order
stress derivatives, the internal Jacobian of a model's own local Newton solve,
and sensitivities of stress and state to material parameters.

The Residual Assembler is a separate product that consumes the transformed
material and assembles element residuals and structural sensitivities. It lives
in its own repository and is versioned independently; see §11.

## 2. What is included

| Directory | Contents |
|---|---|
| `src/umat_oti/` | the package: transform, pipeline, validation, reproduce |
| `parameter_sensitivity/` | benchmark models, contracts, loading paths, provenance |
| `UMATs/` | the UMAT archive the studies draw on |
| `paper_results/` | generated evidence; every table is regenerated from here |
| `tests/` | the test suite, marked by what each test needs |
| `tools/` | round runners, matrix builders, audits |
| `scripts/` | clean-clone acceptance, ARC submission |
| `docs/` | this document and the design notes |

## 3. What requires Abaqus

Only the paired Abaqus validation behind Table 2. Everything else — the source
transformation, compilation, material-point execution, primal parity, and every
numerical verification against finite differences — runs with Python and
`gfortran` alone.

A reviewer without Abaqus can therefore check the central claim of the paper:
that the transformation produces derivatives that agree with an independent
reference. What they cannot check locally is that the transformed subroutine
behaves identically *inside Abaqus*, which is what Table 2 reports. The archived
evidence for that run is in the repository and readable without a licence:
`paper_results/arc_791506/table2_abaqus_paired.json`, recording the Slurm job
id, hostname, compiler version, originating commit, and SHA-256 of every input
and output.

## 4. Installing

```bash
git clone https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation.git
cd UMAT_source_transformation
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
```

Requires Python 3.10+ and `gfortran`. CI runs 3.10, 3.11 and 3.12 on
Ubuntu with the distribution `gfortran`.

## 5. The smallest example

```bash
python -m umat_oti.reproduce --profile smoke
```

Seconds. Transforms `m3_j2`, compiles it, compiles the untransformed subroutine
separately, runs both over a strain path, and compares the derivatives. Exits
non-zero if they disagree. Read `reproduce/smoke/reproduction_summary.md`.

## 6. Reproducing each result

Every row is one command and one artefact. Commands run from the repository root
with the virtual environment active.

| Result | Command | Artefact | Tier |
|---|---|---|---|
| Table 2 — Abaqus paired | `python -m umat_oti.reproduce --profile abaqus` | `paper_results/arc_791506/table2_abaqus_paired.json` | C |
| Table 3 — internal Jacobians | `python tools/run_internal_jacobian_round.py` | `paper_results/internal_jacobians/table3_internal_jacobians.csv` | A |
| Table 4 — higher orders | `python tools/build_table4_from_convergence.py` | `paper_results/higher_order_convergence/table4_reference_quality_summary.json` | A |
| Table 5 — J2 sensitivities | `python tools/validate_table5.py` | `paper_results/parameter_sensitivity/` | A |
| Table 6 — 18-model sweep | `python tools/run_parameter_sensitivity_sweep.py` | `paper_results/parameter_sensitivity/table6_parameter_sensitivity.csv` | A |
| Generality matrix | `python tools/build_generality_matrix.py` | `paper_results/generality/generality_matrix.csv` | A |
| Traceability matrix | `python tools/build_traceability_matrix.py` | `docs/PIPELINE_REQUIREMENTS_TRACEABILITY.md` | A |
| Everything reproducible | `python -m umat_oti.reproduce --profile paper` | `reproduce/paper/` | A |

Tables are generated. Do not edit them by hand: the next regeneration will
overwrite the edit, and the reconciliation tests compare each table against the
round that produced it.

## 7. Runtime and disk

| Profile | Time | Disk |
|---|---|---|
| `smoke` | seconds | a few MB |
| `offline` | a few minutes, dominated by the test suite | tens of MB |
| `paper` | a few minutes | tens of MB |
| `corpus` | depends on the network and upstream availability | varies |
| `abaqus` | ARC scheduling plus solve time | GB, mostly ODBs |

## 8. What to inspect

Start with `reproduce/<profile>/reproduction_summary.md`. Then:

- `run_manifest.json` — every step, its status, and the reason for any
  non-success.
- `claim_matrix.json` — which published claim each step supports.
- `artifact_checksums.sha256` — checksums of everything the run produced.
- `paper_results/generality/generality_matrix.csv` — one row per source,
  showing exactly how far each one got and what blocked it.

## 9. How pass and fail are decided

A derivative is **verified** only when it agrees with centred differences of the
*independently compiled untransformed* subroutine, evaluated on the same loading
path, after the two builds have been shown to compute the same primal response.
Primal parity gates everything downstream: two builds that disagree on stress do
not have comparable derivatives.

The comparison has **three** outcomes, not two:

1. **agrees** — within the reference's resolution.
2. **disagrees** — outside it. A failure.
3. **reference unresolved** — the reference's own noise floor,
   `eps·|f|/(2h)`, is larger than the quantity being checked, so it cannot
   adjudicate. Counted as neither a pass nor a failure, and reported separately.

The third outcome exists because collapsing it into "pass" inflates the verified
count, and collapsing it into "fail" blames the transformation for the
reference's limits.

A step that cannot run reports `blocked_by_external_dependency` or `unsupported`
with a reason. Neither is a pass. Neither is silently dropped from a denominator.

A model's own hand-written Jacobian is never used as a reference. Where it
appears (Table 3), it is a third, *audited* column checked against the same
finite-difference reference as everything else.

## 10. Reproducibility tiers

**Tier A — public, offline.** Needs the repository, Python, `gfortran` and the
redistributable examples. Reproduces the transformations and every numerical
comparison. This is where the central claims live.

**Tier B — network corpus.** Adds a licensed round over third-party sources,
subject to their licences and upstream availability. Uses immutable commit
snapshots. Run deliberately:
`python -m umat_oti.reproduce --profile corpus --allow-network`.

**Tier C — Abaqus / ARC.** Needs a licensed Abaqus and the documented HPC
environment. The scripts and the archived provenance stay public even though
execution does not.

## 11. Versions and compatibility

| Component | Version |
|---|---|
| `umat-oti` package | see `pyproject.toml` and `CITATION.cff` |
| Contract schema | `resasm_umat_transform_v2` |
| Residual Assembler | separate repository, versioned independently |

The two repositories are separate products connected by a versioned contract.
Exchanged artefacts are validated against the published schema.

## 12. Reporting a reproduction problem

Open an issue at
<https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation/issues> with:

- the command you ran and its full output,
- `reproduce/<profile>/run_manifest.json` and `environment.json`,
- your `gfortran --version` and `python --version`.

A derivative that disagrees with the reference is a real finding and we want to
know about it. Please include the contract and the source that produced it.

## 13. Which commit corresponds to the manuscript

`CITATION.cff` carries the released version, and each release is tagged. The
evidence files record the commit that produced them: `run_manifest.json` and
`environment.json` from any profile, and the `execution_commit_sha` and
`audit_commit_sha` fields inside the archived ARC evidence.

Evidence and manuscript are still converging; a release and DOI will be minted
once the evidence stops changing, not before.
