# Example 1: The consistent tangent of a linear elastic UMAT

**Level:** first steps · **Needs:** Python, gfortran · **Abaqus:** not needed · **Run time:** about 6 s

## What this example shows

Every Abaqus UMAT must return two things: the new stress, and the matrix
`DDSDDE`, which tells Abaqus how the stress changes when the strain increment
changes. Most UMAT authors derive `DDSDDE` by hand. UMAT-OTI computes it
instead, exactly, from the stress update the author already wrote.

This example applies the one-line command `umat-oti jacobian` to the simplest
possible material, 3D isotropic linear elasticity. Because the right answer is
known in closed form, you can see for yourself that the computed tangent is
exact, not approximately right.

It is the best place to start: it takes a few seconds and needs no Abaqus.

### The mathematics, briefly

The UMAT updates the stress with the elastic stiffness `C`:

```text
STRESS(n+1) = STRESS(n) + C · DSTRAN
DDSDDE      = d STRESS / d DSTRAN = C
```

For an isotropic material with Young's modulus `E` and Poisson's ratio `nu`,
in Voigt order `11, 22, 33, 12, 13, 23` with engineering shear strains:

```text
lambda = E nu / ((1 + nu)(1 - 2 nu))        mu = E / (2 (1 + nu))

C = | lambda+2mu  lambda      lambda      0   0   0  |
    | lambda      lambda+2mu  lambda      0   0   0  |
    | lambda      lambda      lambda+2mu  0   0   0  |
    | 0           0           0           mu  0   0  |
    | 0           0           0           0   mu  0  |
    | 0           0           0           0   0   mu |
```

The transformed UMAT runs the same Fortran in order-truncated imaginary (OTI)
arithmetic. Each strain component gets its own imaginary direction,
`DSTRAN(j) + e_j`. After the stress update, the imaginary part of `STRESS(i)`
along `e_j` is exactly `d STRESS(i) / d DSTRAN(j)`. There is no step size and
no truncation error.

## Inputs

| Input | Path |
| --- | --- |
| The UMAT (reads `E = PROPS(1)`, `nu = PROPS(2)`) | [parameter_sensitivity/models/m1_elastic/umat.for](../../parameter_sensitivity/models/m1_elastic/umat.for) |
| The check script of this example | [run.py](run.py) |

Nothing else is needed. The command finds the tangent block in the source by
itself; you do not write a contract.

## Run it from the command line

Run these two commands from the repository root, in the virtual environment
where you installed UMAT-OTI ([docs/INSTALL.md](../../docs/INSTALL.md)):

```bash
umat-oti jacobian parameter_sensitivity/models/m1_elastic/umat.for \
    --ntens 6 --out umat_oti_workspace/examples/01_elastic --compile
python examples/01_elastic_tangent/run.py --jacobian-dir umat_oti_workspace/examples/01_elastic
```

1. `umat-oti jacobian` transforms the UMAT. `--ntens 6` is the number of
   stress components (3D). The defaults `--seed DSTRAN --response STRESS
   --target DDSDDE` ask for the standard consistent tangent. `--compile`
   compiles every generated file with gfortran as a quick check.
2. `run.py` compiles the transformed UMAT and the original UMAT separately,
   drives both through a two-increment strain path, and compares the results
   with the analytic stiffness.

`umat_oti_workspace/` is ignored by git, so the outputs never clutter the
repository. You can use any other directory instead.

## Run it from the GUI

1. Start the GUI from the repository root: `streamlit run scripts/app.py`
   ([docs/GUI_GUIDE.md](../../docs/GUI_GUIDE.md)).
2. Open the tab **Constitutive Jacobian**.
3. Under **1. Material source**, upload `umat.for` or type its path
   `parameter_sensitivity/models/m1_elastic/umat.for` into
   **or its path on this machine**.
4. Leave **Number of stress components (NTENS)** at `6`.
5. Leave **2. Derivative to extract** at `DSTRAN`, `STRESS`, `DDSDDE`.
6. Under **3. Tangent block (detected automatically)** the screen shows
   `44-46 replaced; extraction after line 47` and the carried variables
   `DSTRESS, STRESS`.
7. Click **Transform →**. The result panel says **Transform succeeded**, with
   0 blockers, 0 warnings, exit code 0 and 21/21 structural checks.
8. Download **Drop-in UMAT with OTI modules** (and, if you like, the
   transformed UMAT, the transform report and the four-field contract).

The GUI writes into `umat_oti_workspace/gui/jacobian/umat-<random>/` and
prints the equivalent `umat-oti jacobian` command. Its files are byte-identical
to the command-line output (checked on 2026-09-18). To run the check on them,
pass that directory to `run.py --jacobian-dir`.

## What you get

`umat-oti jacobian` writes into `<out>`:

| File | What it is |
| --- | --- |
| `umat_oti_combined.f90` | **The drop-in UMAT.** The transformed routine and every OTI module it needs, in one file, with the standard real-valued UMAT interface. This is the file you give Abaqus. |
| `umat_oti.for` | The transformed UMAT alone (it needs the modules below). |
| `master_parameters.f90`, `real_utils.f90`, `otim6n1.f90`, `oti_intrinsics.f90` | The OTI support modules. `otim6n1` means 6 imaginary directions, first order. |
| `compile_order.txt`, `compile_hint.sh` | The order in which to compile the files, and a script that does it. |
| `jacobian_contract.json` | The four fields of your request, written as a contract. `umat-oti-config --config` accepts it. |
| `derivative_manifest.json` | Which derivative is written where (`DDSDDE(i,j) = d STRESS(i) / d DSTRAN(j)`). |
| `transform_report.txt`, `transform_report.json` | What the transformer did: the variables it promoted, the tangent lines it replaced, and 21 structural checks. |
| `*.o`, `*.mod` | Compiled objects, written only with `--compile`. |

`run.py` adds `<out>/example_check/`, with the two small test programs it
compiled.

### Using the drop-in in Abaqus (optional, needs Abaqus)

Pass the drop-in as the user subroutine file, exactly where you would pass
the original:

```bash
abaqus job=<job> input=<deck>.inp user=umat_oti_combined.f90 double=both interactive
```

This is the form the repository's paired Abaqus validation uses. Running
Abaqus is not part of this example, and no Abaqus result is claimed here.

## Expected output

Measured on 2026-09-18 (Linux, Python 3.11.7, gfortran 9.4.0).
`umat-oti jacobian` prints a JSON summary and exits with 0. The key fields are:

```text
"status_category": "succeeded",
"transform_success": true,
"compilation": { "status": "compiled", ... },
"blockers": [],
"warnings": [],
```

The transform report (`transform_report.txt`) says:

```text
Transformation    : SUCCESS
ntens = 6   order = 1   type = ONUMM6N1   module = otim6n1
Seeded          :   1   DSTRAN
Promoted to OTI :   3   DSTRESS, STATEV, STRESS
Old tangent blocks replaced: 1  (lines 44-46)
-- Semantic checks (21/21 passed) ---
```

`run.py` prints (trimmed):

```text
E = 210000, nu = 0.3
  DDSDDE from the OTI UMAT, last increment:
     2.826923e+05  1.211538e+05  1.211538e+05  0.000000e+00  0.000000e+00  0.000000e+00
     1.211538e+05  2.826923e+05  1.211538e+05  0.000000e+00  0.000000e+00  0.000000e+00
     1.211538e+05  1.211538e+05  2.826923e+05  0.000000e+00  0.000000e+00  0.000000e+00
     0.000000e+00  0.000000e+00  0.000000e+00  8.076923e+04  0.000000e+00  0.000000e+00
     0.000000e+00  0.000000e+00  0.000000e+00  0.000000e+00  8.076923e+04  0.000000e+00
     0.000000e+00  0.000000e+00  0.000000e+00  0.000000e+00  0.000000e+00  8.076923e+04
  OTI tangent vs analytic       : max |diff| / max|C| = 0.000e+00
  stress vs original UMAT       : max |diff| = 0.000e+00 (stress scale 210)
  FD of original, step   1e-04  : max |diff| / max|C| = 4.118e-16
  FD of original, step   1e-06  : max |diff| / max|C| = 7.413e-14
  FD of original, step   1e-08  : max |diff| / max|C| = 9.726e-12

E = 70000, nu = 0.33
  OTI tangent vs analytic       : max |diff| / max|C| = 0.000e+00
  stress vs original UMAT       : max |diff| = 0.000e+00 (stress scale 73.07)
  FD of original, step   1e-04  : max |diff| / max|C| = 4.209e-16
  FD of original, step   1e-06  : max |diff| / max|C| = 5.851e-14
  FD of original, step   1e-08  : max |diff| / max|C| = 4.155e-12

RESULT: PASS (OTI tangent equals the analytic stiffness to 1e-12)
```

How to read it:

- The diagonal `2.826923e+05` is `lambda + 2 mu`, the off-diagonal
  `1.211538e+05` is `lambda`, and the shear entries `8.076923e+04` are `mu`,
  for `E = 210000` and `nu = 0.3`.
- The OTI tangent equals the analytic matrix **to the last bit** (difference
  0) for both materials.
- The transformed UMAT returns exactly the same stress as the original
  (difference 0). The transform changed the number type, not the physics.
- Finite differences of the original get worse as the step gets smaller
  (4e-16 → 7e-14 → 1e-11): round-off grows as `eps / h`. OTI has no step, so
  it has no such error.

## How the result is checked

The reference is independent of the transformed code:

1. **Analytic formula.** The isotropic stiffness above, evaluated in Python
   from `E` and `nu`.
2. **The original UMAT.** Compiled on its own from the untransformed source,
   it gives the stress (primal parity) and, by centred finite differences with
   the last strain increment perturbed by `±h`, a numerical tangent.

## Run time

Measured on 2026-09-18 on a workstation: `umat-oti jacobian` 1.9 s,
`run.py` 3.7 s.

## Common problems

| Symptom | Cause and fix |
| --- | --- |
| `umat-oti: command not found` | The virtual environment is not active. Run `. .venv/bin/activate`, or use `python -m umat_oti.cli jacobian ...`. |
| `"compilation": {"status": "compiler_unavailable"}` and exit code 1 | `gfortran` is not on `PATH`. Install it (`sudo apt install gfortran`) or drop `--compile`. `run.py` also needs gfortran. |
| `run.py: error: ... umat_oti_combined.f90 not found` | Run the `umat-oti jacobian` command first, with the same `--out` directory you pass to `--jacobian-dir`. |
| `jacobian request refused: NTENS must be one of (3, 4, 6)` | Use `--ntens 6` for 3D solids, `4` for plane strain or axisymmetry, `3` for plane stress. |

## Next

- [Example 2](../02_j2_plasticity_tangent/README.md) does the same for J2
  plasticity, where the tangent changes from increment to increment.
- For full control over what is seeded and promoted, write a contract:
  [new_user_umat_starter/README.md](../../new_user_umat_starter/README.md).
