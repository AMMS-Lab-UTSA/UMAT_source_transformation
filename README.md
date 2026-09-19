# UMAT-OTI

[![CI](https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation/actions/workflows/ci.yml/badge.svg)](https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation/actions/workflows/ci.yml)
[![License: GPL-3.0-only](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE.txt)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

**UMAT-OTI** rewrites the Fortran source of an Abaqus user material (UMAT) so
that its derivatives are computed exactly by order-truncated imaginary (OTI)
hypercomplex arithmetic instead of being derived by hand or approximated by
finite differences. From one real-valued UMAT it produces:

- the consistent tangent `DDSDDE = dSTRESS/dDSTRAN` as a drop-in Abaqus UMAT;
- local constitutive Jacobians of the model's own internal Newton solve;
- higher-order stress derivatives;
- parameter and state sensitivities `DSIGMA_DP = dSTRESS/dPROPS` and
  `DSTATEV_DP = dSTATEV/dPROPS` over a loading history, packaged as a compiled
  **OTI material provider** (`OTI_UMAT.obj` + `Mapping.json`) that a
  collaborator can use without ever seeing the source.

The companion project [Residual_Assembler](https://github.com/AMMS-Lab-UTSA/Residual_Assembler)
consumes that provider together with a converged Abaqus analysis
(`Analysis.inp` + `Analysis.odb`) and returns full-field parameter
sensitivities of the finite-element solution by the residual method. The two
are separate programs connected by a versioned contract.

**New here?** Install with [docs/INSTALL.md](docs/INSTALL.md) (about five
minutes), then work through the six [worked examples](examples/README.md). The
[command-line guide](docs/CLI_GUIDE.md) and the [GUI guide](docs/GUI_GUIDE.md)
cover every entry point, with real output. What has been verified, and how, is
in [docs/VERIFICATION_RECORD.md](docs/VERIFICATION_RECORD.md).

## Install

Linux with Python 3.10 or newer and `gfortran` (tested: Python 3.11.7,
gfortran 9.4). Abaqus and the Intel compiler are optional and only needed for
the Abaqus verification paths (tested: Abaqus 2021.HF5, ifort 2023.2.1).

```bash
git clone https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation.git
cd UMAT_source_transformation
python3 -m venv .venv && . .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m umat_oti.reproduce --profile smoke      # transform, compile, verify one J2 model (~10 s)
```

A missing `gfortran` or Abaqus is reported by name as
`blocked_by_external_dependency`; it never reads as a pass.

## The three things you can do

### 1. Constitutive Jacobian (DDSDDE) from four fields

```bash
umat-oti jacobian path/to/umat.for --ntens 6 --out out/j2 --compile
```

`--seed DSTRAN --response STRESS --target DDSDDE` are the defaults. The
transformer finds the existing tangent block itself, promotes the variables
the derivative chain needs, seeds all `NTENS` strain directions and writes the
transformed UMAT, the OTI support modules, `compile_order.txt`, a combined
single-file Abaqus source, `derivative_manifest.json` and `transform_report.txt`
(21 structural checks). For full control use a JSON contract
(`umat-oti-config --config contract.json --out DIR`; see
[new_user_umat_starter/JSON_REFERENCE.md](new_user_umat_starter/JSON_REFERENCE.md)).

### 2. OTI material provider with parameter and state sensitivities

```bash
umat-oti-provider build parameter_sensitivity/models/m3_j2/contract_v2.json \
    --out out/j2_provider --regular-object REAL_UMAT.obj
```

The compact v2 contract names the parameters and their `PROPS` indices. The
build compiles the ORIGINAL UMAT unchanged and its OTI lift into one
relocatable object with the entry points `UMAT`, `UMAT_OTI_INTERNAL`,
`UMAT_OTI_EVAL`, `UMAT_OTI_MARCH` and `UMAT_OTI_EVAL_TOTAL`
([docs/PROVIDER.md](docs/PROVIDER.md), [docs/PROVIDER_EVAL_TOTAL.md](docs/PROVIDER_EVAL_TOTAL.md)),
writes the completed contract (`Mapping.json`), and verifies stress parity and
every derivative column against centred finite differences of the original.

### 3. The GUI

```bash
streamlit run scripts/app.py
```

Tabs: **Start here** (one-click demo on the elastic example), **Constitutive
Jacobian** (upload a UMAT, set NTENS, Transform), **Parameter Sensitivities**
(parameter table, tick DSIGMA_DP / DSTATEV_DP, Build → `REAL_UMAT.obj`,
`OTI_UMAT.obj`, `Mapping.json`, `transform_report.txt`), then Load Config,
Transform, Validate (Abaqus), Constitutive Jacobians, Report and Corpus. Every
button calls the same service function as the CLI and produces byte-identical
files ([docs/GUI_GUIDE.md](docs/GUI_GUIDE.md)).

## Worked examples

Six complete examples, each with the mathematics in brief, the exact commands,
the equivalent GUI clicks, the measured output and how that output is checked
independently. None needs Abaqus; all run from the repository root in seconds
to a minute and a half ([examples/README.md](examples/README.md)).

| # | Example | What it shows |
| --- | --- | --- |
| 1 | [Elastic tangent](examples/01_elastic_tangent/README.md) | `DDSDDE` of a linear elastic UMAT equals the analytic isotropic stiffness exactly |
| 2 | [J2 plasticity tangent](examples/02_j2_plasticity_tangent/README.md) | The consistent tangent over elastic, plastic and unloading increments, against a step-size sweep of finite differences |
| 3 | [J2 parameter sensitivities](examples/03_j2_parameter_sensitivities/README.md) | `DSIGMA_DP` and `DSTATEV_DP` over a history, built into a compiled provider and verified entry by entry |
| 4 | [FCC crystal-plasticity provider](examples/04_fcc_crystal_plasticity_provider/README.md) | The same for 12 slip systems, ten parameters and twelve state variables |
| 5 | [Internal Newton Jacobian](examples/05_internal_newton_jacobian/README.md) | The Jacobian of a UMAT's own local Newton solve, against finite differences and the hand-coded one |
| 6 | [Twenty-model sensitivity sweep](examples/06_parameter_sensitivity_sweep/README.md) | Parameter sensitivities of all twenty bundled models, from transform to verification |

## Verified results

Every number below is measured by the command named, against an independent
reference: centred finite differences of the separately compiled original with
a step-size plateau, an analytic formula, or Abaqus. The full record, including
what did **not** reproduce, is [docs/VERIFICATION_RECORD.md](docs/VERIFICATION_RECORD.md).

| Example | Measured | Command |
| --- | --- | --- |
| DDSDDE of 18 benchmark UMATs (elastic, plastic, viscoplastic, damage, Cosserat) compared with the original in Abaqus | 17 of 18 agree from their committed contracts (12 exactly, 5 within tolerance); UMAT_NKH_1.02 agrees once PROPS(1) = 0, because with PROPS(1) ≠ 0 the source reads a variable it never sets | `python verification/run_all.py --abaqus` (in Residual_Assembler) |
| Parameter sensitivities DSIGMA_DP of 20 material models against finite differences | all 20 transform, compile and reproduce the original's stress; 19 verified in every direction; 83 of 84 parameter directions and 14,539 of 14,540 comparison rows agree (worst relative error 8.2e-7). The one remaining FCC direction is unresolved by the reference, not a disagreement | `python tools/run_parameter_sensitivity_sweep.py --work-dir <dir> --results-dir <dir>` ([Example 6](examples/06_parameter_sensitivity_sweep/README.md)) |
| Internal (local Newton) Jacobians of the ICP UMATs | OTI agrees with finite differences in all 21 (UMAT, Jacobian) pairs; 6 of the hand-coded Jacobians in those sources drop a damage factor | `python verification/run_all.py` (in Residual_Assembler) |
| J2 consistent tangent against finite differences of the original | 3e-11 (scaled) over elastic, plastic and unloading increments | `umat-oti jacobian` + `tests/gui/test_developer_screens.py` |
| Provider verification, entry by entry, J2 and FCC crystal plasticity | J2: 628 entries agree, 240 consistent with zero, none unresolved, none disagrees. FCC (tension with shear): 4,556 agree, 1,572 consistent with zero, 112 the reference cannot resolve, none disagrees | `python -m umat_oti.provider.collaborator <contract> --out <dir>` ([Examples 3](examples/03_j2_parameter_sensitivities/README.md) and [4](examples/04_fcc_crystal_plasticity_provider/README.md)) |

Corpus of 391 UMATs acquired from public repositories, re-transformed and run
in Abaqus at the current transform (2026-09-18): 240 transform, and 43
of the 260 adequately specified genuine UMATs clear all six acceptance gates
(Abaqus job, outputs, finite history, primal agreement, verified derivatives,
informative experiment). Every other source carries a named reason, and the 217
that are this project's to fix are counted as such. Census:
[paper_results/corpus/CORPUS_VERIFICATION.md](paper_results/corpus/CORPUS_VERIFICATION.md);
method: [docs/CORPUS_VERIFICATION.md](docs/CORPUS_VERIFICATION.md).

## Tests

```bash
python -m pytest -q                    # offline suite: no Abaqus, no network
python -m pytest -q -m gui             # browser tests of the GUI screens (playwright)
python -m pytest -q -m abaqus          # tests that need a licensed Abaqus
python -m pytest -q -m corpus_pass     # re-run the whole store in Abaqus (hours)
```

A skipped test names the missing prerequisite; a skip is not a pass.

## Documentation

| Document | What it covers |
| --- | --- |
| [docs/INSTALL.md](docs/INSTALL.md) | Installation from a clean machine, the checks that prove it works, troubleshooting |
| [examples/README.md](examples/README.md) | Six worked examples |
| [docs/CLI_GUIDE.md](docs/CLI_GUIDE.md) | Every command, its options, real output and exit codes |
| [docs/GUI_GUIDE.md](docs/GUI_GUIDE.md) | A step-by-step walkthrough of every GUI screen |
| [docs/USAGE_REPORT.md](docs/USAGE_REPORT.md) | The current state of the program in one place: scope, commands, results |
| [docs/VERIFICATION_RECORD.md](docs/VERIFICATION_RECORD.md) | Every verified result, how it is reproduced, the reference and the measured value |
| [docs/PROVIDER.md](docs/PROVIDER.md) | The compiled OTI provider and its ABI |
| [docs/GUI.md](docs/GUI.md) | The GUI's design and each screen, with screenshots |
| [docs/CORPUS_VERIFICATION.md](docs/CORPUS_VERIFICATION.md) | The public-UMAT corpus and its acceptance gates |
| [docs/SOFTWAREX_REPRODUCTION.md](docs/SOFTWAREX_REPRODUCTION.md) | Reproducing the paper's tables and figures |
| [new_user_umat_starter/](new_user_umat_starter/README.md) | Writing a contract for your own UMAT |

## Known limits

- Small-strain kinematics for the parameter-sensitivity provider; finite-strain
  UMATs are refused with a named reason rather than guessed.
- Some constructs are refused with a named diagnostic (for example LAPACK
  calls on the stress path, some helper routines without source); the corpus
  census lists every refusal and its reason.
- Windows is not tested; use Linux or WSL.

## Citing, contributing, license

Cite with [CITATION.cff](CITATION.cff); contribute via [CONTRIBUTING.md](CONTRIBUTING.md).
UMAT-OTI is GPL-3.0-only ([LICENSE.txt](LICENSE.txt)); it builds on template
code from OTILib / pyoti by Mauricio Aristizabal
(https://github.com/mauriaristi/otilib) — see [COPYRIGHT](COPYRIGHT) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Proprietary Abaqus
verification-manual UMATs are not included.
