# Branch and implementation audit (2026-09-18)

## Recovery Working-Tree Addendum

The baseline below is preserved as history. Current recovery use is documented
in [USAGE_REPORT.md](USAGE_REPORT.md), with captured help, five examples,
all three UMAT GUI renders and genuine source-denied ODB consumption. The
pinned compiled J2 provider/replay and bounded total neo-Hookean finite
formulation have independent numerical evidence; generic FCC/full-size and
higher-order full FE do not. Retained corpus counts are historical.
Latest retained full suites: RA 419 passed/11 existing skips; UMAT 3324
passed/125 existing skips/5 deselected, before the new wrapper regression.
No new analysis job or producer edit occurred in this usage audit.
The recovery worktrees remain uncommitted.

[Ledger and evidence scope](COMPLETION_LEDGER.md): 104 bounded implemented,
159 partial, 11 unestablished; 0 clean-install complete, 274 outstanding.
The previous working-tree wheel gate is not final-branch clean-clone proof.

## Historical Pre-Recovery Inventory

Where every capability the master directive names already exists, in which
branch, commit or checkout, and what state it is in. Recorded before anything
was rewritten. Both repositories are covered here; the same file is kept in
`Residual_Assembler/docs/`.

## Repository state at the start

| Repository | Checkout | Branch | Commit | Working tree |
|---|---|---|---|---|
| UMAT_source_transformation | `~/softwarex_work/UMAT_source_transformation` | `integration/parallel-2026-09-11` → new `integration/imqcam-2026-09-18` | `98f9d76` | clean; stash `stash@{0}` (paper_results regeneration, 4 files, left untouched) |
| Residual_Assembler | `~/softwarex_work/Residual_Assembler` | `agent/F-resasm` → new `integration/imqcam-2026-09-18` | `f1d9a32` | clean |

Remotes fetched: `origin` (github.com/AMMS-Lab-UTSA/*) in both. Added as
read-only remotes for recovery: `documents_umat` →
`~/Documents/UMAT_source_transformation` (main `84bda86`), `desktop_ra` →
`~/Desktop/Residual_Assembler(2)/Residual_Assembler` (main `acdd1bf`).

Baseline suites at the start: UMAT — collection error in
`tests/test_the_crystal_plasticity_trio_lost_one_state_slot.py` (module-level
`pytest.skip` without `allow_module_level`), so the suite did not run;
RA — 279 passed, 2 failed, 20 skipped (`-m "not abaqus and not arc and not network"`);
the failures are `test_a_verified_fixture_passes_every_stage` and
`test_the_nine_layers_are_the_nine_the_brief_names`, both left by the
unvalidated WIP commit `ab0ee10`.

## Where the capabilities live

### A. The two-program IMQCAM framework (Program 1 provider + Program 2 replay)

**`Residual_Assembler` `origin/cross-platform-hardening` (`bfde4d0`, 2026-07-31).**
Layout `umat-oti/` + `residual-assembler/` (commit `4a92c50` "Two-program
framework"). Merge base with the current line is `00c784a` (2026-07-13); nothing
from it was merged into `agent/F-resasm`. It carries:

- `residual-assembler/residual_core/replay/` — `abi.py` (ctypes binding to the
  versioned C ABI `contract/resasm_mat_abi_v1.h`, `mat_eval_v1`/`mat_describe_v1`),
  `objlink.py` (links the distributed `umat_<name>_oti.obj` into a loadable `.so`
  exposing the ABI by calling `UMAT_OTI_EVAL`), `path_material.py` (marches the
  `.obj` over a recorded strain path carrying DSIGMA_DP/DSTATEV_DP; also the
  regular UMAT for an FD reference; uses `UMAT_OTI_MARCH`), `record.py` (replay
  record schema `resasm_replay_record_v1`, preflight), `driver.py` (per-IP replay
  filling the field-sensitivity solver inputs), `engine.py` (record + package +
  request → `du/dp`, `dq/dp`), `outputs.py` (dq/dp for displacement, reaction,
  stress, von Mises), `package.py` (material package manifest, matched-twin rule),
  `job.py` (`sensitivity_job.json` runner: validate/run/init), `request_contract.py`
  (output-parameter request: U/RF/S/state × with_respect_to).
- `residual_core/core/field_sensitivity.py` — assembles K and R_,p from per-IP
  D and dσ/dp and solves `K_ff du/dp = -R_,p` for all parameters at once.
- `residual_core/io/abaqus_odb_export.py` (Abaqus-python ODB → `fields.json`:
  coords, C3D8 connectivity, per-frame U, RF, IP stress, SDV) and
  `io/export_derivative_fields.py` (`resasm_derivative_fields_v1` with an SDV
  layout sidecar).
- `residual_core/runtime/{compat,libload}.py`, `residual_core/interface/versions.py`,
  `schemas/resasm_{material_package,replay_record,sensitivity_job,sensitivity_request,sensitivity_result,verification_job}_v1.schema.json`.
- `resasm_user/project/{pipeline,engine,manifest,state,inspect,cli}.py` — the
  configure → prepare → run (Abaqus) → export → assemble → validate → report
  project pipeline; `resasm_user/{umat_backend,umat_matpoint,abaqus_job,field_recipe}.py`.
- `residual_core/formulations/solid3d_kernel.py`, `stress_driven_adapter.py`;
  `residual_core/materials/{crystal_plasticity,elastic}_adapter.py`,
  `umat_adapter.py`; `residual_core/umat_adapter_fortran/` (gfortran UMAT replay
  driver).
- Examples: `Residual_Assembler@origin/cross-platform-hardening:examples/replay_elastic_c3d8` (runnable Program-2 demo, FD-validated
  ~1e-9), `Residual_Assembler@origin/cross-platform-hardening:examples/residual_sensitivity_c3d8` (engine self-check + Abaqus
  comparison, measured 1.7e-5), `Residual_Assembler@origin/cross-platform-hardening:examples/abaqus_elastic_c3d8`,
  `Residual_Assembler@origin/cross-platform-hardening:examples/field_residual_sensitivity`.
- Tests: `tests/framework/test_{replay_elastic,field_sensitivity,field_recipe_e2e,request_contract,job_validation,abaqus_derivative_export,fcc_cubic_oti,fcc_oriented_oti,otilib_*,solid3d_kernel,umat_backend,project_engine,binary_compat,interface_versions,...}.py`
  with real Abaqus 2021 fixtures under `Residual_Assembler@origin/cross-platform-hardening:tests/abaqus_derivative_export/fixtures/`
  (nonuniform single C3D8 with the verification elastic UMAT; FCC cubic C3D8).
- `results/` — the IMQCAM result scripts: `cp_residual_sensitivities.py`
  (single-IP CP flow, six parameters, OTI vs FD), `cp_mesh_residual.py` (4×4×4
  C3D8 mesh-independence, `cp_mesh_summary.json`), `fcc_crystal_results.py`,
  `program1_material_validation.py`, `build_sweep_tables.py` (the 18/20-material
  DSIGMA_DP table of slide 13), figures and `NASA_STRI_residual_assembler.pptx`.

**`Residual_Assembler` remote `desktop_ra/main` (`acdd1bf`, 2026-07-22)** — the
standalone repository the two-program branch was assembled from; its
`residual_core/` differs from the branch by 8 files (614 insertions) and
`tests/` by 3 files, so the branch supersedes it except for the 248 uncommitted
modifications in that working copy (mostly `UMATs/ICP/**` and
`Residual_Assembler@origin/cross-platform-hardening:tests/verification_zoo/`, snapshot kept outside the repositories).

**`UMAT_source_transformation` remote `documents_umat/main` (`84bda86`, 2026-07-21).**
`oti_provider/` (Program 1): `umat_transform.py` (compact contract → `.obj` with
Fortran symbols `UMAT`, `UMAT_OTI_INTERNAL`, `UMAT_OTI_EVAL`, `UMAT_OTI_MARCH`,
plus completed contract `umat_<name>_oti.json` schema
`resasm_umat_oti_contract_v1`), `build_resmat.py` (v2 contract → `mat_eval_v1`
C-ABI wrapper → `.so` → `material.resmat.zip`), `elastic/` reference provider,
`contract/` (ABI header, package schema, version hash), and
`materials/{m1_elastic,m2_cubic,m2_elastic3d,m3_j2,m5_cpflow,m6_fcc,sweep_*}`
with built objects. The checkout at `~/Documents/UMAT_source_transformation`
still holds the built `umat_m3_j2_oti.obj`, `umat_m5_cpflow_oti.obj`,
`umat_m6_fcc_oti.obj` and their `build/` directories (OTI module `otim10n1`,
`otim17n1`, march drivers). The same subtree is in
`origin/cross-platform-hardening:umat-oti/oti_provider/` on the RA repository.

**Current `UMAT_source_transformation` (`98f9d76`)** re-implemented the provider
as a material-point *driver executable* path rather than the `.obj` ABI:
`parameter_sensitivity/models/*` (20 models, `contract_v2.json` schema
`resasm_umat_transform_v2`), `src/umat_oti/services/contract_adapter.py` (`adapt_v2_contract`),
`src/umat_oti/transform/parameter_sensitivity_transform.py`,
`src/umat_oti/validation/parameter_sensitivity_validation.py` (gfortran driver,
CSV outputs, centred FD, branch-crossing bookkeeping),
`tools/run_parameter_sensitivity_sweep.py` → `paper_results/parameter_sensitivity/parameter_sensitivity_round.json`
(20/20 models `derivatives_verified`, e.g. m3_j2 560/560 rows, worst 2.5e-8).
Symbols `UMAT_OTI_EVAL`/`UMAT_OTI_MARCH` no longer exist anywhere in the current
tree; `residual_core/materials/umat_oti_driver.py` in RA consumes the
`umat-oti-driver-contract/1.1` JSONL stream instead. **Decision:** recover the
`.obj` + C-ABI provider (it is what the replay engine and the IMQCAM slides use)
as `src/umat_oti/provider/`, driven by the current transformer, keeping the
driver path as its offline verification.

### B. Presentation claims (IMQCAM Annual Meeting 2026-08-12, V4)

- Slide 8: 18/18 benchmark UMATs verified for DDSDDE (`benchmarks/*.json`,
  `json_files/*.json`; current tree `paper_results/generality/`).
- Slide 13: 18 material models, 76 parameter directions, DSIGMA_DP vs FD ≤ 1.6e-7
  (current `paper_results/parameter_sensitivity/parameter_sensitivity_round.json`
  carries 20 models).
- Slides 15–18: FCC single-crystal cantilever, 384 C3D8, 2,025 DOF, 3,072 IPs,
  tip 0.25 mm over 25 steps, 10 parameters (mesh 2×8×24 → 675 nodes).
- Slides 39–42: J2 cantilever, 1,536 C3D8, 7,497 DOF, 12,288 IPs, E = 200 GPa,
  ν = 0.3, σy = 250 MPa, H = 2 GPa, tip 0.7 mm over 40 steps (mesh 2×16×48 →
  2,499 nodes). No input deck, ODB or replay record for either cantilever exists
  on this machine (searched `~`, both Desktop copies, `~/Documents`, all
  branches); the largest committed replay is the 4×4×4 CP cube. They are
  regenerated here as structured meshes with the same counts and run in the
  local Abaqus 2021.HF5.
- Slides 28–32: single-C3D8 CP flow sensitivities (`results/cp_residual_sensitivities.py`),
  NRMSE < 1e-8 vs analytic chain rule; timing OTI vs FD.

### C. Other branches and worktrees (UMAT)

- `agent/B-transformer` `6b7b4f2` SUM/PRODUCT over the OTI type (validated) +
  `3ce76c9` WIP `oti/lapack_shims.py` (not validated).
- `agent/D-primal` `1c9b4f2` WIP divergence localisation; `agent/E-tangent`
  `586540b` WIP quad reference; `agent/C-experiment` `a6c1209` WIP author shape
  and fields; `agent/F-gui` `2f30004` WIP Abaqus-level parameter FD;
  `agent/G-gui` `b8e4668` WIP process tree; `agent/A-registry` `17c960e` WIP
  script-published decks. All marked NOT VALIDATED; to be inspected before use.
- `origin/develop` `3b835d2` (2026-06-17) and `origin/main` `fe40e9f` (2026-07-10):
  older layouts, superseded by the integration line.
- `backup/pre-author-rewrite-20260825-111009`: pre-rewrite history, no
  provider commits.
- `fix-shape`, `fix-finite`, `fix-ddsdde`, `worktree-wf_*`: earlier transform
  fixes, all merged.

### D. Other branches (RA)

- `agent/contract-ra` `0435eab` = contract 3.0.0 (merged).
- `feature/umat-oti-residual-bridge` `031fcb7` (superseded by the integration line).
- `backup/pre-author-rewrite-20260825-111009`: 14 pre-rewrite commits (same content).

### E. External dependencies found

- Abaqus 2021.HF5 at `/usr/bin/abaqus` (licensed, usable); `gfortran` 9.4;
  `ifort` 2023.2.1 (`/opt/intel/oneapi`).
- OTILib clone at `~/otilib` (clean, commit `51e3970e`) built for CPython 3.8/3.9
  under conda env `pyoti` (`~/.conda/envs/pyoti`, Python 3.8.12); the project
  venv is Python 3.11.7 with numpy 2.4.6, so `import pyoti` fails there. A
  Python-3.11 build is required (Cython + CMake are available).
