# Reference LAPACK/BLAS OTI Port

## Status: incomplete, experimental

The target is the entire Reference LAPACK/BLAS Fortran library, including its
real, complex, and mixed-precision families. This is **not yet a usable OTI
LAPACK library**. The individually generated reference LAPACK objects are not
integrated into either derivative workflow. Separate, tested implementations of
the `DSPEVD`, `DGETRF`, and `DGETRS` interfaces are available as described below.

The current implementation supplies a reproducible source-port audit and
numerical regression tests for five double-precision BLAS kernels. It does not
replace unresolved LAPACK calls with stubs or calls into a real-valued binary.
Passing an OTI derived type to the ordinary real LAPACK ABI is invalid.

## Working DSPEVD Interface

Missing `DSPEVD` calls on the reachable stress path are now supplied automatically
in the Jacobian transformation and generic parameter-sensitivity transformation.
This includes a call inside another helper. Fixed- and free-form sources are
supported; an existing user definition is never replaced.

The implementation in
[spectral_definitions.py](../src/umat_oti/transform/spectral_definitions.py)
uses cyclic Jacobi rotations entirely in OTI arithmetic. It is an independent
implementation of the packed real-symmetric interface, **not** LAPACK's original
divide-and-conquer algorithm and not a derivative wrapper around a real binary.
It needs no external LAPACK/BLAS library. Its fixed 50 sweeps favor small material
tensors over large dense eigenproblems.

Supported contract:

- `UPLO='U'/'L'`, `JOBZ='V'/'N'`, ascending eigenvalues, column eigenvectors.
- Standard workspace minima and queries (`LWORK=-1` or `LIWORK=-1`), including
   empty and scalar matrices. Negative `INFO` identifies invalid arguments.
- Positive `INFO=1` reports nonconvergence; `INFO=N+1` refuses repeated or
   unresolved eigenvalues (adjacent normalized gaps <= `1e-12`, with normalization
   by the largest absolute input entry). **Callers must check INFO.** Outputs on
   failure are not valid derivatives. This refusal is stricter than real LAPACK.
- Input matrices must be finite. Invalid arguments return `INFO`; the built-in
   implementation does not call the external `XERBLA` handler.
- Each eigenvector's largest-magnitude component is made positive. Derivatives
   use that local sign convention; eigenvectors remain ambiguous at repeated
   eigenvalues and a sign convention need not be globally continuous.
- Automatic use is limited to derivative order one. Higher orders are refused
   until independently verified. This does not certify the rest of LAPACK.

Tests in [test_dspevd_oti.py](../tests/test_dspevd_oti.py) compile and link the
actual OTI solver, compare against NumPy eigenpairs and central finite differences,
and check differentiated eigen-equations. Coverage includes diagonal and rotated
matrices of sizes 1, 2, 3, 6, and 12, two simultaneous directions, scales from
`1e-200` through `1e200`, equal diagonals, workspace queries, invalid arguments,
and degenerate-spectrum refusal. Synthetic UMATs exercise the real transformation
pipeline in both source forms and compare the generated full 6x6 tangent against
independent finite differences. A separate PROPS-seeded test checks parameter
sensitivities against analytic eigenvalue derivatives.

```bash
python -m pytest -q tests/test_dspevd_oti.py
```

No private UMAT was used for these checks.

## Working LU Interfaces

Missing `DGETRF` and `DGETRS` calls are supplied automatically through the same
reachable-helper mechanism in the Jacobian and generic parameter-sensitivity
transformations, including with dependency discovery enabled. Existing source
definitions are preserved. Both fixed- and free-form inputs are tested.

[lu_definitions.py](../src/umat_oti/transform/lu_definitions.py) implements
unblocked Gaussian elimination with partial row pivoting and forward/backward
substitution, directly in OTI-liftable Fortran. These are independent reference
implementations of the interfaces, not the blocked Reference LAPACK algorithms.
They do not require an external BLAS/LAPACK library or a downloaded source tree.

- `DGETRF(M,N,A,LDA,IPIV,INFO)` supports rectangular matrices, in-place packed
   L/U factors, and one-based sequential row pivots. `INFO>0` reports the first
   zero primal pivot. Do not use singular factors to compute a solution.
- `DGETRS(TRANS,N,NRHS,A,LDA,IPIV,B,LDB,INFO)` supports multiple right-hand sides
   and `N`, `T`, or `C` (case-insensitive). For real matrices, `C` equals `T`.
   It overwrites B with the solution, leaving factors and pivots unchanged.
- Invalid arguments return the LAPACK argument position as negative `INFO`,
   without calling `XERBLA`. As an additional safeguard, `DGETRS` returns a
   positive diagonal index for singular factors instead of dividing by zero.
   Callers must check `INFO` from both routines and supply valid `IPIV` values.
- Empty dimensions, zero right-hand sides, padded leading dimensions, and
   zero-primal values carrying nonzero derivative seeds are supported.
- Inputs must be finite. Constant-factor rescaling protects the OTI divisions;
   numerical tests include systems scaled by `1e-200` and `1e200`. This is not
   an accuracy guarantee for ill-conditioned or overflow-prone systems.
- Pivot choices use primal magnitudes. Derivatives of the factors follow the
   selected pivot branch; no smoothness of factorization across pivot changes
   is promised. Singular systems have no supported solution derivative.
- Automatic fallback use is limited to derivative order one; higher orders
   are refused pending independent verification.

[test_lu_oti.py](../tests/test_lu_oti.py) checks rectangular factor reconstruction
and its derivatives, sequential pivots, normal/transpose solves, multiple RHS,
argument errors, singularities, and scaling. Solution derivatives are compared
both to central finite differences and to the independent identity
`dX = solve(A, dB - dA X)`, with transposed operators where appropriate.
Synthetic UMAT tests exercise dependency discovery and the generated 6x6 tangent
in both source forms. A PROPS-seeded test verifies all parameter sensitivities.

```bash
python -m pytest -q tests/test_lu_oti.py
```

The combined LU, eigensolver, helper-safety, sensitivity, dependency, and intrinsic
regressions passed 163 tests with GNU Fortran 8.5.0. No private JHU source was
opened or used, and no result here certifies a particular private UMAT.

## Pinned Public Input

- Upstream: <https://github.com/Reference-LAPACK/lapack>
- Release: `v3.12.1`
- Commit: `6ec7f2bc4ecf4c4a93496aa2fa519575bc0e39ca`
- Input must be a clean Git checkout at that commit, including no untracked files.
- Output must be a separate, new or empty directory.
- The upstream license and selected original source files, including notices,
  are retained in each output. Generated OTI support also depends on the
  GPL-licensed OTIlib components described in [the notices](../THIRD_PARTY_NOTICES.md).

No private UMAT or private helper source is needed by this workflow.

## Reproduction

Run from the repository root with Python >=3.10, the project installed, and
`gfortran` available. Download only once:

```bash
git clone --depth 1 --branch v3.12.1 \
  https://github.com/Reference-LAPACK/lapack.git out/lapack_reference_v3.12.1
python -m umat_oti.oti.lapack_port \
  --source-root out/lapack_reference_v3.12.1 \
  --out out/lapack_port_audit --compile
```

The full audit currently exits **1**, because some routines fail. The JSON report
is still written to `out/lapack_port_audit/port_report.json`. With `--compile`,
an exit status of 0 means only that the selected routines compiled individually;
without it, 0 means only that source emission succeeded. Neither means library
support or correct derivatives. Unknown names, an empty selection, conflicting
source choices, and source/provenance errors are not successes.

For a smaller reproducible numerical check:

```bash
UMAT_OTI_LAPACK_SOURCE="$PWD/out/lapack_reference_v3.12.1" \
  python -m pytest -q tests/test_lapack_port.py
```

Tests do not download anything. Integration tests explicitly skip when the public
checkout or compiler is absent; those skips are not evidence of support. To
generate only selected kernels, append
`--routines DAXPY DCOPY DDOT DSCAL DSWAP` to the audit command and use a fresh
output directory. `--directions` and `--order` control the generated OTI algebra;
the numerical evidence below covers only two directions and first order.

## Measured Evidence

With GNU Fortran 8.5.0, two OTI directions, order one:

| Routine-level audit status | Count |
| --- | ---: |
| Compiled, not numerically verified | 1,082 |
| Compilation failed | 1,118 |
| Emission failed | 31 |
| Source selection required | 47 |
| Total indexed routine names | 2,278 |

The inventory scans `SRC`, `BLAS/SRC`, and `INSTALL`. It includes optional and
alternate implementations; it is not a proof that every upstream build target
or module was recognized. Files without indexed routines are listed separately.
Top-level sources are preferred, with explicit upstream build choices for
`LSAME`, error handlers, machine constants, and the legacy NaN helpers.
Unresolved alternatives remain failures. Full CMake configuration, preprocessing,
host/module association, and optional/deprecated source selection are unfinished.

`DAXPY`, `DCOPY`, `DDOT`, `DSCAL`, and `DSWAP` pass 240 parameter combinations
against independently compiled, unmodified Reference BLAS. Tests compare primal
values and two central-finite-difference derivative directions. They exercise
empty vectors, lengths 1/3/7, unit/nonunit/negative strides, and scales 0/1/2.5.
Negative `DSCAL` strides retain upstream's no-operation behavior.

Two arithmetic shortcuts required explicit corrections: `DAXPY` at a zero scale
and `DSCAL` at a unit scale must not return early when the scale carries
derivatives. The port removes these exact pinned-source shortcuts and records
the changes. It also removes `INTRINSIC` declarations that conflict with generic
interfaces actually exported by the generated OTI support modules.

`DGEMM`, `DGETRF`, `DGETRS`, and `DSPEVD` now compile as individual objects.
**Their complete OTI call chains have not been linked or numerically verified.**
These are the reference-audit artifacts, not the independent working fallbacks
described above.
The audit lifts each routine separately; external calls may still target ordinary
symbols. Do not link these exploratory objects against a real LAPACK library.
All audit entries intentionally retain `numerically_verified: false`; separate
tests do not automatically certify generated outputs or other configurations.

## Remaining Acceptance Gates

1. Resolve the complete canonical upstream build, including modules and source
   variants, and audit every dependency in each OTI call chain.
2. Preserve callable interfaces and return types across the entire lifted call
   graph; link with no accidental real-valued arithmetic fallback.
3. Add complex OTI arithmetic, precision/kind handling, callback interfaces,
   modern Fortran module support, and missing intrinsic behavior.
4. Audit primal-dependent shortcuts, pivot choices, scaling, workspace queries,
   integer/status outputs, convergence criteria, and error paths.
5. Pass upstream primal tests plus independent derivative tests for all public
   routines, precisions, layouts, transposes, and supported derivative orders.
6. Define and test behavior at singular systems, pivot transitions, and repeated
   eigenvalues. Source overloading alone does not make these differentiable.
7. Package a closed reference library only after these gates pass. The independent
   `DSPEVD` interface above does not complete the reference-library port.