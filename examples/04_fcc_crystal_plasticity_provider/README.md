# Example 4: A ten-parameter FCC crystal-plasticity provider

**Level:** advanced · **Needs:** Python, gfortran · **Abaqus:** not needed · **Run time:** about 40 s

## What this example shows

Example 3 packaged a four-parameter J2 model. This example does the same for a
much richer material: a face-centred cubic (FCC) single crystal with 12 slip
systems, cubic elasticity, rate-dependent slip and self- and latent hardening.
It has **ten parameters and twelve state variables**, and its stress update is
an explicit, sub-stepped integration over all slip systems. Deriving its
parameter sensitivities by hand would be a large and error-prone job. Here
they come out of the same one-command build, and every entry is checked.

The example also shows why the **loading path of the check matters**. A
derivative can only be verified on a path that actually exercises it.

### The model and its parameters

| PROPS | Name | Meaning |
| --- | --- | --- |
| 1-3 | `C11`, `C12`, `C44` | cubic elastic constants in the crystal frame (MPa) |
| 4 | `g0` | initial slip resistance (MPa) |
| 5 | `gsat` | saturation slip resistance (MPa) |
| 6 | `h0` | initial hardening rate (MPa) |
| 7 | `a` | hardening exponent |
| 8 | `q` | latent-hardening ratio |
| 9 | `gd0` | reference slip rate (1/s) |
| 10 | `m` | rate sensitivity |

`STATEV(1..12)` hold the growth of the twelve slip resistances above `g0`
(the resistance of system `alpha` is `g0 + STATEV(alpha)`). The crystal axes
are aligned with the global axes.

### The mathematics, briefly

On each slip system `alpha` the resolved shear stress `tau_alpha` drives a
power-law slip rate, and the slip resistances harden:

```text
gamma_dot_alpha = gd0 · |tau_alpha / g_alpha|^(1/m) · sign(tau_alpha)
g_dot_alpha     = sum_beta q_alpha_beta · h0 · (1 - g_beta / gsat)^a · |gamma_dot_beta|
q_alpha_alpha   = 1,   q_alpha_beta = q  (alpha != beta)
```

The stress is updated with the cubic stiffness and the plastic strain of the
slip increments, in ten explicit sub-steps per increment.

The provider carries `DSIGMA_DP` (6 x 10) and `DSTATEV_DP` (12 x 10) through
every sub-step and every increment, plus `DDSDDE` (6 x 6): 16 OTI directions
in total. The chain rule through the history is the same as in
[Example 3](../03_j2_parameter_sensitivities/README.md#the-mathematics-briefly).

## Inputs

| Input | Path |
| --- | --- |
| The UMAT | [parameter_sensitivity/models/m6_fcc/umat.for](../../parameter_sensitivity/models/m6_fcc/umat.for) |
| The contract of this example | [contract_tension_shear.json](contract_tension_shear.json) |
| The package reader (the reader of Example 3 with crystal defaults) | [run.py](run.py) |
| A quad-precision check of the reference (see *How the result is checked*) | [quad_check.py](quad_check.py) |

The model directory also ships a contract,
[parameter_sensitivity/models/m6_fcc/contract_v2.json](../../parameter_sensitivity/models/m6_fcc/contract_v2.json).
This example uses its own small contract for two reasons:

1. **The check path.** The shipped contract declares no check path, so the
   verifier would use the provider's J2 path. Its strain increments (up to
   `3.2e-3` per unit time) drive this rate-dependent crystal to non-finite
   values. On plain uniaxial strain along a cube axis there is no shear
   stress, so the `C44` column is zero along the whole path and cannot be
   verified. The contract here declares **tension with shear**: 20 increments
   of `1e-4` in `11` and `1e-4` engineering shear in `12`. That path yields
   and exercises all ten parameters.
2. **The material constants.** `g0 = 13`, `gsat = 55`, `h0 = 800` MPa (the
   other seven constants are those of the shipped contract). At the shipped
   constants one entry of about `1e-15` lies below what the double-precision
   reference can resolve; see *How the result is checked*.

The contract points at the shipped source (`"main_file":
"../../parameter_sensitivity/models/m6_fcc/umat.for"`), so nothing is copied.

## Run it from the command line

From the repository root:

```bash
# 1. Build the provider and the regular object
umat-oti-provider build examples/04_fcc_crystal_plasticity_provider/contract_tension_shear.json \
    --out umat_oti_workspace/examples/04_fcc/build --regular-object REAL_UMAT.obj

# 2. Build, verify and package the four hand-off files
python -m umat_oti.provider.collaborator examples/04_fcc_crystal_plasticity_provider/contract_tension_shear.json \
    --out umat_oti_workspace/examples/04_fcc/package

# 3. Read the package
python examples/04_fcc_crystal_plasticity_provider/run.py --package umat_oti_workspace/examples/04_fcc/package
```

There is no `--j2-branches` here: that requirement is for J2-type models.
`run.py` tabulates the shear stress `S12` and the first slip resistance
`SDV1` by default; `--component` and `--state` choose others.

## Run it from the GUI

1. `streamlit run scripts/app.py`, tab **Parameter Sensitivities**.
2. Upload or type `parameter_sensitivity/models/m6_fcc/umat.for`.
3. Click **Fill the table from parameter_sensitivity/models/m6_fcc/contract_v2.json**.
   **NSTATV** becomes `12` and the table lists the ten parameters in `PROPS`
   order.
4. **Edit three values** in the table: `g0` to `13`, `gsat` to `55` and `h0`
   to `800`. The table starts from the shipped contract's values (16, 40,
   300); see *Common problems* for what happens if you keep them.
5. Open **Options**:
   - **check path**: choose **tension with shear: 20 increments of 1e-4 in 11
     and 1e-4 engineering shear in 12, ...**;
   - leave **require the check path to cross elastic, plastic and unloading
     increments** unticked;
   - untick **build REAL_UMAT.obj with the Abaqus toolchain** for the gfortran
     object used on this page.
6. Click **Build OTI object →**. The result says **Build succeeded and
   verified**, with `DSIGMA_DP vs finite diff. 5.69e-08`,
   `DSTATEV_DP vs finite diff. 1.03e-09` and `DDSDDE vs finite diff. 3.47e-08`.
7. Download the four files.

![Parameter Sensitivities after Build for the FCC model](../../docs/screenshots/umat_parameter_sensitivities_fcc.png)

## What you get

The same layout as [Example 3](../03_j2_parameter_sensitivities/README.md#what-you-get),
with the canonical names `umat_m6_fcc_oti.obj` and `umat_m6_fcc_oti.json`. The
generated OTI module is `otim16n1` (10 parameter directions + 6 strain
directions).

## Expected output

Measured on 2026-09-18.

**Step 2** exits with 0. The `Validation` block of
`collaborator/transform_report.txt` reads:

```text
Verdict          : verified
Check path       : 20 increments; tension with shear: 20 increments of 1e-4 in 11 and 1e-4 engineering shear in 12
J2 branches      : not required
Largest state    : 2.52462 at the end of the path
Primal parity    : stress max |diff| 2.842e-13, state max |diff| 1.776e-15

Array                 columns agree/unresolved   entries agree   zero   unresolved   worst rel. error (agreeing)
  DSIGMA_DP              10     10/0                   726    424           50   5.692e-08
  DSTATEV_DP             10     10/0                  2400      0            0   1.029e-09
  DSIGMA_DP (MARCH)      10     10/0                   726    424           50   5.692e-08
  DDSDDE                  6      6/0                   352    362            6   3.474e-08
  DDSDDE (MARCH)          6      6/0                   352    362            6   3.474e-08
Unresolved columns: none
Entries          : {'eval_primal': 360, 'march_final_primal': 6, 'verified_entries': 4556, 'consistent_with_zero': 1572, 'reference_unresolved': 112, 'disagreeing': 0}
Shipped object   : byte-identical to the verified build; returns bit-identical arrays to it on the check path
```

All ten parameter columns and all six tangent columns **agree**; no entry
disagrees. The 112 *reference unresolved* entries are small entries whose
finite-difference reference scatters by more than `2e-6` of their size. They
are reported, never counted as agreement, and each has its own row in
`verification/verification_entries.csv`.

**Step 3** prints (trimmed to four of the ten parameter columns):

```text
  model umat_m6_fcc_oti: NTENS=6 NPROPS=10 NSTATV=12, 10 parameters: C11, C12, C44, g0, gsat, h0, a, q, gd0, m

inc   branch         S12     dS12/dC44      dS12/dg0      dS12/dh0       dS12/dm
  1               7.5000   1.00000e-04   5.85984e-09   4.30186e-23  -1.64020e-06
  2              14.9842   1.97216e-04   2.41435e-02   2.16987e-09  -2.15796e+00
  3              18.8266   1.42619e-04   9.45109e-01   6.60350e-05  -3.05037e+01
 ...
 20              24.7774   8.61503e-05   1.40139e+00   4.30398e-03  -6.92887e+01

3. REAL_UMAT.obj alone: stress max |diff| to OTI_UMAT.obj = 2.842e-13
   centred FD of REAL_UMAT.obj over the whole path, last increment, max |FD - OTI| / max|OTI| per parameter:
    parameter     h=1e-04     h=1e-05     h=1e-06        best
          C11   6.400e-09   5.555e-10   3.678e-09   5.555e-10
          C44   5.626e-09   2.292e-09   2.523e-08   2.292e-09
           g0   6.875e-11   7.927e-10   9.378e-09   6.875e-11
           h0   1.753e-10   1.248e-09   4.301e-08   1.753e-10
            m   3.100e-10   2.864e-09   4.039e-08   3.100e-10

RESULT: PASS
```

Over all ten parameters, the best-step error of this check lies between
`6.9e-11` (`g0`) and `6.4e-09` (`gsat`).

How to read it:

- **Increment 1 is elastic.** `S12 = C44 · gamma12 = 75000 · 1e-4 = 7.5` MPa,
  so `dS12/dC44 = gamma12 = 1e-4` exactly, and the slip parameters barely
  matter yet.
- **From increment 2 the crystal slips.** The shear stress levels off near
  25 MPa, and the slip parameters take over: `dS12/dg0` grows to 1.4 and the
  rate sensitivity `m` has a large negative effect.
- **The slip resistances grow** by up to 2.52 MPa (the largest state value),
  so the path exercises hardening, and `DSTATEV_DP` has 2,400 agreeing
  entries.

## How the result is checked

Exactly as in [Example 3](../03_j2_parameter_sensitivities/README.md#how-the-result-is-checked):
every entry of `DSIGMA_DP`, `DSTATEV_DP` and `DDSDDE`, from both the EVAL
and the MARCH entry points, against centred finite differences of the
separately compiled original UMAT over an eleven-step ladder, after primal
parity to round-off. `run.py` adds an independent check with `REAL_UMAT.obj`
alone.

### When the reference, not the derivative, is the limit

The verifier trusts nothing it cannot resolve: an entry the reference cannot
pin down is *reference unresolved*, never agreement. Its uncertainty estimate
for the reference is, however, itself computed in double precision, and one
entry on this path shows its limit. At the shipped constants (`g0 = 16`,
`gsat = 40`, `h0 = 300`), `dS22/dC11` at increment 2 is about `9.4e-16`,
twelve orders of magnitude below the largest entry of its column (`8.0e-4`).
It is not zero: slip has just begun, and the same entry is `2.1e-9` one
increment later. There the verifier reports **disagrees**: OTI `9.379e-16`
against a reference `9.992e-16` with an estimated uncertainty of `5.8e-17`.

Which of the two is right is settled by a higher-precision reference.
`quad_check.py` compiles the ORIGINAL UMAT twice, in double precision and with
every `REAL*8` promoted to 16-byte reals (`gfortran -freal-8-real-16`), and
prints the centred differences:

```bash
python examples/04_fcc_crystal_plasticity_provider/quad_check.py
```

Measured on 2026-09-18 (increment 2, abridged; runs in under a second):

```text
double precision
   relative step  increment  derivative
       1.000e-02          2  +1.0013154327e-15
       3.162e-03          2  +9.4625321105e-16
       1.000e-03          2  +9.9391394585e-16
       3.162e-04          2  +9.6965876751e-16
       1.000e-04          2  +1.0573552615e-15

quad precision
   relative step  increment  derivative
       1.000e-06          2  +9.3792278096e-16
       1.000e-08          2  +9.3792278033e-16
       1.000e-10          2  +9.3792278033e-16
```

The quad-precision differences converge to `9.3792278033e-16`, and the OTI
value `9.379227787e-16` agrees with them to `1.7e-9`. The double-precision
reference is 6.5 % high: at this entry one unit in the last place of `S22`
is about 1 % of the difference quotient at the step `1e-3`, and the
extrapolation over its flattest steps inherits that scatter. The
disagreement is the reference's error, not the derivative's. The verifier
still reports it, because it cannot tell the two apart by itself, and this
example uses constants at which every entry is resolved.

## Run time

Measured on 2026-09-18: step 1 8.1 s, step 2 31.0 s, step 3 0.8 s.

## Common problems

| Symptom | Cause and fix |
| --- | --- |
| Verifier exits 2 with `nonfinite` | The check path is too violent for this rate-dependent, explicitly integrated model (for example the provider's J2 path). Use the tension-with-shear path of this example, or a smaller increment. The objects are built but not verified. |
| `verified_with_unresolved_columns`, with `C44` unresolved | The path has no shear (for example uniaxial strain along a cube axis), so `dS/dC44` is zero along it. Use a path with shear. |
| Verification fails with `DSIGMA_DP C11: 1 entries disagree with the reference` at `g0 = 16`, `gsat = 40`, `h0 = 300` | One entry, `dS22/dC11` at increment 2 (about `9.4e-16`), is below what the double-precision reference resolves. A quad-precision reference (`quad_check.py`) shows that the OTI value is right to `1.7e-9` and the reference is 6.5 % high; see [When the reference, not the derivative, is the limit](#when-the-reference-not-the-derivative-is-the-limit). With the constants of this example every entry passes. |
| `run.py: error: not a complete package` | Run step 2 first and pass its `--out` directory. |

## Next

[Example 5](../05_internal_newton_jacobian/README.md) looks inside a UMAT: the
Jacobian of its own local Newton iteration.
