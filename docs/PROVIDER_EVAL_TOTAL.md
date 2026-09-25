# `UMAT_OTI_EVAL_TOTAL`: the total-derivative entry point

This page documents the third replay routine of the compiled provider, for
integrators who replay a whole finite-element history with parameter
sensitivities. Read [PROVIDER.md](PROVIDER.md) first for the build, the
verifier and the other two entry points.

## Signature

Every provider built by `umat-oti-provider build <contract_v2.json> --out DIR`
exports this routine next to `UMAT_OTI_EVAL` and `UMAT_OTI_MARCH`, which are
unchanged. It is used for whole-model history replay by the Residual
Assembler's `resasm history` (see
[REPLAY_HISTORY.md](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/docs/REPLAY_HISTORY.md)
in that repository).

```fortran
SUBROUTINE UMAT_OTI_EVAL_TOTAL(STRESS,STATEV,DDSDDE,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP, &
  PROPS,NPROPS,NTENS,NSTATV,NPARAM,DSIGMA_DP,DSTATEV_DP,DSIGMA_DP_IN,DSTATEV_DP_IN, &
  STRAN_DP_IN,DSTRAN_DP_IN,DSTATEV_DDSTRAN,COORDS,CELENT,NOEL,NPT,KSTEP,KINC,PNEWDT)
```

The completed contract lists it as `symbols.oti_eval_total`
(`umat_oti_eval_total_`), with the 28-entry
`symbols.oti_eval_total_signature`.

| Argument | Layout | Meaning |
| --- | --- | --- |
| `DSIGMA_DP_IN`, `DSTATEV_DP_IN` | (NTENS,NPARAM), (NSTATV,NPARAM) | derivatives of the incoming STRESS and STATEV |
| `STRAN_DP_IN` | (NTENS,NPARAM) | derivative of STRAN (the strain at the start of the increment) |
| `DSTRAN_DP_IN` | (NTENS,NPARAM) | derivative of the strain increment DSTRAN |
| `DSIGMA_DP`, `DSTATEV_DP` | out | TOTAL derivatives of the updated STRESS and STATEV |
| `DDSDDE` | out, (NTENS,NTENS) | dSTRESS/dDSTRAN at fixed incoming history |
| `DSTATEV_DDSTRAN` | out, (NSTATV,NTENS) | dSTATEV/dDSTRAN at fixed incoming history |
| `COORDS`, `CELENT`, `NOEL`, `NPT`, `KSTEP`, `KINC` | in | passed to the UMAT |
| `PNEWDT` | out | the UMAT's cut-back request, returned rather than stopping the program |

## How the derivatives are formed

Parameter direction j of the first-order OTI number is seeded with the unit
PROPS seed and with column j of all four incoming derivatives. The imaginary
parts of the outputs are therefore the complete first-order chain rule through
the update, whatever the UMAT does with STRAN, DSTRAN, STRESS and STATEV.
Directions NPARAM+1 to NPARAM+NTENS are unit DSTRAN seeds, as in
`UMAT_OTI_EVAL`; they give DDSDDE and DSTATEV_DDSTRAN.

## Why it is needed

`UMAT_OTI_EVAL` carries dSTRESS/dp and dSTATEV/dp, but it neither seeds
dSTRAN/dp nor returns dSTATEV/dDSTRAN. A replay that couples the material to
equilibrium needs both. After solving K du/dp = -dR/dp it must add
DDSDDE B du/dp to the stress derivative and DSTATEV_DDSTRAN B du/dp to the
state derivative.

## Verification

`tests/test_provider_eval_total.py` uses a real compiler and compiles the
ORIGINAL UMAT into the same object as the reference. It checks that:

- with zero strain seeds, the routine reproduces `UMAT_OTI_EVAL` bit for bit;
- with random history seeds, every parameter direction matches central
  differences of the ORIGINAL UMAT (two steps, plateau check) to at most
  8.4e-10 relative, for `m3_j2`, for `m6_fcc` at a slip-hardening point, and for
  a total-strain damage fixture that reads STRAN
  (`tests/fixtures/provider_total_strain/`);
- DDSDDE and DSTATEV_DDSTRAN match finite differences;
- a PNEWDT < 1 request is returned to the caller.

## Effect on the transform generation

The transform fingerprint (`umat_oti.store.transform_store`) covers
`src/umat_oti/provider/`, so adding this routine changed it. The transform
generation was then re-frozen and the whole corpus re-run at the new value. The
current fingerprint is recorded in one place,
`src/umat_oti/contract/schemas/transform_generation.json`, which both
repositories read.

---

# `UMAT_OTI_EVAL_TOTAL_F`: the same thing, with the deformation gradient

`UMAT_OTI_EVAL_TOTAL` hard-sets `DFGRD0 = DFGRD1 = I` and drives the UMAT
through `STRAN`/`DSTRAN`. That is correct for a small-strain UMAT and silently
wrong for any other kind: a UMAT that reads its kinematics from the
deformation gradient — every large-deformation UMAT — then sees no deformation
at all and returns **zero stress for every increment**. The run converges, the
output is a field of zeros, and nothing reports a failure. `_F` exists so that
a consumer never has to find that out by inspection.

```fortran
SUBROUTINE UMAT_OTI_EVAL_TOTAL_F(STRESS,STATEV,DDSDDE,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP, &
  PROPS,NPROPS,NTENS,NSTATV,NPARAM,DSIGMA_DP,DSTATEV_DP,DSIGMA_DP_IN,DSTATEV_DP_IN, &
  STRAN_DP_IN,DSTRAN_DP_IN,DSTATEV_DDSTRAN,COORDS,CELENT,NOEL,NPT,KSTEP,KINC,PNEWDT, &
  DFGRD0,DFGRD1,DROT,DFGRD0_DP,DFGRD1_DP)
```

Every argument of `UMAT_OTI_EVAL_TOTAL` keeps its meaning and its position, so
the two are read back identically. The five new ones are:

| Argument | Layout | Meaning |
| --- | --- | --- |
| `DFGRD0`, `DFGRD1` | in, (3,3) | the deformation gradient at the start and end of the increment, forwarded to the UMAT instead of the identity |
| `DROT` | in, (3,3) | the incremental rotation, forwarded instead of the identity |
| `DFGRD0_DP`, `DFGRD1_DP` | in, (3,3,NPARAM) | derivatives of those gradients with respect to each parameter |

`DFGRD0_DP`/`DFGRD1_DP` are what keeps a parameter direction *total* when the
geometry itself moves with the parameter, which is the ordinary case in a
residual sensitivity: the displacement solution responds to the parameter, so
the gradient at the integration point does too. Pass zeros to hold the
kinematics fixed.

## Which entry point to drive

The completed contract answers this directly, so a consumer need not guess:

```json
{"kinematics": "finite_strain", "drive": "umat_oti_eval_total_f_"}
```

`kinematics` echoes the v2 contract; `drive` is the symbol to call. Both entry
points are compiled into every object — `drive` says which one this material
is meant to be driven through. `symbols.oti_eval_total_finite_signature`
carries the 33-entry signature.

## The tangent directions

Directions `NPARAM+1 … NPARAM+NTENS` seed the deformation gradient as
`dF = eps . F`, **not** `dF = eps`. The velocity gradient a perturbation of
the deformation gradient produces is `l = dF . F^-1`, so asking for `l = eps`
— which is what the strain increment Abaqus differentiates against means —
asks for `dF = eps . F`. Adding `eps` straight onto F is the same thing only
at `F = I` and wrong by order `||F - I||` everywhere else. The map is
`_finite_strain_seed_terms`, shared with the in-place transform so the two
cannot drift apart.

The same direction also carries the matching unit `DSTRAN` seed, so one
direction means one strain increment in *every* representation the UMAT might
read. A UMAT that consumes both `DFGRD1` and `DSTRAN` gets a consistent total
derivative rather than half of one.

`DDSDDE` carries the Kirchhoff term on its direct columns:

```
DDSDDE(ij,kl) = d sigma_ij / d eps_kl  +  sigma_ij * delta_kl
```

That, not `d sigma / d eps`, is the matrix Abaqus's `nlgeom` stiffness is
built from, so it is the one a consumer's `K` has to be scored against.

## What is measured

`tests/test_the_gradient_never_reached_the_material.py`, against
`tests/fixtures/provider_finite_strain` — a compressible neo-Hookean that
reads `DFGRD1` and never touches `DSTRAN`, added because no other fixture in
this repository can tell the two entry points apart:

| Check | Result |
| --- | --- |
| Small-strain entry point on this material | returns exactly zero stress; `_F` returns the neo-Hookean stress |
| Stress vs the original UMAT under the same gradient | equal to 1e-9 |
| `DDSDDE` vs central FD with `dF = eps . F` + Kirchhoff | worst scaled error < 5e-6, at h = 1e-5 and 1e-6 (a plateau) |
| `dSTRESS/dp` over a three-increment path vs FD of the whole path | worst scaled error < 1e-6, at h = 1e-4 and 1e-5 |
| `DFGRD1_DP` contribution vs FD along the same gradient direction | worst scaled error < 1e-6 |
| At `F = I` on a small-strain fixture | identical to `UMAT_OTI_EVAL_TOTAL` except for the Kirchhoff term, on the direct columns and nowhere else |

Every reference is a central difference of the **original** UMAT compiled into
the same provider; no constitutive mathematics is restated in Python.
