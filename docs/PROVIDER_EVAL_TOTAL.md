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
