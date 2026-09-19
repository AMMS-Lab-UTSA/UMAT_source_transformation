# Verification record: claims that rest on this repository

The complete claim-by-claim record (every slide, the command, the independent
reference, the measured value and the status) is `docs/VERIFICATION_RECORD.md`
in the Residual Assembler repository, whose `verification/` directory holds the
reproduction scripts (`verification/run_all.py`). This file lists what those
scripts run from **this** repository, so a reader of this repository can re-run
each piece directly. Measured values are those of the 2026-09-18 run reported
there.

| Slide | What this repository supplies | Command (from this repository's root) | Measured |
|---|---|---|---|
| 13 | Program 1: the source transform of all 20 parameter-sensitivity models against centred FD of the separately compiled ORIGINAL | `python tools/run_parameter_sensitivity_sweep.py --work-dir <dir> --results-dir <dir>/results` | 20 transformed and compiled, 20 primal parity, 19 verified, 83/84 directions (m6_fcc: one noise-floor row withheld), 14 539/14 540 rows agree |
| 13, 28–32 | the compiled OTI provider (Program 1 object consumed by the Residual Assembler) | `python -m umat_oti.provider build parameter_sensitivity/models/<model>/contract_v2.json --out <dir>` (console script `umat-oti-provider`) | builds for 20 of the 21 model directories (m2_elastic3d's contract uses another schema and is refused); DSIGMA_DP within 1.6e-7 of FD for all 20 (RA claim 1) |
| 28–32 | the flow model `parameter_sensitivity/models/m5_cpflow` | via RA `verification/claim3_cp_residual_c3d8.py` | OTI vs hand-derived chain rule 2.9e-16 (NRMSE) |
| 8 | the transformer on the 19 `benchmarks/*.json` contracts and the paired Abaqus validation (`umat_oti.validation.job_builder`, `abaqus_runner`, `compare_results`) | via RA `verification/claim4_benchmark_ddsdde.py --abaqus` (the functions `tools/run_completed_json_batch.py --validate` uses, with DDSDDE forced into the comparison as in the slide's run) | 18 of 18 slide cases run from their committed contracts, 17 pass (12 exact, 5 within tolerance); NKH needs PROPS(1) = 0 (source defect below); the seven contracts whose transformed source changed with `5b97c2f` (UMAT_HIN, PCL, PCLI, PCLI_R, PCLK, PCO, VPDCL_R) re-run in Abaqus 2021.HF5 on 2026-09-18: the six slide cases 0 / 0 again, VPDCL_R's 3-D contract fails in both builds again, its plane-strain variant 0.3673 / 3.2e-4 again; counts unchanged |
| 9–12, 17, 41 | the developer side of the provider split: `REAL_UMAT.obj` (the ORIGINAL compile), the object with the OTI lift, `Mapping.json`, `transform_report.txt` | `umat-oti-provider build parameter_sensitivity/models/m3_j2/contract_v2.json --out <dir> --regular-object REAL_UMAT.obj` (add `--abaqus-toolchain` to build REAL_UMAT with `abaqus make`), or the GUI's Parameter Sensitivities tab | every DSIGMA_DP / DSTATEV_DP / DDSDDE entry judged against centred FD of the separately compiled ORIGINAL: m3_j2 628 agree, 240 consistent with zero, 0 disagree; m6_fcc (slide-15 values, tension-with-shear path) 4,556 / 1,572 / 112 unresolved / 0; objects rebuild byte-identically and carry no machine paths |
| 16, 40 | the Constitutive Jacobian screen | `umat-oti jacobian <umat.for> --ntens 6 --out <dir> --compile`, or the GUI tab (byte-identical outputs) | J2 tangent vs FD of the ORIGINAL 3e-11 (scaled) over elastic, plastic and unloading increments (`tests/gui/test_developer_screens.py`) |
| 15, 39 | the m3_j2 and m6_fcc providers the Residual Assembler's history engine replays the full-size cantilevers with (entry point `UMAT_OTI_EVAL_TOTAL`, [PROVIDER_EVAL_TOTAL.md](PROVIDER_EVAL_TOTAL.md)) | [Residual_Assembler examples/cantilevers](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/examples/cantilevers/README.md) | see the RA document, slides 15, 33, 39 |
| 25 | the internal-Jacobian probe (`umat_oti.transform.internal_jacobian`, `local_jacobian_probe`) and the parameter-sensitivity transform | via RA `verification/claim5_constitutive_jacobians.py`; FJAC alone: `python tools/run_internal_jacobian_round.py` | see the RA document, claim 5 |

## Defects found by the reproduction (fixed 2026-09-18)

1. `src/umat_oti/transform/source_transform.py` (`7c4975c`): a labelled IF whose
   condition reads a promoted variable (`  802 IF (IFLAG.EQ.1) THEN` in UMAT_PCL,
   PCLI, PCLI_R, PCLK) lost its label and started inside the label field, so the
   Abaqus user file did not compile.
2. `src/umat_oti/fortran/regions.py` (`7c4975c`): in sources that keep the elastic
   stiffness in DDSDDE and form the predictor stress from it (UMAT_VPDCL,
   UMAT_NKH_1.02), the inputs of those DDSDDE writes were classed tangent-only and
   their assignments skipped; the transformed stress differed from the original's.
3. `src/umat_oti/transform/source_transform.py` (`b124e39`): a DATA-initialised
   name that nothing assigns but the contract lists under `promote` (UMAT_HIN:
   ONE, TWO, ZERO) made the DATA blocker refuse the file; it is now kept real. An
   assigned DATA name is still refused.
4. `src/umat_oti/services/transformation.py` (`24143f8`): a compact contract
   could not name where the helpers its UMAT calls are published. It may now
   declare `"dependency_roots"`; the closure is resolved, written entry file
   first and transformed, and recorded in the summary as `dependency_closure`.
   `benchmarks/UMAT_PCO.json` declares `../UMATs/UMATs/ICP`;
   `tools/run_completed_json_batch.py --validate` compiles the original from the
   same resolved file.
5. `src/umat_oti/transform/source_transform.py` (`f11806f`, found by the corpus
   re-transform after fix 2): an assignment to a kept-real variable whose
   right-hand side reads a promoted value, continued over several lines, was
   rewritten from its first physical line only (`EMOD = REAL(A + B *)` with the
   continuation left dangling), so one corpus source that compiled at every
   earlier generation stopped compiling. The logical statement is now rewritten
   whole, as on the stress path; a second corpus source with the same construct
   now compiles for the first time.
6. `src/umat_oti/transform/source_transform.py` (`5b97c2f`, found by continuous
   integration with a newer gfortran): INTEGER variables on the stress path (UMAT_HIN's
   flags ISTEP, ICYCLE, IFLAG) were promoted, and the lifted helpers' dummies
   typed hypercomplex through IMPLICIT were not seen, so real actuals (RSTE,
   TMPTIM, ...) reached them. Integers are no longer promoted, the implicit types
   are read, and both directions are checked; HIN's stress now equals the
   original's to 1.1e-9 on an offline path (63 % off before).

Regression tests: `tests/test_benchmark_transforms_keep_labels_and_predictor_inputs.py`,
`tests/test_a_data_constant_in_the_promote_list_stays_real.py`,
`tests/test_a_contract_resolves_its_helper_closure.py`,
`tests/test_continued_assignment_from_promoted_value.py`,
`tests/test_lifted_helper_arguments_match_their_dummies.py`. After the last fix the
whole corpus was rerun and the transform generation re-frozen
([evidence/final_refreeze.md](evidence/final_refreeze.md)).

With these, all 18 slide-8 benchmarks run from their committed contracts in the
paired Abaqus validation: 17 pass (12 exact, 5 within tolerance); UMAT_NKH_1.02
fails on the source defect below and passes (0.7234 / 7.5e-4) with PROPS(1) = 0.
`5b97c2f` (INTEGER variables kept out of the promotion; the implicit types of the
lifted helpers' dummies read by the rewrite) changed the transformed sources of
seven benchmark contracts; before it, UMAT_HIN's transformed build passed wrongly
typed arguments to its helper routines, which its single-increment Abaqus deck
did not reveal. The seven were re-run in the paired Abaqus 2021.HF5 validation on
2026-09-18: UMAT_HIN, PCL, PCLI, PCLI_R, PCLK and PCO reproduce the original
DDSDDE, stress and state variables exactly (0 / 0), UMAT_VPDCL_R's 3-D contract
fails in both builds as before and its plane-strain variant gives 0.3673 / 3.2e-4;
the other twelve transform byte-identically. The counts above are unchanged, and
the earlier UMAT_HIN result is superseded by the re-run.

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
