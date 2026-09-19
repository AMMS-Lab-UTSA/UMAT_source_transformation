# GUI screen reference

This is the reference for each screen of the UMAT-OTI graphical interface: what
every field means, which function a button calls, what it writes, the
equivalent command, and what was measured. For a step-by-step walkthrough, read
[GUI_GUIDE.md](GUI_GUIDE.md) first.

Every button calls the same Python function as a command-line entry point, so a
screen never computes something the command line would not. Each section below
gives the matching command.

## Launch

From the repository root, with the package installed (`pip install -e .`;
Streamlit is a core dependency) and `gfortran` on `PATH`:

```bash
streamlit run scripts/app.py
```

Headless, on a chosen port (this is how the browser tests start it):

```bash
streamlit run scripts/app.py --server.headless true --server.port 8501
```

## Screens at a glance

| Tab | Purpose | Needs |
|---|---|---|
| Start here | what the tool does, which tools this machine has, and a demo that runs end to end | `gfortran` |
| Constitutive Jacobian | transform a UMAT so `DDSDDE` is computed by OTI, from four fields and one click | `gfortran` |
| Parameter Sensitivities | build and verify the compiled provider (`OTI_UMAT.obj`, `Mapping.json`, `REAL_UMAT.obj`, `transform_report.txt`) | `gfortran`; Abaqus optional |
| 1. Load Config | choose or upload a JSON contract that drives tabs 2 to 5 | nothing |
| 2. Transform | transform the loaded contract's UMAT, optionally compiling it | `gfortran` |
| 3. Validate | run the original and the transformed UMAT in Abaqus on the same job and compare | Abaqus |
| 4. Constitutive Jacobians | original versus OTI tangent, component by component and increment by increment | tab 3's results |
| 5. Report | the validation workspace's reports and files, for download | tab 3's results |
| 6. Corpus | every acquired third-party UMAT and how far it got | a corpus batch's results |

The first three tabs are the material developer's side of the workflow. The
numbered tabs are the contract-driven console.

## Where the screens write

The Constitutive Jacobian and Parameter Sensitivities screens write under
`umat_oti_workspace/gui/` in the checkout (git-ignored). Set
`UMAT_OTI_GUI_WORKSPACE` to write somewhere else. Each click gets a new
directory, so an earlier result is never overwritten.

The numbered tabs write under `umat_oti_workspace/` in the working directory;
set `UMAT_OTI_WORKSPACE` to change that.

## Start here

The first tab explains what the tool does and reports whether `gfortran` and
the configured Abaqus command are on `PATH`. Tabs up to Transform need only
`gfortran`; Validate and later need Abaqus. The tab also offers a demo contract
that runs end to end.

## Constitutive Jacobian

![Constitutive Jacobian screen after Transform on the m3_j2 UMAT](screenshots/umat_constitutive_jacobian.png)

Load a UMAT, set the number of stress components, and click **Transform**. The
screen differentiates `STRESS` with respect to `DSTRAN` and writes the result
into `DDSDDE`; it finds the tangent block for you.

| Field | What it is |
| --- | --- |
| Fortran source file (.for) | an upload, or a path on this machine |
| Number of stress components (NTENS) | 3, 4 or 6. The screen suggests a value from the source; the user decides |
| differentiate with respect to / of the output / write into | `DSTRAN` / `STRESS` / `DDSDDE` by default |
| Tangent block (detected automatically) | read-only: what happens to the lines that assign DDSDDE, and the variables the transform will carry through the derivative. A hand-written tangent after the stress update is *replaced*. An assignment that the stress update itself reads (an elastic stiffness used as the predictor) is *kept*. The OTI extraction that fills DDSDDE is written after the named line |

**What it calls.** `umat_oti.services.jacobian_request.run_jacobian_transform`
([source](../src/umat_oti/services/jacobian_request.py)). It writes a compact
contract with `replace` left empty. The transformer's own anchor inference
(`merge_completed_anchors_into_config` in
`src/umat_oti/core/transformation_anchors.py`) then finds the DDSDDE block. The
function then runs `umat_oti.services.transformation.run_transformation`, the
service behind every other front end. The preview shown before the click comes
from the same two steps, run without writing anything.

**What it writes.** A fresh directory `jacobian/<source>-XXXX/` holding:

- `jacobian_contract.json`, the four fields as a contract;
- the transformed source (for the J2 model, `umat_oti.for`);
- the drop-in `umat_oti_combined.f90`, which contains the transformed routine
  together with every OTI module it needs;
- the OTI modules, `derivative_manifest.json`, and
  `transform_report.txt`/`.json`.

You can download the transformed UMAT, the drop-in, the report and the
contract.

**The same thing from a terminal.** The screen prints this command:

```bash
umat-oti jacobian path/to/umat.for --ntens 6 --out out_dir
# equivalently, from the contract the screen wrote:
umat-oti-config --config out_dir/jacobian_contract.json --out out_dir2
```

Add `--compile` to `umat-oti jacobian` to compile the generated Fortran with
`gfortran`.

**Measured (2026-09-18).**

- **m3_j2** (`parameter_sensitivity/models/m3_j2/umat.for`, NTENS 6). The
  screen shows "86-108 replaced; 38-48 kept (read by the stress update);
  extraction after line 111". It carries DEQPL, EQPLAS, FLOW, SHYDRO, SMISES,
  STATEV, STRESS, SYIEL0 and SYIELD, and reports 0 blockers, 0 warnings and
  21 of 21 structural checks passed. The downloaded `umat_oti.for` and the
  drop-in are byte-identical to the output of `umat-oti jacobian` and of
  `umat-oti-config` with the written contract. The drop-in's DDSDDE was checked
  against centred finite differences of the separately compiled ORIGINAL
  routine at all 7 increments of the provider check path (elastic, plastic
  and unloading increments), at E=200000, nu=0.3, SIGY0=250, H=2000. Primal
  stress differed by at most 3.6e-15 (stress scale 684). Scaled tangent errors
  were 3.25e-8, 3.25e-10 and 2.95e-11 at strain steps 1e-6, 1e-7 and 1e-8.
- **Elastic example** (`UMATs/UMATs/ICP/elasticity/elastic.f`, NTENS 4). The
  screen shows "83-87 replaced; extraction after line 87". The transformed
  `elastic_oti.f` is byte-identical to what the hand-written
  `examples/elastic_minimal.json` produces. The tangent's scaled errors against
  finite differences of the original were at most 2.8e-12.
- **FCC crystal plasticity** (`parameter_sensitivity/models/m6_fcc/umat.for`,
  NTENS 6, 12 slip systems). Its only DDSDDE assignment is the elastic
  stiffness at line 132, before the stress update. The screen shows "131-133
  kept (read by the stress update); extraction after line 189". It carries
  BASE, DEP, DG, DGAM, DSUB, GDOT, GRES, HALP, R2, RATIO, STATEV, STRESS and
  TAU, with 21 of 21 structural checks passed, and the output is
  byte-identical to the CLI's. The drop-in's DDSDDE was compared with centred
  finite differences of the original at the ten reference parameter values
  (see [Parameter Sensitivities](#parameter-sensitivities)) on the provider
  check path scaled by 0.3; the unscaled path gives non-finite values in the
  original. Scaled errors were 4.57e-5, 4.57e-7 and 4.57e-9 at steps 1e-6,
  1e-7 and 1e-8. Each tenfold step reduction divides the error by 100, which is
  the h² truncation of the centred difference converging on the OTI value. On
  the path scaled by 0.1 the errors were 1.69e-8, 1.69e-10 and 9.84e-12.

![Constitutive Jacobian on the 12-slip-system FCC routine](screenshots/umat_constitutive_jacobian_fcc.png)

## Parameter Sensitivities

![Parameter Sensitivities after Build for m3_j2](screenshots/umat_parameter_sensitivities_j2.png)

Take the UMAT loaded on the Constitutive Jacobian screen (or another source),
list the parameters with their PROPS index and value, tick the stress and state
derivatives, and click **Build OTI object**. The screen builds the OTI-enabled provider
and verifies it.

| Field | What it is |
| --- | --- |
| use the UMAT from the Constitutive Jacobian screen | ticked when that screen has a source; otherwise upload a file or give a path |
| Number of state variables (NSTATV) | the routine's physical state size |
| parameter / PROPS index / value | one row per parameter. The table starts empty. A source that is byte-identical to a shipped model (`parameter_sensitivity/models/*`) gets a button that fills the table from that model's contract |
| stress (DSIGMA_DP), state (DSTATEV_DP, auto) | the provider's derivative requests. DSIGMA_DP cannot be switched off, because it is what the provider builds. DSTATEV_DP is always carried when NSTATV > 0 |
| Options | model name (names the canonical `umat_<name>_oti.obj`); verification on or off; the **check path** (the provider's seven-increment J2 path, the sweep's declared uniaxial-strain path, or tension with shear); whether the check path must cross the J2 branch sequence; whether to build `REAL_UMAT.obj` with the **Abaqus toolchain** (`abaqus make`; ticked when `abaqus` is on `PATH`) |

The provider needs the original routine, not the DDSDDE-transformed file: it
lifts the original itself, with one OTI direction per parameter plus the six
strain directions. That is why this screen reuses the *source* the
Constitutive Jacobian screen loaded.

NPROPS is the largest PROPS index in the table, and every slot up to it must
have a row. The independent check replays the original routine, and that needs
a value in every slot.

**What it calls.** `umat_oti.provider.collaborator.package`
([source](../src/umat_oti/provider/collaborator.py)) runs two existing commands
as subprocesses and keeps their exit codes:

```bash
python -m umat_oti.provider build contract_v2.json --out out/build --regular-object REAL_UMAT.obj [--abaqus-toolchain]
python -m umat_oti.validation.parameter_sensitivity_provider contract_v2.json --out out/verification
```

The first is `umat-oti-provider build`. The second is the provider's
independent check on the contract's `validation.check_path`. It checks primal
parity against the separately compiled ORIGINAL, then judges every entry of
DSIGMA_DP, DSTATEV_DP and DDSDDE against centred differences of the ORIGINAL
over a ladder of steps. Each entry is *agrees*, *consistent with zero*,
*reference unresolved* (never counted as agreement) or *disagrees* (see
[PROVIDER.md](PROVIDER.md#verify)).

The verifier builds its own copy of the object. Builds compile relative file
names and reproduce byte for byte, so the package requires the shipped object
to be byte-identical to the verified one. It also evaluates both objects
through the verifier's ABI client on the check path, and checks that the
generated Fortran sources are identical.

**What it writes.** A fresh directory `provider/<model>-XXXX/` with:

- the staged model (`<model>/umat.for`, `contract_v2.json`);
- `out/build/`: the provider's canonical `umat_<model>_oti.obj` and `.json`,
  `REAL_UMAT.obj`, and the retained `build-*` sources;
- `out/verification/verification.json`, `out/logs/` and `out/package.json`;
- `out/collaborator/`: the four files a material developer hands to a
  collaborator.

| File | Content |
| --- | --- |
| `REAL_UMAT.obj` | the ORIGINAL UMAT compiled unchanged. With the Abaqus toolchain it is what `abaqus make` produces (the Abaqus site compiler and flags; ifort on the development workstation); otherwise it is the same object the provider bundles |
| `OTI_UMAT.obj` | the provider: the original routine plus the differentiated one (`umat_oti_eval_`, `umat_oti_eval_total_`, `umat_oti_march_`) |
| `Mapping.json` | the provider's generated contract, unchanged. It records both objects' SHA-256 (`object.sha256_full`, `regular_object.sha256_full`) |
| `transform_report.txt` | the build and verification commands with their exit codes; the parameter table; the check path; primal parity; the per-array counts of verified, zero and unresolved entries with the worst relative error; every unresolved column with its reason; the regular object's toolchain; and the tie between the shipped and the verified object |

All four can be downloaded. The source is not among them. The same package
from a terminal:

```bash
python -m umat_oti.provider.collaborator model_dir/contract_v2.json --out out --j2-branches
```

Exit code 0 means built and verified, 1 means built but not verified, and
2 means not built. `--no-verify` builds only; `--abaqus-toolchain` builds
`REAL_UMAT.obj` with `abaqus make`.

**Measured (2026-09-18).**

- **m3_j2** at E=200000, nu=0.3, SIGY0=250, H=2000 (NSTATV 1, the provider's
  J2 path, J2 branch sequence required). Build exit 0, verification exit 0,
  verdict *verified*. Branches: elastic, elastic, plastic, plastic, elastic,
  plastic, elastic. Primal parity: stress 3.6e-15, state 2.2e-19. Every column
  agrees: 628 entries are determined to the tolerance and agree, 240 are zero to
  within the reference, none are unresolved and none disagree. Worst relative
  error of the agreeing entries: DSIGMA_DP 1.9e-9, DSTATEV_DP 3.6e-11, DDSDDE
  7.6e-10 (tolerance 2e-6 per entry). The shipped `OTI_UMAT.obj` is
  byte-identical to the verified build. The manuscript's Table 5 reports
  largest differences of 5.98e-11 and 1.37e-10; this check reports the worst
  per-entry relative error, a different quantity, so those numbers are not
  expected to reappear here.
- **m6_fcc** with the ten reference parameter values (C11=168000, C12=121000,
  C44=75000, g0=13, gsat=55, h0=800, a=2, q=1.4, gd0=0.001, m=0.05; NSTATV 12)
  on **tension with shear** (20 increments of 1e-4 in 11 and 1e-4 engineering
  shear in 12). Build exit 0, verification exit 0, verdict *verified*. The slip
  resistances grow to 2.52 (g0 = 13), so the path yields. Primal parity: stress
  2.8e-13, state 1.8e-15. All 10 columns of DSIGMA_DP and DSTATEV_DP agree, as
  do all 6 DDSDDE columns: 4,556 entries agree, 1,572 are zero to within the
  reference, 112 are unresolved (small entries whose reference scatter exceeds
  2e-6 of their size), and none disagree. Worst relative errors: DSIGMA_DP
  5.7e-8, DSTATEV_DP 1.0e-9, DDSDDE 3.5e-8.
- The same FCC table on the sweep's declared **uniaxial-strain** path
  (`parameter_sensitivity/loading_paths.json`, 20 increments of 1e-4 in 11):
  verdict *verified_with_unresolved_columns*. Nine parameters agree. The C44
  column is reported unresolved ("every entry is zero to within the
  reference's resolution"), because uniaxial strain along the cube axis puts no
  shear stress on the crystal, so the derivative is zero along the path.
- On the provider's default J2 path the FCC routine returns non-finite values
  (strain increments up to 3.2e-3 per unit time). The objects are built, the
  verifier exits 2 with "nonfinite", and the screen says so.

![Parameter Sensitivities after Build for the ten-parameter FCC model](screenshots/umat_parameter_sensitivities_fcc.png)

## 1. Load Config

Choose a JSON contract from the list or upload one. The list shows every
contract in `examples/` (curated examples, the place to start), `json_files/`
(the benchmark contracts used in the paper) and `user_jsons/` (your own). A
contract that fails to load shows its error on the screen instead of stopping
the application. The selected contract drives tabs 2 to 5. The contract format
is described in
[new_user_umat_starter/JSON_REFERENCE.md](../new_user_umat_starter/JSON_REFERENCE.md).

## 2. Transform

Transforms the loaded contract's UMAT with
`umat_oti.services.transformation.run_transformation`, the same service as
`umat-oti-config --config CONTRACT --out DIR`. The stress update is rewritten
in OTI arithmetic and the hand-written `DDSDDE` is replaced with values
extracted from it; the constitutive logic is not re-derived. You choose the
output directory (by default `umat_oti_workspace/gui_<name>/oti_transform/<name>`)
and whether to compile the generated Fortran with `gfortran`.

## 3. Validate

Builds a paired validation workspace, runs the original and the transformed
UMAT through the same single-element Abaqus job, extracts the results and
compares them (`umat_oti.validation.job_builder`, `abaqus_runner` and
`compare_results`). The tab is locked until a transform exists. Without Abaqus
on `PATH` you can still build the workspace and inspect the decks it writes,
then run them wherever Abaqus is installed.

## 4. Constitutive Jacobians

Tables and line plots of the original and the OTI-transformed tangent,
component by component and increment by increment, read from the results that
tab 3 wrote. The tab is locked until a validation workspace exists.

## 5. Report

The validation workspace's comparison and validation reports, and its files
for download. The tab is locked until a validation workspace exists; the
transform's own artefacts (the drop-in UMAT, the derivative manifest and the
transform report) are on tab 2 and do not need Abaqus.

## 6. Corpus

Every acquired third-party UMAT, how far it got, and where to look, drawn from
the records of a corpus batch run. Set `UMAT_OTI_CORPUS_RESULTS` and
`UMAT_OTI_CORPUS_WORK` to that run's `results` and `work` directories; by
default the tab reads `corpus_run/results` and `corpus_run/work` beside the
checkout. The method and the records are described in
[CORPUS_VERIFICATION.md](CORPUS_VERIFICATION.md).

## Tests

| Test | What it drives | Run |
| --- | --- | --- |
| `tests/gui/test_developer_screens.py` | both developer screens through `streamlit.testing` (AppTest): GUI output against `umat-oti jacobian` and `umat-oti-config` for m3_j2, elastic and m6_fcc; the elastic output against the curated example; the downloaded tangent against finite differences of the original (J2, elastic, and the FCC convergence); the J2 and FCC builds against the verifier CLI; and the table and tick rules | the offline suite |
| `tests/test_provider_regular_object.py` | `umat-oti-provider build --regular-object`: the object is the bundled original; its hash is in the contract; linked alone it replays the original bit for bit; no directory of the developer's appears in either object or the mapping; a rebuild elsewhere is byte-identical; `--abaqus-toolchain` gives the `abaqus make` object (marked `abaqus`) | the offline suite |
| `tests/test_provider_check_path_and_verdicts.py` | the check path read from the contract; the four verdicts on synthetic ladders; a wrong DSIGMA_DP (all entries off by 1e-5, or one entry off by 1e-3) is caught; m6_fcc at the reference values verifies on tension with shear and reports C44 unresolved on uniaxial strain | the offline suite |
| `tests/gui/test_developer_screens_browser.py` | the same flows in headless Chromium, as a user performs them: upload, type the table, tick, click, download. Compares with the CLI and writes the screenshots above | `python -m pytest -m gui tests/gui` |

Browser tests need Playwright and a Chromium build
(`pip install -e ".[screenshots]"`, then `playwright install chromium`). They
start their own Streamlit server and stop only that process, and they are
deselected unless `-m gui` is given (see
[tests/gui/conftest.py](../tests/gui/conftest.py)).

## Limits

- The provider screen builds what the provider supports: three-dimensional
  (NTENS 6), small-strain, first-order STRESS-with-respect-to-PROPS providers
  ([PROVIDER.md](PROVIDER.md#limits)).
- The check path is a choice, recorded in the report. A column whose derivative
  is zero along the chosen path (C44 on uniaxial strain) is reported
  unresolved, not verified; verifying it needs a path that exercises it.
- `REAL_UMAT.obj` in Abaqus: on Linux, Abaqus accepts a precompiled user object
  only with the `.o` extension, so copy it to `REAL_UMAT.o` (same bytes). Built
  with the provider's compiler it refers to `_gfortran_runtime_error_at` (from
  its bounds checks), which Abaqus does not load; the Abaqus toolchain avoids
  that. See the next section for an abort at job teardown and its cause.

## Running `REAL_UMAT.obj` in Abaqus

Measured on 2026-09-18 with Abaqus 2021.HF5 on a one-element example deck (one
C3D8, four increments; `Analysis.inp` from the Residual Assembler's examples),
running jobs `gui_*` one at a time:

| Job | `user=` | How run | .sta | Process |
| --- | --- | --- | --- | --- |
| `gui_real` | gfortran REAL_UMAT (SHA-256 53bac302...) | as usual | COMPLETED SUCCESSFULLY | aborted: "buffer overflow detected", signal 6, exit 1 |
| `gui_ifort` | `abaqus make` object of the same source | as usual | COMPLETED SUCCESSFULLY | aborted the same way |
| `gui_noLD` | gfortran REAL_UMAT | `LD_LIBRARY_PATH` unset | COMPLETED SUCCESSFULLY | aborted the same way |
| `gui_clean` | `--abaqus-toolchain` REAL_UMAT (SHA-256 deefc08a..., the same bytes the GUI build gives for m3_j2) | in a new PID namespace | COMPLETED SUCCESSFULLY | **clean: "Abaqus JOB gui_clean COMPLETED", exit 0** |
| `gui_gfns` | gfortran REAL_UMAT (SHA-256 fed08fae..., path-free build) | in a new PID namespace | COMPLETED SUCCESSFULLY | clean, exit 0 |

The exported U, RF, CF, S and SDV1 of all five frames of `gui_clean` and
`gui_gfns` equal those of a reference job in which Abaqus compiled the same
source itself, with a maximum absolute difference of 0.

**The abort is not caused by the user object's compiler.** The abort's call
stack (`*.exception`) ends in Abaqus's own finalisation:
`SMAAspSupport_finalize -> bcu_cleanup -> for_inquire -> ... ->
fname_from_piped_fd -> __sprintf_chk -> __chk_fail`. That code is in
`libifcoremt.so.5`, the Intel Fortran runtime bundled with Abaqus. Disassembly
shows `fname_from_piped_fd` formatting the process ID with `"%d"` into a 7-byte
stack buffer (`__sprintf_chk(buf, 1, 7, "%d", pid)`). A PID of 1,000,000 or more
needs 8 bytes, so glibc's FORTIFY check aborts the process.

The development workstation allows PIDs up to 4,194,304
(`/proc/sys/kernel/pid_max`), and its PIDs had passed 1,000,000. Other Abaqus
jobs on the same workstation agree: 205 left an exception file (PIDs 1,071,012
to 1,684,135), and 204 of them stopped in the same `fname_from_piped_fd` frame.
They include all 126 cantilever runs, in which Abaqus compiled the user source
with its own ifort. In a PID namespace (`unshare -r -p -f --mount-proc`) the
solver's PID is small, and both objects run clean.

**What to do.** Judge a job by its `.sta` file, or run it where PIDs are below
1,000,000, for example:

```bash
unshare -r -p -f --mount-proc sh -c 'abaqus job=NAME input=Analysis.inp user=REAL_UMAT.o interactive'
```
