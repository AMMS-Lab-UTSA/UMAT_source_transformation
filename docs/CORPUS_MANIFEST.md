# Corpus manifest

`paper_results/corpus/manifest/corpus_manifest.json` describes every candidate in the
UMAT corpus in machine-readable form: one row per acquired source (the 391 registry
records) and one row per candidate file the discovery inventory found but never
acquired (`row_kind: discovered_not_acquired`, counted apart from the acquired
rows). `corpus_manifest.csv` is a flat view with one line per row, and
`corpus_manifest.schema.json` is its JSON Schema (draft 2020-12).

## Regenerate

```bash
PYTHONPATH=src python tools/build_corpus_manifest.py \
    --merge-ra ../corpus_campaign/batches/B1/noether/records.jsonl   # ~15 s, offline
PYTHONPATH=src python -m pytest -q tests/test_corpus_manifest_*.py
```

The published files were built with exactly that command. The build is
deterministic. If the inputs are unchanged, a rebuild writes byte-identical
files, because `generated` keeps its old value when nothing else in the
document changed.

The build reads only local files: the registry and discovery inventory in this
repository, and the workspace roots beside it. You can override each root with a flag or an
environment variable:

| root | default | override |
|---|---|---|
| `discovery_cache` | `../discovery_cache` | `--discovery-cache`, `UMAT_OTI_DISCOVERY_CACHE` |
| `transform_store` | `../transform_store` | `--transform-store`, `UMAT_OTI_TRANSFORM_STORE` |
| `corpus_run` | `../corpus_run` (passes, family files) | `--corpus-run`, `UMAT_OTI_CORPUS_RUN` |
| `campaign` | `../corpus_campaign` (batch evidence) | `--campaign`, `UMAT_OTI_CAMPAIGN` |
| `ra` | `../final-ra` (Residual Assembler) | `--ra-repo`, `UMAT_OTI_RA_REPO` |
| `umat` (= `repo`) | this checkout | — |
| families | `corpus_run/material_families_checked_E.json` | `--families` |

`--current-pass` (default `pass16`, the frozen pass the registry was built from)
supplies the stage statuses. `--later-pass` (default `pass17`) is only compared
against it. Differences are reported and never override the current pass.

## Evidence locators

Every cell has an `evidence` string of the form `<root>:<relative path>[#selector]`.
`roots` in the header maps each root name to the absolute path used for the build:

| root | what it is |
|---|---|
| `campaign` | `/home/ammslab3/softwarex_work/corpus_campaign` (batch reports, harness output) |
| `umat` / `repo` | `/home/ammslab3/softwarex_work/final-umat` (`repo` is kept for B1 locators) |
| `ra` | `/home/ammslab3/softwarex_work/final-ra` |
| `corpus_run` | `/home/ammslab3/softwarex_work/corpus_run` (passes; also `families`) |
| `discovery_cache` | `/home/ammslab3/softwarex_work/discovery_cache` |
| `transform_store` | `/home/ammslab3/softwarex_work/transform_store` |

For example, `corpus_run:pass16/results/store_verification.jsonl#key=<key>` is the
line with that `key`. `resolve_locator(locator, roots)` returns the file, or the reason
it does not resolve. A locator must name an existing file and must stay inside its
root. The selector after `#` is not checked. The merge rewrites an absolute path that
lies under a known root to the `<root>:<relative>` form, and refuses any other absolute
path. Every locator in the published manifest resolves; a test checks this.

## Row fields

- **Identity and provenance**
  - `source_id`, `repository`, `path_in_repository`, `url` (+ `url_provenance`), `commit`.
  - `sha256.registry` is the registry's hash. `sha256.recomputed` is the hash of the cached file. `sha256.agrees` compares the two.
  - `normalised_content_sha256` and `code_only_sha256` come from `umat_oti.corpus.identity`. They are used to match sources across rounds.
  - `bytes.on_disk` and `bytes.registry`. The frozen registry's value is the length of the decoded text, not the file size, so the two differ on 115 rows (CRLF line endings, non-UTF-8 bytes). `tools/build_corpus_registry.py` now records the file size, and the difference disappears when the registry is re-frozen.
  - `retrieval`: URL@commit + path + sha256, with a shell recipe to fetch the file again.
- **license** (lead decision D-1/D-2)
  - `redistribution` is `permitted` only when a licence **file** sits at the repository root in the acquisition cache (the tree at the pinned commit) and its text reads as MIT, BSD-2/3-Clause, Apache-2.0, GPL-3.0(-or-later) or LGPL-3.0.
  - Without such a file, a compatible licence known only from repository metadata (registry `license_spdx` / GitHub licence API) is `unknown`. The basis then says "file absent from cache". The cache holds a partial tree, so this does not mean the repository has no licence.
  - No licence at all, or an incompatible one (GPL-2.0-only, NC/ND), is `not_permitted`.
  - Licences that are compatible but not on the lead's list (AGPL-3.0, ISC, Zlib) are `unknown` until the lead decides.
  - Each row also records `redistribution_basis`, `licence_file` (locator, detected SPDX, sha256), `spdx_metadata`, `attribution_required`, `copyleft` (`none|weak|strong|network`) and `conditions`.
  - `umat_oti.corpus.acquire.classify_license_text` classifies the licence file. A GNU licence is identified by the notice at the top of the file, which also decides whether "any later version" is allowed, or else by its own title line. It is never identified by searching the body for a phrase. The GPL-3.0 body names the Affero licence in its section 13, and the LGPL-3.0 body names "version 3 of the GNU General Public License". Because of this, the old whole-text search read every GPL-3.0 file as AGPL-3.0 and every LGPL-3.0 file as GPL-3.0.
  - The licence is repository-scoped. Per-file headers are not read.
- **model**
  - `family`: the family from the reviewed classification (see below), with `review` = `agent_reviewed_code_evidence` (the row was checked by Agent E from code evidence) or `keyword_only` (the row still carries the keyword marker). `human_reviewed` is false for every row, because neither family file records a human review. `second_pass` carries the 2026-09-30 second pass (Vera) for comparison.
  - `entry_point`.
  - `required_files`:
    - `companions`: the full closure from `umat_oti.abaqus.companions.resolve`. In the frozen registry this string is cut at 500 characters (2 rows). The registry builder no longer truncates it, nor `missing_companions` (which was cut at 300).
    - `missing_companions` and `unresolved_by_resolver`.
    - `includes`: each with where it resolves (`abaqus_installation`, `published_beside_source`, `not_found_in_cache`).
    - `data_files`: the `FILE=` arguments of `OPEN` statements.
  - `external_routines`: names called by `CALL` but not defined anywhere in the closure, classified as `abaqus_utility`, `lapack_blas`, `fortran_intrinsic_or_vendor`, `mpi` or `unresolved_external`. Calls through dummy procedures also land in `unresolved_external`.
  - `modules_used`: each with `defined_in_closure` and `intrinsic_or_vendor`.
  - `compiler_requirements`: form, suffix, preprocessor directives, extensions (tabs in fixed form, lines past column 72/132, `REAL*8`, `DOUBLE COMPLEX`, `!DEC$`/`!DIR$`), OpenMP, whether the Abaqus header is needed, and the registry's offline compile defect. These are read from the source, not from a compile.
- **interface**
  - `dimensionality` covers `three_d` (NTENS 6), `plane_strain` and `axisymmetric` (NTENS 4) and `plane_stress` (NTENS 3), plus `cohesive`/`shell`/`membrane` where a deck uses them. Each entry has a `support` (`supported|not_supported|unknown`), a `basis` and an `evidence_kind`:
    - `measured` / `abaqus_run`: the original ran to completion in Abaqus on that element class.
    - `inferred` / `author_deck`: the author's deck assigns the material to that element.
    - `inferred` / `source_branch`: the source tests `NTENS`/`NDI`/`NSHR` against that value.
    - `inferred` / `source_array_shape`: the arguments are dimensioned `(6)`/`(6,6)`, so only 3D is supported and the other classes are marked `not_supported`.
    - `unknown`: none of the above.
  - `ntens_measured` and `element_measured` give the NTENS and element of the verification run. That element is often not the author's (e.g. C3D8H for the author's C3D20H). `elements_in_author_deck` lists the author's.
  - `strain_formulation`: which of `DSTRAN`, `STRAN`, `DFGRD0`, `DFGRD1`, `DROT` the executable statements read, the resulting `measure`, whether "logarithmic/Hencky" strain is mentioned anywhere, the registry kinematics, and `nlgeom` as read from the author's deck (`yes|no|unknown`).
  - `props` and `nstatv`: the count, its provenance (the deck block it came from), and the largest literal index the source uses.
  - `state_initialisation`: whether SDVINI is defined, whether the deck supplies initial STATEV, whether the source branches on `KINC/KSTEP == 1`, and whether it opens files.
- **pipeline**: one cell per stage, each with `status`, `reason` and `evidence`. `compiled.layouts` holds `offline_gfortran_store` (the transform store build) and `abaqus_ifort_job` (the OTI job built with Abaqus's own compile line).
- **features**: one cell per feature column, measured on the Abaqus-pipeline (`store`) build. Each cell has:
  - `status`, `reason`, `evidence`;
  - `reference` (`original|analytical|fd`);
  - `max_error`, `tolerance`, `tolerance_rule_id`, `rtol` (see the merge contract below);
  - `build` and `history`.

  Derivative cells also state `quantity`, `wrt`, `held_fixed` and `scope` (`local|total`).
- **features_other_builds**: `{"lifted": {...}, "provider": {...}}`. These are cells measured on a different build of the same source: the parameter-sensitivity lifter, or `umat_oti.provider` as used by the Residual Assembler. They are counted only in `summary.features_other_builds`, never in `summary.features`.
- **ddsdde_legacy_gate**: what the pass16 gate `derivatives_verified` said (`passed|failed|not_run`), with its reason, evidence, worst relative error, tolerance and step ladder. `counts_as_verified` is always false (see `ddsdde` below).
- `registry`: terminal state, kind, stage and store key.
- `later_pass`: the stage recorded in pass17.
- `data_quality`: problem codes for this row.

## How statuses are decided

The statuses are:

- `verified`.
- `failed`.
- `blocked`: an external cause, such as missing data or a missing dependency.
- `unsupported`: a named limitation of this project.
- `not_applicable`.
- `not_attempted`.
- `conflict`: feature cells only. Independent evidence says both `verified` and `failed`. Both are listed in `conflicting` and neither is counted.
- `inconclusive`: feature cells only. The evidence neither establishes nor refutes the claim.

| stage | verified when | otherwise |
|---|---|---|
| discovered | the file is in the discovery inventory | — |
| eligible | registry `adequately_specified` (D2) | not a UMAT or a duplicate → `not_applicable`; external inadequacy → `blocked` |
| attempted | registry `attempted` | — |
| transformed | registry `transformed` | not a UMAT → `not_applicable`; external cause → `blocked`; transformer refusal → `unsupported` |
| compiled | at least one layout compiled | a layout attempted but not compiled → `failed` |
| original_executed | the pass row's `original.completed` | job did not complete → `failed` (`blocked` if the cause is external); no material data → `blocked`; NTENS mismatch → `unsupported` |
| oti_executed | the pass row's `transformed.completed` | as above |
| primal_agreed | gate `primal_agreed` is true | gate false → `failed` |

A stage with no evidence of its own inherits `blocked`, `not_applicable` or `unsupported` from the stage above it. If the stage above failed, it is `not_attempted`.

Features:

- **primal_stress_state**: the outcome follows the pass16 gates.
  - `verified`: the gates `abaqus_job_completed`, `complete_history_finite`, `primal_agreed` and `mechanically_informative` are all true.
  - `failed`: only when the values disagree. That means `primal_agreed` is false, the original is finite, and the difference is not explained by the original's own reassociation spread. The cell carries `values_disagree: true`.
  - `inconclusive`: three cases.
    - The builds agree on a run that is not mechanically informative.
    - The original is non-finite.
    - The difference lies within the original's own reassociation spread.
  - The rule is `abaqus_primal_history_floor/1` with `rtol` 1e-10. `max_error` is the worst relative difference divided by `rtol`. The raw values are under `measured`.
- **ddsdde** is `verified` only from merged evidence that complies with D-4 and was measured on the store build, and only while that row's `primal_stress_state` is `verified`.
  - The pass16 gate `derivatives_verified` uses the legacy plateau, taken from the OTI-vs-FD error, which D-4 rejects. It is shown in `ddsdde_legacy_gate` and in `summary.ddsdde_legacy_gate`, and it is never counted.
  - Until such evidence is merged, the cell is `not_attempted` and its reason names the legacy result.
- **internal_jacobian** and the four parameter-sensitivity columns stay `not_attempted`, because no corpus source shares code with the internal-Jacobian round or with the 20 curated parameter-sensitivity models. This was checked by normalised-content and code-only SHA-256.
- **residual_sens** and **global_sens** have no store-build evidence. The Residual Assembler's results (provider build) are in `features_other_builds.provider`.
- **cli_driver** has no evidence yet.

Being skipped, transformed, compiled or executed never makes a cell `verified`.

## Denominators

`summary.denominators`:

- **D0**: acquired sources plus discovered-but-not-acquired candidates.
- **D1**: acquired sources.
- **D2**: eligible sources.
- **discovered_not_acquired**: counted apart.

`summary.stages` and `summary.features` give per-status counts for each population, and every block sums to its denominator. `summary.features` counts the store build only.

Three further blocks are reported apart:

- `summary.ddsdde_legacy_gate`: counts of `passed`, `failed` and `not_run` for D1 and D2, and how many legacy passes have a primal that is not verified.
- `summary.features_other_builds`: per build and feature, `rows_with_cell` and the status counts over those rows. These are results verified on the lifted or provider build. Never add them to the pipeline figures.
- `summary.funnel`: the verified counts in pipeline order.

`discovery_census` counts the inventory's other outcomes, such as repositories refused for a missing or incompatible licence, or files not examined.

## Merging later results (the merge contract)

```python
from umat_oti.corpus_features.manifest import merge_feature_results
report = merge_feature_results(manifest, "results.jsonl")   # or an iterable of dicts
```

Each JSONL line is one cell:

```json
{"source_id": "...", "feature": "ddsdde", "status": "verified", "reason": "...",
 "evidence": "campaign:batches/B2/gauss/run/corpus_features.jsonl#key=...&feature=ddsdde",
 "reference": "fd", "max_error": 0.31, "tolerance": 1.0,
 "tolerance_rule_id": "entrywise/1", "rtol": 1e-6, "atol": 1e-12,
 "fd_steps": [1e-3, 3e-4, 1e-4, 3e-5, 1e-5, 3e-6],
 "min_plateau_observed": 3, "plateau_basis": "fd_only",
 "quantity": "DDSDDE = d STRESS_{n+1}/d DSTRAN", "wrt": "DSTRAN",
 "held_fixed": "incoming STRESS/STATEV, PROPS, TIME, TEMP", "scope": "local",
 "build": {"kind": "store", "fingerprint": "<transform fingerprint>", "sha256": "<object sha256>"},
 "producer": "gauss/B2"}
```

`validate_cell(feature, cell, roots=...)` checks every record.

**Every record** needs:

- a known feature and status;
- a reason, unless the status is `verified`;
- an evidence locator that resolves to a file. This is required for `verified`, `failed`, `inconclusive` and `conflict`, and it is also checked whenever a locator is given.

A record may not claim `conflict`. Only the merge produces that status.

**Derivative cells** with status `verified`, `failed` or `inconclusive` must name a `build`:

- `kind` is `store`, `lifted` or `provider`;
- at least one of `fingerprint` and `sha256` is a real value.

**Tolerance: one semantics.** `tolerance` is exactly 1.0. `max_error` is the largest ratio `|value − reference| / τ_e` over every judged entry, so `verified` needs `0 ≤ max_error ≤ 1`. `tolerance_rule_id` names the rule that defines `τ_e`, and `rtol` (that rule's relative coefficient) must be finite and within the rule's bound:

| rule id | accepted for verified | applies to | rtol ≤ | τ_e |
|---|---|---|---|---|
| `entrywise/1` | yes | derivative, primal | 1e-4 | `atol + rtol·|ref_e|` (+ `2·u_e` for the plateau spread); no column/row/path/history floor |
| `primal_row_scaled/1` | yes | primal | 1e-8 | `atol + rtol·max(|row max|, 1e-3·|history max|)` (harness primal rule) |
| `abaqus_primal_history_floor/1` | yes | primal | 1e-8 | `umat_oti.abaqus.compare`: relative per component; components below 1e-8 of the history max are skipped; differences below 1e-12 of the history max are treated as indistinguishable |
| `legacy_column_norm` | **no** | — | — | `atol + rtol·max(|ref_e|, column norm)` or a path floor (B1 review C) |
| `vector_max_norm` | **no** | — | — | `max|a−d| ≤ atol + rtol·max(max|a|, max|d|)` over a vector |

**FD reference.** `verified` additionally needs:

- `fd_steps` with at least 3 sizes;
- `plateau_basis: "fd_only"`, meaning the FD values themselves agree over consecutive steps. A plateau taken from the OTI-vs-FD error is the legacy rule that D-4 rejects.
- `min_plateau_observed` of at least 3. This is the shortest plateau actually found, not the ladder length, and it may not exceed the ladder length.

**Derivative claims** state `quantity`, `wrt` and `held_fixed` with real values. Placeholders such as `-`, `n/a` or `x`, and anything shorter than 3 characters, are refused. `scope` is `local` or `total`.

**A `failed` primal** must record a disagreement: `max_error > tolerance`, a non-finite value, or `values_disagree: true`. Anything weaker is `inconclusive`.

**How accepted records combine** with the current cell. The result does not depend on the order in which records arrive:

- A record is routed by `build.kind`. `store`, or no build, goes to `features`. `lifted` and `provider` go to `features_other_builds`.
- `verified` and `failed` from any two sources give `conflict`. The cell lists both under `conflicting`, and its reason names who said what.
- A `failed` is never replaced by a `verified`. A `conflict` stays a conflict and collects any new decisive evidence.
- Two `verified` records keep the one with the larger `max_error`.
- Without decisive evidence, the more informative status stays: `inconclusive` > `unsupported` > `blocked` > `not_applicable` > `not_attempted`. A tie goes to the newer record.
- The replaced cells move to `history`.

**Primal gate.** After every merge, a `verified` derivative cell on the store build becomes `inconclusive` unless `features.primal_stress_state` is `verified`. The withheld cell is kept in `withheld_verified`, and it is restored if the primal verifies later. On a lifted or provider build, the same rule uses that build's own primal cell when one was merged. If none was merged, the cell carries `primal_of_this_build: "not recorded"`.

A rejected record leaves the manifest unchanged. Every merge is logged in `manifest.merges`, with its label, counts, full rejection reasons and unmatched source ids. Then the summary is recomputed.

```bash
PYTHONPATH=src python tools/build_corpus_manifest.py --merge results.jsonl
```

### Residual Assembler records

`--merge-ra <records.jsonl>` folds `ra-corpus-residual/1` records with `ra_records_to_cells`. Each record covers one source, feature and problem, and the fold produces one cell per source and feature. Only `residual_sens` (scope `local`) and `global_sens` (scope `total`) are folded; `assembly_consistency` has no manifest column and is skipped. All cells are on the `provider` build.

The RA records do not meet the contract as written, and the adapter states how it maps them:

- `reference` is prose. It maps to `fd`, and the step ladder is parsed out of the text.
- The tolerance is a vector max-norm rule (`vector_max_norm`).
- The plateau is the run of steps where FD agrees with OTI (`plateau_basis: oti_vs_fd`).
- No error/tolerance ratio and no observed plateau are recorded.
- `what` maps to `quantity`. `object_sha256` becomes the build's digest.

The resulting statuses:

- An RA `verified` becomes `inconclusive`. The RA verdict is kept in `producer_status`.
- `failed` on any problem becomes `failed`.
- `unsupported` on every problem becomes `unsupported`.

The adapter's mismatch counts are logged in `manifest.merges[*].ra_adapter`.
