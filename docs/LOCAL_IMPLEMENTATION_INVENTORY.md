# Local implementation inventory

A read-only survey of every UMAT-OTI / HYPAD / OTI / Residual-Assembler
implementation found on this machine, taken before any further development so
that existing work is reused rather than reinvented.

**Nothing outside `~/softwarex_work/` was modified.** No files were copied and no
commits were cherry-picked. Where a copy holds something useful, this document
records what and why; integration happens later, deliberately, with provenance
and tests.

Survey date: 2026-08-24. Active branches at the time:
`UMAT_source_transformation@feature/softwarex-unified-umat-oti` = `407d31d`,
`Residual_Assembler@feature/umat-oti-residual-bridge` = `d96a2ee`.

## Summary of what matters

Three copies hold work the active branches do not:

1. `~/Documents/UMAT_source_transformation` — **the complete 18-model
   parameter-sensitivity set** under `oti_provider/materials/` (21 models, all 18
   named ones present), plus `START_HERE.md`, a user manual, Abaqus validation
   scripts, and six vendored external UMAT repositories. Same project lineage as
   the active repo, but its local `main` is 24 commits of work never pushed.
2. `~/Desktop/Residual_Assembler(2)/Residual_Assembler` — **183 tracked files the
   active branch lacks**, including the replay ABI and driver, full-field
   sensitivity, a 3D solid element kernel, derivative-field exporters and a
   project pipeline. Shares the active tip; its local `main` is divergent work.
3. `~/Desktop/framework_repos (2)/framework_repos/umat-oti` — **web-corpus
   tooling** (the `framework_repos/umat-oti/tools/corpus/` tree of the separate framework_repos checkout: scrape, scan, batch, normalize, plot). Unrelated
   git history; a separate packaging.

Plus two external dependencies and one benchmark: `~/otilib` (the real OTILib),
and `~/Downloads/driver_utsa` (`OTI_computeflowrule`) which contains an
**OTI-vs-analytical timing harness** bearing directly on the performance claims.

## Repositories

### `~/Documents/UMAT_source_transformation`

| | |
|---|---|
| Remote | `https://github.com/santiagarcia/UMAT_source_transformation.git` |
| Branch / SHA | `main` @ `84bda8688fd99c1b6e1db255fd95d1bef60063f9` (2026-07-21) |
| Branches | `main`, `internal-jacobians-base`, 2 worktree-agent branches, origin/{main,develop,feature/softwarex-unified-umat-oti} |
| Tags | `v1.0.0` |
| State | **dirty** (16 entries) |
| Size / commits | 221 MB / 24 |
| Relationship | **Same lineage** — identical root commit `938b821`, and it contains the active tip `9c63def`. Its local `main` is *divergent unpushed work*, not an ancestor: `84bda86` is absent from the active repo. Different remote (`santiagarcia` vs `AMMS-Lab-UTSA`). |
| Verdict | **Newer in some areas, divergent overall.** Mine for content, do not merge wholesale. |

Reusable:

- `oti_provider/materials/` — 21 model directories, each with `contract.json`,
  `umat.for`, a `build/` tree and in several cases a compiled `.obj`. **All 18
  named sensitivity models are here** (`m1_elastic`, `m2_cubic`, `m3_j2`,
  `m5_cpflow`, `m6_fcc`, `sweep_aniso_ortho`, `sweep_damage_elastic`,
  `sweep_eco`, `sweep_j2_bilinear`, `sweep_j2_combined`, `sweep_j2_kinematic`,
  `sweep_lame_elastic`, `sweep_maxwell_ve`, `sweep_mooney_small`,
  `sweep_real_ECL_TEMP`, `sweep_real_PCO`, `sweep_thermoelastic`,
  `sweep_transiso`) plus `m2_elastic3d`, `sweep_drucker_prager`,
  `sweep_perzyna_linear`. This is the Table 6 gap.
- Contract schema `resasm_umat_transform_v2` — a *different* schema from the
  active `1.1` contract, with `kinematics`, `dimensions`, `derivative.of/wrt`,
  `history.path_dependent` and `validation.props_values`. It expresses
  finite-strain kinematics and a PROPS-derivative target directly, which the
  active schema does not. Worth comparing before extending our own.
- `START_HERE.md`, `docs/`, `UMAT_Source_transformation_user_manual.docx`.
- `validate_all_local.py`, `verify_abaqus_local.py` — local Abaqus validation.
- `external_umats/` — six vendored corpus repositories (see below).
- `oti_results/` — `data.json`, `RESULTS.md` and three figures.

Not reusable: `internal-jacobians-base` (`66f80f6`, 2026-06-18) is an **older
base branch**, not new work — diffing it against `main` shows main adding ~7 400
lines. It does not contain an internal-Jacobian implementation.

### `~/Desktop/Residual_Assembler(2)/Residual_Assembler`

| | |
|---|---|
| Remote | `https://github.com/santiagarcia/Residual_Assembler.git` |
| Branch / SHA | `main` @ `acdd1bf3c25faadb6fe05ef24302a988dd3b0a6a` (2026-07-22) |
| State | **dirty** (248 entries) |
| Size / commits | 254 MB / 43 |
| Relationship | Same root `c012029`; contains the active tip `4b698ba` as `origin/feature/umat-oti-residual-bridge`. Local `main` is divergent unpushed work. |
| Verdict | **Substantially ahead on element/replay functionality.** |

183 tracked files exist here and not on the active branch; only 15 exist on the
active branch and not here. The ones that matter:

| File | Lines | What it is |
|---|---:|---|
| `residual_core/core/field_sensitivity.py` | 474 | field-driven residual parameter sensitivities |
| `resasm_user/project/pipeline.py` | 468 | configure → prepare → run → export → assemble |
| `residual_core/formulations/solid3d_kernel.py` | 331 | general 3D solid residual/tangent kernel |
| `residual_core/io/export_derivative_fields.py` | 289 | full-field derivative writer |
| `residual_core/replay/abi.py` | 231 | ctypes binding to the versioned material C ABI |
| `residual_core/replay/engine.py` | 167 | replay record + OTI package + request → sensitivity |
| `residual_core/replay/contract/resasm_mat_abi_v1.h` | — | the versioned ABI header |

Pattern counts, this copy vs the active branch: `du_dp` 10 vs **0** py files,
`B_matrix` 21 vs 6, `odb` 34 vs 18, `factorization` 1 vs 0, `c3d8` 79 vs 37.
This is the §9 gap (real C3D8 path, ODB extraction, full-field `du/dp`,
factorization reuse) and it largely already exists here.

### `~/Desktop/framework_repos (2)/framework_repos/umat-oti`

| | |
|---|---|
| Remote | none (local only) |
| Branch / SHA | `cross-platform-hardening` @ `7459983` (2026-07-23), 2 commits |
| State | dirty (4 entries) · 93 MB |
| Relationship | **Unrelated history** — root `e272a66` ≠ our `938b821`. A separate packaging/export, not a fork. |
| Verdict | Mine for the corpus tooling only. |

Reusable, in the separate framework_repos checkout: `framework_repos/umat-oti/tools/corpus/{scrape_umats,corpus_scan,corpus_batch,umat_normalize,plot_corpus_summary}.py`
— the only web-acquisition code found anywhere, and the §8 gap. Also carries its
own `oti_provider/` and an `INTERFACE.md`.

### `~/Desktop/framework_repos/framework_repos/{umat-oti,residual-assembler}`

Detached HEAD, no commit history, 180 and 463 dirty entries. These are
**extracted-zip snapshots** (from `framework_repos.zip`), superseded by the
`(2)` copies of 2026-07-23. Nothing unique found. **Rejected.**

### `~/Desktop/framework_repos (2)/framework_repos/residual-assembler`

`cross-platform-hardening` @ `4f0f3d2` (2026-07-23), 4 commits, no remote, 61 MB.
Same element/ODB pattern counts as the Desktop `Residual_Assembler(2)` copy, so it
carries no additional capability. Superseded by that copy, which has full history
and shares our lineage. **Rejected as an integration source.**

### `~/otilib`

| | |
|---|---|
| Remote | `https://juan428a@bitbucket.org/mauriaristi/otilib.git` |
| Branch / SHA | `master` @ `51e3970` (2023-05-11), 499 commits, **clean**, 2.3 GB |
| Relationship | The genuine external OTI library, the GPLv3 dependency `Residual_Assembler/scripts/setup_otilib.sh` builds. |
| Verdict | **External dependency — do not vendor.** No `LICENSE` file at root; licensing recorded elsewhere as GPL-3.0. Its presence explains why the OTILib-dependent tests could be enabled locally; the 9 skips in the active suite remain because the Python bindings are not on the venv path. |

### `~/Downloads/driver_utsa` (`OTI_computeflowrule`)

| | |
|---|---|
| Remote | `https://github.com/santiagarcia/OTI_computeflowrule.git` |
| Branch / SHA | `main` @ `fde918b` (2026-02-12), 10 commits, clean, 1.2 GB |
| Verdict | **Directly relevant to the performance claims.** |

Contains `computeFlowRule.f90` and `computeFlowRule_otis.f90` (analytical and
OTI versions of the same routine), `benchmark_analytical.f90`,
`benchmark_otis.f90`, compiled `bench_analytical`/`bench_otis`, and
`benchmark_runs.csv` with 10 measured rows. Measured per-call cost in that file:
analytical ≈ 2.29–2.34 µs, OTI ≈ 3.33–3.43 µs — a **ratio near 1.42**. See the
reconciliation document: this looks like the origin of the "1.4" figure, but it
is a *cost ratio for one routine*, not a speedup and not a nominal-run
equivalence.

### `~/Documents/UMAT_source_transformation/external_umats/`

Six vendored external UMAT repositories — corpus material with real provenance:

| Repository | Upstream | SHA | Licence file |
|---|---|---|---|
| `abaqus-material-lab` | jpsferreira/abaqus-material-lab | `e597e91` | **none** |
| `CrystalPlasticity` | TarletonGroup/CrystalPlasticity | `2f09094` | **none** |
| `MaterialModels` | KnutAM/MaterialModels | `50fce6a` | `LICENSE` |
| `numgeo-hypo-igs-isa-gis` | j-machacek/numgeo-hypo-igs-isa-gis | `3f3b1fa` | `LICENSE` |
| `SCMM-hypo` | frodal/SCMM-hypo | `7c71094` | `LICENSE.md` |
| `Thermomechanical_Gradient_Enhanced_Damage_UMAT` | InstituteOfMechanics/… | `5b42d6d` | `LICENSE` |

`CrystalPlasticity` @ `2f09094` is the **same commit** already pinned in the
active `Residual_Assembler` under `sources/license-unknown/`, and its lack of a
licence file independently confirms that classification. `abaqus-material-lab`
likewise has no licence: **all rights reserved, not redistributable as a
fixture.** The four licensed ones are candidates for the corpus.

### Other repositories (unrelated to this project)

`~/Abaqus_hypercomplex_3D`, `~/abaqus_hypercomplex`, `~/Documents/MATLAB/matlab-multiz-interface`,
`~/Desktop/Juan RIncon/…/{thermal_brick,respository}`, `~/.codex/.tmp/plugins`.
Complex-step / hypercomplex UEL work and unrelated projects. **Not integration
sources**, though the hypercomplex UEL work is the same research programme.

## Archives

`~/Desktop/framework_repos.zip`, `framework_repos (2).zip`,
`Residual_Assembler(2).zip` are the sources of the extracted directories above
and contain nothing additional. Remaining zips (`nonlinear_shell_uel*`,
`DavidRIsk_UEL*`, `results.zip`, `elastic.zip`) belong to other projects.

## Manuscript and presentation files

All five named files remain **absent from this machine**:

- `UMAT_OTI_SoftwareX_V4.docx`
- `IMQCAM_Annual_Meeting_Poster_36x48_v5(1).pptx`
- `IMQCAM_BZM_project_presenation_2026024_V11(10).pptx`
- `IMQCAM_Annual_Meeting_20260812_V4(3).pptx`
- `NASA_STRI_20260703(1).pptx`

Nearest variants exist and are **not substitutes**: `NASA_STRI_20260703.pptx`
(without the `(1)`), many `NASA_STRI_20260724(*)`, several
`IMQCAM_BZM_project_presenation_2026024_V9…V12`,
`UMAT_OTI_SoftwareX.docx`/`_backup.docx`, and
`framework_repos (2)/…/residual-assembler/results/NASA_STRI_residual_assembler.pptx`.
A user manual does exist and is tracked in the active repo at
`docs/UMAT_Source_transformation_user_manual.docx`.

This remains an **external blocker**: the requirements baseline cannot be read
from files that are not here, and no wording, table or figure will be inferred
from a differently-named variant.

## Capability map

Where each currently-missing capability already has an implementation:

| Capability | Best local source | Status |
|---|---|---|
| 18-model sensitivity set (Table 6) | `Documents/…/oti_provider/materials/` | **found, 21 models** |
| Automatic contract generation | `Documents/…/oti_provider/umat_transform.py`, `contract/` | found |
| Finite-strain seed detection | `Documents/…` contract `kinematics` field | partial |
| Internal constitutive Jacobians (Table 3) | only symbol references in `json_files/UMAT_{HIN,NKH}.json` | **no implementation found** |
| Real C3D8 quadrature / residual assembly | `Residual_Assembler(2)`: `solid3d_kernel.py`, `field_sensitivity.py` | **found** |
| ODB/INP extraction | `Residual_Assembler(2)` (34 py files) | **found** |
| Full-field `du/dp`, `dσ/dp` | `Residual_Assembler(2)`: `export_derivative_fields.py` | **found** |
| Compiled-driver bridge / ABI | `Residual_Assembler(2)`: `replay/abi.py`, `resasm_mat_abi_v1.h` | **found** |
| Web acquisition / corpus | `framework_repos (2)/umat-oti/tools/corpus/` | **found** |
| Performance/scaling harness | `driver_utsa` benchmark pair + CSV | **found (one routine only)** |
| Streamlit workflows | active repo `src/umat_oti/app/` (8 modules) | already active |
| Abaqus paired-job generation | active repo `validation/job_builder.py` (1 640 lines) | already active, most complete |
| Higher-order OTI generation | active repo | already active, most complete |

## Integration policy

1. Compare before copying. The active branch is ahead on the pipeline engine,
   the convergence/verification policy and Abaqus paired validation; the other
   copies are ahead on materials, element kernels and corpus tooling.
2. Bring content across as **contracts and data first**, code second.
3. Every integrated file gets provenance (source path, repo, SHA) and a test.
4. `otilib` stays external. `external_umats` entries without a licence stay
   reference-only.
5. The `santiagarcia/*` remotes are a different account from the active
   `AMMS-Lab-UTSA/*` remotes. Nothing here is pushed anywhere; these copies are
   read-only inputs.
