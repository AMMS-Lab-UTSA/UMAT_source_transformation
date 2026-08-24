# Publication results reconciliation

The manuscript, poster and presentations define **what the software must be able
to do**. They do not define what it must compute. Where a measured result
differs from a document value, the measurement wins and the document is revised.

The governing rule for this file:

> Run the real implementations and publish the real reproducible results, even
> when they differ from the manuscript, poster, or presentation.

Consequences applied throughout: no document value is hardcoded anywhere in the
code; no tolerance is widened to recover a claimed number; no unavailable result
is written as zero; no failed model is dropped from a denominator; compiling is
never reported as numerical verification; and the paper is never used as a
reference solution.

**The five named source documents are not on this machine** (see
`LOCAL_IMPLEMENTATION_INVENTORY.md`). Every "historical document value" below is
therefore taken from the delivery requirements as stated to us, or from an
artifact found on this machine, and is labelled with which. Claims that can only
be read from the missing documents are marked
`blocked_by_external_dependency` — not confirmed, not refuted.

Status vocabulary: `verified`, `partially_implemented`, `unimplemented`,
`failed`, `blocked_by_external_dependency`.

## Reconciliation table

| Requirement or claim | Historical document value | Current measured value | Evidence | Status | Required manuscript revision |
|---|---:|---:|---|---|---|
| Abaqus paired validation, successful models | 18 of 19 | **18 passed, 1 failed execution** (total 19) | `paper_results/arc_791506/table2_abaqus_paired.json` | `verified` | none — reproduced |
| Abaqus DDSDDE comparisons | (implied 18) | **17 compared, 17 passed, 1 `not_requested`, 1 unavailable** | same | `verified` | State DDSDDE as **17/17 compared**, not 18. `spin_elas_def` never requested a DDSDDE comparison and must not be counted as one |
| Nineteenth case `UMAT_VPDCL_R` | reported separately | **both original and transformed fail to execute** | `…/validation/UMAT_VPDCL_R/validation_report.json` | `failed` | keep reported separately; do not fold into the 18 |
| Internal constitutive Jacobians | 19 entries across 10 models | **0 data rows** — table is header-only | `…/evidence/table3_internal_jacobians.csv` | `unimplemented` | **Remove or mark unimplemented until executed.** No internal-Jacobian implementation was found in any local copy |
| Higher order, controlled J2 | 108/108 comparisons | **108 rows, 108 supporting, verified**; max rel. err. on resolved rows **3.02e-11** | `…/higher_order_convergence/j2/` | `verified` | Replace the pass-count framing with the row-classification framing; quote 3.02e-11 |
| Higher order, `code_imp` | 96/96 comparisons | **96 rows, 95 supporting, not verified**; one row 2.30e-6 outside a reference resolved to ~1e-9 | `…/higher_order_convergence/code_imp/` | `partially_implemented` | **96/96 must become 95/96.** The old count came from a 2e-5 relative tolerance that accepted the discrepancy |
| Higher order, `UMAT_PCL` | expected to verify | **0 rows** — the transformed build aborts (`double free or corruption`) while the original runs | `…/higher_order_convergence/UMAT_PCL/` | `failed` | Report as a transformation defect, not a result |
| Higher order, `UMAT_PCLK` | expected to verify | **96 rows, 0 counted.** 72 rows classified supporting, but primal parity fails at 5.9e6× the model's own Newton tolerance, so the gate zeroes them | `…/higher_order_convergence/UMAT_PCLK/` | `failed` | Report the primal divergence; no derivative claim is admissible |
| Higher order, `visco_imp` | expected to verify | **96 rows, 90 supporting, not verified**; 6 rows unresolvable in double precision | `…/higher_order_convergence/visco_imp/` | `partially_implemented` | Report 90/96 and the reference limitation |
| Worst relative error, higher order | not stated to us | J2 **3.02e-11**; `code_imp` **9.64e-6**; `visco_imp` **8.67e-5**; `UMAT_PCLK` 0.344 (not counted) | convergence datasets | `verified` | quote per model, on resolved rows only |
| Table 4 covering 4 actual UMATs | `code_imp`, `UMAT_PCL`, `UMAT_PCLK`, `visco_imp` | **none of the four verifies.** Only controlled J2 does | `…/table4_higher_order_convergence.csv` | `partially_implemented` | **The four-model Table 4 claim cannot stand.** Either restrict Table 4 to J2 + the partial `code_imp`/`visco_imp` rows, or defer |
| J2 `DSIGMA_DP` 6×4, `DSTATEV_DP` 1×4 | 6×4 and 1×4 | **560 data rows present** | `…/evidence/table5_j2_parameter_sensitivities.csv` | `partially_implemented` | verify the row set actually reduces to 6×4 and 1×4 before publishing |
| Parameter sensitivities, 18 models | 18 models, 76 of 84 directions | **0 data rows**; the 18 model contracts exist only in `~/Documents/…/oti_provider/materials/` and have never been run through this pipeline | `…/evidence/table6_parameter_sensitivity_sweep.csv` | `unimplemented` | **Do not publish 18/76/84 until measured.** The models exist; the run does not |
| Web corpus, discovered | "8 → 30 UMATs" | **133 discovered, 133 licence-classified, 46 entry routines detected, 45 contracts built, 14 transformed, 14 compiled** | `…/evidence/corpus_round_metrics.json` | `partially_implemented` | Replace "8 → 30". The measured funnel is 133 → 46 → 45 → 14 |
| Web corpus, verified | implied verified | **0 primal-parity verified, 0 derivatives numerically verified, 0 Abaqus verified** | same | `unimplemented` | **14 compiled is not 14 verified.** The manuscript must not describe compilation as verification |
| Web corpus, "17 fixes" | 17 | **not reproducible** — no fix ledger found in any local copy | — | `blocked_by_external_dependency` | mark historical unless a ledger is produced |
| "1.4 nominal-run equivalents" | 1.4 | **measured 1.42 as a cost *ratio*** for one routine: analytical 2.29–2.34 µs/call vs OTI 3.33–3.43 µs/call | `~/Downloads/driver_utsa/benchmark_runs.csv` (10 rows) | `partially_implemented` | The 1.4 appears to be OTI costing **1.42× an analytical call**, i.e. OTI is *slower per call* on this routine. That is not a "nominal-run equivalent" and not a speedup. Restate or withdraw |
| "8× faster" | 8× | **not reproduced.** No end-to-end benchmark exists | — | `unimplemented` | mark `not_yet_verified`; do not publish |
| "49 vs 210 updates" | 49 / 210 | **not measured** | — | `unimplemented` | mark `not_yet_verified` |
| "400 avoided analyses" | 400 | **not measured** | — | `unimplemented` | mark `not_yet_verified` |
| Scaling to ~150 / ~200 directions | claimed | **not measured**; no harness beyond the single-routine one above | — | `unimplemented` | mark `not_yet_verified` |
| Residual Assembler C3D8 `du/dp`, `dσ/dp`, `dq/dp` | claimed | **not validated against 2N+1 Abaqus reruns.** Implementation exists in a divergent local copy, not on the active branch | `LOCAL_IMPLEMENTATION_INVENTORY.md` | `blocked_by_external_dependency` | needs Abaqus; this host has 2021.HF5 while the archived evidence is 2024 |
| Sentinel job `791553` | detects component-level DDSDDE differences | **reproduced**: +1000 on `DDSDDE(1,1)`, `failed_as_expected`, component `(1,1)` identified | `…/arc_791506/ddsdde_sentinel_audit.json` | `verified` | none |
| Version metadata | 1.1.0 | **1.1.0 in all five sources** | pyproject, `__init__`, CITATION.cff, codemeta.json, .zenodo.json | `verified` | none |

## The three revisions that matter most

1. **`code_imp` 96/96 → 95/96.** The retired count rested on a 2e-5 relative
   tolerance. With branch-crossing steps excluded the reference resolves to
   ~1e-9, and one row sits 2.30e-6 outside it. The divergence is 1.41× the
   model's own Newton tolerance (`TOLER=1.D-5`), so it is a property of the
   model, not proof the transformation is wrong — and not proof it is right.

2. **The four-model Table 4 claim cannot stand as written.** `UMAT_PCL` produces
   no rows at all, `UMAT_PCLK`'s derivatives are inadmissible until its primal
   divergence is fixed, and `visco_imp` withholds 6 of 96 rows.

3. **"14 compiled" is not "14 verified".** The corpus funnel ends at compilation:
   zero rows have been numerically verified. Any sentence implying otherwise
   must be rewritten.

## What cannot be reconciled yet

The five named documents are absent, so claims readable only from them —
poster figures, specific manuscript sentences, section-level wording — stay
`blocked_by_external_dependency`. Transferring those files unblocks this
column; nothing else does, and no wording will be inferred from a
differently-named variant.
