# Table 4 - higher-order derivatives from actual UMAT sources

Every row below is admitted only on the strength of an independent
reference. A derivative is **not** counted as verified because its error
fell under a large absolute tolerance; it is counted when the
finite-difference estimate plateaus across consecutive *admissible* step
sizes and the OTI value lies inside that plateau, or when the derivative
is zero and something other than the OTI result *proves* it.

A step is admissible only if every stencil node stayed on the nominal
constitutive branch. A stencil that straddles a yield or unloading
boundary differences across a kink and cannot verify the derivative of
either branch, however stable its value looks.

"Zero (sampled only)" counts rows where the reference was zero at every
point tried but nothing proved it exactly zero. Finitely many equal
samples are empirical local invariance, not structural independence, so
those rows are reported and **not** counted as evidence.

| Model | Branch | Order | Rows | Resolved | Zero (proved) | Zero (sampled only) | Cancellation-limited | Unresolved | Admitted | Max rel. err. (resolved) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| controlled_j2_actual_umat | elastic | 2 | 12 | 0 | 12 | 0 | 0 | 0 | 12 | - |
| controlled_j2_actual_umat | elastic | 3 | 12 | 0 | 12 | 0 | 0 | 0 | 12 | - |
| controlled_j2_actual_umat | elastic | 4 | 12 | 0 | 12 | 0 | 0 | 0 | 12 | - |
| controlled_j2_actual_umat | plastic | 2 | 24 | 10 | 14 | 0 | 0 | 0 | 24 | 4.14e-14 |
| controlled_j2_actual_umat | plastic | 3 | 24 | 10 | 14 | 0 | 0 | 0 | 24 | 3.02e-11 |
| controlled_j2_actual_umat | plastic | 4 | 24 | 11 | 13 | 0 | 0 | 0 | 24 | 2.62e-11 |
| code_imp | elastic | 2 | 8 | 0 | 8 | 0 | 0 | 0 | 8 | - |
| code_imp | elastic | 3 | 8 | 0 | 8 | 0 | 0 | 0 | 8 | - |
| code_imp | elastic | 4 | 8 | 0 | 8 | 0 | 0 | 0 | 8 | - |
| code_imp | inelastic | 2 | 24 | 18 | 6 | 0 | 0 | 0 | 23 | 2.30e-06 |
| code_imp | inelastic | 3 | 24 | 18 | 6 | 0 | 0 | 0 | 24 | 3.49e-06 |
| code_imp | inelastic | 4 | 24 | 18 | 6 | 0 | 0 | 0 | 24 | 9.64e-06 |
| UMAT_PCLK | elastic | 2 | 8 | 0 | 8 | 0 | 0 | 0 | 8 | - |
| UMAT_PCLK | elastic | 3 | 8 | 0 | 8 | 0 | 0 | 0 | 8 | - |
| UMAT_PCLK | elastic | 4 | 8 | 0 | 8 | 0 | 0 | 0 | 8 | - |
| UMAT_PCLK | inelastic | 2 | 24 | 24 | 0 | 0 | 0 | 0 | 16 | 2.01e-01 |
| UMAT_PCLK | inelastic | 3 | 24 | 24 | 0 | 0 | 0 | 0 | 16 | 2.41e-01 |
| UMAT_PCLK | inelastic | 4 | 24 | 24 | 0 | 0 | 0 | 0 | 16 | 3.44e-01 |
| visco_imp | elastic | 2 | 8 | 0 | 8 | 0 | 0 | 0 | 8 | - |
| visco_imp | elastic | 3 | 8 | 0 | 8 | 0 | 0 | 0 | 8 | - |
| visco_imp | elastic | 4 | 8 | 0 | 8 | 0 | 0 | 0 | 8 | - |
| visco_imp | inelastic | 2 | 24 | 22 | 0 | 0 | 0 | 2 | 22 | 4.35e-07 |
| visco_imp | inelastic | 3 | 24 | 24 | 0 | 0 | 0 | 0 | 24 | 1.01e-05 |
| visco_imp | inelastic | 4 | 24 | 20 | 0 | 0 | 4 | 0 | 20 | 8.67e-05 |

## Reference quality per model

### controlled_j2_actual_umat - defensible

- rows: 108; admitted to Table 4: 108; withheld: 0
- reference: independent tensor-product finite differences of validation.j2_reference.integrate_increment evaluated in mpmath at 80 decimal digits
- precision: mpmath, 80 decimal digits
- published step: 2.000e-05; swept over factors [16.0, 8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625]
- independent zero support: structural stencil invariance, exact local affineness, and an independent recomputation at 200 decimal digits with step 2.000e-08
- normalization: D_hat_n = (d^n sigma / d eps^n) * strain_scale**n / stress_scale with stress scale 250.0 MPa (initial yield stress SIGY0 of the controlled J2 model) and strain scale 0.001 (characteristic strain-increment magnitude of the three J2 load steps)

### code_imp - NOT fully defensible

- rows: 96; admitted to Table 4: 95; withheld: 1
- **1 rows disagree with a resolved reference** - this is a discrepancy, not a reference-quality gap
- **primal stress diverges from the independently compiled original build**, so derivative comparisons on the affected increment are not statements about differentiation
- reference: independently compiled original code_imp UMAT replayed for each tensor-product centred finite-difference stencil node
- precision: IEEE double precision (compiled Fortran, gfortran)
- published step: 4.000e-05; swept over factors [16.0, 8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625]
- independent zero support: structural stencil invariance and exact local affineness at amplitudes 1.600e-04, 8.000e-05, 4.000e-05; the reference is a double-precision executable, so no higher-precision recomputation is available for this model
- normalization: D_hat_n = (d^n sigma / d eps^n) * strain_scale**n / stress_scale with stress scale 240.0 MPa (initial yield stress SIGY0 = 240 hard-coded at code_imp.f line 46) and strain scale 0.001 (characteristic strain-increment magnitude of the load path)

Withheld rows (1) - reported, not counted:

| Increment | Branch | Component | Order | Directions | Pattern | Classification |
|---:|---|---:|---:|---|---|---|
| 2 | inelastic | 2 | 2 | 1|2 | mixed | resolved |

Reason (first withheld row): 5 consecutive admissible steps from 2.500e-06 to 4.000e-05 agree to 9.66e-10 relative; the plateau is a genuine independent estimate and its own spread sets the agreement tolerance. 4 step(s) were excluded for leaving the nominal branch.

### UMAT_PCL - NOT fully defensible

- rows: 0; admitted to Table 4: 0; withheld: 0
- finding: The canonical order-4 transform of UMAT_PCL transforms and compiles cleanly, but the resulting executable aborts at run time with glibc 'double free or corruption (out)' (SIGABRT) during the transformed UMAT call.
- The ORIGINAL UMAT_PCL, compiled independently from the same file with the same driver and the same load path, runs to completion and returns a physically sensible stress. The abort is a property of the transformed build, not of the model or the load path.

### UMAT_PCLK - NOT fully defensible

- rows: 96; admitted to Table 4: 72; withheld: 24
- **24 rows disagree with a resolved reference** - this is a discrepancy, not a reference-quality gap
- **primal stress diverges from the independently compiled original build**, so derivative comparisons on the affected increment are not statements about differentiation
- reference: independently compiled original UMAT_PCLK UMAT replayed for each tensor-product centred finite-difference stencil node
- precision: IEEE double precision (compiled Fortran, gfortran)
- published step: 4.000e-05; swept over factors [16.0, 8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625]
- independent zero support: structural stencil invariance and exact local affineness at amplitudes 1.600e-04, 8.000e-05, 4.000e-05; the reference is a double-precision executable, so no higher-precision recomputation is available for this model
- normalization: D_hat_n = (d^n sigma / d eps^n) * strain_scale**n / stress_scale with stress scale 240.0 MPa (initial yield stress SIG0 = PROPS(3)) and strain scale 0.001 (characteristic strain-increment magnitude of the load path)

Withheld rows (24) - reported, not counted:

| Increment | Branch | Component | Order | Directions | Pattern | Classification |
|---:|---|---:|---:|---|---|---|
| 4 | inelastic | 1 | 2 | 1|1 | repeated | resolved |
| 4 | inelastic | 2 | 2 | 1|1 | repeated | resolved |
| 4 | inelastic | 3 | 2 | 1|1 | repeated | resolved |
| 4 | inelastic | 4 | 2 | 1|1 | repeated | resolved |
| 4 | inelastic | 1 | 3 | 1|1|1 | repeated | resolved |
| 4 | inelastic | 2 | 3 | 1|1|1 | repeated | resolved |
| 4 | inelastic | 3 | 3 | 1|1|1 | repeated | resolved |
| 4 | inelastic | 4 | 3 | 1|1|1 | repeated | resolved |
| 4 | inelastic | 1 | 4 | 1|1|1|1 | repeated | resolved |
| 4 | inelastic | 2 | 4 | 1|1|1|1 | repeated | resolved |
| 4 | inelastic | 3 | 4 | 1|1|1|1 | repeated | resolved |
| 4 | inelastic | 4 | 4 | 1|1|1|1 | repeated | resolved |
| 4 | inelastic | 1 | 3 | 1|1|2 | mixed | resolved |
| 4 | inelastic | 2 | 3 | 1|1|2 | mixed | resolved |
| 4 | inelastic | 3 | 3 | 1|1|2 | mixed | resolved |
| 4 | inelastic | 4 | 3 | 1|1|2 | mixed | resolved |
| 4 | inelastic | 1 | 4 | 1|1|2|2 | mixed | resolved |
| 4 | inelastic | 2 | 4 | 1|1|2|2 | mixed | resolved |
| 4 | inelastic | 3 | 4 | 1|1|2|2 | mixed | resolved |
| 4 | inelastic | 4 | 4 | 1|1|2|2 | mixed | resolved |
| 4 | inelastic | 1 | 2 | 1|2 | mixed | resolved |
| 4 | inelastic | 2 | 2 | 1|2 | mixed | resolved |
| 4 | inelastic | 3 | 2 | 1|2 | mixed | resolved |
| 4 | inelastic | 4 | 2 | 1|2 | mixed | resolved |

Reason (first withheld row): 7 consecutive admissible steps from 2.500e-06 to 1.600e-04 agree to 2.92e-07 relative; the plateau is a genuine independent estimate and its own spread sets the agreement tolerance. 2 step(s) were excluded for leaving the nominal branch.

### visco_imp - NOT fully defensible

- rows: 96; admitted to Table 4: 90; withheld: 6
- reference: independently compiled original visco_imp UMAT replayed for each tensor-product centred finite-difference stencil node
- precision: IEEE double precision (compiled Fortran, gfortran)
- published step: 4.000e-04; swept over factors [16.0, 8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625]
- independent zero support: structural stencil invariance and exact local affineness at amplitudes 1.600e-03, 8.000e-04, 4.000e-04; the reference is a double-precision executable, so no higher-precision recomputation is available for this model
- normalization: D_hat_n = (d^n sigma / d eps^n) * strain_scale**n / stress_scale with stress scale 10.0 MPa (hard-coded YIELD = 10 in visco_imp.f) and strain scale 0.01 (characteristic strain-increment magnitude of the load path)

Withheld rows (6) - reported, not counted:

| Increment | Branch | Component | Order | Directions | Pattern | Classification |
|---:|---|---:|---:|---|---|---|
| 2 | inelastic | 2 | 2 | 1|1 | repeated | reference_unresolved |
| 2 | inelastic | 2 | 4 | 1|1|1|1 | repeated | cancellation_limited |
| 2 | inelastic | 1 | 4 | 1|1|2|2 | mixed | cancellation_limited |
| 2 | inelastic | 2 | 4 | 1|1|2|2 | mixed | cancellation_limited |
| 2 | inelastic | 3 | 4 | 1|1|2|2 | mixed | cancellation_limited |
| 2 | inelastic | 1 | 2 | 1|2 | mixed | reference_unresolved |

Reason (first withheld row): The finite-difference sweep is at the zero threshold (normalized 7.335e-10) but nothing independent establishes the derivative as zero, so the reference cannot verify this row.

