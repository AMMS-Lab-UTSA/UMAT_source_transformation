# SoftwareX Compliance Matrix

This document audits publication claims against executable evidence. The machine-readable source is
`paper_results/softwarex_claim_matrix.json`; `tests/test_softwarex_compliance_matrix.py` enforces its
status vocabulary and prevents narrow fixtures from promoting broad claims.

## Manuscript availability

`UMAT_OTI_SoftwareX_V4.docx` was not present in the workspace, the user's home directory, fetched Git
history, or the remote feature tree on 2026-08-24. Table and figure locations below come from the
delivery requirements. Exact prose-section and statement-level mapping remains
`blocked_by_external_environment` until that file is supplied.

## Current claim status

| Claim | Manuscript location | Status | Evidence or blocker |
|---|---|---|---|
| 18-case paired DDSDDE collection | Table 2 | `verified_from_real_abaqus_execution` | `paper_results/arc_791506/table2_abaqus_paired.json` and per-case reports |
| DDSDDE adversarial sentinel | Table 2 validation method | `verified_from_real_abaqus_execution` | `paper_results/arc_791506/ddsdde_sentinel_audit.json` |
| Additional `UMAT_VPDCL_R` | Outside the 18-case Table 2 set | `failed` | Both original and transformed executions fail |
| 19 internal Jacobians | Table 3 | `partially_implemented` | Generated Table 3 is header-only |
| Direction/factorial polynomial | Table 4 / Figure 4 subclaim | `verified_reference_fixture_only` | SymPy bivariate fixture only |
| Orders 2-4 from four actual UMATs | Table 4 / Figure 4 | `partially_implemented` | `code_imp` generated output; four-model independent checks are missing |
| Focused J2 sensitivities | Table 5 / Figures 3 and 6 | `verified_reference_fixture_only` | J2-specific emitter, not generic supplied-source transformation |
| Generic source parameter sensitivities | Generic capability / Table 6 | `partially_implemented` | Controlled fixtures only |
| 18-model, 76-direction sweep | Table 6 | `not_implemented` | Generated Table 6 is header-only |
| Unified derivative-request program | Program architecture | `partially_implemented` | Canonical model exists; all-entry-point combined E2E coverage is missing |
| REAL UMAT vs OTI driver ABI separation | Architecture / availability | `implemented_offline_not_abaqus_verified` | ABI-labelled manifests exist |
| One-command tables and figures | Tables 2-6 / Figures 3-6 | `partially_implemented` | Several tables are empty or fixture-only |
| Runtime/RSS scaling to 200 directions | Figure 5 / presentations | `not_implemented` | Required measured benchmark is absent |
| Public corpus Round 1 transform/compile | Corpus claim | `implemented_offline_not_abaqus_verified` | Compiled outcomes are not numerical verification |
| Corpus numerical ladder and Round 2 | Corpus claim | `not_implemented` | No primal/derivative verified candidates or Round 2 |
| Streamlit unified workflow | UI claim | `partially_implemented` | Core editor exists; multi-file/modes/previews/evidence automation remain |
| Residual Assembler structural sensitivity | Downstream companion, excluded from paper | `partially_implemented` | Real elastic residual check exists; structural 2N+1 sensitivities do not |
| Complete V4 statement audit | Entire manuscript | `blocked_by_external_environment` | The named manuscript file is unavailable |

## Anti-promotion rules

1. Polynomial/SymPy evidence can verify direction indexing and factorial recovery only.
2. The J2-specific emitter cannot verify the generic supplied-source transformer.
3. Transformation and compilation cannot verify primal or derivative parity.
4. A real elastic C3D8 residual comparison cannot verify structural J2 `du/dp` sensitivities.
5. The failing nineteenth `UMAT_VPDCL_R` case is reported separately from the 18-case manuscript set.
6. Header-only tables are incomplete regardless of historical manuscript numbers.

## Immediate blockers

- Supply `UMAT_OTI_SoftwareX_V4.docx` for complete sentence-level section mapping.
- Regenerate Table 3 from 19 current executions and independent references.
- Independently verify orders 2-4 for `code_imp`, `UMAT_PCL`, `UMAT_PCLK`, and `visco_imp`.
- Execute the 18-model/76-direction sweep rather than copying manuscript values.
- Run measured timing and RSS scaling through at least 150 directions.
- Complete corpus primal/derivative stages and a regression-aware Round 2.
