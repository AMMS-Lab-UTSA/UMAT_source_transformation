# Example 6: Parameter sensitivities of twenty material models in one command

**Level:** survey · **Needs:** Python, gfortran, make · **Abaqus:** not needed · **Run time:** about 1.5 min

## What this example shows

Examples 3 and 4 treat one material at a time. This example runs the same
kind of check over **all twenty material models that ship with the
repository**: linear, cubic, orthotropic and transversely isotropic
elasticity, damage, J2 plasticity with isotropic, kinematic and combined
hardening, Drucker-Prager, Perzyna and Maxwell viscous models, a thermally
activated flow rule, FCC crystal plasticity, and self-contained versions of two
UMATs from [UMATs/UMATs/ICP/](../../UMATs/UMATs/ICP/) (temperature-dependent
elasticity and couple-stress plasticity).

For every model it records a **funnel**: was the contract generated, did the
transform succeed, did the OTI build compile and run, did the original run,
do their stresses agree, and do the parameter sensitivities agree with finite
differences of the original. A model that stops early stays in the count with
its reason. Nothing is dropped from the denominator.

### The mathematics, briefly

For each model and each declared parameter `p_k`, the OTI build returns
`d STRESS / d p_k` and `d STATEV / d p_k` at every increment of a loading path.
The reference is a centred finite difference of the separately compiled
original UMAT, replayed over the whole path with `p_k ± h`, over a ladder of
steps. A comparison row agrees when the OTI value is within the reference's
resolution or within the relative tolerance of the converged reference.

## Inputs

| Input | Path |
| --- | --- |
| The twenty models (one folder each, with `umat.for` and `contract_v2.json`) | [parameter_sensitivity/models/](../../parameter_sensitivity/models/) |
| The loading path used for every model (uniaxial strain, 20 increments of `1e-4` in `11`) | [parameter_sensitivity/loading_paths.json](../../parameter_sensitivity/loading_paths.json) |
| The sweep | [tools/run_parameter_sensitivity_sweep.py](../../tools/run_parameter_sensitivity_sweep.py) |

`parameter_sensitivity/models/m2_elastic3d` uses another contract schema and
is not part of the sweep; `--list` shows the twenty that are.

## Run it from the command line

From the repository root:

```bash
python tools/run_parameter_sensitivity_sweep.py --list
python tools/run_parameter_sensitivity_sweep.py \
    --work-dir "$PWD/umat_oti_workspace/examples/06_sweep/work" \
    --results-dir "$PWD/umat_oti_workspace/examples/06_sweep/results"
```

Give both directories as **absolute** paths, as above: with a relative
`--work-dir` the sweep stops at the first model with `FileNotFoundError: ...
ps_driver` (measured on 2026-09-18), because it runs each model's driver from
inside that model's folder.

**Always pass `--results-dir` for your own runs.** Without it, a full sweep
writes its tables to the published location `paper_results/parameter_sensitivity/`
in the repository. A single model can be run with `--model`, for example
`--model m3_j2`.

The sweep also regenerates the canonical contracts in
`parameter_sensitivity/contracts/` from each model's `contract_v2.json`. On an
unmodified checkout the regenerated files are identical to the committed ones,
so `git status` stays clean.

## Run it from the GUI

There is no GUI screen for the sweep. The **Parameter Sensitivities** tab
builds and verifies one model at a time (Examples 3 and 4).

## What you get

In `--results-dir`:

| File | What it is |
| --- | --- |
| `table6_parameter_sensitivity.csv` | One row per model: every funnel stage, parameters verified out of declared, number of comparison rows, worst relative error, elastic and inelastic increments, the furthest stage reached and any failure reason |
| `table6_comparison_rows.csv` | One row per comparison (model, increment, array, component, parameter): the OTI value, the reference, the errors, how it was judged, and whether it agrees |
| `parameter_sensitivity_round.json` | The whole round: the funnel, a failure taxonomy, the policy, and every model's record |

In `--work-dir`, one folder per model with the generated sources, the builds
and the raw outputs.

## Expected output

Measured on 2026-09-18. The sweep exits with 0 and prints the funnel:

```text
{
  "attempted": 20,
  "contract_complete": 20,
  "transformed": 20,
  "compiled_oti": 20,
  "executed_oti": 20,
  "executed_original": 20,
  "primal_parity": 20,
  "reference_resolved": 20,
  "derivatives_verified": 19,
  "parameter_directions_declared": 84,
  "parameter_directions_verified": 83,
  "comparison_rows_total": 14540,
  "comparison_rows_agreeing": 14539
}

failure taxonomy:
  derivatives_verified:unresolved: 1 -> m6_fcc
```

Per model (from `table6_parameter_sensitivity.csv`):

| Model | Parameters | Verified / declared | Rows | Worst rel. error | Elastic / inelastic increments |
| --- | --- | --- | --- | --- | --- |
| m1_elastic | E, nu | 2/2 | 240 | 2.5e-08 | 20 / 0 |
| m2_cubic | C11, C12, C44 | 3/3 | 360 | 3.1e-12 | 20 / 0 |
| m3_j2 | E, nu, SIGY0, H | 4/4 | 560 | 2.5e-08 | 15 / 5 |
| m5_cpflow | tau0, dG, q, p, gam0, H | 6/6 | 840 | 5.9e-07 | 0 / 20 |
| m6_fcc | g0, h0, q, gd0, m, gsat, C11, C12, C44, a | 9/10 | 3600 | 8.2e-07 | 2 / 18 |
| sweep_aniso_ortho | C11, C12, C13, C22, C23, C33, C44, C55, C66 | 9/9 | 1080 | 2.2e-12 | 20 / 0 |
| sweep_damage_elastic | E, nu, d | 3/3 | 360 | 2.5e-08 | 20 / 0 |
| sweep_drucker_prager | E, nu, k, beta | 4/4 | 560 | 1.2e-08 | 10 / 10 |
| sweep_eco | E, nu | 2/2 | 240 | 2.5e-08 | 20 / 0 |
| sweep_j2_bilinear | E, nu, SIGY0, Et | 4/4 | 560 | 2.5e-08 | 16 / 4 |
| sweep_j2_combined | E, nu, SIGY0, HISO, HKIN | 5/5 | 1300 | 2.5e-08 | 16 / 4 |
| sweep_j2_kinematic | E, nu, SIGY0, Hk | 4/4 | 960 | 2.5e-08 | 16 / 4 |
| sweep_lame_elastic | lambda, mu | 2/2 | 240 | 7.6e-12 | 20 / 0 |
| sweep_maxwell_ve | E, nu, tau | 3/3 | 720 | 2.4e-08 | 0 / 20 |
| sweep_mooney_small | mu, kappa | 2/2 | 240 | 3.9e-12 | 20 / 0 |
| sweep_perzyna_linear | E, nu, SIGY0, eta | 4/4 | 560 | 2.5e-08 | 16 / 4 |
| sweep_real_ECL_TEMP | E1, E2, G1, G2, CTE | 5/5 | 600 | 3.0e-07 | 20 / 0 |
| sweep_real_PCO | E, nu, SIGY0, H | 4/4 | 560 | 2.5e-08 | 15 / 5 |
| sweep_thermoelastic | E, nu, alpha | 3/3 | 360 | 2.5e-08 | 20 / 0 |
| sweep_transiso | EP, ET, XNUP, XNUPT, GT | 5/5 | 600 | 1.0e-08 | 20 / 0 |

How to read it:

- **Every model** transforms, compiles, runs, and reproduces the original
  stress (primal parity 20 of 20).
- **14,539 of 14,540 comparison rows agree.** The one that does not is a
  single entry of `m6_fcc`: `dS11/dgsat` at increment 5, whose size is
  `1.4e-10` (OTI `1.397e-10`, reference `1.396e-10`). At that size the
  finite-difference reference cannot resolve the value to the tolerance, so
  the row is reported as *unresolved*, never as agreement. That is why
  `m6_fcc` shows 9 of 10 directions and 19 of 20 models are counted as
  verified. It is not a disagreement.
- The "worst relative error" of most models is about `2.5e-8`: that is the
  accuracy of the finite-difference reference, not of the OTI value. For
  `m1_elastic`, for example, `table6_comparison_rows.csv` gives
  `dS11/dnu = 79.21597633136095` from OTI and `79.21597829572136` from the
  finite difference at the first increment. The closed form
  `E · eps11 · (4 nu - 2 nu^2) / (1 - nu - 2 nu^2)^2` with `E = 210000`,
  `nu = 0.3`, `eps11 = 1e-4` evaluates to `79.21597633136095`, the OTI value
  to the last digit.
- The "elastic / inelastic" columns show which models actually yield on this
  path. A model that stays elastic (`20 / 0`) is verified on its elastic
  branch only; that is a property of the path, not evidence that the model
  has no inelastic branch.

## How the result is checked

Each row compares the OTI derivative with centred finite differences of the
**separately compiled original** UMAT, replayed over the whole path with the
parameter perturbed. Before any derivative is compared, the transformed and
the original builds must return the same stress and state (primal parity).
The funnel keeps every model in the denominator with the stage it reached.

A row agrees when the OTI value is within the reference's own resolution
(its centred-difference noise floor) or within a relative tolerance of `1e-6`
of the reference; a row the reference cannot resolve is reported as
*unresolved*, never as agreement. A disagreeing row is re-judged once against
a reference taken at the step where the reference is best converged, with the
same `1e-6` tolerance; if it then differs by more than both the tolerance and
that reference's uncertainty, it stays a failure.

## Run time

Measured on 2026-09-18: 91.5 s for all twenty models.

## Common problems

| Symptom | Cause and fix |
| --- | --- |
| The published tables in `paper_results/parameter_sensitivity/` changed | A full sweep was run without `--results-dir`. Restore them with `git checkout -- paper_results/parameter_sensitivity` and pass `--results-dir` next time. |
| `FileNotFoundError: [Errno 2] No such file or directory: '.../ps_driver'` | `--work-dir` was a relative path. Use an absolute one (`"$PWD/..."`). |
| Models stop before `compiled_oti` | The sweep compiles with `gfortran` through `make`. Install both (`sudo apt install gfortran make`). |
| A model is listed as elastic only | The uniaxial path does not reach its yield point. The path is declared, per model if needed, in `parameter_sensitivity/loading_paths.json` (`overrides`). |

## Next

- The verifier used by the provider build (Examples 3 and 4) judges every
  entry of `DSIGMA_DP`, `DSTATEV_DP` and `DDSDDE` in the same spirit, with
  four verdicts: [docs/PROVIDER.md](../../docs/PROVIDER.md).
- The full verification record of the repository:
  [docs/VERIFICATION_RECORD.md](../../docs/VERIFICATION_RECORD.md).
