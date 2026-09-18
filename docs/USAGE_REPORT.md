# UMAT-OTI: Current Usage

Updated 2026-09-18 for `main` (the final integration of the IMQCAM directive),
Linux, Python 3.11.7, gfortran 9.4.0, ifort 2023.2.1 and Abaqus 2021.HF5. The
transform generation is `da1f183708c19072`; the whole corpus was re-run at it
([evidence/final_refreeze.md](evidence/final_refreeze.md)). The result of the
clean-install gate for the published `main` commits is in
[Residual_Assembler docs/evidence/final_clean_clone.md](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/docs/evidence/final_clean_clone.md).

## Supported Scope

The compiled provider builds for 20 of the 21 bundled parameter-sensitivity
models (m2_elastic3d's contract uses another schema and is refused). Its
verifier judges every DSIGMA_DP, DSTATEV_DP and DDSDDE entry against centred
finite differences of the separately compiled ORIGINAL on the contract's own
strain path: J2 (elastic, plastic and unloading increments) and the FCC crystal
with the slide-15 constants both verify with no disagreeing entry. The
additive entry point `UMAT_OTI_EVAL_TOTAL`
([PROVIDER_EVAL_TOTAL.md](PROVIDER_EVAL_TOTAL.md)) carries total derivatives
through any UMAT's state, which is what the Residual Assembler's history engine
uses to replay the full-size presentation cantilevers. The advanced example
extracts and verifies a local constitutive Jacobian in bundled m5_cpflow.
Small strain only; finite-strain and higher-order providers are refused.

The offline suite (`python -m pytest -q`, with gfortran, OTILib and the
companion checkout present) is recorded with the clean-clone run linked above.
Skips name their missing prerequisite (Abaqus-only data, optional corpora) and
are never counted as passes. The corpus census was re-run at this generation.
The 20-model sensitivity table and the 18 slide-8 benchmarks were reproduced on
2026-09-18 on the branches merged here, before the last transformer fix
(`f11806f`; the sources it generates for all 19 benchmark contracts and all 20
providers are byte-identical before and after it); the commands in
[PRESENTATION_CLAIMS.md](PRESENTATION_CLAIMS.md) rerun them.

## Installation And Environment

Python >=3.10 with ctypes, ssl and venv is required. Runtime dependencies:
NumPy>=1.26, pandas>=2, Streamlit>=1.30, SymPy>=1.12. Select `test` for pytest,
`paper` for publication/plotting, `screenshots` for browser automation (which
also needs an installed browser). Compiled examples require gfortran and make.
Linux/gfortran is verified here; other operating systems/compilers are not
established by this audit. Abaqus/ifort are not needed for the five examples.

From a fresh clone:

```sh
git clone https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation.git
UMAT="$PWD/UMAT_source_transformation"
BASE_PYTHON=python3.11          # any healthy Python >= 3.10 with venv, ctypes, ssl
ENV=$(mktemp -d /tmp/umat-env-XXXXXX)
"$BASE_PYTHON" -m venv "$ENV"
"$ENV/bin/python" -m pip install "$UMAT[test,paper]"
"$ENV/bin/python" -m pip check
"$ENV/bin/umat-oti-provider" --help
```

For connected consumption also install the companion Residual_Assembler
package with `gui,yaml,test` extras. Do not use its historical `bridge` pin for
this pair. The joint clean-install gate (below) installs both from their
wheels; its result for the published `main` commits is in
[Residual_Assembler docs/evidence/final_clean_clone.md](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/docs/evidence/final_clean_clone.md). Checkout examples and source discovery
are not all installed wheel resources.

For work in the source trees, set the imports explicitly:

```sh
WORKSPACE="$HOME/softwarex_work"        # where the two clones and the venv live
UMAT="$WORKSPACE/UMAT_source_transformation"
RA="$WORKSPACE/Residual_Assembler"
PY="$WORKSPACE/.venv/bin/python"
BASE_PYTHON="$HOME/anaconda3/bin/python3.11"
export PATH="$WORKSPACE/.venv/bin:$PATH"
export PYTHONPATH="$RA:$UMAT/src:$HOME/otilib/build_py311"
export UMAT_OTI_REPO="$UMAT"
export PYOTI_PATH="$HOME/otilib/build_py311"
export OTILIB_ROOT="$HOME/otilib/build_py311"
export RUN_OTILIB_TESTS=1
cd "$UMAT"
"$PY" -c 'import umat_oti; from umat_oti.store import transform_fingerprint; print(umat_oti.__file__); print(transform_fingerprint())'
```

OTILib's Python build is needed for RA's direct/finite examples, not this
provider's generated Fortran OTI. Never install the unrelated PyPI `pyoti`.
The shared editable console scripts may point to original checkouts; use the
module spellings below. Installed wheels use their normal console commands.

## CLI Reference

[Actual help captures](evidence/usage_help.json) preserve stdout, stderr,
argv, cwd and return code. Help confirms flags, not scientific success.

| Installed command | Recovery module / behavior |
| --- | --- |
| `umat-oti` | `umat_oti.cli`; subcommands transform, config and `jacobian SOURCE --ntens N --out DIR [--compile]` (the Constitutive Jacobian screen's command) |
| `umat-oti-config --config JSON --out DIR --compile` | `umat_oti.cli_json`; compact contract, optional compilation |
| `umat-oti-pipeline --config JSON --work-dir DIR --compile` | `umat_oti.pipeline.cli`; staged graph and run manifest |
| `umat-oti-batch --config-dir DIR --batch-dir DIR` | `umat_oti.cli_batch`; batch transformation |
| `umat-oti-provider build CONTRACT --out DIR [--regular-object REAL_UMAT.obj] [--abaqus-toolchain]` | `umat_oti.provider`; relocatable ORIGINAL+OTI object, completed mapping, verification entries; optionally the ORIGINAL alone as `REAL_UMAT.obj`, built with `abaqus make` |
| `python -m umat_oti.reproduce --profile smoke --out-dir DIR` | Reproduction profiles: smoke, offline, paper, corpus, abaqus |

For example, invoke compact configuration as:

```sh
"$PY" -m umat_oti.cli_json --help
"$PY" -m umat_oti.pipeline.cli --list-stages
"$PY" -m umat_oti.provider build parameter_sensitivity/models/m3_j2/contract_v2.json --out /tmp/new-j2-provider
```

Choose a fresh output directory. The provider's build is also exercised by each
compiled example below. For compact transformation supply a supported completed
compact JSON contract; it is not the provider's completed ABI mapping.
Pipeline resume reuses unchanged input/artifact stages; `--no-resume` requests
a cold run; `--only STAGE ...` selects stages while dependencies still gate them.
All-not-requested can exit zero; external blocking exits 3. See each stage in
`run_manifest.json`, not just the process code. Pipeline help and stage listing
ran here; arbitrary compact contracts/resume scenarios are not newly exercised.

Batch `--validate` invokes Abaqus and was **not run**. `--reuse-validation-results`
does not refresh old evidence. Do not run corpus/abaqus profiles as part of this
offline guide. Reproduce exits 0 even for explicitly external-blocked steps,
1 for an unexpected failed step, 2 if it cannot start; inspect its five outputs:
run_manifest.json, environment.json, claim_matrix.json, artifact_checksums.sha256,
reproduction_summary.md. Help capture is not profile completion.

The joint wheel-gate forwarding help requires its companion path even with help:

```sh
"$PY" scripts/clean_install_gate.py --ra-repo "$RA" --help
```

The raw capture retains the initial exit-2 missing-argument diagnostic and the
corrected exit-0 invocation. To run the gate supply a healthy standalone Python,
the genuine matching ODB, optionally `--branch main` and `--cantilever DIR`,
and a fresh external work directory; Residual_Assembler `docs/USAGE_REPORT.md`
describes each check. Both trees must be clean.

## Five Reproduced Examples

All outputs below use a new `OUT` directory. Full commands, compiler outputs,
input/object identities, FD ladders, comparison counts and numerical reports
are embedded in [raw example evidence](evidence/usage_examples.json).
The verifier compiles actual ORIGINAL and transformed routines; no core mocks,
new skips or weakened tolerances are used.

```sh
OUT=$(mktemp -d /tmp/umat-examples-XXXXXX)
```

### 1. Elastic Tangent

```sh
"$PY" -m umat_oti.validation.parameter_sensitivity_provider \
	parameter_sensitivity/models/m1_elastic/contract_v2.json --elastic --out "$OUT/elastic"
```

Uses the bundled contract's constants and source without hand-entered replacements.
The `--elastic` option selects the stateless convention and removes the J2
branch-sequence requirement, not derivative checking. Fresh EVAL/MARCH tangent
and parameter FD checks against ORIGINAL passed the report's `2e-6` scaled
tolerance. Do not use this switch to disguise absent plastic history in J2.

### 2. Nonlinear J2 Tangent

```sh
"$PY" -m umat_oti.validation.parameter_sensitivity_provider \
	parameter_sensitivity/models/m3_j2/contract_v2.json --out "$OUT/j2"
```

E=210000, nu=0.3, SIGY0=250, H=2000, one physical state slot. Seven increments:
elastic, elastic, plastic, plastic, elastic, plastic, elastic. The separately
compiled original-source FD reference checks 756 EVAL and 756 MARCH tangent
components over three step sizes, with a plateau check and `2e-6` scaled limit.
The 49 EVAL primal and 6 final MARCH primal comparisons also passed.

### 3. Parameter Sensitivities

```sh
"$PY" -m umat_oti.validation.parameter_sensitivity_provider \
	parameter_sensitivity/models/m3_j2/contract_v2.json --out "$OUT/parameters"
```

This deliberately reruns the same complete J2 verification with parameter
results as the focus, not a third material model. E,nu,SIGY0,H are simultaneous
first-order directions. The report records 588 EVAL parameter comparisons
(stress and state) and 504 MARCH stress comparisons; all three FD steps and
plateau checks pass the unchanged `2e-6` limit. Active derivatives are nonzero.

### 4. State Sensitivities

```sh
"$PY" -m umat_oti.validation.parameter_sensitivity_provider \
	parameter_sensitivity/models/m3_j2/contract_v2.json --out "$OUT/state"
```

Same full verifier, separate invocation/output, focused on equivalent-plastic-
strain derivatives and carried incoming stress/state derivatives. ORIGINAL
history FD and primal state checks pass; resetting derivative carry changes
the result by about 2720.126, so the check detects lost history. Physical SDV1
is not overloaded with derivative storage. This is dSTATEV/dPROPS, not a claim
to arbitrary partial derivatives with respect to every initial-state variable.

Examples 1-4 write verification.json, a completed provider mapping, a compiled
object, original/transformed/support/build files. `passed=true` means the
specified independent verifier passed; source/object hashes establish identity,
not correctness by themselves. Compilation, branch mismatch, nonfinite results
or unresolved verification produce diagnostics/nonzero failure. The supported
[provider contract](PROVIDER.md) gives exact ABI and derivative layouts.

### 5. Internal Constitutive Jacobian

```sh
"$PY" examples/verify_internal_jacobian.py --out "$OUT/internal"
```

This new thin wrapper calls the existing verifier on bundled m5_cpflow with its
existing regression inputs: 20 increments of DSTRAN11=1e-4 and properties
[200000,0.3,1500,25,0.4,1.6,0.1,60000]. It seeds the local Newton iterate,
extracts the residual Jacobian and compares it to independently compiled
untransformed-source FD, retaining the step ladder. Recording changes primal
stress by exactly zero. Measured relative Jacobian error `3.8755690795e-12`
is below `1e-8`; the hand-coded Jacobian is audited, not used as the independent
reference. verification.json preserves all named stages and tolerances.
An existing output directory is refused; failed verification exits 2.
This is a local material solve, not full FCC crystal-plasticity FE verification.

One command repeats all ten cross-repository examples and numerical assertions:

```sh
"$PY" "$RA/scripts/audit_recovery_usage.py" --umat "$UMAT" --phase examples
```

## GUI Use And Limits

```sh
"$PY" -m streamlit run scripts/app.py --server.address=127.0.0.1 --server.port=8502
"$PY" -m streamlit run src/umat_oti/app/unified_app.py --server.address=127.0.0.1 --server.port=8503
"$PY" -m streamlit run src/umat_oti/app/workbench_app.py --server.address=127.0.0.1 --server.port=8504
```

Launch only the desired GUI, using a free port, and open its printed URL. The
primary GUI handles transformation/evidence; the unified and workbench apps
are retained secondary interfaces. All three rendered without exceptions in
[current GUI evidence](evidence/usage_gui.json); the primary server also reached
HTTP readiness and was stopped by owned PID. No audit URL is still live.
Installed GUI: locate `umat_oti.app.streamlit_app` using importlib.util and pass
its installed path to Streamlit, as in the wheel installation evidence.

The primary GUI's **Constitutive Jacobian** tab (upload a UMAT, set NTENS,
Transform) and **Parameter Sensitivities** tab (parameter table, DSIGMA_DP /
DSTATEV_DP ticks, Build) call the same service functions as `umat-oti jacobian`
and `umat-oti-provider build` and write byte-identical files; browser tests
(`pytest -m gui`, 5 passed on 2026-09-18) click through both
([GUI.md](GUI.md)). The internal-Jacobian probe and the corpus tools remain
CLI-only; RA's GUI consumes the generated object and mapping.

## Connected Collaborator Workflow

The developer builds m3_j2 with `umat-oti-provider build` and shares only the
object and completed generated mapping, alongside the converged analysis files.
The input transformation contract is not the completed mapping. Keep the latter
unchanged as the object-stem JSON or alias `Mapping.json` beside `OTI_UMAT.obj`.
The RA collaborator invokes:

```sh
"$PY" -m residual_core.ui.cli request --model Analysis.inp --odb Analysis.odb \
	--material OTI_UMAT.obj --request sensitivity_request.json --out new_results
```

Mapping discovery is automatic. Conflicting sidecars require `--mapping PATH`;
full object hash, source fingerprint, ABI/dimensions, parameter order, PROPS
indices, OTI directions and derivative/Voigt layout must match. No manual map
construction, private material source, transformation or production rerun is
needed by the collaborator. A compatible gfortran linker/runtime and licensed
Abaqus odbAccess are needed; `--abaqus PATH` overrides the extractor executable.
Only trusted compiled binaries should be loaded. The source-read denial proof
is a Python audit check, not a security sandbox for native processes.

Exactly three public root outputs:

| Output | Contents |
| --- | --- |
| `sensitivity_results.json` | Requested scalar values/derivatives, resolved scope and metadata |
| `sensitivity_tables.csv` | Output/increment/parameter rows; 16 rows for the bundled four-output request |
| `run_report.txt` | Execution checks, tolerances, verification status and limits |

Full fields, K/R/derivatives, generated replay record, exporter logs and link
products remain under `private/`. The ordinary result says `verified=false`:
execution/equilibrium checks are not an independent derivative certificate.
`--validate` explicitly requests ORIGINAL whole-history FD and may fail the
strict double-precision gate on float32 ODB inputs. The audit's separate
uniaxial-J2 analytic proof passed with the original `2e-5` relative / `1e-8`
zero-reference absolute thresholds. [Raw proof](evidence/usage_presentation.json)
records the copied input hashes, exact filenames and public scalar results.

Request example, with exactly outputs/parameters/domain/increments at top level:

```json
{"outputs":[{"name":"loaded_U1","field":"U","component":1,"reduction":"mean"}],"parameters":["E","SIGY0","H"],"domain":{"nodes":[2,3,6,7]},"increments":"LAST"}
```

U/RF use nodes; S/SDV use elements and all eight IPs. Component is one-based or
ALL; stress order is 11,22,33,12,13,23; SDV1 is equivalent plastic strain.
Parameters are a unique subset of E,nu,SIGY0,H. ALL/LAST/list selects output
increments only after replaying the full preceding history. Reductions are
component (one location), unweighted sum/mean, Euclidean L2 and signed max.
Zero L2 norm and tied maxima fail. Mean is not volume-weighted; L2 is not
von Mises. Unknown names, ids or unsupported requests fail explicitly.

Supported physics is only one static NLGEOM=NO, homogeneous pinned J2 C3D8/B-bar
step, one untransformed instance, virgin state, zero fixed BCs and ramped nodal
loads. ODB must include every increment plus frame zero and matching U/RF/CF/S/
SDV1, mesh and history. Scaled free residual must be <1e-5; stress/RF use
2e-5 relative plus field-scaled absolute tolerance; state uses 2e-5 relative and
1e-8 absolute. Missing frames are not interpolated. Nonzero BCs, multistep,
pressure/contact/body loads, amplitudes, multiple materials/instances, initial
state, finite strain and generic FCC/full-size models are not supported here.

Repeat consumption without a new solve:

```sh
"$PY" "$RA/scripts/audit_recovery_usage.py" --umat "$UMAT" --phase presentation
```

The runner copies five existing genuine collaborator artifacts into new scratch
space, invokes the existing source-denied `consume` path and checks all three
outputs. It never calls `prepare`. The genuine ODB is an external prerequisite,
not a packaged fixture. Prior real-browser download proof is a local artifact:
The browser report and desktop image were stored in the RA run's ignored
`.pytest_cache/presentation_browser_cli_final` directory. They are unavailable
in a clean clone; no image was duplicated. Complete companion details:
[presentation interface](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/docs/PRESENTATION_INTERFACE.md).

## Requirement Coverage

### Review Follow-Up: Historical Service Tests

The two original HEAD PASS11 integration tests were restored separately from
the retained, explicitly named synthetic unit tests. Their historical assertions
are unchanged: 237 records, 55 at stage verified, 42 holding all six gates and
13 exceptions with `primal_agreed` not holding. These describe the historical
PASS11 file, **not current-generation corpus capability**. No tolerances,
service verdicts, generation fingerprints or fixture contents changed.

Review run on 2026-09-18: **18 passed, six skipped, zero failures** in the service
test file. All six skips, including the two restored tests, are because the
external PASS11 file is genuinely absent. Existing `UMAT_OTI_CORPUS_RUN` override
and absent-file handling remain in use; a present invalid file fails rather
than being skipped. The two synthetic passes are not corpus evidence.
Retained result: [focused JUnit](evidence/review_fixes_focused.xml). From the
workspace root with the recovery import environment above:

```sh
.venv/bin/pytest -q -ra imq-umat-recovery/tests/test_the_services_are_the_one_place_a_verdict_is_decided.py --junitxml=imq-umat-recovery/docs/evidence/review_fixes_focused.xml
.venv/bin/pytest -q imq-umat-recovery/tests/test_repository_standards.py::test_documented_commands_and_links_resolve --junitxml=imq-umat-recovery/docs/evidence/review_fixes_docs.xml
```

The second command runs the existing documentation auditor through its test
wrapper. No full suite, fresh corpus run or licensed analysis was requested.
Companion RA review checks: 60 passes for presentation and thin-CLI guards;
injected error tests establish disclosure handling only, not numerical proof.

The [274-row ledger](COMPLETION_LEDGER.md) and [structured requirement index](evidence/usage_requirements.json)
separate 104 bounded implemented rows, 159 partial rows and 11 unestablished
release-gate rows. **Zero rows have clean-install PASS;
all 274 remain open under the master completion rule.** Top priorities: clean
final-branch pair reproduction; all-example GUI equivalence; generic provider
support and current corpus verification; full-size/FCC and general stateful
finite-strain integration; higher-order full FE. Historical evidence, successful
compilation, a resolved reference path, an available derivative and an
independently verified derivative are different claims.