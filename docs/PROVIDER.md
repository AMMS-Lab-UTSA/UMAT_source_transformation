# Compiled OTI Provider

This provider restores the legacy Program 1 relocatable-object interface using
the **current** generic parameter-sensitivity transformer. It does not copy the
old regex-based inference or reimplement J2. The original author UMAT and the
generic OTI lift are compiled separately and bundled into one position-independent
object, with an explicit small-strain replay wrapper.

Verified scope: the repository's `m3_j2` and `m1_elastic` contracts on Linux with
gfortran. Compilation of another source is not evidence of its physical validity.
The subsequent working-tree wheel gate also builds m3_j2 using the installed
`umat-oti-provider` command and copied public inputs, then consumes its binary
through the installed Residual Assembler. See
[evidence/recovery_install.md](evidence/recovery_install.md) for installation,
installed GUI launch, exact gate commands, evidence and remaining failures.
This is not a final-branch clean-clone verification or a corpus pass.

## Build and Verify

After wheel installation, the provider command needs only the developer's
contract/source inputs and gfortran, not a repository import path:

```sh
umat-oti-provider build /path/to/public_model/contract_v2.json --out /tmp/new_provider
```

The collaborator receives the generated object and completed mapping, not the
source. The presentation request does not run the provider build command.

From the recovery repository root, using the supplied development environment:

```sh
export PYTHONPATH="$PWD/src"
PY="${PY:-python3}"
"$PY" -c 'import umat_oti,sys; print(sys.executable); print(umat_oti.__file__)'
"$PY" -m umat_oti.provider build \
  parameter_sensitivity/models/m3_j2/contract_v2.json \
  --out /tmp/imq-recovery-W3-j2
"$PY" -m umat_oti.validation.parameter_sensitivity_provider \
  parameter_sensitivity/models/m3_j2/contract_v2.json \
  --out /tmp/imq-recovery-W3-j2-verified
```

The build command prints absolute paths for `object`, `contract`, and `build_dir`.
It emits `umat_m3_j2_oti.obj` and `umat_m3_j2_oti.json`. Generated sources and the
link-check shared library are retained in a unique `build-*` subdirectory for
diagnosis. Use a dedicated output directory outside the original model directory.
The output JSON describes `resasm_umat_oti_contract_v1` and uses the legacy
16-character SHA-256 prefix in `object.sha256`; `object.sha256_full` adds the full
digest. Building runs a no-undefined-symbol shared-library link check, but leaves
`validation.passed=false` and `validation.status="not_run"`.

The verification command rebuilds the object, separately compiles the ORIGINAL
UMAT with the existing reference driver, and writes `verification.json`. Success
has `passed=true`, the object digest, exact properties/path, comparison counts,
FD step sizes, plateau checks, and measured errors. Failure exits nonzero and
writes `passed=false` with the diagnostic; it is not converted to a warning.

The J2 path contains seven increments: elastic, elastic, plastic, plastic,
elastic unloading, reverse plastic, elastic unloading. Properties come from the
input contract: `[210000, 0.3, 250, 2000]`, not invented defaults. The FD sweep
uses parameter steps `h * max(abs(p), 1)` for `h = 1e-4, 3e-5, 1e-5` and strain
steps `1e-6, 1e-7, 1e-8`. Parameter perturbations replay the entire ORIGINAL path;
tangent perturbations change only the last increment of each prefix, keeping its
incoming history fixed. Perturbations must preserve the nominal J2 branch.
Every step is checked, not just the best step. Error scales are the maximum
reference magnitude per parameter column over the path, or per increment for
the tangent, with a `1e-12` floor. The limit is `2e-6`; the last two FD estimates
must also agree to that limit. This is a scaled-array error, not a per-entry
relative error near zero.

The additional elastic example uses the same commands with `m1_elastic` and the
verification flag `--elastic`. Stateless EVAL is checked at total strain from
zero stress; MARCH is checked incrementally. This distinction matters: a
16-argument EVAL cannot carry derivatives of incoming stress.

## Object ABI

gfortran symbols are `umat_`, `umat_oti_internal_`, `umat_oti_eval_`, and
`umat_oti_march_`. Public replay arguments are double precision arrays/scalars
and default INTEGER dimensions, passed by reference. Arrays use Fortran column
order. Voigt order is `11,22,33,12,13,23`, with engineering shear strains.
Link one material object per shared library using gfortran; the object bundles
the OTI runtime but the linked library still needs the Fortran runtime.

J2 EVAL has exactly 18 arguments:

```fortran
SUBROUTINE UMAT_OTI_EVAL(STRESS,STATEV,DDSDDE,STRAN,DSTRAN, &
  TIME,DTIME,TEMP,DTEMP,PROPS,NPROPS,NTENS,NSTATV,NPARAM, &
  DSIGMA_DP,DSTATEV_DP,DSIGMA_DP_IN,DSTATEV_DP_IN)
```

- `STRESS(NTENS)` and `STATEV(NSTATV)` are incoming/outgoing physical values.
- `DDSDDE(NTENS,NTENS)` is the lifted stress derivative with respect to the
  current `DSTRAN`, at fixed incoming stress/state and strain history. It is
  extracted from extra strain directions, not trusted from the author's tangent.
- `DSIGMA_DP(NTENS,NPARAM)` and `DSTATEV_DP(NSTATV,NPARAM)` are separate outputs.
  Incoming arrays of the same shapes seed the full chain rule through the lift.
  Pass distinct incoming/output buffers. Derivatives never occupy physical SDVs.
- `STRAN` is the strain at increment start; `TIME(2)` is step/total time.
- J2 dimensions are `NPROPS=4, NTENS=6, NSTATV=1, NPARAM=4`; parameter columns
  are `E, nu, SIGY0, H` in contract order. Parameters occupy directions 1-4;
  the six local strain tangent directions occupy 5-10.

Stateless contracts emit the legacy 16-argument EVAL signature, omitting the two
incoming derivative arrays. Their incoming parameter sensitivities are zero.
`history.path_dependent=true` selects the 18-argument form even if there are no
physical state slots. Any physical state requires the path-dependent form.

MARCH has exactly 11 arguments for both variants:

```fortran
SUBROUTINE UMAT_OTI_MARCH(PROPS,NPROPS,PATH,NPATH,DTARR, &
  NTENS,NSTATV,NPARAM,DSIG,STROUT,DDOUT)
```

`PATH(NTENS,NPATH)` contains increments; `DTARR(NPATH)` contains positive time
steps. `DSIG(NTENS,NPARAM,NPATH)` and `DDOUT(NTENS,NTENS,NPATH)` contain every
increment's derivatives/tangent; `STROUT(NTENS)` is final stress. MARCH starts
at zero physical state/stress/strain, carries stress/state parameter derivatives,
advances both time values and KINC, and recreates local strain directions each
increment. Its ABI has no state output; use EVAL for physical and derivative SDVs.

`UMAT` is the untransformed author's standard Abaqus entry point.
`UMAT_OTI_INTERNAL` is an implementation-private kernel with the 18 EVAL
arguments plus an integer increment. It is **not** the old scratch-SDV internal
UMAT interface; consumers must use EVAL or MARCH.

## Original Program 2 Consumption

The following verifies the actual replay implementation at
`origin/cross-platform-hardening`, without checking out or editing that repo:

```sh
"$PY" -m umat_oti.provider.legacy_check \
  /tmp/imq-recovery-W3-j2-verified/verification.json \
  --repo ../Residual_Assembler
```

It exports unchanged legacy Python files into the verification directory, loads
the generated object through the old `PathMaterial`, requires `has_march=true`,
and compares both replay methods to FD of the bundled ORIGINAL UMAT through
`march_regular`. It writes `legacy_verification.json` with the commit and errors.
There is no mock material or shim replacing the original consumer.

Inside an environment using that original Program 2 code:

```python
import json
from pathlib import Path
from residual_core.replay.path_material import PathMaterial

output = Path('/tmp/imq-recovery-W3-j2-verified')
contract = json.loads((output / 'umat_m3_j2_oti.json').read_text())
verification = json.loads((output / 'verification.json').read_text())
material = PathMaterial(str(output / contract['object']['file']), contract)
increments = verification['path']
times = [1.0] * len(increments)
full = material.march_oti(verification['props'], increments, times)
fast = material.march_fast(verification['props'], increments, times)
assert material.has_march
assert full[-1]['dsigma_dp'].shape == (6, 4)
assert full[-1]['dstatev_dp'].shape == (1, 4)
```

Use `PathMaterial` for J2, not the old stateless `objlink` C-ABI adapter.

## Limits and Integration

- Only 3D, small-strain, first-order STRESS/PROPS contracts are accepted.
  Finite strain, other tensor dimensions, higher order, explicit alternative
  derivative-request schemas, extra source files, and non-UMAT entry points fail
  with diagnostics. There is no claim for the remaining model collection.
- The legacy EVAL ABI has no KINC argument (it uses 1), deformation gradients,
  coordinates, rotations, characteristic length, energy history, predefined
  fields, or cutback return. Wrappers use identity gradients/rotation, zero
  coordinates/predefined fields/energies, and unit length. MARCH uses temperature
  293.15 with no temperature increments. Models requiring other context are not
  established by these checks. J2 and the tested elasticity do not depend on it.
- Dimension errors, nonpositive MARCH time steps, and UMAT cutback requests abort
  explicitly with Fortran `ERROR STOP`; this legacy ABI has no status return.
  Validate dimensions before calling, and isolate untrusted material evaluation
  in a worker process. These are not recoverable C status codes.
- Linux/gfortran was exercised. Objects are platform/compiler specific; Windows,
  other Fortran compilers, and binary distribution compatibility are unverified.
- No C `mat_eval_v1` library, `.resmat` package or provider-build GUI entry is
  added in this bounded slice. The existing UMAT GUI launches from its installed
  module; that does not claim a provider GUI workflow.
- `umat-oti-provider = "umat_oti.provider.build:main"` is now registered and
  exercised in a fresh wheel installation. The `python -m umat_oti.provider`
  entry also remains available.

Recovery evidence and exact measured results are in
[evidence/recovery_W3.md](evidence/recovery_W3.md).