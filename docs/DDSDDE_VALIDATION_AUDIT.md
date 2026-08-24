# DDSDDE Paired-Abaqus Validation Audit

## Conclusion

The former all-zero aggregate table was a reporting defect, not evidence that all transformed tangents were bitwise identical. The original aggregator read `comparison_report.json`, which could contain only an overall status, requested metric keys named `max_absolute_difference` / `max_relative_difference`, while the validator emits `max_abs_difference` / `max_rel_difference`, and allowed absent values to appear as zero in downstream reporting. Commit `cf6530d` corrected the source to the complete `validation_report.json` and the emitted key names.

The corrected real Abaqus collection contains 18 overall passing cases and one additional failed-execution case. Observable-specific accounting is:

| Observable | Requested | Available | Compared | Passed | Failed | Not requested | Unavailable |
|---|---:|---:|---:|---:|---:|---:|---:|
| STRESS | 19 | 18 | 18 | 18 | 0 | 0 | 1 |
| STATEV | 19 | 18 | 18 | 18 | 0 | 0 | 1 |
| DDSDDE | 18 | 17 | 17 | 17 | 0 | 1 | 1 |
| CONVERGENCE | 19 | 18 | 18 | 18 | 0 | 0 | 1 |

Thus the DDSDDE result is 17 of 17 available comparisons passed. It is not 18 of 19: `spin_elas_def` did not request DDSDDE, and `UMAT_VPDCL_R` did not produce a valid paired execution.

Nonzero DDSDDE differences among the 17 comparisons include:

| Case | Maximum absolute difference | Maximum relative difference |
|---|---:|---:|
| `UMAT_NKH_1.02` | 0.72344970703125 | 0.0021311044913665477 |
| `UMAT_VPDCL` | 0.2370147705078125 | 0.0011540414668875243 |
| `UMAT_VPDCO` | 0.37164306640625 | 0.0011223434438184547 |
| `code_exp` | 0.03125 | 1.5808898243892252e-7 |
| `code_imp` | 0.015625 | 8.20550119775701e-8 |

`spin_elas_def` is not a zero-difference result. Its archived run did not request DDSDDE comparison, so its DDSDDE metrics are `null` and status is `not_requested`. Both result readers nevertheless exported four distinct 6x6 increment matrices, now retained in the audit record.

`UMAT_VPDCL_R` is the nineteenth additional case. Both paired executions failed and do not form a valid comparison. Its requested observables are `unavailable`, with the original/transformed run statuses retained as the reason. Comparison metrics, matrices, and increment differences are `null` or empty rather than fabricated from partial outputs.

## Adversarial proof

Slurm job `791553` added 1000 to transformed `DDSDDE(1,1)` after OTI `GETIM` extraction and before STATEV export. The production comparator failed as expected and reported:

- component `(1,1)`
- original value `184058.078125`
- perturbed value `185058.078125`
- maximum absolute difference `1000.0`
- maximum relative difference `0.005403708987642984`

The incorrect generated source was temporary and was not committed. The archived proof is `paper_results/arc_791506/ddsdde_sentinel_audit.json`.

## Per-case archive

`paper_results/arc_791506/table2_abaqus_paired.json` now records for every case:

- original and transformed source paths and SHA256 identities
- instrumented original and combined transformed user-subroutine identities
- immutable Abaqus execution commit separately from the later audit-tool commit
- distinct original/transformed job names, working directory, user path, and command
- retained compiled objects where Abaqus leaves them, otherwise an explicit not-retained status
- compile/link log identities
- line-resolved OTI strain seeding
- original DDSDDE assignments and their line span
- bypassed DDSDDE assignments and their line span
- OTI `GETIM(STRESS_OTI, ...)` extraction lines and span
- DDSDDE-to-STATEV validation export lines
- extraction script identity and STATEV slot layout
- distinct result-file identities
- original/transformed DDSDDE matrices for every paired increment
- element-wise absolute and relative differences and per-increment maxima

Matrices and differences are present only when both executions completed. Failed-execution cases retain source, job, command, log, and result-file identities without exposing partial matrices as comparison evidence.

The historical execution provenance is Slurm job `791506`, node `c015`, execution commit `13e98cafe38c30242a6139cec0bb6c27e477a40a`. Re-aggregation never relabels this execution with the current code commit.
