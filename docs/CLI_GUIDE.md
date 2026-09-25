# Command-line guide

UMAT-OTI installs five console commands. This guide describes each one: what
it is for, its synopsis and important options (taken from its `--help`), one
worked invocation with the output it actually printed, the files it writes,
and its exit codes. Every invocation shown was run on 2026-09-18 from the
repository root, with Python 3.11.7 and gfortran 9.4.0. Long outputs are
trimmed, and absolute paths are shortened to `<out>`.

Install first: [INSTALL.md](INSTALL.md). Worked examples that combine these
commands: [examples/README.md](../examples/README.md).

## At a glance

| Command | Module form | Use it to |
| --- | --- | --- |
| [`umat-oti all`](#umat-oti-all) | `python -m umat_oti.cli all` | discover dependencies, compile the tangent, build and verify stress/state parameter sensitivities |
| [`umat-oti jacobian`](#umat-oti-jacobian) | `python -m umat_oti.cli jacobian` | get the consistent tangent `DDSDDE` of a UMAT from four fields, without writing a contract. **Start here.** |
| [`umat-oti config`](#umat-oti-config) | `python -m umat_oti.cli config` | transform a UMAT from a JSON contract (full control) |
| [`umat-oti-config`](#umat-oti-config-1) | `python -m umat_oti.cli_json` | the same, as a stand-alone command |
| [`umat-oti transform`](#umat-oti-transform) | `python -m umat_oti.cli transform` | the original whole-routine wrapper transform (kept for compatibility) |
| [`umat-oti-pipeline`](#umat-oti-pipeline) | `python -m umat_oti.pipeline.cli` | run one contract through the staged pipeline with a run manifest and resume |
| [`umat-oti-batch`](#umat-oti-batch) | `python -m umat_oti.cli_batch` | transform every contract in a folder, optionally validate each in Abaqus |
| [`umat-oti-provider build`](#umat-oti-provider-build) | `python -m umat_oti.provider build` | build the compiled parameter-sensitivity provider (`OTI_UMAT.obj` + mapping) |
| [`python -m umat_oti.provider.collaborator`](#python--m-umat_otiprovidercollaborator) | (module only) | build, verify and package the four files a collaborator receives |
| [`python -m umat_oti.validation.parameter_sensitivity_provider`](#python--m-umat_otivalidationparameter_sensitivity_provider) | (module only) | verify a provider entry by entry against finite differences |
| [`python -m umat_oti.reproduce`](#python--m-umat_otireproduce) | (module only) | run a reproduction profile (smoke, offline, paper, corpus, abaqus) |

Every console command also runs as `python -m <module>`. Use that form if the
virtual environment's `bin/` folder is not on `PATH`.

**Paths.** Contract files name their UMAT source relative to the contract
itself, so a contract can be used from any working directory. Output
directories are created if needed. `umat_oti_workspace/` is ignored by git
and is a good place for outputs.

## Exit codes in one table

| Command | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| `umat-oti jacobian`, `umat-oti config`, `umat-oti-config` | transform succeeded (and compiled, if `--compile`) | transform failed, source missing, invalid request, or compilation failed or unavailable | the contract needs completing (tangent block not found), the request was refused (for example an invalid NTENS), or a command-line error | |
| `umat-oti transform` | files generated; validation passed or was skipped | validation ran and failed | command-line error | |
| `umat-oti-pipeline` | no stage failed or was unsupported (stages that were not requested do not count) | a stage failed or is unsupported, or a required argument is missing | command-line error | a stage is blocked by missing external software |
| `umat-oti-batch` | the batch ran (read the report for each contract's category) | | command-line error | |
| `umat-oti-provider build` | provider built | | build refused or failed (the message says why), or a command-line error | |
| `python -m umat_oti.provider.collaborator` | built and verified | built but not verified | not built | |
| `python -m umat_oti.validation.parameter_sensitivity_provider` | verified | | not verified (the report says why) | |
| `python -m umat_oti.reproduce` | every step succeeded, or was unavailable for a stated external reason | a step that should have worked failed | the profile could not start | |

A zero exit code is not, by itself, a verification. Each command writes a
record (`transform_report.txt`, `run_manifest.json`, `verification.json`,
`reproduction_summary.md`) that says what was checked and how.

---

## `umat-oti all`

Automatically discover material settings and dependencies, name candidate
parameters, generate and compile the tangent, then build and independently
verify the sensitivity provider. To also run Abaqus:

```bash
umat-oti all /path/to/umat.f90 --out out/complete --abaqus
```

No material JSON is required. The existing experiment planner searches the
source directory for associated material decks and uses a sibling
`SOURCE_STEM.abaqus.json` when present. Use `--material-discovery-root PATH`
to search another model directory. Discovery writes `material_workflow.json`
automatically, with evidence in `abaqus_discovery.json` and the experiment
record in `abaqus_experiment.json`. Missing or ambiguous material data is a
reported blocker, not a request to fabricate a configuration or physical values.

The discovered experiment supplies material values, state size and strain
targets. Its targets are interpolated using its increment counts; the
standalone diagnostic uses **unit time increments**, temperature 293.15 and
zero initial stress/state, not the author's original timing. Unsupported
kinematics, initialization, orientation and non-strain loading are refused.
This bounded diagnostic is not evidence that all material regimes activated.

`--material-config` remains an optional explicit override, for example:

```bash
umat-oti all parameter_sensitivity/models/m3_j2/umat.for \
    --material-config examples/03_j2_parameter_sensitivities/material_workflow.json \
    --out out/j2_complete
```

To also run the generated Jacobian UMAT in Abaqus after both standalone checks
succeed, add `--abaqus`:

```bash
umat-oti all parameter_sensitivity/models/m3_j2/umat.for \
  --material-config examples/03_j2_parameter_sensitivities/material_workflow.json \
  --out out/j2_complete_abaqus \
  --abaqus
```

The order is dependency discovery, parameter selection, Jacobian generation and
compilation, sensitivity generation and finite-difference verification, then
Abaqus analysis. The default single-element C3D8 input deck uses the same
`props_values`, `nstatev`, and cumulative `check_path` strain targets. Each
input increment becomes a one-time-unit step with one requested increment;
Abaqus can cut it back. Initial stress/state are zero and initial temperature
is 293.15, consistent with the standalone check's setup.

`--abaqus-input DECK.inp` overrides the generated deck.
`--abaqus-experiment SETTINGS.json` supplies alternative experiment settings.
Either implies `--abaqus`; an explicit input deck takes precedence over
experiment settings for the Abaqus run. Without `--material-config`, material
discovery still runs for the sensitivity workflow; an experiment override also
supplies its discovery settings. A deck outside the source directory needs
`--material-discovery-root` pointing to its model directory.

`--abaqus-smoke` requests a build-only check instead of analysis and cannot be
combined with analysis options. Both modes support `--abaqus-command`,
`--abaqus-modules`, and `--abaqus-run-prefix`, with the same ARC defaults as
`jacobian`. Use `--abaqus-run-prefix "" --abaqus-modules ""` when already on a
configured compute node. The analysis working directory is `OUT/jacobian`;
relative deck assets must be available there. Generated decks, trial reports,
and solver files also live there; build-only jobs use its fresh trial subfolder.

The complete workflow does not accept `--abaqus-allow-semantic-failures`:
failed transformation, compilation, or sensitivity verification stops it
before Abaqus. For deliberately unverified candidates use the separate
`jacobian` trial command. `workflow_summary.json` records Abaqus as `not_run`
when an earlier stage fails, and an Abaqus failure keeps the overall exit code
nonzero.

This combines **standalone sensitivity verification and an Abaqus execution
trial**. Abaqus does not test the parameter-sensitivity provider or perform an
original-versus-transformed numerical comparison in this mode. Its trial
report therefore retains `verified: false`, even after a completed analysis.
The existing standard-UMAT, NTENS=6, small-strain provider restrictions remain.

Both discovery and compilation are automatic; neither `--discover-dependencies`
nor `--compile` is needed. Add repeatable `--dependency-root PATH` options for
helper directories outside the source directory. Search boundaries and Fortran
limitations are the same as for `jacobian` discovery below.

The optional material-settings override is physical input, not a transformation
contract. This smaller example describes a two-property elastic model only:

```json
{
  "kinematics": "small_strain",
  "ntens": 6,
  "nstatev": 0,
  "props_values": [210000.0, 0.3],
  "check_path": {
    "dstran_per_increment": [0.0001, 0, 0, 0.0001, 0, 0],
    "n_increments": 4
  }
}
```

Use your model's actual values and state size, not these example values.
`props_values` supplies every slot in PROPS order, including slots not selected
for differentiation. `check_path` can instead contain `increments`, an explicit
list of six-component strain increments. The existing provider verifier uses
engineering shear, unit time increments, temperature 293.15, zero temperature
increments and zero initial stress/state. This command does not configure
other time, thermal or initial-state histories; unknown settings are refused.

Direct assignments such as `E = PROPS(1)` supply candidate parameter names.
Otherwise names are `PROPS_1`, `PROPS_2`, etc. By default all supplied slots are
differentiated. Source analysis cannot establish which slots are continuous
material parameters rather than integer flags or switches. To choose a subset
or override inferred names, add a `parameters` array to the settings:

```json
"parameters": [
  {"name": "E", "props_index": 1},
  {"name": "nu", "props_index": 2}
]
```

Dynamic PROPS indexing requires this explicit selection. Property values and
state size must be supported by discovered data or an explicit override;
they are not invented from PROPS slot reads. Review the generated `parameters.json` before relying on
results, especially if the model uses discrete flags.

Outputs are placed under a **new or empty** output directory:

- `discovery/dependency_report.json`: resolved routines and external dependencies.
- `parameters.json`: chosen names, indices and values.
- `jacobian/`: the transformed tangent source, compiler artifacts and reports.
- `sensitivities/collaborator/`: `REAL_UMAT.obj`, `OTI_UMAT.obj`, `Mapping.json`,
  and `transform_report.txt`.
- `sensitivities/verification/`: finite-difference comparisons of stress/state
  parameter sensitivities and tangent against the original model.
- `workflow_summary.json`: stage results and the first failed stage, if any.

Exit code 0 means all requested stages passed; 1 means a stage failed; 2 means
an invalid CLI invocation or a nonempty output directory. Later stages are not
run after an earlier failure. A sensitivity failure may leave a successful
tangent build, but the overall result remains failed.

This combines the existing engines; it does not broaden their mathematical
support. The provider requires entry name `UMAT`, NTENS=6, small-strain
kinematics and first-order parameter derivatives. Higher-order derivatives,
arbitrary included/module state, contained helpers and differentiation through
binary LAPACK calls are not supplied by this command. Internal Newton-Jacobian
requests are not generated automatically. A successful bounded verification
is evidence only for the declared values and history, not all loading regimes.

## `umat-oti jacobian`

### Optional Abaqus Trial

For a **build-only smoke test** before material settings are known, use
`--abaqus-smoke` instead of `--abaqus`:

```bash
umat-oti jacobian UMAT_Files/my_umat.f90 \
  --ntens 6 --out out/my_umat_abaqus_smoke \
  --discover-dependencies \
  --abaqus-smoke --abaqus-allow-semantic-failures
```

This bypasses experiment settings and invokes `abaqus make` on the combined
candidate in a fresh subdirectory of `--out`. Staged Fortran dependencies and
an existing `OUT/abaqus_v6.env` are copied into that directory. A `built` result
requires exit code zero and a newly produced nonempty shared library. The
report still records `verified: false` and `analysis_completed: false`.
Semantic failures retain the nonzero CLI exit code; hard transformation
blockers still prevent the build. This mode cannot be combined with
`--abaqus`, `--abaqus-input`, or `--abaqus-experiment`.

A build smoke test does **not** execute a solver increment, check activation,
or establish that the UMAT argument interface is correct. A nonstandard
routine still needs a standard Abaqus UMAT wrapper before an analysis can
exercise it. Missing includes and build errors remain real failures; material
constants and array dimensions are not invented to bypass them.

Add `--abaqus` to try the generated UMAT in Abaqus immediately after
transformation. By default the existing single-element generator builds the
input deck from a sibling settings file: `umat.f90` uses `umat.abaqus.json`.
If that file is absent or its required settings are unset, automatic material
discovery searches the source directory for a matching Abaqus material deck.
It reuses the harness's source/deck pairing and experiment planner to obtain
property values, state size, formulation, and initialization with provenance.
Use `--abaqus-discovery-root PATH` to search a related model directory instead.
Explicit sidecar settings, including loading, take precedence over discovered
settings. A malformed sidecar or an explicitly named nonexistent settings file
is still an error.

Discovery records its evidence or refusal in `OUT/abaqus_discovery.json`.
It does not turn `PROPS(index)` reads into invented property values. When no
matching deck supplies usable values, it stops with the reason and writes the
discovery report; it does not submit an under-specified material to Abaqus.
The `all` command also reuses this planner to generate its material
configuration automatically, subject to its narrower provider restrictions.

Select a different settings file with `--abaqus-experiment SETTINGS.json`.
Override generation with `--abaqus-input DECK.inp` to use an existing deck;
this takes precedence over experiment settings. Both options imply `--abaqus`.
To deliberately try a candidate that failed semantic checks, also add
`--abaqus-allow-semantic-failures`:

```bash
umat-oti jacobian /path/to/umat.f90 --ntens 6 --out out/umat_trial \
  --discover-dependencies \
    --abaqus \
  --abaqus-allow-semantic-failures
```

The following settings illustrate a **synthetic elastic test**, not a particular
model's material data. Supply your model's actual properties, state size, kinematics,
initialization and loading. Missing settings are discovered where possible,
otherwise refused rather than guessed.

```json
{
  "name": "elastic_trial",
  "element_type": "C3D8",
  "kinematics": "small strain",
  "props": [210000.0, 0.3],
  "material_provenance": "Synthetic elastic example only",
  "nstatv": 0,
  "loading": [
    {
      "name": "shear",
      "strain": [0, 0, 0, 0.001, 0, 0],
      "increments": 20,
      "period": 1.0
    }
  ]
}
```

Each loading segment uses the existing `LoadingSegment` fields. Strain
components are ordered `(11, 22, 33, 12, 13, 23)`, with engineering shear;
their values set the loading amplitude. Add segments for a loading history.
Optional `VerificationManifest` fields include initial state, orientation,
temperature and geometry. Source and source-bundle fields are not accepted
here: the transformation supplies the candidate. Element tensor dimensions
must agree with `--ntens`. Material, initial-state and orientation provenance
requirements are enforced by the existing manifest.

Generated files are `OUT/abaqus_trial.inp` and `OUT/abaqus_experiment.json`.
This command runs the prescribed history once; it does not automatically
launch the harness's multi-job amplitude search.

The override does not bypass hard transformation blockers or missing generated
compilation units. Abaqus compiles the candidate itself; `--compile` is optional
and requests a separate gfortran check, which remains gated by semantic success.
The transform report remains failed and the CLI exit code stays nonzero when
semantic checks failed, even if Abaqus finishes successfully.

On ARC the defaults load `abaqus/2024 intel/oneapi/2024.2.0.634` inside
`srun --partition=compute1 --ntasks=1 --cpus-per-task=2 --time=00-00:30:00`.
Override these with `--abaqus-command`, `--abaqus-modules`, and
`--abaqus-run-prefix`. When already on a configured compute node, pass
`--abaqus-run-prefix "" --abaqus-modules ""` to avoid a nested allocation.

The working directory is `--out`, not the input deck's directory. Stage any
relative input-deck includes, model data files, and required `abaqus_v6.env`
there before running. Dependency discovery stages Fortran dependencies, not
Abaqus deck assets. Each attempt uses a unique `oti_trial_*` job name; its
solver files and stdout/stderr logs remain in `--out`. The latest attempt is
recorded in `abaqus_trial.json`. A trial completes only with a zero process
exit code and Abaqus's analysis-completed marker in the job's `.dat` file.
The launcher times out after one hour; check the scheduler for remaining jobs
after a timeout before retrying.

This is an **unverified execution trial**, not an original-versus-transformed
comparison or proof of tangent correctness. `verified` is always false.

**Purpose.** Transform a UMAT so that `DDSDDE` is computed by OTI arithmetic,
from four fields: the source, NTENS, and what to differentiate. The
transformer finds the lines that assign the tangent by itself. This is the
command behind the GUI's **Constitutive Jacobian** tab.

**Synopsis** (from `umat-oti jacobian --help`):

```text
usage: umat-oti jacobian [-h] --ntens NTENS [--seed SEED]
                         [--response RESPONSE] [--target TARGET]
                         [--order ORDER] --out OUT [--compile]
                         [--discover-dependencies] [--dependency-root PATH]
                         source
```

| Option | Meaning |
| --- | --- |
| `source` | the UMAT source (`.for`, `.f`, `.f90`) |
| `--ntens N` | number of stress components: `6` (3D), `4` (plane strain, axisymmetric) or `3` (plane stress). Required |
| `--seed` | differentiate with respect to (default `DSTRAN`) |
| `--response` | the output to differentiate (default `STRESS`) |
| `--target` | where the derivative is written (default `DDSDDE`) |
| `--order` | derivative order (default `1`) |
| `--out DIR` | output directory. Required |
| `--compile` | also compile every generated file with gfortran |
| `--discover-dependencies` | recursively search beneath the source directory for helper definitions |
| `--dependency-root PATH` | search an additional source directory or file; repeatable; relative to the current working directory |

**Automatic helper discovery.** No hand-written contract is needed:

```bash
umat-oti jacobian materials/umat.for --ntens 6 --out out/material \
  --discover-dependencies --dependency-root shared_helpers --compile
```

Discovery is opt-in. The source directory is searched only with
`--discover-dependencies`; explicit roots also work without that flag. The
search stays within those roots and the entry file, not the entire machine.
The current output directory and paths containing `.git`, `.venv`,
`__pycache__`, `out`, `build`, or `umat_oti_workspace` directory components are
excluded. Keep input sources outside those directories and use a dedicated
material source tree to avoid unrelated alternative implementations.

The resolver follows subroutine calls and recognized function references,
collects the required source definitions, and passes the combined source to
the existing OTI transformation. Helpers on the derivative path are lifted;
unrelated code is not indiscriminately overloaded. Missing or conflicting
definitions stop discovery. `dependency_report.json` records the call graph,
selected definitions, missing symbols, conflicts, and recognized runtime or
library dependencies, including when resolution fails. The generated contract
records the search roots for repeat runs.

**Output-local dependencies.** Each transformation now stages the entry source,
resolved helper source files, and recursively referenced literal include files
directly under `OUT/dependencies/`, without per-source subdirectories. Original
filenames are kept unless they collide; colliding names receive a deterministic
suffix so different helpers' files are never overwritten. Include references in
the staged and resolved sources are rewritten relative to `OUT`; originals are
not modified. Single-source runs stage their local includes even without helper
discovery. Extra include search roots come from the dependency-root options.

`OUT/dependency_bundle.json` records original paths, portable bundled paths,
SHA-256 hashes, missing includes, solver-provided includes, and known external
runtime/library calls. Missing files are reported, never fabricated. Available
dependencies are staged before transformation, so the bundle remains useful for
diagnostics when semantic checks fail; its existence does not certify the output.
The files are local copies of your sources and retain their confidentiality.

After a successful transformation, move the **whole output directory**, not just
the combined Fortran file. Its build script can be invoked from another directory:

```bash
bash /path/to/moved-output/compile_hint.sh
```

Compile only the units in `compile_order.txt`; the copies in `dependencies/`
must not be compiled again alongside the resolved/transformed UMAT. The script
changes to its own directory and adds it to the include search path. `--compile`
also supplies the existing standalone `ABA_PARAM.INC` stub for the compiler smoke
check; actual Abaqus execution still requires the licensed solver and its runtime.
External modules, binary libraries, macro-generated includes, and runtime data
files are not automatically bundled. A copied include does not add new syntax or
declaration support to the OTI lifter. Original paths in reports/contracts are
provenance, not a guarantee that transformation itself can be rerun after moving.

Discovery is not a complete Fortran build system. It does not implement
preprocessing, arbitrary module/host association, or OTI versions of binary
libraries such as LAPACK. Contained helpers can still be missed by the
transform parser. Nonstandard entry names are discovered, but some such
transforms have a known variable-scope limitation. Finding a source definition
does not guarantee that the lifter supports its contents. Compilation and
numerical derivative verification remain necessary; do not use artifacts
from a failed run, including files left by an earlier run in the same folder.

**Example.**

```bash
umat-oti jacobian parameter_sensitivity/models/m3_j2/umat.for \
    --ntens 6 --out umat_oti_workspace/cli/j2 --compile
```

It printed a JSON summary (2.2 s, exit code 0). Trimmed:

```text
{
  "anchor_status": "ready_with_json_contract",
  "blockers": [],
  "combined_source": "<out>/umat_oti_combined.f90",
  "compilation": { "returncode": 0, "status": "compiled", ... },
  "derivative_requests": [ { "id": "material_tangent", "output_shape": [6, 6],
                             "response": "STRESS", "seed": ["DSTRAN"], "target": "DDSDDE", ... } ],
  "semantic_checks": { "ddsdde_output_present": true, ... 21 checks, all true },
  "status_category": "succeeded",
  "transform_success": true,
  "transformed_source": "<out>/umat_oti.for",
  "warnings": []
}
```

**Output files.** `umat_oti_combined.f90` (the drop-in UMAT: the transformed
routine plus every OTI module, one file), `umat_oti.for` (the transformed
routine alone), the OTI modules (`master_parameters.f90`, `real_utils.f90`,
`otim6n1.f90`, `oti_intrinsics.f90`), `compile_order.txt`, `compile_hint.sh`,
`jacobian_contract.json` (the four fields as a contract),
`derivative_manifest.json`, `transform_report.txt` and `.json` (21 structural
checks). With `--compile`, also the `.o` and `.mod` files. See
[Example 1](../examples/01_elastic_tangent/README.md) and
[Example 2](../examples/02_j2_plasticity_tangent/README.md).

**When it refuses.** Measured:

```text
$ umat-oti jacobian parameter_sensitivity/models/m3_j2/umat.for --ntens 5 --out <out>
jacobian request refused: NTENS must be one of (3, 4, 6), not 5          (exit code 2)
```

With `--compile` and no `gfortran` on `PATH`, the transform is written but
`"compilation": {"status": "compiler_unavailable"}` and the exit code is 1.

---

## `umat-oti config`

**Purpose.** Transform a UMAT from a JSON contract. A contract gives full
control: which lines are replaced, which variables are promoted to OTI or kept
real, the derivative requests and their order. How to write one:
[new_user_umat_starter/JSON_REFERENCE.md](../new_user_umat_starter/JSON_REFERENCE.md).

**Synopsis:**

```text
usage: umat-oti config [-h] --out OUT [--compile] config
```

| Option | Meaning |
| --- | --- |
| `config` | a schema 1.1 or legacy project contract (JSON) |
| `--out DIR` | output directory. Required |
| `--compile` | compile the generated Fortran with gfortran |

**Example** on the smallest contract in the repository (the NTENS = 4 elastic
UMAT):

```bash
umat-oti config examples/elastic_minimal.json --out umat_oti_workspace/cli/config --compile
```

It printed the same kind of JSON summary as `jacobian` (1.8 s, exit code 0)
with `"status_category": "succeeded"`, `"compilation": {"status":
"compiled"}`, 21 of 21 structural checks true, no blockers and no warnings.

**Output files.** `elastic_oti.f` (transformed routine),
`elastic_oti_combined.f90` (drop-in), `otim4n1.f90` and the other OTI modules,
`compile_order.txt`, `compile_hint.sh`, `derivative_manifest.json`,
`transform_report.txt` and `.json`, and with `--compile` the objects.

### Combined Tangent And Parameter Requests

For nonstandard deformation-gradient argument names, a compact/schema 1.1
contract may specify:

```json
"transformation_settings": {
  "seed_dfgrd1": true,
  "gradient_aliases": {"DFGRD0": "F_t", "DFGRD1": "F_tau"}
}
```

These are native analysis and transformation mappings, not preprocessing
renames. The selected routine must declare both mapped arguments as `(3,3)`
arrays. The emitted interface retains their names; the new-gradient shadow
receives `dF = deps * F_tau`, while the old gradient stays unseeded. The
tangent extraction includes the finite-strain stress correction. The mapping
does not supply missing modules, change state layouts, or make a nonstandard
entry a drop-in Abaqus UMAT.

A first-order contract requesting `DDSDDE`, `DSIGMA_DP`, and/or `DSTATEV_DP`
allocates all directions before code generation: `NTENS` strain directions,
existing local-Jacobian slots, then one direction per unique selected PROPS
index. Stress and state requests share parameter slots. Six strain directions
and 89 parameters therefore generate `otim95n1`, not two separate algebras.

The generated source retains the original real-valued entry and also exports
`<entry>_WITH_SENSITIVITIES` with the same arguments followed by two real arrays:
`OTI_DSIGMA_DP(stress_extent, parameter_count)` and
`OTI_DSTATEV_DP(state_extent, parameter_count)`. Both are input/output arrays;
column order is recorded in `combined_sensitivity_interface.json` under
`directions.parameter_slots`. The companion computes the tangent and both
sensitivity arrays in one OTI evaluation.

Supply the derivatives of incoming stress/state on entry. Initialize them to
zero only for parameter-independent initial conditions, then retain returned
arrays between increments for history sensitivities. Strain directions reset
on each call. This interface carries stress/state history only; it does not
track parameter dependence of externally imposed loads, kinematics, or hidden
saved material data. Abaqus calls the unchanged original entry and does not
automatically retain or expose these extra arrays.

Numerical property values and driver settings are not needed for source-only
generation. With numerical parameter values and material-point driver settings,
the optional `parameter_sensitivity/ps_driver.f90` calls the combined entry
and writes `DDSDDE_OTI.csv`, `DSIGMA_DP_OTI.csv`, and `DSTATEV_DP_OTI.csv`.
The supplied driver requires the standard UMAT argument order; a nonstandard
entry needs its own caller. Source generation still requires valid source
dependencies, mappings, and transformation anchors. A generated candidate is
not numerical verification or an Abaqus validation.

---

## `umat-oti-config`

**Purpose.** The same transformation as `umat-oti config`, as a stand-alone
command whose output directory is optional.

**Synopsis:**

```text
usage: umat-oti-config [-h] --config CONFIG [--out OUT] [--compile]
```

| Option | Meaning |
| --- | --- |
| `--config FILE` | the contract. Required |
| `--out DIR` | output directory. Default `./umat_oti_workspace/new_user_runs/<config-stem>` |
| `--compile` | compile the generated Fortran with gfortran |

**Example.**

```bash
umat-oti-config --config examples/elastic_minimal.json --out umat_oti_workspace/cli/config2 --compile
```

Exit code 0 in 2.0 s. The transformed `elastic_oti.f` is byte-identical to
the one `umat-oti config` wrote. Output files and exit codes are those of
`umat-oti config`.

The contract that `umat-oti jacobian` writes (`jacobian_contract.json`) is a
valid input here: `umat-oti-config --config <out>/jacobian_contract.json
--out <dir>` reproduces the same transform.

---

## `umat-oti transform`

**Purpose.** The original, whole-routine transform: it renames the UMAT to
`UMAT_OTI_KERNEL`, promotes every non-parameter real variable to OTI, strips
the existing `DDSDDE` assignments and writes a wrapper with a fixed six-
direction backend. It is kept for compatibility. For new work use `umat-oti
jacobian` or `umat-oti config`, which locate the tangent block, transform only
what the derivative needs, and run 21 structural checks.

**Synopsis:**

```text
usage: umat-oti transform [-h] --out OUT [--config CONFIG] [--no-validation]
                          source
```

| Option | Meaning |
| --- | --- |
| `source` | the UMAT source |
| `--out DIR` | output directory. Required |
| `--config FILE` | a `material_point.json` for the optional finite-difference validation; the command reads `material_point.json` from that file's folder |
| `--no-validation` | generate the files without running the validation |

**Example.**

```bash
umat-oti transform UMATs/UMATs/ICP/elasticity/elastic.f --out umat_oti_workspace/cli/transform --no-validation
```

Output (0.2 s, exit code 0):

```text
{
  "generated_files": [
    "reports/transform_report.json",
    "reports/unsupported_features.json",
    "reports/validation_report.json",
    "source/original/elastic.f",
    "source/transformed/umat_oti_backend.f90",
    "source/transformed/umat_otis.f90",
    "validation/fd_check.py",
    "validation/material_point_driver.f90"
  ],
  "output_dir": "<out>",
  "validation_pass": false,
  "validation_status": "skipped"
}
```

Without `--no-validation` and without a `material_point.json` next to the
source, the validation is also skipped; `reports/validation_report.json` then
says `"reason": "No material_point.json was supplied next to the UMAT
source."`.

---

## `umat-oti-pipeline`

**Purpose.** Run one contract through the canonical stage graph, from source
acquisition to the distributable package. Every run writes
`run_manifest.json`; a rerun reuses the stages whose inputs and artefacts are
unchanged.

**Synopsis:**

```text
usage: umat-oti-pipeline [-h] [--config CONFIG] [--work-dir WORK_DIR]
                         [--run-id RUN_ID] [--compile] [--no-resume]
                         [--only STAGE [STAGE ...]] [--list-stages] [--json]
```

| Option | Meaning |
| --- | --- |
| `--config FILE` | the contract (required unless `--list-stages`) |
| `--work-dir DIR` | where the stages write and `run_manifest.json` lives (required unless `--list-stages`) |
| `--run-id ID` | a name for the run (default `run`) |
| `--compile` | compile during the transformation; needed for every stage from `compilation` on |
| `--no-resume` | ignore cached stage results (cold run) |
| `--only STAGE ...` | run only these stages; their dependencies still gate them |
| `--list-stages` | print the stage graph and exit |
| `--json` | print the run summary as JSON |

`umat-oti-pipeline --list-stages` printed:

```text
 1. source_acquisition                 requires: -
 2. source_inventory                   requires: source_acquisition
 3. license_classification             requires: source_inventory
 4. entry_routine_detection            requires: source_inventory
 5. dependency_closure                 requires: source_inventory, entry_routine_detection
 6. contract_inference                 requires: source_inventory, dependency_closure
 7. derivative_request_normalization   requires: contract_inference
 8. source_transformation              requires: derivative_request_normalization
 9. oti_support_generation             requires: source_transformation
10. compilation                        requires: oti_support_generation
11. material_point_execution           requires: compilation
12. primal_parity                      requires: material_point_execution
13. derivative_verification            requires: material_point_execution
14. abaqus_validation                  requires: compilation
15. evidence_generation                requires: derivative_verification
16. distributable_package              requires: evidence_generation
```

**Example.** The transformation stages of the smallest contract:

```bash
umat-oti-pipeline --config examples/elastic_minimal.json --work-dir umat_oti_workspace/cli/pipeline \
    --compile --only source_transformation oti_support_generation compilation
```

```text
  succeeded                        source_acquisition
  succeeded                        source_inventory
  not_requested                    license_classification
      not included in the requested stage subset
  succeeded                        entry_routine_detection
  ...
  succeeded                        compilation
  not_requested                    material_point_execution
      not included in the requested stage subset
  ...
summary : {"not_requested": 7, "succeeded": 9}
```

Exit code 0. Running the same command again marks every reused stage
`(cached)`; a cached rerun of the full graph took 0.4 s instead of 2.6 s.

**Read the manifest, not only the exit code.**

- A full run without `--only` exits with **1** today even when nothing went
  wrong, because the stage `abaqus_validation` reports `unsupported` ("Abaqus
  validation is not yet routed through the engine"). For
  `examples/elastic_minimal.json` the full run reported
  `{"not_requested": 5, "succeeded": 10, "unsupported": 1}`: this contract
  has no `validation` block, so there is no material-point history to run.
- A stage that succeeded means the stage executed. For
  `derivative_verification`, the scientific outcome is the `verified` field
  and the per-row classifications in its `outputs` in `run_manifest.json`.
- Without `--compile`, the `compilation` stage and everything after it is
  `not_requested`, and a run of only those stages exits with 0 having done
  nothing. Keep `--compile` whenever you ask for execution or verification.

**Output files.** `run_manifest.json` (every stage: status, reason, inputs,
outputs, cache key), `history/`, and one folder per executed stage (for
example `source_transformation/`).

---

## `umat-oti-batch`

**Purpose.** Transform every contract in a folder and write one report;
optionally build, run and compare each transform in Abaqus.

**Synopsis:**

```text
usage: umat-oti-batch [-h] [--config-dir CONFIG_DIR] [--batch-dir BATCH_DIR]
                      [--validate] [--abaqus-command ABAQUS_COMMAND]
                      [--abaqus-modules ABAQUS_MODULES]
                      [--run-prefix RUN_PREFIX] [--reuse-validation-results]
```

| Option | Meaning |
| --- | --- |
| `--config-dir DIR` | the folder of contracts (every `*.json` except reports). Default `json_files_completed`, which a fresh checkout does not have, so always pass it |
| `--batch-dir DIR` | where transforms and reports go. Default `umat_oti_workspace/completed_json_batch` |
| `--validate` | also run the paired Abaqus validation for each clean transform (**needs Abaqus**) |
| `--abaqus-command`, `--abaqus-modules`, `--run-prefix` | how to start Abaqus (command name, environment modules, a prefix such as `srun`) |
| `--reuse-validation-results` | reuse existing comparison reports instead of rerunning Abaqus |

**Example** (no Abaqus):

```bash
umat-oti-batch --config-dir examples --batch-dir umat_oti_workspace/cli/batch
```

Output (4.2 s, exit code 0):

```text
wrote batch reports in <out>
UMAT_PCLK_actual_higher_order.json	ready_with_json_contract	Transformation succeeded; validation not requested.
UMAT_PCL_actual_higher_order.json	ready_with_json_contract	Transformation succeeded; validation not requested.
code_imp_actual_higher_order.json	ready_with_json_contract	Transformation succeeded; validation not requested.
elastic_minimal.json	ready_with_json_contract	Transformation succeeded; validation not requested.
hin_reference.json	ready_with_json_contract	Transformation succeeded; validation not requested.
j2_actual_higher_order.json	ready_with_json_contract	Transformation succeeded; validation not requested.
visco_imp_actual_higher_order.json	ready_with_json_contract	Transformation succeeded; validation not requested.
```

**Output files.** `completed_json_batch_report.json` and `.md` (one row per
contract with its category and status), `oti_transform/<name>/` (each
transform), `validation/` (filled only with `--validate`).

The exit code is 0 whenever the batch ran. Read each contract's category in
the report: `ready_with_json_contract`, `needs_json_completion`,
`blocked_by_user_marked_unsafe` or `transformation_generated_invalid_code`,
and, with `--validate`, the comparison status. `--validate` starts Abaqus; it
was not run for this guide.

---

## `umat-oti-provider build`

**Purpose.** Build the compiled **material provider** for parameter
sensitivities: the original UMAT and its OTI lift in one relocatable object,
with the entry points `UMAT`, `UMAT_OTI_EVAL`, `UMAT_OTI_MARCH` and
`UMAT_OTI_EVAL_TOTAL`, plus the completed contract (the mapping). The ABI is
described in [PROVIDER.md](PROVIDER.md).

**Synopsis:**

```text
usage: umat-oti-provider build [-h] --out OUT [--compiler COMPILER]
                               [--regular-object NAME.obj]
                               [--abaqus-toolchain] [--abaqus ABAQUS]
                               contract
```

| Option | Meaning |
| --- | --- |
| `contract` | a provider contract, schema `resasm_umat_transform_v2` (for example `parameter_sensitivity/models/m3_j2/contract_v2.json`) |
| `--out DIR` | output directory; must be outside the model's own folder. Required |
| `--compiler` | Fortran compiler (default `gfortran`) |
| `--regular-object NAME.obj` | also publish the original UMAT compiled unchanged under this name; its SHA-256 goes into the mapping |
| `--abaqus-toolchain` | build the regular object with `abaqus make` instead (**needs Abaqus**) |
| `--abaqus CMD` | the Abaqus command for `--abaqus-toolchain` (default `abaqus`) |

**Example.**

```bash
umat-oti-provider build parameter_sensitivity/models/m3_j2/contract_v2.json \
    --out umat_oti_workspace/cli/j2_provider --regular-object REAL_UMAT.obj
```

Output (6.1 s, exit code 0):

```text
{
  "object": "<out>/umat_m3_j2_oti.obj",
  "contract": "<out>/umat_m3_j2_oti.json",
  "build_dir": "<out>/build-<random>",
  "regular_object": "<out>/REAL_UMAT.obj"
}
```

**Output files.** The provider object `umat_m3_j2_oti.obj`; the mapping
`umat_m3_j2_oti.json` (dimensions, parameter order and OTI directions,
signatures, layouts, SHA-256 of both objects); `REAL_UMAT.obj`; and
`build-<random>/` with the generated sources. The build does **not** verify:
the mapping says `"validation": {"status": "not_run", "passed": false}`. Use
the collaborator package or the verifier below.

**When it refuses.** Measured:

```text
$ umat-oti-provider build parameter_sensitivity/models/m2_elastic3d/contract_v2.json --out <out>
provider build failed: provider supports only small_strain, not deformation-gradient kinematics   (exit code 2)

$ umat-oti-provider build parameter_sensitivity/models/m3_j2/contract_v2.json --out <out> --compiler no-such-fortran
provider build failed: compiler 'no-such-fortran' not on PATH                                       (exit code 2)
```

---

## `python -m umat_oti.provider.collaborator`

**Purpose.** The material developer's one-command hand-off. It runs
`umat-oti-provider build ... --regular-object REAL_UMAT.obj`, then the
independent verifier, checks that the shipped object is byte-identical to the
verified one, and copies the four shared files into `collaborator/`. This is
what the GUI's **Parameter Sensitivities** tab runs.

**Synopsis:**

```text
usage: collaborator.py [-h] --out OUT [--no-verify] [--abaqus-toolchain]
                       [--j2-branches]
                       contract
```

| Option | Meaning |
| --- | --- |
| `contract` | the provider contract |
| `--out DIR` | output directory. Required |
| `--no-verify` | build only |
| `--abaqus-toolchain` | build `REAL_UMAT.obj` with `abaqus make` (**needs Abaqus**) |
| `--j2-branches` | require the check path to cross elastic, plastic and unloading increments (J2-type materials) |

**Example.**

```bash
python -m umat_oti.provider.collaborator parameter_sensitivity/models/m3_j2/contract_v2.json \
    --out umat_oti_workspace/cli/j2_package --j2-branches
```

17.1 s, exit code 0. It prints the SHA-256 of the four shared files;
`collaborator/transform_report.txt` then reads `Verdict: verified`, with 628
entries agreeing, 240 consistent with zero, 0 unresolved and 0 disagreeing.
The full walk-through is [Example 3](../examples/03_j2_parameter_sensitivities/README.md).

**Output files.** `collaborator/` (`REAL_UMAT.obj`, `OTI_UMAT.obj`,
`Mapping.json`, `transform_report.txt`), `build/`, `verification/`
(`verification.json`, `verification_entries.csv`), `logs/` and `package.json`.

---

## `python -m umat_oti.validation.parameter_sensitivity_provider`

**Purpose.** The independent verifier of a provider. It builds its own copy of
the provider, compiles the original UMAT separately, checks primal parity to
round-off, and judges every entry of `DSIGMA_DP`, `DSTATEV_DP` and `DDSDDE`
(from EVAL and from MARCH) against centred finite differences of the original
over a ladder of steps. Each entry is *agrees*, *consistent with zero*,
*reference unresolved* (never counted as a pass) or *disagrees*. The loading
path is the contract's `validation.check_path`, or the provider's
seven-increment J2 path when the contract declares none.

**Synopsis:**

```text
usage: parameter_sensitivity_provider.py [-h] --out OUT [--elastic] contract
```

| Option | Meaning |
| --- | --- |
| `contract` | the provider contract |
| `--out DIR` | output directory. Required |
| `--elastic` | do not require the J2 branch sequence (use it for every non-J2 material) |

**Example.**

```bash
python -m umat_oti.validation.parameter_sensitivity_provider \
    parameter_sensitivity/models/m3_j2/contract_v2.json --out umat_oti_workspace/cli/j2_verify
```

The collaborator package of the previous section ran exactly this command on
2026-09-18 (exit code 0, verdict `verified`). It prints `verification.json`
and writes it with `verification_entries.csv` (one row per entry, with the
OTI value, the reference, its uncertainty, the step and the verdict). On
failure it exits with 2 and `verification.json` holds `"passed": false` and
the diagnostic.

---

## `python -m umat_oti.reproduce`

**Purpose.** Run a named reproduction profile and write five artefacts that
say what ran, what passed, and what could not run and why.

**Synopsis:**

```text
usage: python -m umat_oti.reproduce [-h] --profile
                                    {smoke,offline,paper,corpus,abaqus}
                                    [--out-dir OUT_DIR] [--allow-network]
```

| Option | Meaning |
| --- | --- |
| `--profile` | `smoke` (seconds: one UMAT transformed, compiled and checked), `offline` (every redistributable test), `paper` (regenerate the publication artefacts), `corpus` (the public-UMAT corpus), `abaqus` (smoke plus Abaqus availability) |
| `--out-dir DIR` | where to write the artefacts (default `reproduce/<profile>/`) |
| `--allow-network` | permit steps that fetch third-party sources |

**Example.**

```bash
python -m umat_oti.reproduce --profile smoke
```

```text
reproduce: profile=smoke out=<repository>/reproduce/smoke
  [                         succeeded] import_package (0.1s)
  [                         succeeded] material_point_smoke (4.7s)

wrote <repository>/reproduce/smoke/reproduction_summary.md
```

Exit code 0 in 6.0 s. The `offline`, `paper` and `corpus` profiles were not
run for this guide.

**Output files.** `reproduction_summary.md` (read this),
`run_manifest.json`, `environment.json`, `claim_matrix.json`,
`artifact_checksums.sha256`, plus the step's own results. A step that needs
software that is not installed reports `blocked_by_external_dependency` with
the name of what is missing (examples in
[INSTALL.md](INSTALL.md#9-troubleshooting)).

---

## Related scripts

These are plain scripts rather than console commands. Run them from the
repository root.

| Script | Purpose | Documented in |
| --- | --- | --- |
| `python tools/run_parameter_sensitivity_sweep.py` | the parameter-sensitivity check over all twenty bundled models; always pass `--results-dir`, and give `--work-dir` as an absolute path | [Example 6](../examples/06_parameter_sensitivity_sweep/README.md) |
| `python tools/run_internal_jacobian_round.py` | discover, extract and verify the internal Jacobians of every bundled model; pass `--results-dir` for your own runs | its `--help` |
| `python examples/verify_internal_jacobian.py` | the internal-Jacobian check of the bundled flow model; give `--out` as an absolute path | [Example 5](../examples/05_internal_newton_jacobian/README.md) |
| `python tools/audit_documentation_commands.py` | check that every documented command, script and link resolves | its `--help` |

The GUI (`streamlit run scripts/app.py`) calls the same functions as these
commands: [GUI_GUIDE.md](GUI_GUIDE.md).
