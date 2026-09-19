# Example 2: The consistent tangent of J2 plasticity

**Level:** core · **Needs:** Python, gfortran · **Abaqus:** not needed · **Run time:** about 8 s

## What this example shows

In a plastic material the tangent `DDSDDE` is no longer a constant matrix. It
depends on the current stress, on how far the material has yielded, and on
whether the increment is elastic, plastic, or an elastic unloading. Abaqus
needs the *consistent* (algorithmic) tangent of the return mapping the UMAT
actually implements; with a wrong tangent, the global Newton iteration slows
down or fails to converge.

This example transforms a small-strain von Mises (J2) plasticity UMAT with
linear isotropic hardening and checks its OTI tangent at every increment of a
seven-increment strain path that is **elastic, elastic, plastic, plastic,
elastic (unloading), plastic (reverse loading), elastic**. The reference is
centred finite differences of the separately compiled original UMAT, over a
sweep of step sizes.

### The mathematics, briefly

The UMAT computes an elastic trial stress and, if the von Mises stress
exceeds the current yield stress, returns it radially to the yield surface:

```text
trial:     sigma_tr = sigma_n + C : d_eps,      q_tr = von Mises(sigma_tr)
yield:     sigma_y  = SIGY0 + H * EQPLAS
plastic:   d_eqpl   = (q_tr - sigma_y) / (3 G + H)
           sigma    = sigma_tr - 3 G d_eqpl * s_tr / q_tr
tangent:   DDSDDE   = d sigma / d d_eps  (consistent with the return above)
```

The source also codes this consistent tangent by hand
(`EFFG`, `EFFLAM`, `EFFHRD` in lines 86-108). The transformer disables those
lines and fills `DDSDDE` from OTI arithmetic instead: the six strain
components are seeded with six imaginary directions and the tangent is read
from the imaginary parts of the stress. The hand-coded tangent is kept for
comparison only.

Centred finite differences of the original, `(sigma(d_eps + h e_j) -
sigma(d_eps - h e_j)) / 2h`, carry a truncation error that shrinks as `h^2`
and a round-off error that grows as `eps / h`. Plotting their error against
`h` gives a "V". The OTI value sits at the bottom of that V without choosing
any `h`.

## Inputs

| Input | Path |
| --- | --- |
| The UMAT: `E = PROPS(1)`, `nu = PROPS(2)`, `SIGY0 = PROPS(3)`, `H = PROPS(4)`; `STATEV(1)` = equivalent plastic strain | [parameter_sensitivity/models/m3_j2/umat.for](../../parameter_sensitivity/models/m3_j2/umat.for) |
| The check script (material constants, path and step sizes are at its top) | [run.py](run.py) |

Material constants: `E = 210000`, `nu = 0.3`, `SIGY0 = 250`, `H = 2000` (MPa).
The strain path is the provider verifier's default path
([docs/PROVIDER.md](../../docs/PROVIDER.md)).

## Run it from the command line

From the repository root:

```bash
umat-oti jacobian parameter_sensitivity/models/m3_j2/umat.for \
    --ntens 6 --out umat_oti_workspace/examples/02_j2 --compile
python examples/02_j2_plasticity_tangent/run.py --jacobian-dir umat_oti_workspace/examples/02_j2
```

1. `umat-oti jacobian` finds the tangent block, disables it, carries the
   variables the stress depends on through OTI arithmetic, and writes the
   drop-in UMAT.
2. `run.py` compiles the drop-in and the original UMAT separately, with a
   driver that prints `STRESS`, `STATEV` and `DDSDDE` after every increment,
   and compares them.

## Run it from the GUI

The GUI does step 1; step 2 is the script.

1. `streamlit run scripts/app.py`, tab **Constitutive Jacobian**.
2. Upload `parameter_sensitivity/models/m3_j2/umat.for`, or type the path into
   **or its path on this machine**.
3. Keep **NTENS** at `6` and the three derivative fields at `DSTRAN`,
   `STRESS`, `DDSDDE`.
4. The screen shows, before you click:
   - **line(s) that assign the tangent:** `86-108 replaced; 38-48 kept (read by
     the stress update); extraction after line 111`
   - **variables carried through the derivative:** `DEQPL, EQPLAS, FLOW,
     SHYDRO, SMISES, STATEV, STRESS, SYIEL0, SYIELD`

   Lines 38-48 are kept because the stress update reads that `DDSDDE` as the
   elastic predictor. Lines 86-108, the hand-written plastic tangent, are
   replaced.
5. Click **Transform →** and download **Drop-in UMAT with OTI modules**.

![Constitutive Jacobian screen after Transform on this UMAT](../../docs/screenshots/umat_constitutive_jacobian.png)

The GUI's files are byte-identical to the command-line output. Run
`run.py --jacobian-dir` on the directory the GUI wrote
(`umat_oti_workspace/gui/jacobian/umat-<random>/`).

## What you get

The same files as in [Example 1](../01_elastic_tangent/README.md#what-you-get):
the drop-in `umat_oti_combined.f90`, the transformed `umat_oti.for`, the OTI
modules (`otim6n1.f90` and friends), `derivative_manifest.json`,
`jacobian_contract.json` and `transform_report.txt`.

## Expected output

Measured on 2026-09-18. `umat-oti jacobian` exits with 0; its report says:

```text
Transformation    : SUCCESS
Promoted to OTI :   9   DEQPL, EQPLAS, FLOW, SHYDRO, SMISES, STATEV, STRESS, SYIEL0, SYIELD
Old tangent blocks replaced: 1  (lines 86-108)
Stress-update regions transformed: 3
-- Semantic checks (21/21 passed) ---
```

`run.py` prints:

```text
Example 2: consistent tangent of J2 plasticity (radial return, linear hardening)
  PROPS        : E=210000 nu=0.3 SIGY0=250 H=2000
  stress vs original UMAT: max |diff| = 5.684e-14 (stress scale 710.2)

  Scaled error max|DDSDDE_OTI - reference| / max|reference| at each increment:
  inc  branch   EQPLAS     FD h=1e-05  FD h=1e-06  FD h=1e-07  FD h=1e-08  FD h=1e-09    best FD   hand-coded
    1  elastic  0.000e+00  1.853e-15    2.636e-14    1.748e-13    2.014e-12    7.041e-12    1.853e-15 0.000e+00
    2  elastic  0.000e+00  3.192e-15    2.636e-14    1.748e-13    3.013e-12    5.060e-11    3.192e-15 0.000e+00
    3  plastic  6.762e-04  1.636e-06    1.636e-08    1.651e-10    2.291e-11    1.578e-10    2.291e-11 1.277e-16
    4  plastic  1.136e-03  2.381e-06    2.381e-08    2.360e-10    1.557e-11    1.775e-10    1.557e-11 1.872e-16
    5  elastic  1.136e-03  6.846e-15    1.979e-13    1.009e-12    1.307e-11    1.076e-10    6.846e-15 0.000e+00
    6  plastic  1.533e-03  2.839e-06    2.839e-08    2.834e-10    6.178e-12    8.124e-11    6.178e-12 2.391e-16
    7  elastic  1.533e-03  3.192e-15    2.388e-14    3.280e-13    3.013e-12    7.041e-12    3.192e-15 0.000e+00

  DDSDDE from the OTI UMAT at increment 3 (plastic), MPa:
        176892.8     177777.2     170330.0      -5585.4       1117.1      -1303.3
        177777.2     220426.3     126796.5       3121.3       -624.3        728.3
        170330.0     126796.5     227873.6       2464.2       -492.8        575.0
         -5585.4       3121.3       2464.2      48403.0         98.6       -115.0
          1117.1       -624.3       -492.8         98.6      48876.1         23.0
         -1303.3        728.3        575.0       -115.0         23.0      48869.0

RESULT: PASS (best-step FD agrees with the OTI tangent to 2.3e-11; tolerance 1e-08)
```

How to read it:

- **Branches.** `EQPLAS` (the equivalent plastic strain) grows in increments
  3, 4 and 6 and stays constant in 1, 2, 5 and 7, so the path covers loading,
  unloading and reverse loading.
- **Plastic increments show the step-size plateau.** The error drops by a
  factor of 100 for each tenfold smaller step (`1.6e-6 → 1.6e-8 → 1.7e-10`),
  which is the `h^2` truncation of the centred difference converging on the
  OTI value. It bottoms out near `h = 1e-8` (`2.3e-11`) and rises again at
  `1e-9` as round-off takes over.
- **Elastic increments** are linear in the strain increment, so finite
  differences have no truncation error there and agree to about `1e-15` at the
  largest step.
- **Hand-coded column.** This UMAT's own tangent is correct: it agrees with
  the OTI tangent to `2.4e-16` (round-off). For a UMAT whose hand-coded
  derivative is wrong, see [Example 5](../05_internal_newton_jacobian/README.md).
- The plastic tangent is no longer isotropic: the shear block has entries
  of about 48,400-48,900 MPa, compared with the elastic shear modulus
  `mu = 80,769` MPa, and there is coupling between normal and shear
  components.

## How the result is checked

- **Independent reference.** Centred finite differences of the ORIGINAL
  UMAT, compiled separately from the untransformed source and run in ordinary
  double precision. Only the last increment of each path prefix is perturbed,
  so the incoming stress and `EQPLAS` are fixed, exactly as in an Abaqus
  increment.
- **Step-size sweep.** Five steps from `1e-5` to `1e-9`; the verdict uses the
  best one, and the whole sweep is printed so you can see the plateau.
- **Primal parity.** The transformed UMAT returns the same stress as the
  original to `5.7e-14` MPa on a stress scale of 710 MPa.

## Run time

Measured on 2026-09-18: `umat-oti jacobian` 2.2 s, `run.py` 5.2 s.

## Common problems

| Symptom | Cause and fix |
| --- | --- |
| Large finite-difference errors at every step in a plastic increment | The perturbation moved the increment across the yield surface (from plastic to elastic or back). Use a smaller `h`, or a path whose increments are well inside one branch. The OTI tangent is not affected: it is the derivative on the branch the increment actually took. |
| Error at `h = 1e-9` larger than at `1e-8` | Expected: round-off in the finite difference. It is not an error of the OTI tangent. |
| `Transform did not succeed` on your own UMAT | Read `transform_report.txt`: it names every blocker. See [new_user_umat_starter/TROUBLESHOOTING.md](../../new_user_umat_starter/TROUBLESHOOTING.md). |

## Next

[Example 3](../03_j2_parameter_sensitivities/README.md) differentiates the
same UMAT with respect to its material parameters instead of the strain.
