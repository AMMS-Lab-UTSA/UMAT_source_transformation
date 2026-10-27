# R1 (j2_voce_newton) transformed and verified at UMAT-OTI `2ae2ee0`: NEWLY GENERATED EVIDENCE

Builder: Ada, 2026-10-27. **Builder output. Numerically reviewed by Gauss (`reviews/gauss-r1.md`, no blocking finding); Curie and Vera have not reviewed it.** Task T4
names Gauss and Curie as reviewers and Vera as the independent check. No result here is in the
manuscript. Santiago decides whether R1 enters §3.5.

- UMAT-OTI commit: `2ae2ee07547ae86c5c4c9bb9fe123b1245c13dbc` (`origin/pipeline/library-routines`).
  See `refreeze/RECOMMENDATION.md`.
- R1 source: `evidence/replacement-models/j2_voce_newton/umat_j2_voce.f`, sha256
  `06902c55…149e`. It was used unchanged. The k-step variants below are generated copies in which only
  the PARAMETER line is altered.
- Platform: Windows 11 with MinGW-w64 GNU Fortran 16.1.0, Python 3.11.16, and the refreeze POSIX
  shim (`refreeze/scripts/posix_shim/`). This is **not** the Linux platform that UMAT-OTI declares.
- Material: E=200000, ν=0.3, σy0=250, H=1000, Q=150, b=20.

## Provenance check against the unresolved files (requested by the coordinator after Scout's report)
- R1 is **not** derived from `umatmst3.f` (the Abaqus/Dassault J2 example) or from any of the 20 imported
  sweep models. I compared its identifiers with `umatmst3.f`, recovered read-only from the clone at
  `a4a64c3^:UMATs/UMATs/ICP/umatmst3.f`. They share only `ONE`, `TWO` and `THREE`. R1 has none of that
  file's distinctive names (EBULK3, EG2, EG3, EFFG, EFFHRD, SMISES, SHYDRO, EELAS, EPLAS, FLOW, SYIELD,
  DEQPL, HARD, KEWTON). It also differs in structure: R1 returns along the trial-deviator norm with a
  closed-form Voce law, while umatmst3 uses SMISES with a tabular `UHARD` lookup. Script:
  `refreeze/scripts/r1/provenance_idcmp.py`. The umatmst3.f copy is not archived here, because it is not redistributable.
- R1's author statement (Quill, written from the textbook specification) is Quill's. I have not
  verified it independently. The identifier evidence supports it and does not prove it.
- **The verification references do not depend on any unresolved model.** They are: the README
  specification, a new Python implementation of that specification (`refreeze/scripts/r1/r1_verify.py`),
  a new Fortran driver (`refreeze/scripts/r1/r1_driver.f90`) and closed forms. No sweep model, no ICP or
  EAFIT file and no `j2_props.f` is used.
- Naming clash: Scout's report calls a human attribution fact "R1". In this file, R1 always means the
  replacement model.

## Results (from `r1_report.json`, `r1_tangent_rows.csv` and `r1_parameter_rows.csv`)
Revised 2026-10-27 after Gauss's review (`reviews/gauss-r1.md`, I-1, I-2, O-2–O-5). The numbers are
unchanged. Gauss reproduced them bit for bit. The wording, the norms and the explanations were corrected.

**Model.** R1 is **not** linear hardening. It has a Voce term:
σy = σy0 + H·EP + Q(1 − e^(−b·EP)), with Q = 150 and b = 20. The residual therefore has nonzero curvature,
r″ = −Q b² e^(−b·EP), and a single Newton step is not exact.

**Paths.** Every "uniaxial" path is **uniaxial (confined) strain**: only ε11 is nonzero, and the other strain
components are held at zero. This produces a pressure of about 3.3 GPa. That is irrelevant to the
pressure-independent J2 model, but these paths are not a tension test. The paths are:

| Path | Increments | Plastic |
|---|---|---|
| `uniaxial_strain` (confined, Δε11 = 2e-4) | 30 | 22 |
| `multiaxial_nonproportional` | 23 | 9 |
| `large_increment_multiaxial` (Δε = (5e-3, −1e-3, 0, 4e-3, 0, 0)) | 4 | 4 |
| `hydrostatic` | 5 | 0 |
| `check_path` (confined uniaxial strain, ±2 % cyclic) | 40 | 37 |

**Norms.** Each number below names its norm.
- **N1 (matrix max-norm)**: max|A−B| / max|B| over one 6×6 matrix or stress/EP vector. This hides the
  relative error of small entries.
- **N2 (per-entry)**: |a−b| / |b_ref|, with the complex-step value as b_ref, or with the closed form
  where stated.

The worst case is reported with its path and increment. Tangent maxima include elastic increments, where
the comparison is trivially exact. The binding cases are plastic.

| Check | Norm | Worst (where) |
|---|---|---|
| Primal parity, transformed vs untransformed (stress, EP) | N1 | 2.8e-15, check_path inc. 40. This is **agreement to round-off**, not bitwise (about 10 ulps, likely from the OTI intrinsics). Python and untransformed Fortran agree exactly |
| DDSDDE (OTI) vs Eq. T (numpy) | N1 | 6.2e-16, uniaxial (confined) inc. 16 |
| DDSDDE (OTI) vs hand-coded DDSDDE in R1 | N1 | 6.2e-16, uniaxial (confined) inc. 16. The hand-coded tangent vs Eq. T: 2.8e-16, check_path inc. 28 |
| DDSDDE (OTI) vs complex step of the Python implementation | N1 | 8.6e-16, check_path inc. 12 |
| DDSDDE (OTI) vs central FD of the untransformed build | N1 | best step per increment ≤ 7.8e-11, check_path inc. 12 (h = 1e-8). Step sweep, worst over plastic increments for each h. The worst comes from **different increments for different h**: h = 1e-4…1e-7 give 5.4e-4, 5.4e-6, 5.4e-8, 5.4e-10, all at multiaxial inc. 13, so O(h²) with a coefficient of about 5.4e4·h². The floor at h = 1e-8 is 1.4e-10, at large-increment inc. 4, consistent with round-off at stresses of about 3e3 MPa. Round-off grows at h ≤ 1e-9. h = 1e-3 (0.18) straddles the yield kink and is pre-asymptotic, so it is not part of the O(h²) range |
| DSIGMA_DP / DSTATEV_DP (provider from `umat-oti check`) vs closed form for monotone confined uniaxial strain (EP solves 2Gε − 3G·EP − σy(EP) = 0) | N2 (closed form) | 9.2e-15 over 180 entries, increments 1–10, worst DSTATEV_DP ∂EP/∂ν at inc. 9 |
| Same vs complex step of the Python implementation, whole history | N2 (CS) | 1.2e-12 over 1680 entries, worst ∂σ22/∂ν at inc. 20 (value −2.89). This is cancellation against stresses of about 3.3e3 MPa, not a defect (Gauss O-3). DSTATEV_DP worst is 1.0e-14 |
| Same vs central FD of the untransformed build, relative step 1e-2…1e-9 | N2 (CS scale) | best step per entry ≤ 8.3e-9, worst ∂σ22/∂E at inc. 20 |
| UMAT-OTI's own check (`umat-oti check`, FD of the original) | tool's rule | 2640 agree, 3360 zero in both, 0 disagree, worst 7.3e-10 |
| Internal Jacobian (UMAT-OTI probe, all 11 stages succeeded) | scalar relative | confined uniaxial strain, inc. 30, DGAM = 1.31e-4: OTI −234601.99278664890 vs −3G−H′ = −234601.99278664892 (1.2e-16); FD −234601.9927867112. This validates UMAT-OTI's **extraction**. The reference is the same expression as R1's own DRES, so it is not an independent derivative |

### Tangent through a truncated Newton solve (I-1)
The variants perform exactly k Newton updates and have no tolerance test. For every k, the OTI tangent
equals the derivative of the executed k-step map (complex step of the same k-step Python, N1 ≤ 4.9e-16).
Its gap to Eq. T at the converged solution (N1, worst over plastic increments) is:

| Path | k=1 | k=2 | k≥3 |
|---|---|---|---|
| large increment (DGAM* ≈ 4.3e-3) | 4.3e-4 | 1.9e-10 | ≤ 3.1e-16 |
| uniaxial (confined), 2e-4 (DGAM* ≈ 1.3e-4) | 1.4e-5 | 7.9e-15 | ≤ 6.2e-16 |
| multiaxial non-proportional | 1.4e-5 | 3.3e-14 | ≤ 2.4e-16 |

Explanation (Gauss I-1): the derivative error lags the iterate error. The Newton map N(x, ε) = x − r/r_x has
r_x independent of ε. The derivative recursion D_{k+1} = N_x·D_k + N_ε therefore gives
δD_{k+1} ≈ (r_xx/r_x)·e_k·δD_k + O(e_k²). The starting guess DGAM = 0 carries no derivative, so δD_1 is of
first order in DGAM*. Gauss predicts 5.6e-4 / 2.7e-10 (large increment) and 1.9e-5 / 1.0e-14 (uniaxial),
against the observed 4.3e-4 / 1.9e-10 and 1.4e-5 / 7.9e-15. For k ≥ 3 the predicted gap is below round-off.
**Control (Gauss):** the same k-step OTI builds with QSAT = 0 (pure linear hardening) on the large-increment
path give 3.1e-16 at both k=1 and k=2. One step is then exact, as theory requires.
My metric compares against Eq. T on the converged history and so mixes history drift into the gap.
Measured from the same incoming state, Gauss finds 4.39e-4 / 1.89e-10, so the drift is negligible. R1's own
tolerance rule takes 3–4 updates on these paths.

### Hydrostatic increments (I-2)
The trial deviator is **not exactly zero**. In IEEE arithmetic it is round-off: 5.7e-14, 1.1e-13, 2.3e-13,
0 and 5.7e-14 MPa at increments 1–5 (Gauss, gfortran -O1). The OTI √0 case is therefore reached only at
inc. 4. On the elastic branch, the derivative of SNORM feeds only QTR/PHI and the branch test. It never
reaches STRESS or DDSDDE. "All transformed outputs finite, DDSDDE = elastic matrix" therefore shows only
that the **unused elastic-branch value does not leak**. It is **not** evidence that the OTI square root is
safe at a zero argument, and it must not be cited as such.

## Limitations
- Material-point only. No Abaqus run: the local Abaqus licence was in use by other jobs, and this task
  excluded ARC.
- Parameter sensitivities were exercised on confined uniaxial strain (one fixed deviatoric direction)
  only. Multiaxial parameter sensitivities were not run. PNEWDT (the non-convergence branch) is never
  exercised.
- No state lies near the yield tie (smallest |φ_trial|/σy0 = 1.5e-2). Gauss probed the tie separately and
  found a clean switch (not archived here).
- Independence: Eq. T, R1's hand-coded DDSDDE and my Python all derive from the same README. Their mutual
  agreement is not independent evidence. The independent legs are FD of the Fortran, complex step, and
  Gauss's tensor-form derivation and code.
- Windows plus shim, not the declared Linux platform. One set of material constants.
- I found and fixed an FD-driver defect during this work: the DDSDDE output overwrote earlier FD columns.
  Every number above comes from the fixed driver.

## Reproduce
```
bash refreeze/scripts/run_candidate.sh 2ae2ee0 install
cd refreeze/wt/2ae2ee0 && ../../venv/2ae2ee0/Scripts/python.exe umat-oti check \
  ../../../evidence/2ae2ee0/r1/input/umat_j2_voce.f \
  --props "YMOD=200000 PNU=0.3 SIGY0=250 HLIN=1000 QSAT=150 BSAT=20" --peak 0.02 \
  --out ../../../evidence/2ae2ee0/r1/check
cd ../../.. && PYTHONHASHSEED=0 refreeze/venv/2ae2ee0/Scripts/python.exe refreeze/scripts/r1/r1_verify.py --commit 2ae2ee0
```
