# IMQCAM Annual Meeting presentation: claims that rest on this repository

The complete claim-by-claim record (every slide, the command, the independent
reference, the measured value and the status) is `docs/PRESENTATION_CLAIMS.md`
in the Residual Assembler repository, whose `presentation/` directory holds the
reproduction scripts (`presentation/run_all.py`). This file lists what those
scripts run from **this** repository, so a reader of this repository can re-run
each piece directly. Measured values are those of the 2026-09-18 run reported
there.

| Slide | What this repository supplies | Command (from this repository's root) | Measured |
|---|---|---|---|
| 13 | Program 1: the source transform of all 20 parameter-sensitivity models against centred FD of the separately compiled ORIGINAL | `python tools/run_parameter_sensitivity_sweep.py --work-dir <dir> --results-dir <dir>/results` | 20 transformed and compiled, 20 primal parity, 19 verified, 83/84 directions (m6_fcc: one noise-floor row withheld), 14 539/14 540 rows agree |
| 13, 28–32 | the compiled OTI provider (Program 1 object consumed by the Residual Assembler) | `python -m umat_oti.provider build parameter_sensitivity/models/<model>/contract_v2.json --out <dir>` (console script `umat-oti-provider`) | builds for 20 of the 21 model directories (m2_elastic3d's contract uses another schema and is refused); DSIGMA_DP within 1.6e-7 of FD for all 20 (RA claim 1) |
| 28–32 | the flow model `parameter_sensitivity/models/m5_cpflow` | via RA `presentation/claim3_cp_residual_c3d8.py` | OTI vs hand-derived chain rule 2.9e-16 (NRMSE) |
| 8 | the transformer on the 19 `benchmarks/*.json` contracts and the paired Abaqus validation (`umat_oti.validation.job_builder`, `abaqus_runner`, `compare_results`) | via RA `presentation/claim4_benchmark_ddsdde.py --abaqus` (the functions `tools/run_completed_json_batch.py --validate` uses, with DDSDDE forced into the comparison as in the slide's run) | 18 of 18 slide cases run from their committed contracts, 17 pass (12 exact, 5 within tolerance); NKH needs PROPS(1) = 0 (source defect below) |
| 25 | the internal-Jacobian probe (`umat_oti.transform.internal_jacobian`, `local_jacobian_probe`) and the parameter-sensitivity transform | via RA `presentation/claim5_constitutive_jacobians.py`; FJAC alone: `python tools/run_internal_jacobian_round.py` | see the RA document, claim 5 |

## Defects found by the reproduction (fixed 2026-09-18)

1. `src/umat_oti/transform/source_transform.py` (`884d39e`): a labelled IF whose
   condition reads a promoted variable (`  802 IF (IFLAG.EQ.1) THEN` in UMAT_PCL,
   PCLI, PCLI_R, PCLK) lost its label and started inside the label field, so the
   Abaqus user file did not compile.
2. `src/umat_oti/fortran/regions.py` (`884d39e`): in sources that keep the elastic
   stiffness in DDSDDE and form the predictor stress from it (UMAT_VPDCL,
   UMAT_NKH_1.02), the inputs of those DDSDDE writes were classed tangent-only and
   their assignments skipped; the transformed stress differed from the original's.
3. `src/umat_oti/transform/source_transform.py` (`1cd2e58`): a DATA-initialised
   name that nothing assigns but the contract lists under `promote` (UMAT_HIN:
   ONE, TWO, ZERO) made the DATA blocker refuse the file; it is now kept real. An
   assigned DATA name is still refused.
4. `src/umat_oti/services/transformation.py` (`0b075b4`): a compact contract
   could not name where the helpers its UMAT calls are published. It may now
   declare `"dependency_roots"`; the closure is resolved, written entry file
   first and transformed, and recorded in the summary as `dependency_closure`.
   `benchmarks/UMAT_PCO.json` declares `../UMATs/UMATs/ICP`;
   `tools/run_completed_json_batch.py --validate` compiles the original from the
   same resolved file.

Regression tests: `tests/test_benchmark_transforms_keep_labels_and_predictor_inputs.py`,
`tests/test_a_data_constant_in_the_promote_list_stays_real.py`,
`tests/test_a_contract_resolves_its_helper_closure.py`. The transformer edits move
the transform fingerprint; `transform_generation.json` has to be re-frozen by the
lead before
`tests/test_contract_fixtures.py::test_the_recorded_generation_is_this_worktrees_actual_transform`
passes again.

With these, all 18 slide-8 benchmarks run from their committed contracts in the
paired Abaqus validation: 17 pass (12 exact, 5 within tolerance); UMAT_NKH_1.02
fails on the source defect below and passes (0.7234 / 7.5e-4) with PROPS(1) = 0.

## Source defects the reproduction measured (not changed; the sources are inputs)

* UMAT_VPDCL_R reads its back stress with `DO K1=10,2*NTENS+5` into `XBACK(NTENS)`:
  in bounds only for NTENS = 4; the benchmark contract declares 6 and both archived
  3-D Abaqus runs of it failed.
* UMAT_NKH_1.02 sets `THTA=PROPS(1)` when PROPS(1) ≠ 0 but then uses `DTHTA`
  (thermal strain, line 111) without setting it.
* The hand-coded internal Jacobians ANP1P and BNP1P (UMAT_NKH_1.02) and GDIA(3,3)
  (UMAT_VPDCO, UMAT_VPDCL_R) drop a factor (1 − D); with damage active they differ
  from centred FD by 1.9e-4 and 6.7e-5, and FJAC, which uses them, by 2.6e-3 in
  VPDCO/VPDCL_R. The OTI values agree with FD in every case.
* Licence of the ICP family: `UMATs/UMATs/ICP/*.for` are, after line-ending
  normalisation, byte-identical to `UMATS/*.for` of
  `https://github.com/jgomezc1/ABAQUS-US` (MIT, "Copyright (c) 2015 Juan Gomez",
  Universidad EAFIT). The helper routines UMAT_PCO needs are in that family
  (resolved here from `UMAT_ECL_TEMP.for`; upstream also ships them in
  `UELS/UEL8_PCOR.for`), so they may be included under MIT with its notice kept.
  `THIRD_PARTY_NOTICES.md` section 2a now credits that upstream and carries its
  MIT notice; section 2b records that the ICP subfolders are the companion code
  of Dunne & Petrinic, *Introduction to Computational Plasticity* (OUP 2005),
  whose redistribution rights are not stated and must be confirmed before release.
