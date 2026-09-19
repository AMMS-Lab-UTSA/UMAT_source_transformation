# UMAT-OTI usage report

This page shows what UMAT-OTI does, how to install and use it, what it has
been checked against, and where its limits are. Every command below runs from
the repository root as written. The numbers were measured on 2026-09-18 on
Linux (Ubuntu 20.04) with Python 3.11.7 and gfortran 9.4.0, unless a section
says that a number comes from a linked record.

UMAT-OTI rewrites the Fortran source of an Abaqus user material (UMAT) so that
its derivatives are computed exactly with order-truncated imaginary (OTI)
numbers, instead of being derived by hand or approximated by finite
differences. From one real-valued UMAT it produces:

- the consistent tangent `DDSDDE = dSTRESS/dDSTRAN`, as a drop-in UMAT;
- the Jacobian of the model's own local Newton iteration;
- higher-order stress derivatives;
- parameter and state sensitivities `DSIGMA_DP = dSTRESS/dPROPS` and
  `DSTATEV_DP = dSTATEV/dPROPS` along a loading history, packaged as a
  compiled **material provider** (`OTI_UMAT.obj` + `Mapping.json`, with the
  original routine as `REAL_UMAT.obj`).

The companion program
[Residual_Assembler](https://github.com/AMMS-Lab-UTSA/Residual_Assembler)
consumes that provider together with a finished Abaqus analysis and returns
parameter sensitivities of the finite-element solution.

## 1. Supported scope

| Capability | Entry point | Scope |
| --- | --- | --- |
| Consistent tangent `DDSDDE` | `umat-oti jacobian`, `umat-oti config`, GUI tab **Constitutive Jacobian** | NTENS 3, 4 or 6; first and higher order; the tangent block is found automatically, or named in a JSON contract |
| Compiled parameter-sensitivity provider | `umat-oti-provider build`, `python -m umat_oti.provider.collaborator`, GUI tab **Parameter Sensitivities** | 3D (NTENS 6), small strain, first-order `STRESS` with respect to `PROPS`; path-dependent state carried through the history; builds for 20 of the 21 bundled models |
| Per-entry verification of a provider | `python -m umat_oti.validation.parameter_sensitivity_provider` | every entry of `DSIGMA_DP`, `DSTATEV_DP` and `DDSDDE` judged against finite differences of the original |
| Internal (local Newton) Jacobian | `examples/verify_internal_jacobian.py`, `tools/run_internal_jacobian_round.py` | scalar Newton updates `X = X +/- A/B`, found by scanning the source |
| Paired Abaqus validation | GUI tabs **3. Validate** to **5. Report**, `umat-oti-batch --validate` | needs a licensed Abaqus |
| Reproduction profiles | `python -m umat_oti.reproduce` | `smoke`, `offline`, `paper`, `corpus`, `abaqus` |

The provider also exports the entry point `UMAT_OTI_EVAL_TOTAL`, which carries
total derivatives through any UMAT's state. Residual_Assembler's history
engine uses it ([PROVIDER_EVAL_TOTAL.md](PROVIDER_EVAL_TOTAL.md)). The provider
ABI is specified in [PROVIDER.md](PROVIDER.md).

Beyond the bundled models, 391 UMATs acquired from public repositories were
re-transformed and run in Abaqus at the current transform generation (see
section 9): 240 transform, and 43 of the 260 adequately specified genuine UMATs
clear all six acceptance gates. Every other source carries a named reason.
Census: [paper_results/corpus/CORPUS_VERIFICATION.md](../paper_results/corpus/CORPUS_VERIFICATION.md);
method: [CORPUS_VERIFICATION.md](CORPUS_VERIFICATION.md).

## 2. Known limits

- **Kinematics.** The provider accepts small-strain contracts only. A
  deformation-gradient contract is refused by name: `provider build failed:
  provider supports only small_strain, not deformation-gradient kinematics`.
- **Provider shape.** Only 3D (NTENS 6), first-order `STRESS` with respect to
  `PROPS`. Its EVAL entry point has no `KINC`, coordinates, rotations or
  predefined fields; it passes neutral values for them (see
  [PROVIDER.md](PROVIDER.md)).
- **Refused constructs.** Some constructs are refused with a named diagnostic,
  for example LAPACK calls on the stress path or helper routines whose source
  is not available. The corpus census lists every refusal and its reason.
- **The check path matters.** A derivative can only be verified on a loading
  path that exercises it. A column that is zero along the chosen path is
  reported *unresolved*, never as verified.
- **One verifier edge case.** At the FCC model's shipped constants on the
  tension-with-shear path, one round-off-sized entry (about `1e-15`) is judged
  *disagrees*, and the verification fails. With the constants of
  [Example 4](../examples/04_fcc_crystal_plasticity_provider/README.md) every
  entry passes. The example's README gives the details.
- **Pipeline exit code.** A full `umat-oti-pipeline` run exits with 1 because
  its `abaqus_validation` stage is not yet routed through the pipeline and
  reports `unsupported`. Read `run_manifest.json`, or run the stages you need
  with `--only` ([CLI_GUIDE.md](CLI_GUIDE.md#umat-oti-pipeline)).
- **Platforms.** Linux with gfortran is tested. Windows and macOS are not;
  on Windows, use WSL 2.
  Compiled objects are specific to the platform and compiler.

## 3. Installation

Requirements: Linux, Python 3.10 or newer, `gfortran` and `make`. Abaqus and
the Intel Fortran compiler are optional; they are needed only for the Abaqus
paths.

```bash
git clone https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation.git
cd UMAT_source_transformation
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m umat_oti.reproduce --profile smoke
```

In a new virtual environment, `pip install -e ".[test]"` took 23.9 s and
`python -m pip check` reported no broken requirements. The smoke check
transforms one J2 UMAT, compiles it and the original separately, and compares
their derivatives. It exited 0 in 6.6 s with `import_package` and
`material_point_smoke` both `succeeded`.

A missing tool is reported by name and never counts as a pass. For example,
without gfortran the smoke step reports `blocked_by_external_dependency` with
the reason `gfortran is not on PATH`. Never install the unrelated PyPI package
`pyoti`.

The full guide, including the companion Residual_Assembler, the optional
Abaqus setup and troubleshooting, is [INSTALL.md](INSTALL.md).

## 4. Command-line entry points

| Command | Use it to | Measured example |
| --- | --- | --- |
| `umat-oti jacobian SOURCE --ntens N --out DIR [--compile]` | get `DDSDDE` from four fields, without a contract | J2 UMAT: 21/21 structural checks, compiled, exit 0, 2.2 s |
| `umat-oti config CONTRACT --out DIR [--compile]` or `umat-oti-config --config CONTRACT` | transform from a JSON contract | `examples/elastic_minimal.json`: exit 0, 1.8 s |
| `umat-oti-pipeline --config CONTRACT --work-dir DIR --compile` | run the 16-stage pipeline with a run manifest and resume | stage subset: exit 0; a cached rerun took 0.4 s |
| `umat-oti-batch --config-dir DIR --batch-dir DIR` | transform every contract in a folder | the 7 contracts in `examples/`: all `ready_with_json_contract`, 4.2 s |
| `umat-oti-provider build CONTRACT --out DIR [--regular-object REAL_UMAT.obj]` | build the compiled provider | J2: exit 0, 6.1 s |
| `python -m umat_oti.provider.collaborator CONTRACT --out DIR` | build, verify and package the four hand-off files | J2: `verified`, exit 0, 17.1 s |
| `python -m umat_oti.reproduce --profile NAME` | run a reproduction profile | `smoke`: exit 0, 6.0 s |
| `umat-oti transform SOURCE --out DIR` | the original whole-routine transform, kept for compatibility | |

Every console command also runs as a module, for example
`python -m umat_oti.cli jacobian ...`. [CLI_GUIDE.md](CLI_GUIDE.md) gives every
option, one worked invocation per command with its real output, the files each
command writes, and a table of exit codes.

## 5. Worked examples

Six complete examples live in [examples/](../examples/README.md). Each one has
a README with the mathematics, the exact commands, the GUI steps, the expected
output and its independent check. None needs Abaqus.

| # | Example | Headline result (measured 2026-09-18) | Run time |
| --- | --- | --- | --- |
| 1 | [Elastic tangent](../examples/01_elastic_tangent/README.md) | OTI `DDSDDE` equals the analytic isotropic stiffness exactly (difference 0) for two materials; stress identical to the original | 6 s |
| 2 | [J2 plasticity tangent](../examples/02_j2_plasticity_tangent/README.md) | Over elastic, plastic and unloading increments, centred finite differences of the original converge on the OTI tangent (100x smaller error per decade of step), best 2.3e-11; the source's own tangent agrees to 2.4e-16 | 8 s |
| 3 | [J2 parameter sensitivities](../examples/03_j2_parameter_sensitivities/README.md) | Provider `verified`: 628 entries agree, 240 consistent with zero, 0 unresolved, 0 disagree; object byte-reproducible; a separate check with `REAL_UMAT.obj` alone agrees to 2.3e-10 | 25 s |
| 4 | [FCC crystal-plasticity provider](../examples/04_fcc_crystal_plasticity_provider/README.md) | Ten parameters, twelve state variables, tension with shear: `verified`, 4,556 agree, 1,572 zero, 112 unresolved, 0 disagree | 40 s |
| 5 | [Internal Newton Jacobian](../examples/05_internal_newton_jacobian/README.md) | Bundled flow model: OTI vs finite differences 3.9e-12. Viscoplastic damage UMAT: OTI vs finite differences 2.7e-13, while the source's hand-coded Jacobian is 2.6e-2 away from the derivative of its own residual | 10 s |
| 6 | [Twenty-model sweep](../examples/06_parameter_sensitivity_sweep/README.md) | 20 of 20 models transform and match the original stress; 19 verified; 83 of 84 parameter directions; 14,539 of 14,540 comparison rows agree (the other is a 1.4e-10 entry reported as unresolved) | 1.5 min |

Each example was run twice on 2026-09-18: once in this checkout, and once in
a new virtual environment where every command block of its README ran as
written. All exited 0 and printed the numbers above.

## 6. The GUI

```bash
streamlit run scripts/app.py
```

Streamlit prints a local URL (by default `http://localhost:8501`). The
application has nine tabs:

- **Start here** runs a one-click demo: the elastic contract is transformed
  and compiled, with 21/21 structural checks.
- **Constitutive Jacobian** turns any UMAT into one that returns the exact
  `DDSDDE`, from four fields and one click. It writes byte-identical files to
  `umat-oti jacobian`.
- **Parameter Sensitivities** builds and verifies the provider from a
  parameter table, and offers the four hand-off files for download. It runs
  the same commands as `python -m umat_oti.provider.collaborator`.
- **1. Load Config** to **5. Report** form the contract-driven console. Tabs 3
  to 5 run the paired validation and need Abaqus.
- **6. Corpus** browses the results of a corpus round.

Driving the two main screens headlessly gave the same results as the
command line. For the FCC provider the screen showed "Build succeeded and
verified" after 33 s. `python -m pytest -q tests/gui/test_developer_screens.py`
reported `17 passed in 121.21s`.

The walkthrough, with screenshots, is [GUI_GUIDE.md](GUI_GUIDE.md); the
field-by-field reference is [GUI.md](GUI.md).

## 7. Connected workflow with Residual_Assembler

The material developer builds and verifies the provider and shares only
compiled files. The collaborator uses them with a finished Abaqus analysis and
never sees the Fortran source.

Install Residual_Assembler next to this repository, in the same environment
([INSTALL.md](INSTALL.md#7-install-the-companion-residual_assembler-optional)).
The commands below assume that layout (`../Residual_Assembler`).

**Step 1: the developer packages the provider** (Example 3; exit 0, 17.2 s):

```bash
python -m umat_oti.provider.collaborator parameter_sensitivity/models/m3_j2/contract_v2.json \
    --out umat_oti_workspace/connected/package --j2-branches
```

The folder `collaborator/` then holds `OTI_UMAT.obj`, `Mapping.json`,
`REAL_UMAT.obj` and `transform_report.txt`. The collaborator needs the first
two. `REAL_UMAT.obj` is the original routine for the regular analysis; Abaqus
on Linux accepts it only under the extension `.o`.

**Step 2: the collaborator requests sensitivities of a finished analysis.**
This needs the collaborator's own converged analysis (`Analysis.inp` and
`Analysis.odb`) and a licensed Abaqus, whose Python reads the ODB. It was
**not run** for this report.

```bash
resasm request --model <analysis>.inp --odb <analysis>.odb \
    --material umat_oti_workspace/connected/package/collaborator/OTI_UMAT.obj \
    --request <sensitivity_request>.json --out <results>
```

- `Mapping.json` is found automatically beside the object. Its SHA-256 of the
  object, parameter order and layouts are checked.
- The public outputs are `sensitivity_results.json`, `sensitivity_tables.csv`
  and `run_report.txt`. Full fields stay under `private/`.
- The request format, the supported models and the refused features (pressure
  and body loads, contact, amplitudes, several steps, initial state, finite
  strain) are specified in Residual_Assembler's
  [REQUEST_INTERFACE.md](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/docs/REQUEST_INTERFACE.md).

**Step 2 without Abaqus: replay a committed export.** Residual_Assembler ships
a J2 beam analysis (96 C3D8 elements, 10 increments) whose ODB is already
exported to `fields.npz`. `resasm history` replays it with the provider from
step 1:

```bash
resasm history --model ../Residual_Assembler/examples/replay_history/j2_beam/Analysis.inp \
    --fields ../Residual_Assembler/examples/replay_history/j2_beam/fields.npz \
    --material umat_oti_workspace/connected/package/collaborator/OTI_UMAT.obj \
    --request ../Residual_Assembler/examples/replay_history/j2_beam/sensitivity_request.json \
    --out umat_oti_workspace/connected/beam
```

Measured (exit 0, 1.1 s):

```text
history replay: 10 increments, 768 integration points, 4 parameters; yes: max|R_free| = 1.288e-03 N at increment 10 (limit 1.609e-01 N there)
```

- The replayed stress, state and reactions reproduce the recorded ODB at every
  integration point and increment, within 0.5 % of their single-precision
  limits.
- At the last increment the tip reaction is `-191.726` N. Its weighted
  sensitivities `p dRF2/dp` are `-35.31` (E), `-0.37` (nu), `-154.73` (SIGY0)
  and `-1.69` (H) N.

Adding `--reequilibrate --verify fd` (with a new `--out`) first brings every
increment to double-precision equilibrium, then checks the derivatives against
whole-model central finite differences of the original UMAT. That run exited 0
in 11.7 s. `run_report.txt` says:

```text
Tangent verified: yes: max relative error 1.88e-10 vs central FD of the ORIGINAL UMAT at 36 points (FD plateau spread 1.96e-10)
Derivative verified: yes: whole-model central FD of the ORIGINAL UMAT re-equilibrated in Python; worst nonzero-derivative error 1.46e-07 (plateau spread 3.05e-07); ...
```

A second check needs no finite differences. J2 plasticity with linear
hardening scales linearly with `(E, SIGY0, H)`, so
`E dQ/dE + SIGY0 dQ/dSIGY0 + H dQ/dH = Q` for a reaction `Q`. For the
re-equilibrated tip reaction this holds to a relative 4.3e-15.

The full-size cantilevers, the GUI of Residual_Assembler and the history
engine are documented in its repository:
[examples/replay_history](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/tree/main/examples/replay_history),
[examples/cantilevers](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/examples/cantilevers/README.md),
[docs/REPLAY_HISTORY.md](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/docs/REPLAY_HISTORY.md).

## 8. How results are verified

Nothing is reported as verified without an independent reference:

- **Finite differences of the original.** The untransformed UMAT is compiled
  separately and differenced over a ladder of steps. The reference is taken
  where the ladder is flattest, with an explicit uncertainty.
- **Four verdicts per entry.** Every derivative entry gets one of *agrees*,
  *consistent with zero*, *reference unresolved* or *disagrees*.
  *Unresolved* never counts as agreement, and one *disagrees* fails the
  verification ([PROVIDER.md](PROVIDER.md)).
- **Primal parity first.** The transformed build must reproduce the original
  stress and state to round-off before any derivative is compared.
- **Analytic references** where they exist: the isotropic stiffness
  (Example 1), homogeneity identities (section 7).
- **Abaqus.** The paired validation runs the original and the transformed
  UMAT in the same job and compares stress, state and tangent.

The claim-by-claim record, with the command, the reference and the measured
value of each result, is [VERIFICATION_RECORD.md](VERIFICATION_RECORD.md).
That record also covers the Abaqus comparison of the 18 benchmark UMATs.

## 9. Transform generation

Stored transforms and fixtures are evidence about the transform code that
produced them, and only about that code. The code is identified by a
fingerprint:

```bash
python -c "from umat_oti.store import transform_fingerprint; print(transform_fingerprint())"
```

It prints `16c9f305df378089`, the value recorded in
`src/umat_oti/contract/schemas/transform_generation.json` and read by both
repositories. At this generation:

- all 391 acquired corpus sources were re-transformed;
- all 240 transformed entries were run in Abaqus 2021.HF5;
- the corpus registry was rebuilt;
- the two current Residual_Assembler fixtures were regenerated and verified.

The procedure, the commands and the census are in
[evidence/final_refreeze.md](evidence/final_refreeze.md). The older collection
under `umat/` keeps its earlier generation and is read only as history.

## 10. Clean-install gate

Residual_Assembler's clean-install gate clones both repositories, builds and
installs their wheels in a new environment, and runs the connected workflow
from the installed packages. This includes `resasm request` on a genuine ODB
and the full-size J2 cantilever. Its record for the published `main` branches
(Residual_Assembler `3504a02`, UMAT-OTI `1352114`) reports:

- all 22 gate commands exited 0;
- UMAT-OTI's offline test suite: 3370 passed, 158 skipped, 0 failed.

See
[final_clean_clone.md](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/docs/evidence/final_clean_clone.md).
That record predates the commits after `1352114`, including the last
transform change (`5b97c2f`, which set the fingerprint above). The examples
and numbers in this report were measured on the current code.

## 11. Status and evidence

Requirement-level status is tracked in
[COMPLETION_LEDGER.md](COMPLETION_LEDGER.md). Run records are in
[evidence/](evidence/).
