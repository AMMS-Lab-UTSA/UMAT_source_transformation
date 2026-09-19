# Example 3: Parameter sensitivities of J2 plasticity, packaged as a compiled provider

**Level:** core · **Needs:** Python, gfortran · **Abaqus:** not needed (only for the optional hand-off) · **Run time:** about 25 s

## What this example shows

Examples 1 and 2 differentiate the stress with respect to the strain. Here we
differentiate it with respect to the **material parameters**: Young's modulus
`E`, Poisson's ratio `nu`, the initial yield stress `SIGY0` and the hardening
modulus `H`. These sensitivities answer questions such as "how much would the
stress at this point change if the yield stress were 1 MPa higher?". They are
the input to calibration, uncertainty quantification and design studies.

In a plastic material the answer depends on the whole loading history, so the
derivatives must be carried from increment to increment. UMAT-OTI builds this
into a compiled **material provider**: one relocatable object file,
`OTI_UMAT.obj`, that contains the original UMAT and its OTI-differentiated
twin. Together with the mapping file `Mapping.json` it can be given to a
collaborator who never sees the Fortran source. The companion program
[Residual_Assembler](https://github.com/AMMS-Lab-UTSA/Residual_Assembler)
uses exactly these files to compute sensitivities of a whole finite-element
analysis.

This example builds the provider, verifies **every** derivative entry against
finite differences of the original UMAT, and then reads the result the way a
collaborator would.

### The mathematics, briefly

For a path-dependent material the update of increment `n` is
`sigma(n+1) = f(sigma(n), q(n), d_eps(n); p)`, with state `q` (here the
equivalent plastic strain) and parameters `p`. The total derivative follows
the chain rule through the history:

```text
d sigma(n+1)/dp = df/dp + df/dsigma(n) · d sigma(n)/dp + df/dq(n) · d q(n)/dp
d q(n+1)/dp     = dg/dp + dg/dsigma(n) · d sigma(n)/dp + dg/dq(n) · d q(n)/dp
```

The provider seeds each parameter `PROPS(k)` with its own imaginary direction
and passes the incoming derivatives `DSIGMA_DP_IN`, `DSTATEV_DP_IN` into every
call, so each increment returns the exact total derivatives

```text
DSIGMA_DP(i,k)  = d STRESS(i) / d p_k          (NTENS x NPARAM)
DSTATEV_DP(s,k) = d STATEV(s) / d p_k          (NSTATV x NPARAM)
```

Six more imaginary directions give `DDSDDE` at the same time, so the J2
provider uses 4 + 6 = 10 directions (`otim10n1`). The exact calling convention
is in [docs/PROVIDER.md](../../docs/PROVIDER.md).

## Inputs

| Input | Path |
| --- | --- |
| The UMAT (same as Example 2) | [parameter_sensitivity/models/m3_j2/umat.for](../../parameter_sensitivity/models/m3_j2/umat.for) |
| The provider contract | [parameter_sensitivity/models/m3_j2/contract_v2.json](../../parameter_sensitivity/models/m3_j2/contract_v2.json) |
| The package reader of this example | [run.py](run.py) |

The contract is short. It names the source, the dimensions, the parameters and
their `PROPS` slots, and the values at which the check runs:

```json
"dimensions": {"ntens": 6, "nprops": 4, "nstatev": 1},
"parameters": [
  {"name": "E", "props_index": 1}, {"name": "nu", "props_index": 2},
  {"name": "SIGY0", "props_index": 3}, {"name": "H", "props_index": 4}
],
"derivative": {"of": "STRESS", "wrt": "PROPS", "order": 1},
"history": {"path_dependent": true, "state": ["EQPLAS"]},
"validation": {"props_values": [210000.0, 0.3, 250.0, 2000.0]}
```

It declares no `validation.check_path`, so the check uses the provider's
seven-increment J2 path (the same path as Example 2).

## Run it from the command line

From the repository root:

```bash
# 1. Build the provider and the regular object
umat-oti-provider build parameter_sensitivity/models/m3_j2/contract_v2.json \
    --out umat_oti_workspace/examples/03_j2/build --regular-object REAL_UMAT.obj

# 2. Build, verify and package the four hand-off files
python -m umat_oti.provider.collaborator parameter_sensitivity/models/m3_j2/contract_v2.json \
    --out umat_oti_workspace/examples/03_j2/package --j2-branches

# 3. Read the package as a collaborator would
python examples/03_j2_parameter_sensitivities/run.py --package umat_oti_workspace/examples/03_j2/package
```

What each step does:

1. **`umat-oti-provider build`** transforms the UMAT for parameter
   sensitivity, compiles the original source unchanged and its OTI lift, and
   links both into one relocatable object. `--regular-object REAL_UMAT.obj`
   also publishes the original UMAT compiled on its own. This step does **not**
   verify anything; the generated mapping says `"validation": {"status":
   "not_run"}`.
2. **`python -m umat_oti.provider.collaborator`** runs step 1 again and then
   the independent verifier (`python -m
   umat_oti.validation.parameter_sensitivity_provider`), which judges every
   entry of `DSIGMA_DP`, `DSTATEV_DP` and `DDSDDE`. `--j2-branches` also
   requires the check path to cross elastic, plastic and unloading increments.
   It then copies the four files a collaborator receives into
   `<package>/collaborator/`. Step 2 is self-contained; step 1 is shown
   because it is the command you would use inside your own build.
3. **`run.py`** uses only those four files and the verifier's report: it
   checks the SHA-256 of both objects, calls `OTI_UMAT.obj` along the path,
   repeats a finite-difference check with `REAL_UMAT.obj` alone, and counts
   the per-entry verdicts.

To build `REAL_UMAT.obj` with the Abaqus compiler instead of gfortran, add
`--abaqus-toolchain` to step 1 or step 2 (needs Abaqus; not run here).

## Run it from the GUI

1. `streamlit run scripts/app.py`, tab **Parameter Sensitivities**.
2. Under **1. Material source**, tick **use the UMAT from the Constitutive
   Jacobian screen** if you did Example 2 in the GUI; otherwise upload or type
   `parameter_sensitivity/models/m3_j2/umat.for`.
3. Click **Fill the table from
   parameter_sensitivity/models/m3_j2/contract_v2.json**. The table fills with
   `E 1 210000`, `nu 2 0.3`, `SIGY0 3 250`, `H 4 2000`, and **Number of state
   variables (NSTATV)** becomes `1`. You can edit any value; the screenshot
   below was taken with `E = 200000`.
4. Under **3. Derivatives**, keep **stress (DSIGMA_DP)** and **state
   (DSTATEV_DP, auto)** ticked.
5. Open **Options**. Keep **verify against finite differences of the original
   routine** ticked and the check path **the provider's seven-increment J2
   path**. Tick **require the check path to cross elastic, plastic and
   unloading increments**. Untick **build REAL_UMAT.obj with the Abaqus
   toolchain** to get the gfortran object used on this page (the box is ticked
   by default when `abaqus` is on `PATH`).
6. Click **Build OTI object →**. The result says **Build succeeded and
   verified**, with the three worst relative errors and the entry counts.
7. Download **REAL_UMAT.obj**, **OTI_UMAT.obj**, **Mapping.json** and
   **transform_report.txt**.

![Parameter Sensitivities after Build for the J2 model](../../docs/screenshots/umat_parameter_sensitivities_j2.png)

The GUI calls the same two commands as step 2 and writes the same package
layout under `umat_oti_workspace/gui/provider/<model>-<random>/out/`.
Pass that `out` directory to `run.py --package`.

## What you get

`umat-oti-provider build` writes into `<out>`:

| File | What it is |
| --- | --- |
| `umat_m3_j2_oti.obj` | The provider: the original UMAT plus the differentiated routine, entry points `UMAT`, `UMAT_OTI_EVAL`, `UMAT_OTI_MARCH`, `UMAT_OTI_EVAL_TOTAL` |
| `umat_m3_j2_oti.json` | The completed contract: dimensions, parameter order and OTI directions, calling signatures, array layouts, object SHA-256 |
| `REAL_UMAT.obj` | The original UMAT compiled unchanged (with `--regular-object`) |
| `build-<random>/` | The generated Fortran sources and objects, kept for diagnosis |

The collaborator package writes into `<package>`:

| Path | What it is |
| --- | --- |
| `collaborator/OTI_UMAT.obj` | The provider, renamed for hand-off |
| `collaborator/REAL_UMAT.obj` | The original UMAT, for the regular Abaqus analysis |
| `collaborator/Mapping.json` | The completed contract, unchanged. It records the SHA-256 of both objects, so the receiver can check they are a matched pair |
| `collaborator/transform_report.txt` | Build and verification commands with exit codes, the parameter table, the check path, primal parity, per-array verdict counts and worst errors |
| `verification/verification.json` | The verifier's full record: verdict, path, properties, criteria, per-column results |
| `verification/verification_entries.csv` | **One row per derivative entry**, with the OTI value, the finite-difference reference, its uncertainty, the step used and the verdict |
| `package.json`, `logs/` | The machine-readable summary and the two command logs |

The Fortran source is not among the four hand-off files.

## Expected output

Measured on 2026-09-18.

**Step 1** prints the four paths and exits with 0:

```text
{
  "object": ".../build/umat_m3_j2_oti.obj",
  "contract": ".../build/umat_m3_j2_oti.json",
  "build_dir": ".../build/build-<random>",
  "regular_object": ".../build/REAL_UMAT.obj"
}
```

**Step 2** exits with 0. The `Validation` block of
`collaborator/transform_report.txt` reads:

```text
Verdict          : verified
Check path       : 7 increments; provider default: the seven-increment J2 path of docs/PROVIDER.md
J2 branches      : elastic, elastic, plastic, plastic, elastic, plastic, elastic
Primal parity    : stress max |diff| 5.684e-14, state max |diff| 2.168e-19
Tolerance        : relative 2e-06 per entry, where the reference determines the entry to within it

Array                 columns agree/unresolved   entries agree   zero   unresolved   worst rel. error (agreeing)
  DSIGMA_DP               4      4/0                   144     24            0   1.704e-10
  DSTATEV_DP              4      4/0                    28      0            0   9.543e-11
  DSIGMA_DP (MARCH)       4      4/0                   144     24            0   1.704e-10
  DDSDDE                  6      6/0                   156     96            0   4.811e-10
  DDSDDE (MARCH)          6      6/0                   156     96            0   4.811e-10
Unresolved columns: none
Entries          : {'eval_primal': 49, 'march_final_primal': 6, 'verified_entries': 628, 'consistent_with_zero': 240, 'reference_unresolved': 0, 'disagreeing': 0}
Shipped object   : byte-identical to the verified build; returns bit-identical arrays to it on the check path
```

The SHA-256 of `OTI_UMAT.obj` was
`cf0cd2e87db9b7335bbaf5ec28eca25c6dc3df41354a366a0dd708f2c33a4686` in both
step 1 and step 2: the build is reproducible byte for byte. `REAL_UMAT.obj`
was `fed08fae9f224b94e493b5b700e1e914b181b9c39bc7c72af2ff20d7934b332d`.
Another compiler version gives other digests.

**Step 3** prints (trimmed):

```text
1. SHA-256 of OTI_UMAT.obj matches Mapping.json: True; REAL_UMAT.obj: True

2. OTI_UMAT.obj along the path (stress component 11, state SDV1):

inc   branch         S11       dS11/dE      dS11/dnu   dS11/dSIGY0       dS11/dH
  1  elastic    113.0769   5.38462e-04   3.16864e+02   0.00000e+00   0.00000e+00
  2  elastic    191.8269   9.13462e-04   5.08691e+02   0.00000e+00   0.00000e+00
  3  plastic    586.2457   2.00648e-03   2.09895e+03   6.55990e-01   4.43579e-04
  4  plastic    710.1584   2.58483e-03   2.71226e+03   6.63364e-01   7.51347e-04
  5  elastic    601.9276   2.06945e-03   2.43205e+03   6.63364e-01   7.51347e-04
  6  plastic   -227.8427  -3.37828e-04  -3.08889e+02  -6.19949e-01  -9.55771e-04
  7  elastic   -171.3043  -6.85974e-05  -1.50457e+02  -6.19949e-01  -9.55771e-04

inc                 SDV1      dSDV1/dE     dSDV1/dnu  dSDV1/dSIGY0      dSDV1/dH
  3           6.7620e-04   4.89922e-09  -7.91412e-04  -4.09320e-06  -2.76781e-09
  ...
  7           1.5330e-03   1.47235e-08  -2.37841e-03  -1.22441e-05  -1.54481e-08

3. REAL_UMAT.obj alone: stress max |diff| to OTI_UMAT.obj = 5.684e-14
   centred FD of REAL_UMAT.obj over the whole path, last increment, max |FD - OTI| / max|OTI| per parameter:
    parameter     h=1e-04     h=1e-05     h=1e-06        best
            E   9.624e-09   1.854e-10   5.991e-10   1.854e-10
           nu   2.098e-08   2.254e-10   7.564e-10   2.254e-10
        SIGY0   9.694e-10   9.900e-12   4.775e-10   9.900e-12
            H   9.880e-11   5.449e-10   1.358e-08   9.880e-11

4. Verifier verdict: verified (per-entry verdicts from verification/verification_entries.csv):
   array                               agrees  consistent_with_zero  reference_unresolved             disagrees
   DSIGMA_DP                              144                    24                     0                     0
   DSTATEV_DP                              28                     0                     0                     0
   DSIGMA_DP (MARCH)                      144                    24                     0                     0
   DDSDDE                                 156                    96                     0                     0
   DDSDDE (MARCH)                         156                    96                     0                     0

RESULT: PASS
```

How to read the sensitivities:

- **Increment 1 is elastic**, and the elastic stress is proportional to `E`,
  so `dS11/dE = S11/E = 113.0769 / 210000 = 5.3846e-4`. The yield stress and
  the hardening modulus have not entered yet: their columns are exactly 0.
- **Increment 3 yields.** From here on `SIGY0` and `H` matter:
  `dS11/dSIGY0 = 0.656` means one more MPa of initial yield stress gives about
  0.66 MPa more axial stress.
- **Increment 5 unloads elastically.** The `SIGY0` and `H` sensitivities are
  carried through unchanged. This is the history carry at work: the
  derivative of the incoming stress is propagated, not recomputed.
- `dSDV1/dSIGY0` is negative: a higher yield stress means less plastic strain.

## How the result is checked

The verifier compares every derivative entry with **centred finite
differences of the separately compiled original UMAT**, replayed along the
whole path, over a ladder of eleven steps (relative `1e-2` down to `1e-7`,
half a decade apart). The reference value is taken where the ladder is
flattest (Richardson-extrapolated where that is tighter), with an explicit
uncertainty. Each entry then gets one of four verdicts:

| Verdict | Meaning |
| --- | --- |
| **agrees** | the reference pins the entry down to within the relative tolerance `2e-6`, and the OTI value is within it |
| **consistent with zero** | both the OTI value and the reference are zero to within the reference's resolution |
| **reference unresolved** | the reference is too noisy to judge this entry; never counted as agreement |
| **disagrees** | outside both the reference's uncertainty and the tolerance; the verification fails |

Before any derivative is judged, the provider's stress and state must match
the original UMAT to round-off (primal parity). Step 3 repeats a smaller,
separate check that needs nothing but `REAL_UMAT.obj`.

## Handing the provider to a collaborator (optional, needs Abaqus data)

The collaborator runs Residual_Assembler on a converged Abaqus analysis with
the provider, for example:

```bash
resasm request --model Analysis.inp --odb Analysis.odb \
    --material OTI_UMAT.obj --request sensitivity_request.json --out results
```

`Mapping.json` is found automatically next to `OTI_UMAT.obj`. This needs a
converged Abaqus analysis (`Analysis.odb`) and is documented in the
Residual_Assembler repository. It was not run for this example. To use
`REAL_UMAT.obj` in Abaqus on Linux, copy it to `REAL_UMAT.o` (Abaqus accepts a
precompiled user object only with the `.o` extension).

## Run time

Measured on 2026-09-18: step 1 6.1 s, step 2 17.1 s, step 3 0.6 s.

## Common problems

| Symptom | Cause and fix |
| --- | --- |
| `provider build failed: output directory must be outside the original model directory` | Choose an `--out` outside `parameter_sensitivity/models/m3_j2/`. |
| `provider build failed: --abaqus-toolchain builds the regular object; name it with --regular-object` | Add `--regular-object REAL_UMAT.obj`. |
| `provider build failed: Abaqus executable 'abaqus' not on PATH` | `--abaqus-toolchain` needs Abaqus. Drop the option to build `REAL_UMAT.obj` with gfortran. |
| Package exit code 1 | Built but not verified. `transform_report.txt` and `verification/verification.json` give the verifier's diagnostic. |
| `J2 check must exercise elastic, plastic, and unloading increments` | `--j2-branches` is for J2-type materials on a path that yields and unloads. Leave it out for other materials. |
| `run.py: error: not a complete package` | Run step 2 first and pass its `--out` directory. |

## Next

[Example 4](../04_fcc_crystal_plasticity_provider/README.md) builds the same
kind of provider for a ten-parameter crystal-plasticity model.
