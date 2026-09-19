# Example 5: The internal (local Newton) Jacobian of a viscoplastic damage UMAT

**Level:** advanced · **Needs:** Python, gfortran, make · **Abaqus:** not needed · **Run time:** about 10 s

## What this example shows

Many UMATs solve a nonlinear equation **inside** every increment: for example
the plastic multiplier that brings the stress back to the yield surface of a
rate-dependent or damaged material. They do it with Newton's method,

```text
x  <-  x - F(x) / F'(x)
```

and the derivative `F'(x)`, the *internal* (or local) Jacobian, is almost
always derived and typed by hand. If it is wrong, Newton's method converges
more slowly or not at all, and any consistent tangent built from it inherits
the error.

UMAT-OTI finds such a Newton update in the source by itself, evaluates the
residual in OTI arithmetic with the iterate as the seeded variable, and reads
`F'(x)` out exactly. This example does it for two UMATs and compares the
result with two things: centred finite differences of the untransformed UMAT,
and the Jacobian the source codes by hand.

| Part | UMAT | Newton update found in the source | Hand-coded Jacobian |
| --- | --- | --- | --- |
| A | bundled Kocks-type viscoplasticity, [parameter_sensitivity/models/m5_cpflow/umat.for](../../parameter_sensitivity/models/m5_cpflow/umat.for) | `DEQPL = DEQPL - F/DF` | `DF` |
| B | rate-dependent plasticity coupled with continuum damage, [UMATs/UMATs/ICP/UMAT_VPDCO.for](../../UMATs/UMATs/ICP/UMAT_VPDCO.for) | `GAM_PAR = GAM_PAR - FGAM/FJAC` | `FJAC` |

The result of part B is the reason this matters: the hand-coded `FJAC` of
`UMAT_VPDCO` is **2.6 % away** from the derivative of the residual the code
actually evaluates. The OTI value agrees with the independent reference to
`2.7e-13`.

### The mathematics, briefly

Let `x*` be the converged iterate at some increment. The tool

1. injects a small probe into a copy of the source. The probe records the
   iterate, the residual and the hand-coded Jacobian into spare `STATEV`
   slots, and at the chosen increment it replaces the iterate by a value
   passed in a spare `PROPS` slot, `x = PROPS(seed)`;
2. checks that recording changes nothing (the stress must be identical, to the
   bit, with and without the probe);
3. runs the original with `PROPS(seed) = x*` to confirm the seed takes effect;
4. transforms the probed source for parameter sensitivity with `PROPS(seed)` as
   the single parameter, so OTI evaluates `F(x* + e)` and returns
   `F'(x*) = Im(F)`, exactly;
5. computes the reference `(F(x* + h) - F(x* - h)) / 2h` with the separately
   compiled **original** probe, over a ladder of eleven steps (relative
   `1e-2` to `1e-7`), and takes the value where the ladder is flattest
   (Richardson-extrapolated where that is tighter).

The hand-coded Jacobian is *audited* against the same reference. It is never
used as the reference.

## Inputs

| Input | Path |
| --- | --- |
| Part A: the UMAT and the script | [parameter_sensitivity/models/m5_cpflow/umat.for](../../parameter_sensitivity/models/m5_cpflow/umat.for), [examples/verify_internal_jacobian.py](../verify_internal_jacobian.py) |
| Part B: the UMAT | [UMATs/UMATs/ICP/UMAT_VPDCO.for](../../UMATs/UMATs/ICP/UMAT_VPDCO.for) |
| Part B: helper routines it calls (found automatically) | [UMATs/UMATs/ICP/UMAT_ECL_TEMP.for](../../UMATs/UMATs/ICP/UMAT_ECL_TEMP.for) |
| Part B: the script (material constants and path at its top) | [run.py](run.py) |

Part A uses `PROPS = (E, nu, TAU0, DG, p, q, GAM0, H) = (200000, 0.3, 1500,
25, 0.4, 1.6, 0.1, 60000)` and 20 increments of `DSTRAN11 = 1e-4`.

Part B uses the 26 material constants of the sample material input published
with this UMAT (listed in `run.py`) and 20 increments of `DSTRAN11 = 1e-4`.
`UMAT_VPDCO` calls 13 helper routines; eight of them are defined in
`UMAT_ECL_TEMP.for` in the same folder. The script resolves this closure
into one file before anything else.

## Run it from the command line

From the repository root:

```bash
# Part A: the bundled viscoplastic model (give --out as an absolute path)
python examples/verify_internal_jacobian.py --out "$PWD/umat_oti_workspace/examples/05_cpflow"

# Part B: the viscoplastic damage UMAT
python examples/05_internal_newton_jacobian/run.py --out umat_oti_workspace/examples/05_vpdco
```

Both scripts refuse an `--out` directory that already exists, so earlier
results are never overwritten. Delete the directory, or choose a new name, to
run again.

Part A needs an **absolute** `--out` path, hence `"$PWD/..."`. The script
passes the path unchanged to the build steps, which compile inside that
folder; with a relative path the compiler looks for `ABA_PARAM.INC` in the
wrong place and the stage `probe_injected` fails (measured on 2026-09-18).
Part B's `run.py` makes the path absolute itself.

## Run it from the GUI

There is no GUI screen for internal Jacobians; this is a command-line
workflow. The GUI's **Constitutive Jacobian** tab computes `DDSDDE`, the
derivative with respect to the strain increment (Examples 1 and 2).

## What you get

Part B writes into `<out>`:

| Path | What it is |
| --- | --- |
| `UMAT_VPDCO_resolved.for` | The UMAT and the 13 helper routines it calls, in one file |
| `verification.json` | The full record: the discovered solve, every stage and its status, the converged iterate, the OTI value, the finite-difference ladder, the hand-coded value, and the audit |
| `verification/umat_probe_observe_offset0.for` | The source with the recording probe (used to find the converged iterate) |
| `verification/umat_probe_seeded.for` | The source with the seeding probe |
| `verification/original_reference/` | The separately compiled original builds used for the reference |
| `verification/oti_probe/` | The OTI-transformed probe, its driver, `Makefile` and CSV outputs |

Part A writes the same kind of `verification.json` and folders into its
`--out` directory.

## Expected output

Measured on 2026-09-18.

**Part A** prints one line and exits with 0:

```text
{"passed": true, "report": ".../05_cpflow/verification.json"}
```

The record says (from `verification.json`):

| Quantity | Value |
| --- | --- |
| Newton update found | `DEQPL = DEQPL - F/DF` (lines 88-110 of the source) |
| Increment and converged iterate | 20, `DEQPL = 3.0508e-05` |
| OTI `dF/dDEQPL` | `1.142430784081278` |
| Finite differences of the original (step `1e-4`) | `1.1424307840768504` |
| Hand-coded `DF` | `1.1424307840812775` |
| OTI vs finite differences | `3.9e-12` (relative) |
| Stress change caused by the probe | `0.0` |

Here the hand-coded Jacobian is correct: it agrees with the OTI value to
round-off.

**Part B** prints:

```text
Example 5: internal (local Newton) Jacobian of a viscoplastic damage UMAT
  source       : UMATs/UMATs/ICP/UMAT_VPDCO.for + 13 helper routines
  Newton update: GAM_PAR = GAM_PAR - FGAM/FJAC (resolved source, line 205)
  derivative   : dFGAM/dGAM_PAR (hand-coded in the source as FJAC)
  loading      : 20 increments of DSTRAN11 = 0.0001

  stage solve_discovered               succeeded
  stage probe_injected                 succeeded
  stage recording_is_non_perturbing    succeeded
  stage converged_iterate_located      succeeded
  stage compiled_original_probe        succeeded
  stage probe_took_effect              succeeded
  stage compiled_oti_probe             succeeded
  stage primal_parity                  succeeded
  stage fd_reference_resolved          succeeded
  stage jacobian_extracted             succeeded
  stage jacobian_verified              succeeded

  increment 8, converged GAM_PAR = 3.6192934108e-06

  Centred finite differences of the original over the step ladder
  (the reference is the flattest three-step window, Richardson-extrapolated
  where that is tighter):
    relative step        dFGAM/dGAM_PAR
        1.000e-02   -6.373541997845374e+05
        3.162e-03   -6.373535422031283e+05  <- reference taken here
        1.000e-03   -6.373534764451466e+05
        3.162e-04   -6.373534698697191e+05
        1.000e-04   -6.373534692151409e+05
        3.162e-05   -6.373534691309417e+05
        1.000e-05   -6.373534691807866e+05
        3.162e-06   -6.373534692085482e+05
        1.000e-06   -6.373534694752439e+05
        3.162e-07   -6.373534712262165e+05
        1.000e-07   -6.373534792914059e+05

  OTI (transformed UMAT)        : -6.373534691386975e+05
  finite-difference reference   : -6.373534691385273e+05
  hand-coded FJAC               : -6.208168449783465e+05

  |OTI - FD| / |FD|             : 2.670e-13
  |hand-coded - FD| / |FD|      : 2.595e-02

RESULT: PASS (OTI agrees with finite differences to 2.7e-13; tolerance 1e-08)
NOTE: the hand-coded FJAC differs from the finite-difference reference by 2.6e-02; the OTI value does not.
```

How to read it:

- **The eleven stages** are the funnel of step 1-5 above. Each one must
  succeed before the next is attempted; `verification.json` gives the reason
  if one does not.
- **The finite-difference ladder** shows the usual pattern: the coarsest steps
  are biased by truncation (`-6.37354e5` at `1e-2`), the values between
  `1e-4` and `3e-6` agree with each other to about `1e-10` (relative), and the
  finest steps drift again from round-off.
- **OTI** agrees with the reference to `2.7e-13`, without any step size.
- **The hand-coded FJAC** is `-6.208e5`, 2.6 % smaller in magnitude. The
  value in the source is not the derivative of the residual the code
  evaluates: it differentiates the residual with the yield stress taken at the
  current iterate, while the loop updates the yield stress after each Newton
  step from the previous iterate. The OTI value is the derivative, and it needs
  no derivation. The Newton iteration still converges with the hand-coded
  value, but the loop stops once the step `|FGAM/FJAC|` falls below `1e-7`, so
  the stress it returns depends on `FJAC`: with `FJAC` corrected in a copy of
  the source, the stress along this path changes by up to `2.9e-5` (relative).
  The repository's verification record lists this and other hand-coded
  internal Jacobians that differ from the reference:
  [docs/VERIFICATION_RECORD.md](../../docs/VERIFICATION_RECORD.md).

## How the result is checked

- **Independent reference:** centred finite differences of the untransformed
  (probed) source, compiled on its own and run in ordinary double precision,
  over an eleven-step ladder.
- **Non-perturbing probe:** the stress with and without the recording probe
  must be identical (`recording_is_non_perturbing`, drift exactly 0).
- **Primal parity:** the OTI build and the original build of the same probed
  source must return the same stress and state.
- **The hand-coded value** is reported next to both, as an audit.

## Run time

Measured on 2026-09-18: part A 4.0 s, part B 4.5 s.

## Common problems

| Symptom | Cause and fix |
| --- | --- |
| `--out must be a new directory` | The directory exists. Delete it or choose another name. |
| Part A: `probe_injected: failed` with `Can't open included file 'ABA_PARAM.INC'` | `--out` was a relative path. Use an absolute one: `--out "$PWD/umat_oti_workspace/examples/05_cpflow"`. |
| `solve_discovered: unsupported` ("no local Newton solve was discovered") | The UMAT integrates its law in closed form, without a local iteration, so it has no internal Jacobian. The scan looks for a scalar Newton update `X = X +/- A/B`. |
| `converged_iterate_located: unsupported` ("no increment along this loading path evaluated the local residual more than once") | The loading path stays elastic, so the Newton loop never runs. Use a path that reaches the inelastic range. |
| `compiled_oti_probe: failed` mentioning `make` | The OTI probe is built with `make` and `gfortran`. Install both (`sudo apt install make gfortran`). |
| `helper routines not found` | A routine the UMAT calls is defined in no file of its folder. Put the file that defines it next to the UMAT. |

## Next

[Example 6](../06_parameter_sensitivity_sweep/README.md) runs the parameter
sensitivity check over all twenty bundled material models in one command.
