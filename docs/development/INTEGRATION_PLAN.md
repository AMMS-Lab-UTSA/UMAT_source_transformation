# Review of earlier local copies: findings and integration plan (2026-08-25)

This is a historical development record, kept for its technical findings. It
summarises four independent read-only analyses of the earlier local copies
catalogued in [LOCAL_IMPLEMENTATION_INVENTORY.md](../LOCAL_IMPLEMENTATION_INVENTORY.md),
and the integration plan derived from them. It is not reviewer-facing
documentation and is not needed to use the software. Each claim was produced by
reading the referenced files; where the repository acted on a claim, the claim
was first re-verified independently, and that is noted.

Several recommendations have since been carried out:

- the internal-Jacobian discovery rule is implemented in
  `src/umat_oti/transform/internal_jacobian.py`;
- the legacy DDSDDE-assignment fallback is ported to
  `src/umat_oti/corpus/tangent_regions.py`;
- the v2 contract adapter is `src/umat_oti/services/contract_adapter.py`, with
  `tests/test_contract_adapter.py`.

Line numbers and function names below refer to the code as it was on
2026-08-25.

## Verified independently before acting

- The two `Residual_Assembler` trees **share history at `00c784a`**, which is an
  ancestor of the active branch. The older divergent copy had **41 commits**
  past that base; the active branch had 6. Confirmed with
  `git merge-base --is-ancestor` and `git log`.
- Of 25 sampled "modified" files in that copy, **21 differed only by line
  endings**: CRLF noise from a Windows checkout, not content. Integration
  therefore had to be a **staged git merge, not file copying**.
- The internal-Jacobian discovery rule is real. A purely syntactic scan for
  `X = X ± A/B` finds `(GAM_PAR, FGAM, FJAC)` in **9 of 12** ICP sources, with no
  symbol whitelist and no model names.
- `validation.props_values` is indexed by **PROPS index, not list position**.
  `m5_cpflow` proves it (`q` is listed third but is `PROPS(6)`). This was
  cross-checked against the Fortran and is pinned by a regression test.

## 1. Legacy corpus tooling versus the active corpus package

The legacy `tools/corpus/` bundle and the active `src/umat_oti/corpus/` package
solved overlapping halves of the same problem, and neither was complete.

The legacy tool was strong at *acquisition*: repository-search discovery, a
shallow-clone harvest that avoids API rate limits, byte-exact deduplication and
a resumable index. It was also strong at *locating the DDSDDE tangent block*:
its `corpus_batch._fallback_ranges` was the one algorithm with a measured
effect (`no_ddsdde_region` 66 to 17, transform success 35 to 65 on 207 UMATs,
per its own report). Its architecture was not worth keeping: `sys.path` hacks,
no licence categorisation, no immutable pin, and a summary figure whose numbers
were Python literals.

The active package had the better skeleton: a canonical 10-stage vocabulary, a
16-entry failure taxonomy, licence classification, normalised-form hashing and
a snapshot cache. Its contract synthesis, however, was a stub:
`corpus/cli.py::_process_one` wrote `ntens: 4, promote: [], replace: []` and
skipped `merge_completed_anchors_into_config`, unlike
`services/transformation.py` and unlike the legacy batch runner. That stub
caused 31 of the 119 failures in `corpus_round_metrics.json` (22
`confirmed_transformation_defect`, 8 `dimension_inference_failure`, 1
`unsupported_fortran_construct`). Labelling contract-synthesis failures as
confirmed engine defects is a paper-integrity risk.

The missing bridge could be built almost entirely from functions the active
repository already had (`infer_ntens`, `_max_subscript`/`_contract_inference`,
`umat_like_routines`, `suggest_variable_roles`, `detect_seed`,
`build_transformation_anchors`), plus one ported algorithm (the
DDSDDE-assignment fallback) and one new inference (the PROPS parameter map).
NTENS, the *meaning* of each parameter and the validation loading path cannot
be inferred from source; they must stay declared or defaulted, with the
confidence recorded.

Findings:

- `scrape_umats.py` discovered candidates through the GitHub
  *repository*-search API (not code search), driven by 10 hard-coded
  natural-language queries, then harvested file contents by shallow git clone,
  so harvesting cost no API rate budget. This acquisition strategy was the
  best part of the legacy bundle and worth reusing.
- The legacy scraper did **not** classify licences. It recorded the raw
  repository-level SPDX identifier and nothing else: no permissive, copyleft or
  unknown category, no per-file SPDX header, no filtering. 113 of 254 harvested
  files had a `null` licence.
- The legacy scraper did **not** snapshot immutably. It cloned whatever the
  default branch pointed at and recorded no commit SHA or ref, so a re-run
  against a moved branch silently yielded different bytes. Its only SHA-256 was
  a content hash of the file, not a version-control identity.
- The legacy scraper deduplicated by the exact SHA-256 of the raw bytes,
  globally across repositories, in a resumable `seen_hashes` set. That catches
  verbatim forks but misses whitespace and case variants; the active
  repository's normalised hash is the better rule.
- `corpus_batch._fallback_ranges` is the most valuable algorithm in the legacy
  bundle. When the region classifier finds no "tangent" region, it finds the
  DDSDDE assignments directly, expands each to its enclosing `DO`/`END DO`
  block and merges overlaps.
- The active repository's equivalent, `_infer_ddsdde_output_region` in
  `core/transformation_anchors.py`, could not fire in exactly the case the
  legacy fallback was built for: it returned `None` whenever no stress region
  was found, so a UMAT whose stress update was not detected got no tangent
  output region either.

## 2. Mapping the v2 contracts onto the canonical request model

This analysis covered the mapping from `resasm_umat_transform_v2` to the
canonical schema-1.1 / `DerivativeRequest` contract for the 21
parameter-sensitivity materials.

The set is 21 material contracts: in the original model directories, 20 carry
`contract.json` and `m2_elastic3d` carries `transform_contract_v2.json`. All declare
`"schema": "resasm_umat_transform_v2"`, in exactly three shapes:

- `derivative: {response, export}` (17 models);
- `derivative: {of, wrt, order}` (3: `m3_j2`, `m5_cpflow`, `m6_fcc`);
- the fully explicit `derivative_requests[]` + `interface` + `oti` +
  `transformation_hints` + `resasm_provider` form (1: `m2_elastic3d`).

Every one declares `kinematics: "small_strain"`, the only value anywhere in the
set. All 21 `umat.for` files are fixed-form and self-contained (no CALLs, no
extra routines, only `INCLUDE 'ABA_PARAM.INC'`, which the lifter drops), with
NTENS = 6, NPROPS 2-10 and NSTATEV 0-12. At the time, the imported copies in
this repository were byte-identical to the originals.

Every v2 request is a PROPS-seeded parameter sensitivity, so the canonical
destination is the `parameter_sensitivity` / `state_sensitivity` kinds plus the
`GenericPSContract` path. That path needs a `material_point_driver` block and
`parameters[].value`, for which v2 has no field, and for `m5_cpflow` it
silently lost the two unseeded PROPS values. A `contract_adapter.py` with its
test already existed; it adapted and normalised all 21 cleanly, but running it
exposed three defects.

At the time, the canonical model could not express a deformation-gradient
seed. `DerivativeRequest.seed` accepted the string `"DFGRD1"`, but no consumer
read it. The only DFGRD1 seeding in the code base was a DSTRAN-parameterised
perturbation of F, gated on `validation_settings.material_test_mode` /
`transformation_settings.seed_dfgrd1`, neither of which a schema-1.1 contract
could set.

Findings:

- **Field inventory.** Two key sets. Set A (20 models): `schema, source,
  kinematics, dimensions, parameters, derivative, history, output,
  validation`. Set B (`m2_elastic3d` only): `schema, source, interface, oti,
  derivative_requests, history, transformation_hints, resasm_provider`.
  Sub-shapes: `source` is `{entry_point, main_file}` ×17,
  `{entry_point, main_file, additional_files}` ×1, `{main_file}` ×3 (`m3_j2`,
  `m5_cpflow` and `m6_fcc` lack `entry_point`); `dimensions` is
  `{ntens, nprops, nstatev}` ×20; `derivative` is `{response, export}` ×17 and
  `{of, wrt, order}` ×3; `history` is `{state, export, propagate}` ×17,
  `{path_dependent, state}` ×3 and
  `{argument, export_derivatives_as, propagate_parameter_coefficients}` ×1;
  `output` is `{object, contract}` ×20; `validation` is `{props_values}` ×20.
- **Kinematics.** Exactly one value, `"small_strain"`: 20 carry it at top level
  and `m2_elastic3d` as `interface.kinematics`. No finite-strain contract exists
  in the set, and no `umat.for` uses DFGRD0/DFGRD1 executably; the two DFGRD
  hits per file are the SUBROUTINE argument list and the DIMENSION declaration.
- **Field-by-field map (v2 key to canonical key).**
  - `schema` is replaced by `schema_version: "1.1"` (assert before adapting).
  - `source.main_file` becomes top-level `source` (a path that must resolve on
    disk through `_resolve_source_path`).
  - `source.entry_point` becomes `entry_routine` (default `"UMAT"` for the
    three that omit it).
  - `kinematics` / `interface.kinematics` has no canonical field; it only
    decides the seed, so record it under `provenance` and refuse anything other
    than `small_strain`.
  - `dimensions.ntens` / `interface.ntens` becomes top-level `ntens`. It is
    required: `_compact_transformation_settings` raises for a unified contract
    when `ntens` is absent and inference confidence is not "high".
  - `dimensions.nprops` has no canonical field; it can be derived only as the
    largest `props_index`, and PROPS is sized through
    `material_point_driver.static_props`.
  - `dimensions.nstatev` becomes `material_point_driver.nstatv` (plus
    `len(state_variables)`).
  - `interface.preserve_standard_inputs/outputs` has no home; it is always
    true, because the transform preserves the ABI unconditionally.
  - `parameters[].name` maps to `parameters[].name` (upper-cased by
    `_parameter_map_from_config`), and `parameters[].props_index` to
    `parameters[].props_index` (1-based, positive, unique; enforced by
    `validate_derivative_requests`).
  - `parameters[].value` is derived as `validation.props_values[props_index-1]`.
  - `derivative.response` / `derivative.of` /
    `derivative_requests[].response.argument` become `derivatives[].response`
    (`"STRESS"` in all 21).
  - `derivative.export` / `derivative_requests[].export.name` become
    `derivatives[].target` (`"DSIGMA_DP"`).
  - `derivative.wrt` / `derivative_requests[].seed.argument`, or the seed
    implied by the export, become `derivatives[].seed` = `"PROPS"`.
  - `derivative.order` / `oti.order` become `derivatives[].order` (1).
  - `derivative_requests[].id` becomes `derivatives[].id`.
  - `response.components: "all"` means omitting `components` (None means all).
  - `export.shape: ["NTENS", "NPARAM"]` becomes `derivatives[].output_shape`,
    resolved to integers `[6, nparam]`.
  - `export.layout` becomes `derivatives[].output_layout` (free text,
    lower-cased).
  - `history.state: "STATEV"` / `history.argument` becomes the `response` of the
    second (DSTATEV_DP) request.
  - `history.state: ["EQPLAS"]` / `["g_alpha"]` becomes `state_variables[].name`,
    expanded to `nstatev` 1-based entries.
  - `history.export` / `history.export_derivatives_as` becomes the second
    `derivatives[].target` = `"DSTATEV_DP"` (`_classify_kind` gives
    `state_sensitivity`).
  - `oti.number_of_directions` is derived as `len(parameters)`.
  - `transformation_hints.force_promote` becomes the compact `promote` list and
    `transformation_hints.keep_real` the compact `real` list.
  - `resasm_provider.ddsdde_block: "44-46"` becomes `replace: ["44-46"]`.
  - `resasm_provider.props_values` is the same as `validation.props_values`.
- **`validation.props_values` is indexed by PROPS index (1..nprops), not by
  position in `parameters[]`.** In `m5_cpflow`, `parameters` is out of order
  (tau0 at 3, dG at 4, q at 6, p at 5, gam0 at 7, H at 8), and `props_values`
  has 8 entries `[200000.0, 0.3, 1500.0, 25.0, 0.4, 1.6, 0.1, 60000.0]`, so p
  (PROPS 5) is 0.4 and q (PROPS 6) is 1.6. This was cross-checked against
  `m5_cpflow/umat.for` (`PEXP=PROPS(5)`, `QEXP=PROPS(6)`). The adapter rule is
  `value = props_values[props_index-1]`.
- **v2 information with no canonical home.**
  1. `history.propagate` (17 models; true for the 7 sweep models
     drucker_prager, j2_bilinear, j2_combined, j2_kinematic, maxwell_ve,
     perzyna_linear and real_PCO, false for the other 10),
     `history.propagate_parameter_coefficients` (`m2_elastic3d`) and
     `history.path_dependent` (`m3_j2`, `m5_cpflow`, `m6_fcc`): the canonical
     model had no flag for whether parameter coefficients are carried across
     increments.
  2. `derivative_requests[].seed.components[].oti_direction`: the canonical
     model assigns OTI directions implicitly by *position* in `parameters[]`
     (`_emit_driver` enumerates the parameters from 1 and sets
     `PROPS(props_index) = value + E{k}`), so the adapter must order
     `parameters` so that list position equals `oti_direction`.
  3. `seed.components[].units` and `export.dtype` (`"float64"`).
  4. `dimensions.nprops` as an independent quantity.
  5. `output.object` / `output.contract` (prebuilt artefacts of another run).
  6. `interface.preserve_standard_inputs/outputs`.
  7. `transformation_hints.intrinsic_replacements` /
     `external_oti_procedures` (both `{}` here).
  8. `resasm_provider.tangent_variable` (`"DDS"`) and `stress_update_line`
     (41).
  9. The unseeded entries of `validation.props_values`, unless
     `material_point_driver.static_props` is populated.

## 3. Generic extraction of internal constitutive Jacobians

This analysis covered FJAC, DETDG, GDIA, ANP1P, BNP1P and CEVPI.

All six symbols live only in the ICP UMAT family: 10 files and 21 distinct
(symbol, model) pairs. Nine of the ten models share one textbook scalar Newton
solve on the consistency parameter `GAM_PAR`. The triple (iteration variable,
residual, hand-coded Jacobian) = (`GAM_PAR`, `FGAM`, `FJAC`) can be found at
exact line numbers by a purely syntactic scan for `X = X - A/B`, with no model
names and no symbol whitelist; the scan hit 9 of 9.

- FJAC is dFGAM/dGAM_PAR.
- ANP1P and BNP1P are dANP1/dGAM_PAR and dBNP1/dGAM_PAR.
- DETDG is dPHIINV/dGAM_PAR (Perzyna overstress).
- GDIA is d(DIAG)/dGAM_PAR.
- CEVPI is different: HIN has no Newton update at all, and CEVPI is
  KINVER(DEE + dt*XKAPPA*G1), the inverse of a local viscoplastic operator.

At the time, the contracts did not name any of these as derivative targets.
They appeared only in the `variables.{promote,constant,real}` classification
lists, and DETDG was even classified `constant` in NKH, VPDCL and VPDCO while
FJAC, ANP1P and BNP1P were `promote`, which truncates the chain that feeds FJAC.
`derivative_request.py` could already express `KIND_LOCAL_JACOBIAN`, but nothing
consumed it. The working mechanism was `extra_jacobian_contracts`, which
already reseeds at a loop anchor with `REAL(x_OTI) + OTI_E{slot}`, extracts with
`GETIM`, blanks the hand-coded assignment and raises the number of bases from 4
to 5. It had simply never been pointed at a local Jacobian. The generic
algorithm therefore needed no new code-generation primitives, only a discovery
rule, and a closure rule to replace the hand-written `reseed_prelude` Fortran.

Findings:

- **Where the symbols occur.** 21 distinct (symbol, model) pairs across 10
  files: FJAC in 9 models, GDIA in 5, DETDG in 4, ANP1P and BNP1P in NKH only,
  CEVPI in HIN only. The manuscript's Table 3 claims 19 entries, so the count
  needs reconciling.
- **Machine-discoverable triple.** A regular expression for the Newton-update
  shape `X = X ± A/B` (X a scalar assigned to itself) finds exactly one hit per
  model in 9 of the 10 files, and in every case yields iterate `GAM_PAR`,
  residual `FGAM` and Jacobian `FJAC`. Update lines: NKH:224, PCL:157,
  PCLI:189, PCLI_R:188, PCLK:167, PCO:185, VPDCL:197, VPDCL_R:215, VPDCO:205,
  all `GAM_PAR=GAM_PAR-...`. HIN gives no hit, which correctly signals that
  CEVPI is a different kind of object.
- **FJAC in NKH** is the exact analytic dFGAM/dGAM_PAR and is available right
  after the residual, inside the local Newton loop. The residual FGAM (line 214)
  and FJAC (line 217) sit at the top of an unbounded `DO` block (lines 213 to
  259) whose whole bottom half (lines 225-245) recomputes every
  GAM_PAR-dependent intermediate from the new iterate. That structure is what
  makes seed propagation automatic.
- **ANP1P as coded is wrong by a factor 1/(1-D).** ANP1 = HMOD(1-D)/u with
  u = 1 + GAMHARD(1-D)(1-THETA)GAM_PAR, so dANP1/dGAM_PAR =
  -HMOD·GAMHARD(1-D)²(1-THETA)/u², but the source writes (1-D) to the first
  power (`UMAT_NKH_1.02.for`, lines 194-198 and 225-229). It is exact only at
  D = 0. Checked at 40-digit precision: coded/exact = 1/(1-D), which is 17.6%
  high at D = 0.15 and 53.8% high at D = 0.35. BNP1P = GAMHARD·ANP1P/HMOD
  inherits the same error, and both feed FJAC, so the model's own local tangent
  is wrong in a damage-dependent way.
- **GDIA(3,3) in the two damaged variants drops the same factor (1-D).**
  DIAG(3,3) = 1/TETA1 with TETA1 = 1 + (2/3)GAM_PAR(1-D)EK gives
  -(2/3)(1-D)EK/TETA1², but the source omits (1-D) (`UMAT_VPDCO.for` line 539,
  `UMAT_VPDCL_R.for` line 541). The undamaged variants (PCO, PCLI, PCLI_R) set
  DIAG(3,3) = ONE and GDIA(3,3) = ZERO, which is correct, so this is
  specifically a damage-coupling defect.
- **DETDG is dPHIINV/dGAM_PAR** for the Perzyna overstress inverse
  PHIINV = (SNETA/DTIME)^(1/SN) · GAM_PAR^(1/SN), and it is correct as coded in
  all four viscoplastic models. It is singular as GAM_PAR tends to 0, because
  the exponent 1/SN - 1 is negative; that is why those models seed
  `GAM_PAR = ZERO + 1.0d-25` rather than `ZERO`. A finite-difference reference
  taken at the first iterate is meaningless. The rate-independent models
  initialise `GAM_PAR` differently.

## 4. Residual Assembler: the active branch versus the older divergent copy

The two trees were not independent copies: they share history at `00c784a`,
whose tree is identical in both (`f3ad8ba4cfd21a944bd4b328eac46e1e95829c41`).
The active branch had 6 commits past it and the divergent copy 41. A trial
merge in a scratch clone (`git fetch` from the copy's `.git`, then
`git merge --no-commit`) applied with **zero conflicts**, so the 183-file gap
had to be integrated by git, not by copying files.

The apparent whole-file divergence of 234 shared files was CRLF noise from a
Windows checkout: every git blob was LF, and only 16 shared files differed in
real content. Copying with `rsync` or `cp` would have imported 162 CRLF files
and destroyed the diff.

The divergent copy was clearly more complete on the residual-sensitivity path.
It owned the entire field-driven path (`field_sensitivity.py`, derivative-field
IO, the ODB derivative exporter, B-bar assembly, `solid3d_kernel`), the whole
compiled-material replay stack (C ABI, ctypes binding, engine, driver, outputs
and job), the project pipeline, and real-Abaqus fixture validation. None of
these existed on the active branch in any form. The active branch alone owned
the umat-oti driver-contract bridge, the submodule and CI reproducibility work,
and 3 test files the divergent copy lacked.

Measured test results: active branch 68 passed / 9 skipped; divergent copy 129
passed / 14 skipped; merged trial 140 passed / 14 skipped / 3 **failed**. The
three failures were real integration blockers, not merge artefacts:

- **Two files that committed code depends on had never been committed** in the
  divergent copy: `resasm_user/abaqus_job.py` (imported by
  `residual_core/ui/cli.py` line 491 for the `verify-job` command) and
  `examples/residual_sensitivity_c3d8/sensitivity_engine.py` (imported by
  `tests/framework/test_field_sensitivity.py` line 234). A pure git integration
  silently drops both.
- **Two tests poisoned each other in one process.** The active branch's
  `tests/framework/test_compiled_umat_oti_to_resasm.py` and the copy's
  `tests/framework/test_umat_backend.py` both compile Fortran through
  `umat_oti`; whichever ran second failed, and each passed alone.
- **A latent crash masked the real diagnostic.** `resasm_user/umat_backend.py`
  line 408 formats `max_relerr` with `%.3e`, but
  `resasm_user/umat_matpoint.py` line 243 legitimately returns
  `{'available': True, 'passed': False, 'max_relerr': None}` when the
  transformed build fails. The result was
  `TypeError: must be real number, not NoneType` instead of the reason string.
