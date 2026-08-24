# Table 4 - higher-order derivatives from actual UMAT sources

Every row below is admitted only on the strength of an independent
reference. A derivative is **not** counted as verified because its error
fell under a large absolute tolerance; it is counted when the
finite-difference estimate plateaus across consecutive step sizes and the
OTI value lies inside that plateau, or when the derivative is zero and
something other than the OTI result establishes that.

| Model | Branch | Order | Rows | Resolved | Zero (supported) | Cancellation-limited | Unresolved | Admitted | Max rel. err. (resolved) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| controlled_j2_actual_umat | elastic | 2 | 12 | 0 | 12 | 0 | 0 | 12 | - |
| controlled_j2_actual_umat | elastic | 3 | 12 | 0 | 12 | 0 | 0 | 12 | - |
| controlled_j2_actual_umat | elastic | 4 | 12 | 0 | 12 | 0 | 0 | 12 | - |
| controlled_j2_actual_umat | plastic | 2 | 24 | 10 | 14 | 0 | 0 | 24 | 4.14e-14 |
| controlled_j2_actual_umat | plastic | 3 | 24 | 10 | 14 | 0 | 0 | 24 | 3.02e-11 |
| controlled_j2_actual_umat | plastic | 4 | 24 | 11 | 13 | 0 | 0 | 24 | 2.62e-11 |
| code_imp_legacy_umat | elastic | 2 | 8 | 0 | 8 | 0 | 0 | 8 | - |
| code_imp_legacy_umat | elastic | 3 | 8 | 0 | 8 | 0 | 0 | 8 | - |
| code_imp_legacy_umat | elastic | 4 | 8 | 0 | 8 | 0 | 0 | 8 | - |
| code_imp_legacy_umat | plastic | 2 | 24 | 18 | 6 | 0 | 0 | 24 | 2.30e-06 |
| code_imp_legacy_umat | plastic | 3 | 24 | 18 | 6 | 0 | 0 | 24 | 3.49e-06 |
| code_imp_legacy_umat | plastic | 4 | 24 | 18 | 6 | 0 | 0 | 24 | 9.64e-06 |

## Reference quality per model

### controlled_j2_actual_umat - defensible

- rows: 108; admitted to Table 4: 108; withheld: 0
- reference: independent tensor-product finite differences of validation.j2_reference.integrate_increment evaluated in mpmath at 80 decimal digits
- precision: mpmath, 80 decimal digits
- published step: 2.000e-05; swept over factors [16.0, 8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625]
- independent zero support: structural stencil invariance, exact local affineness, and an independent recomputation at 200 decimal digits with step 2.000e-08
- normalization: D_hat_n = (d^n sigma / d eps^n) * strain_scale**n / stress_scale with stress scale 250.0 MPa (initial yield stress SIGY0 of the controlled J2 model) and strain scale 0.001 (characteristic strain-increment magnitude of the three J2 load steps)

### code_imp_legacy_umat - defensible

- rows: 96; admitted to Table 4: 96; withheld: 0
- reference: independently compiled original code_imp UMAT replayed for each tensor-product centred finite-difference stencil node
- precision: IEEE double precision (compiled Fortran, gfortran)
- published step: 4.000e-05; swept over factors [16.0, 8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625]
- independent zero support: structural stencil invariance and exact local affineness (bitwise-zero second and mixed differences at amplitudes 1.600e-04, 8.000e-05, 4.000e-05); the reference is a double-precision executable, so no higher-precision recomputation is available for this model
- normalization: D_hat_n = (d^n sigma / d eps^n) * strain_scale**n / stress_scale with stress scale 240.0 MPa (initial yield stress SIGY0 hard-coded in code_imp.f) and strain scale 0.001 (characteristic strain-increment magnitude of the four code_imp load steps)

