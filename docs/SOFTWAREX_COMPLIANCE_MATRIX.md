# SoftwareX compliance matrix

This document audits the manuscript's claims against executable evidence. It is
for reviewers and authors who need to know which claims the repository
supports, at what strength, and what still blocks the rest.

The machine-readable record is `paper_results/softwarex_claim_matrix.json`.
`tests/test_softwarex_compliance_matrix.py` enforces its status vocabulary and
stops narrow fixtures from promoting broad claims. The claim statuses below are
those of the audit performed on 2026-08-24. Evidence produced since then is
summarised in [Changes since the audit](#changes-since-the-audit); the
generated, always-current views are
[PUBLICATION_RESULTS_RECONCILIATION.md](PUBLICATION_RESULTS_RECONCILIATION.md)
and [PIPELINE_REQUIREMENTS_TRACEABILITY.md](PIPELINE_REQUIREMENTS_TRACEABILITY.md).

## Status vocabulary

| Status | Meaning |
|---|---|
| `verified_from_generic_transformed_source` | verified on a source transformed by the generic transformer |
| `verified_from_real_abaqus_execution` | verified by real Abaqus executions |
| `verified_reference_fixture_only` | verified on a controlled fixture only; does not extend to arbitrary sources |
| `implemented_offline_not_abaqus_verified` | implemented and exercised offline, not verified in Abaqus |
| `partially_implemented` | some of the required capability or evidence exists |
| `not_implemented` | the required capability or evidence does not exist |
| `blocked_by_external_environment` | cannot be decided without something outside the repository |
| `failed` | executed and failed |

## Claim status at the 2026-08-24 audit

| Claim | Manuscript location | Status | Evidence or blocker |
|---|---|---|---|
| 18-case paired DDSDDE collection | Table 2 | `verified_from_real_abaqus_execution` | `paper_results/arc_791506/table2_abaqus_paired.json` and per-case reports |
| DDSDDE adversarial sentinel | Table 2 validation method | `verified_from_real_abaqus_execution` | `paper_results/arc_791506/ddsdde_sentinel_audit.json` |
| Additional `UMAT_VPDCL_R` | Outside the 18-case Table 2 set | `failed` | Both original and transformed executions fail |
| 19 internal Jacobians | Table 3 | `partially_implemented` | Generated Table 3 was header-only |
| Direction/factorial polynomial | Table 4 / Figure 4 subclaim | `verified_reference_fixture_only` | SymPy bivariate fixture only |
| Orders 2-4 from four actual UMATs | Table 4 / Figure 4 | `partially_implemented` | Only the controlled J2 model is verified; see below |
| Focused J2 sensitivities | Table 5 / Figures 3 and 6 | `verified_reference_fixture_only` | J2-specific emitter, not generic supplied-source transformation |
| Generic source parameter sensitivities | Generic capability / Table 6 | `partially_implemented` | Controlled fixtures only |
| 18-model, 76-direction sweep | Table 6 | `not_implemented` | Generated Table 6 was header-only |
| Unified derivative-request program | Program architecture | `partially_implemented` | Canonical model exists; combined end-to-end coverage of every entry point is missing |
| REAL UMAT vs OTI driver ABI separation | Architecture / availability | `implemented_offline_not_abaqus_verified` | ABI-labelled manifests exist |
| One-command tables and figures | Tables 2-6 / Figures 3-6 | `partially_implemented` | Several tables were empty or fixture-only |
| Runtime/RSS scaling to 200 directions | Figure 5 | `not_implemented` | Required measured benchmark is absent |
| Public corpus Round 1 transform/compile | Corpus claim | `implemented_offline_not_abaqus_verified` | Compiled outcomes are not numerical verification |
| Corpus numerical ladder and Round 2 | Corpus claim | `not_implemented` | No primal/derivative verified candidates or Round 2 |
| Streamlit unified workflow | UI claim | `partially_implemented` | Core editor exists; multi-file controls, modes, previews and evidence automation remain |
| Residual Assembler structural sensitivity | Downstream companion, excluded from the paper | `partially_implemented` | Real elastic residual check exists; structural 2N+1 sensitivities do not |
| Complete V4 statement audit | Entire manuscript | `blocked_by_external_environment` | `UMAT_OTI_SoftwareX_V4.docx` was not available to the audit |

## Anti-promotion rules

1. Polynomial/SymPy evidence can verify direction indexing and the factorial
   correction only.
2. The J2-specific emitter cannot verify the generic supplied-source
   transformer.
3. Transformation and compilation cannot verify primal or derivative parity.
4. A real elastic C3D8 residual comparison cannot verify structural J2 `du/dp`
   sensitivities.
5. The failing nineteenth `UMAT_VPDCL_R` case is reported separately from the
   18-case manuscript set.
6. A header-only table is incomplete, whatever the historical manuscript
   numbers say.

## Changes since the audit

The statuses above have not been re-graded in the JSON record. The following
evidence has been produced since, and each item names where to read it.

- **Manuscript.** `UMAT_OTI_SoftwareX_V4.docx` was located after the audit. It
  is held outside this repository; its SHA-256 is recorded in
  `docs/manuscript_claims.json`. The V5 manuscript,
  `docs/manuscript/UMAT_OTI_SoftwareX_V5.docx`, is generated from the executed
  evidence by `tools/manuscript/build_v5_manuscript.py`.
- **Table 3 (internal Jacobians).**
  `paper_results/internal_jacobians/table3_internal_jacobians.csv` now holds 8
  verified executions over 6 distinct source implementations, with none
  disagreeing. Of 39 candidate sources, 25 have no local Newton solve and 6 are
  blocked because no property vector for them exists in either repository. The
  manuscript's 19 entries are therefore not all reproduced.
- **Table 4 (higher orders).** Only the controlled J2 model is verified against
  a step-size-converged, branch-audited reference. `code_imp`, `UMAT_PCL`,
  `UMAT_PCLK` and `visco_imp` are studied but not verified; the reasons are in
  the `reference_quality` section of the JSON record.
- **Table 6 (parameter sensitivities).**
  `paper_results/parameter_sensitivity/parameter_sensitivity_round.json` covers
  20 models: all 20 are transformed, compiled, executed and in primal parity,
  and 19 have their derivatives verified. 83 of the 84 declared parameter
  directions verify, and 14,539 of 14,540 comparison rows agree; the one
  remaining row (`m6_fcc`) sits at the centred-difference noise floor.
- **Corpus.** The whole corpus of 391 acquired sources was re-run in Abaqus on
  2026-09-18. 43 of the 260 adequately specified genuine UMATs clear all six
  evidence gates; see
  [paper_results/corpus/CORPUS_VERIFICATION.md](../paper_results/corpus/CORPUS_VERIFICATION.md)
  and [CORPUS_VERIFICATION.md](CORPUS_VERIFICATION.md).
- **Runtime and memory scaling (Figure 5).** Still not measured.

## Remaining blockers

- Reproduce, or correct, the manuscript's 19 Table 3 entries; six candidates
  lack a published property vector.
- Independently verify orders 2-4 for `code_imp`, `UMAT_PCL`, `UMAT_PCLK` and
  `visco_imp`.
- Measure runtime and RSS scaling through at least 150 parameter directions.
- Complete the sentence-level audit of the manuscript against the evidence.
