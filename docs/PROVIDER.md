# Compiled OTI provider

This is the reference for the compiled provider: the relocatable object that
carries a UMAT's parameter sensitivities to the companion
[Residual Assembler](https://github.com/AMMS-Lab-UTSA/Residual_Assembler). It
is written for material developers who build a provider and for integrators
who link one. The step-by-step GUI route is described in [GUI.md](GUI.md).

## What the provider is

The build takes the author's original UMAT and a `resasm_umat_transform_v2`
contract. It lifts the UMAT with the current generic parameter-sensitivity
transformer, which needs no model-specific code. The original routine and the
lifted routine are compiled separately and bundled into one
position-independent object, together with explicit small-strain replay
wrappers.

A collaborator receives the object and its completed mapping, never the
source. The files that are handed over are:

| File | Content |
|---|---|
| `OTI_UMAT.obj` | the provider: the original routine plus the differentiated one |
| `Mapping.json` | the completed contract the build generates, unchanged |
| `REAL_UMAT.obj` (optional) | the original UMAT compiled unchanged, for ordinary Abaqus runs |
| `transform_report.txt` | build and verification commands, exit codes and results |

`python -m umat_oti.provider.collaborator` (and the GUI's Parameter
Sensitivities screen) produces exactly these four files; see
[GUI.md](GUI.md#parameter-sensitivities).

**Verified scope.** Linux with gfortran. The independent verifier's full
results are recorded below for `m3_j2` and `m6_fcc`, and the elastic model
`m1_elastic` is checked by the same commands. Compiling another source is not
evidence that it is physically valid.

## Build

With the package installed, the build needs only the contract, the source it
names and `gfortran`:

```sh
umat-oti-provider build path/to/model/contract_v2.json --out out/provider
umat-oti-provider build path/to/model/contract_v2.json --out out/provider \
  --regular-object REAL_UMAT.obj [--abaqus-toolchain]
```

From a source checkout the same command is available as a module:

```sh
python -m umat_oti.provider build \
  parameter_sensitivity/models/m3_j2/contract_v2.json --out out/m3_j2
```

Use a dedicated output directory outside the model directory. For the J2 model
the build writes:

- `umat_m3_j2_oti.obj`, the provider object;
- `umat_m3_j2_oti.json`, the completed contract (`resasm_umat_oti_contract_v1`);
- a unique `build-*` subdirectory holding the generated sources and the
  link-check shared library, kept for diagnosis.

The command prints the absolute paths of `object`, `contract` and `build_dir`
(and `regular_object` when one was requested).

**Reproducible objects.** Every file is compiled on a relative name from inside
its build directory. gfortran writes the name it was given into bounds-check
messages, and gfortran 9 does not remap it. The objects therefore contain no
directory of the developer's, and rebuilding the same contract reproduces them
byte for byte.

**Regular object.** `--regular-object REAL_UMAT.obj` also publishes the
original UMAT compiled unchanged, with the same compiler and flags as the
bundled copy. With `--abaqus-toolchain` that object is built by `abaqus make`
(the Abaqus site compiler and flags) instead. Its SHA-256 is recorded in the
contract under `regular_object`.

**Locals read before they are assigned.** A UMAT that can read a local before
any statement sets it has undefined behaviour there (a plasticity model that
sets its plastic-strain increment only inside its Newton loop, and adds it to
the state on every call, is the example). The build names each such local
(`build.reads_before_assignment` in the contract, and on standard error),
starts it at zero on entry to the lifted routine, and compiles the original
with the same statement at its entry (`build.original_entry_statements`; the
regular object's `role` says so and `compiled_source_sha256_full` is the digest
of what was compiled). The source file is not changed. The analysis is a data flow over the UMAT routine only; a bare CALL argument counts as assigned and an array is reported only when no element can have been set, so the equivalence with `-init=zero` holds for the reported locals, not for every read. `--zero-init-locals`
(every local zero in every build, by compiler flags) is still accepted.

**Library routines (LAPACK and BLAS).** A UMAT may call routines Abaqus links
in from its MKL. umat-oti supplies bodies, and so OTI copies, for DGESV,
DGETRF, DGETRS, DGETRI, DSYEV, DSPEVD, DGEMM, DGEMV, DCOPY, DSCAL and DAXPY,
and for the functions DDOT and DNRM2; a call to or reference of any other
LAPACK/BLAS routine or function (DPOTRF, DASUM, DLAMCH, ...) on the derivative
path is refused at transform time with its name, and a provider whose original
calls one is not built (it could not link on its own). A function is
referenced in expressions, so the source is read with the supplied function
bodies appended after its last line (no line number moves): DNRM2(NTENS,B,1)
is then a call of a function the file defines, not an element of an
undeclared array.

*No standard name is ever defined by a generated object.* Measured on Abaqus
2021: the user-subroutine library is loaded as a dependency of the solver's own
libraries and sits before MKL in the process's global symbol scope (position 31
against 66), and the solver's libABQSMABlaModule.so imports dgesv_, dgetrf_,
dgetrs_, dgemm_, dgemv_, dsyev_ and dpotrf_. A dgesv_ defined in the user
library would be the one every caller in the solver gets. So:

- the transformed UMAT (`<name>_oti.f`, `<name>_oti_combined.f90`) keeps its
  real calls (`CALL DGESV`) for the host library -- MKL inside Abaqus, exactly
  what the original calls there -- and calls private OTI copies
  (`UMATOTI_DGESV_OTI`, ...) for the differentiated ones; the supplied real
  bodies are removed from the emitted file;
- inside the provider object the bundled original's calls are renamed to
  private real twins (`UMATOTI_DGESV_R`, ...; `objcopy --redefine-sym`), each
  compiled with its whole chain (`UMATOTI_DGESV_R` calls `UMATOTI_DGETRF_R`);
  the mapping records them under `build.library_routines`. The regular object
  keeps the original's own calls for the host's library;
- a standard name the AUTHOR defines (a DGETRF of their own) is transformed
  exactly like any helper of the author's, under its own name, and renamed with
  every reference to it in what is written: `UMATOTI_AUTH_DGETRF` in the
  transformed file and its helpers, and by `objcopy` in the provider's bundled
  original and in the regular object (the provider's lifted copy is a module
  procedure and exports no standard name). The transform report records it
  (`author_library_definitions_renamed`), and so does the provider contract
  (`build.library_routines.author_definitions_renamed`). The author's own calls
  still reach the author's routine; a library routine the author calls and does
  not define keeps the library's whole chain, so the supplied DGESV calls a
  supplied DGETRF (under the private name `UMATOTI_DGETRF` when the author
  defines DGETRF), not the author's. That is what Abaqus does: measured, an
  author's DGETRF linked beside MKL's DGESV is not called by it (beside
  reference LAPACK 3.9.0 it is: an executable linked plainly against it runs
  the author's DGETRF inside DGESV). So every stand-alone build umat-oti makes of
  such a source links MKL or the twins, whose chains call private names only,
  never another library: the original's reference build, the gate's replays and
  the routine-level harness compute what Abaqus and the transformed code compute
  on any host (tested with `UMAT_OTI_LAPACK=reference` forced).

*The twins follow reference LAPACK.* DGETRF/DGETRS/DGESV give the same bits as
the reference LAPACK on random, ill-conditioned, singular and pivoting cases
(`tests/test_library_routines.py`): the first largest pivot, INFO = the first
exactly-zero pivot with the factorization completed, the reciprocal scaling of
DGETRF2, DTRSM's loop orders, and no INFO from DGETRS for a zero diagonal. Each
division is first brought into [2^-166, 2^166] by powers of two, which is exact
in real arithmetic and keeps the OTI copy's derivative parts finite (the OTI
algebra divides as x*y^-1). The BLAS bodies give reference BLAS's bits; DGETRI
inverts by solves and DSYEV uses the cyclic Jacobi DSPEVD, so those agree with
LAPACK to rounding (eigenvectors up to sign). The OTI copies' real parts agree
with the real twins to a few ulps; their derivatives agree with central
differences and the complex step.

*Where MKL and reference BLAS disagree, the twins follow MKL*, the library the
original runs with inside Abaqus. Measured with MKL 2023.2 against reference
BLAS 3.9.0 over increments 1, 2, -1, -2 and 0, N <= 0, and invalid leading
dimensions and options: DNRM2 computes the norm for INCX < 0 (as LAPACK 3.10 and
later do) and for INCX = 0 (N copies of X(1)), where reference BLAS returns
zero; DSCAL scales X(1), X(1+|INCX|), ... for INCX < 0 and X(1) N times for
INCX = 0, where reference BLAS does nothing; DGEMV and DGEMM leave their output
alone for an invalid argument, as both do. DDOT, DAXPY, DCOPY and the rest agree
for every increment. A UMAT taking the norm with INCX = -1 transformed silently
to a stress that differed from the original's inside Abaqus. MKL's arithmetic
differs from reference BLAS's in the last bits even for unit increments (fused
multiply-adds, reordered sums), so the twins agree with MKL to a few ulps, not
bit for bit (`test_the_twins_follow_mkl_for_every_increment_and_invalid_argument`).

*Stand-alone builds link a real LAPACK.* The verifier's reference, the
six-check gate's offline replays and the routine-level harness link the host's
library (`umat_oti.core.host_lapack`: oneAPI MKL, else OpenBLAS, else the
reference LAPACK, found through `ldconfig` -- on PATH, or in /sbin or
/usr/sbin -- and by reading the standard library directories;
`UMAT_OTI_LAPACK` overrides) and record which, with its version (MKL's
`mkl_version.h`, the library files the link resolves to, and the LAPACK
version the library reports through ILAVER): `reference_lapack` in
`verification.json`, `lapack` in each build record. The twins are compiled in
only where no library links, in every REAL(16) build, and, when the host
library is not MKL, where the source defines a standard name itself or calls
DNRM2 or DSCAL (whose results for INCX <= 0 differ from MKL's). Abaqus's own
bundled MKL is not used outside Abaqus.

*Literals and expressions.* A literal or an expression handed to a library
routine (`CALL DGEMM('N','N',6,6,6,1.0D0,...)`) is given the OTI type in the
provider's lifted code as in the transformed UMAT: `(1.0D0) - 0.0D0*E1`, the
same value with zero derivative parts.

*Licence.* The supplied bodies follow Reference LAPACK/BLAS (BSD-3-Clause);
THIRD_PARTY_NOTICES.md, section 5, lists them. Every generated file that holds
one starts with the notice, and a provider contract whose object holds them
records it under `build.library_routines.licence`.

**Hashes and status.** `object.sha256` holds the legacy 16-character SHA-256
prefix; `object.sha256_full` holds the full digest. The build runs a
no-undefined-symbol shared-library link check but leaves
`validation.passed=false` and `validation.status="not_run"`. Only the verifier
below can establish that the object is correct.

**Accepted contracts.** The build refuses, with a diagnostic, any contract that
is not all of the following:

- schema `resasm_umat_transform_v2` with `kinematics: "small_strain"`;
- `NTENS = 6` and `NPROPS >= 1`;
- a first-order derivative of `STRESS` with respect to `PROPS` (`DSIGMA_DP`);
- parameters with unique names and unique PROPS indices;
- `history.path_dependent = true` whenever there are physical state variables;
- a single source file (`main_file`) whose entry point is `UMAT`.

## Verify

```sh
python -m umat_oti.validation.parameter_sensitivity_provider \
  parameter_sensitivity/models/m3_j2/contract_v2.json --out out/m3_j2_verified
```

The verifier rebuilds the object and separately compiles the ORIGINAL UMAT with
the existing reference driver. It writes `verification.json` and
`verification_entries.csv`. On success `passed=true`, and the report carries the
object digest, the exact properties and path, comparison counts, step sizes and
measured errors. On failure the command exits non-zero and writes
`passed=false` with the diagnostic; a failure is never turned into a warning.

**Primal tolerance.** The provider's stress and state are compared with the
original's reference build entry by entry with rtol = 1e-12 and an absolute
tolerance of 1e-12 times the largest magnitude of that array over the run,
never less than 1e-10 (stress) or 1e-14 (state), the fixed values used before
(`primal_tolerance` in `verification.json`). A fixed absolute tolerance does
not scale with the stress: a component that cancels to about zero carries the
rounding of the large terms it was computed from, about 1e-15 of the largest
stress, which for stresses of order 1e5 is above 1e-10, and valid providers
were rejected for it.

**Check path.** The path comes from the contract's `validation.check_path`,
in one of two forms:

- `{"increments": [[...six strain components...], ...]}`, or
- `{"dstran_per_increment": [...], "n_increments": N}` (the form
  `parameter_sensitivity/loading_paths.json` uses).

Each row is a strain increment in Voigt order with engineering shear, applied
over a unit time step. A contract without the field, such as the shipped
`m3_j2` contract, is checked on the provider's seven-increment J2 path:
elastic, elastic, plastic, plastic, elastic unloading, reverse plastic, elastic
unloading. Properties come from the contract (`[210000, 0.3, 250, 2000]` for
`m3_j2`), never from invented defaults.

**Primal parity.** The provider's stress and state must match the separately
compiled ORIGINAL to round-off: stress `rtol=1e-12, atol=1e-10`, state
`rtol=1e-12, atol=1e-14`.

**Derivatives.** Every derivative entry (DSIGMA_DP, DSTATEV_DP and DDSDDE,
from both EVAL and MARCH) is judged against centred differences of the
separately compiled ORIGINAL. The differences are taken over the project's
half-decade step ladder (`reference_resolution.DEFAULT_LADDER`, 1e-2 to 1e-7).
Parameter steps are relative to the parameter's own value; strain steps are
relative to the increment's largest component. Parameter perturbations replay
the whole path; tangent perturbations change only the last increment of each
prefix. Unless `--elastic` is given, the verifier requires the J2 branch
sequence (elastic, plastic and unloading increments) and leaves out any step
that moves an increment onto another branch.

The reference value is `reference_resolution.converged_value`: the flattest
three-step window, or its Richardson extrapolation where that is tighter. Its
uncertainty is the largest of the window's spread, the Richardson residual, the
next finer step's distance from the estimate, and the cancellation floor
`eps*|response|/(2h)`. Each entry is then one of:

- **agrees**: the reference determines the entry to within the relative
  tolerance `2e-6`, and the value is within that tolerance;
- **consistent with zero**: both the value and the reference are within the
  reference's uncertainty of zero;
- **reference unresolved**: the value is within the reference's uncertainty,
  but that uncertainty is wider than the tolerance. This is never counted as a
  pass;
- **disagrees**: the value is outside both the reference's uncertainty and the
  tolerance.

A column *agrees* when at least one entry agrees and none disagrees. It is
*unresolved*, with its reason, when no entry is determined. Verification fails
on any disagreeing entry, or on an array with no agreeing column. Otherwise the
verdict is `verified`, or `verified_with_unresolved_columns` with each such
column and its reason listed.

**Measured (2026-09-18).**

- `m3_j2` on the J2 path: verified, every column agrees; 628 entries agree,
  240 are consistent with zero, none unresolved; worst relative error 4.8e-10;
  primal parity 5.7e-14.
- `m6_fcc` at the ten reference parameter values listed in
  [GUI.md](GUI.md#parameter-sensitivities), on tension with shear (20
  increments of `1e-4` in 11 and `1e-4` engineering shear in 12): verified,
  every column of all ten parameters agrees. On the sweep's uniaxial path the
  C44 column is unresolved: uniaxial strain along a cube axis puts no shear
  stress on the crystal, so that derivative is zero along the path.

**Elastic example.** `m1_elastic` uses the same commands with the verifier flag
`--elastic`. Stateless EVAL is checked at total strain from zero stress; MARCH
is checked incrementally. The distinction matters because a 16-argument EVAL
cannot carry derivatives of the incoming stress.

## Object ABI

The gfortran symbols are `umat_`, `umat_oti_internal_`, `umat_oti_eval_`,
`umat_oti_eval_total_` and `umat_oti_march_`. Public replay arguments are double
precision arrays and scalars and default INTEGER dimensions, passed by
reference. Arrays use Fortran column order. Voigt order is `11,22,33,12,13,23`,
with engineering shear strains. Link one material object per shared library
using gfortran: the object bundles the OTI runtime, but the linked library still
needs the Fortran runtime.

### `UMAT_OTI_EVAL`

For path-dependent contracts (such as J2), EVAL has exactly 18 arguments:

```fortran
SUBROUTINE UMAT_OTI_EVAL(STRESS,STATEV,DDSDDE,STRAN,DSTRAN, &
  TIME,DTIME,TEMP,DTEMP,PROPS,NPROPS,NTENS,NSTATV,NPARAM, &
  DSIGMA_DP,DSTATEV_DP,DSIGMA_DP_IN,DSTATEV_DP_IN)
```

- `STRESS(NTENS)` and `STATEV(NSTATV)` are the incoming and outgoing physical
  values.
- `DDSDDE(NTENS,NTENS)` is the lifted stress derivative with respect to the
  current `DSTRAN`, at fixed incoming stress, state and strain history. It is
  extracted from extra strain directions, not taken from the author's tangent.
- `DSIGMA_DP(NTENS,NPARAM)` and `DSTATEV_DP(NSTATV,NPARAM)` are separate
  outputs. The incoming arrays of the same shapes seed the full chain rule
  through the lift. Pass distinct incoming and output buffers. Derivatives
  never occupy physical SDVs.
- `STRAN` is the strain at the start of the increment; `TIME(2)` is step and
  total time.
- For J2, `NPROPS=4, NTENS=6, NSTATV=1, NPARAM=4`. The parameter columns are
  `E, nu, SIGY0, H` in contract order. Parameters occupy OTI directions 1-4;
  the six local strain tangent directions occupy 5-10.

Stateless contracts emit the legacy 16-argument EVAL signature, which omits the
two incoming derivative arrays; their incoming parameter sensitivities are
zero. `history.path_dependent=true` selects the 18-argument form even when there
are no physical state slots. Any physical state requires the path-dependent
form.

### `UMAT_OTI_MARCH`

MARCH has exactly 11 arguments for both variants:

```fortran
SUBROUTINE UMAT_OTI_MARCH(PROPS,NPROPS,PATH,NPATH,DTARR, &
  NTENS,NSTATV,NPARAM,DSIG,STROUT,DDOUT)
```

`PATH(NTENS,NPATH)` holds the strain increments and `DTARR(NPATH)` the positive
time steps. `DSIG(NTENS,NPARAM,NPATH)` and `DDOUT(NTENS,NTENS,NPATH)` hold every
increment's derivatives and tangent; `STROUT(NTENS)` is the final stress. MARCH
starts from zero physical state, stress and strain, carries the stress and
state parameter derivatives, advances both time values and KINC, and recreates
the local strain directions at each increment. Its ABI has no state output; use
EVAL for physical and derivative SDVs.

### Other symbols

- `UMAT` is the author's untransformed, standard Abaqus entry point.
- `UMAT_OTI_EVAL_TOTAL` returns total derivatives for whole-model history
  replay; it is described in [PROVIDER_EVAL_TOTAL.md](PROVIDER_EVAL_TOTAL.md).
- `UMAT_OTI_INTERNAL` is a private kernel with the 18 EVAL arguments plus an
  integer increment. It is **not** the old scratch-SDV internal UMAT interface;
  consumers must use EVAL, EVAL_TOTAL or MARCH.

## Loading the object in the Residual Assembler replay

`umat_oti.provider.legacy_check` checks that a verified provider loads in the
Residual Assembler's `PathMaterial` replay:

```sh
python -m umat_oti.provider.legacy_check out/m3_j2_verified/verification.json \
  --repo ../Residual_Assembler
```

It reads the replay code from a Residual Assembler checkout at the git
reference given by `--ref` (default `origin/cross-platform-hardening`) without
checking it out or editing it. It exports that replay code into the
verification directory, loads the generated object through `PathMaterial`, and
requires `has_march=true`. It then compares both replay methods with finite
differences of the bundled ORIGINAL UMAT through `march_regular`, and writes
`legacy_verification.json` with the commit and the errors. No mock material or
shim replaces the consumer.

In an environment where the Residual Assembler is importable:

```python
import json
from pathlib import Path
from residual_core.replay.path_material import PathMaterial

output = Path("out/m3_j2_verified")
contract = json.loads((output / "umat_m3_j2_oti.json").read_text())
verification = json.loads((output / "verification.json").read_text())
material = PathMaterial(str(output / contract["object"]["file"]), contract)
increments = verification["path"]
times = [1.0] * len(increments)
full = material.march_oti(verification["props"], increments, times)
fast = material.march_fast(verification["props"], increments, times)
assert material.has_march
assert full[-1]["dsigma_dp"].shape == (6, 4)
assert full[-1]["dstatev_dp"].shape == (1, 4)
```

Use `PathMaterial` for J2, not the older stateless `objlink` C-ABI adapter.

## Limits

- Only three-dimensional, small-strain, first-order STRESS/PROPS contracts are
  accepted. Finite strain, other tensor dimensions, higher orders, alternative
  derivative-request schemas, extra source files and non-UMAT entry points are
  refused with a diagnostic.
- The legacy EVAL ABI has no KINC argument (it uses 1), and no deformation
  gradients, coordinates, rotations, characteristic length, energy history,
  predefined fields or cutback return. The wrappers use identity gradients and
  rotation, zero coordinates, predefined fields and energies, and unit length.
  MARCH uses a temperature of 293.15 with no temperature increments. Models that
  need other context are not established by these checks; J2 and the tested
  elasticity do not depend on it. `UMAT_OTI_EVAL_TOTAL` passes COORDS, CELENT,
  NOEL, NPT, KSTEP and KINC through and returns PNEWDT.
- In EVAL and MARCH, dimension errors, non-positive MARCH time steps and UMAT
  cutback requests stop the program with Fortran `ERROR STOP`; that ABI has no
  status return. Validate dimensions before calling, and run untrusted material
  evaluation in a separate process.
- Only Linux with gfortran has been exercised. Objects are platform- and
  compiler-specific; Windows, other Fortran compilers and binary distribution
  compatibility are unverified.
- The provider is a Fortran object only. There is no C `mat_eval_v1` library
  and no `.resmat` package.
- `umat-oti-provider` (`umat_oti.provider.build:main`) is a registered console
  script and has been exercised from a fresh wheel installation; the
  `python -m umat_oti.provider` entry point remains available.
