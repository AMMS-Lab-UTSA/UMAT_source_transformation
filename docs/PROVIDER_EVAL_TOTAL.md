# `UMAT_OTI_EVAL_TOTAL`: the total-derivative provider entry point

Every provider built by `umat-oti-provider build <contract_v2.json> --out DIR`
exports, next to `UMAT_OTI_EVAL` and `UMAT_OTI_MARCH` (unchanged), a third
routine for whole-model history replay (the Residual Assembler's
`resasm history`, see its `docs/REPLAY_HISTORY.md`):

```fortran
SUBROUTINE UMAT_OTI_EVAL_TOTAL(STRESS,STATEV,DDSDDE,STRAN,DSTRAN,TIME,DTIME,TEMP,DTEMP,
    PROPS,NPROPS,NTENS,NSTATV,NPARAM,DSIGMA_DP,DSTATEV_DP,DSIGMA_DP_IN,DSTATEV_DP_IN,
    STRAN_DP_IN,DSTRAN_DP_IN,DSTATEV_DDSTRAN,COORDS,CELENT,NOEL,NPT,KSTEP,KINC,PNEWDT)
```

The completed contract lists it as `symbols.oti_eval_total`
(`umat_oti_eval_total_`) with the 28-entry `symbols.oti_eval_total_signature`.

| argument | layout | meaning |
| --- | --- | --- |
| `DSIGMA_DP_IN`, `DSTATEV_DP_IN` | (NTENS,NPARAM), (NSTATV,NPARAM) | derivatives of the incoming STRESS and STATEV |
| `STRAN_DP_IN` | (NTENS,NPARAM) | derivative of STRAN (strain at the start of the increment) |
| `DSTRAN_DP_IN` | (NTENS,NPARAM) | derivative of the strain increment DSTRAN |
| `DSIGMA_DP`, `DSTATEV_DP` | out | TOTAL derivatives of the updated STRESS and STATEV |
| `DDSDDE` | out, (NTENS,NTENS) | dSTRESS/dDSTRAN at fixed incoming history |
| `DSTATEV_DDSTRAN` | out, (NSTATV,NTENS) | dSTATEV/dDSTRAN at fixed incoming history |
| `COORDS`, `CELENT`, `NOEL`, `NPT`, `KSTEP`, `KINC` | in | passed to the UMAT |
| `PNEWDT` | out | the UMAT's cut-back request (returned, not an `ERROR STOP`) |

Parameter direction j of the first-order OTI number is seeded with the unit
PROPS seed and with column j of all four incoming derivatives, so the
imaginary parts of the outputs are the complete first-order chain rule through
the update, whatever the UMAT does with STRAN, DSTRAN, STRESS and STATEV.
Directions NPARAM+1 .. NPARAM+NTENS are unit DSTRAN seeds, as in
`UMAT_OTI_EVAL`; they give DDSDDE and DSTATEV_DDSTRAN.

Why: `UMAT_OTI_EVAL` carries dSTRESS/dp and dSTATEV/dp but neither seeds
dSTRAN/dp nor returns dSTATEV/dDSTRAN. A replay that couples the material to
equilibrium needs both: after solving K du/dp = -dR/dp it must add
DDSDDE B du/dp to the stress derivative and DSTATEV_DDSTRAN B du/dp to the
state derivative.

Verification (`tests/test_provider_eval_total.py`, real compiler, ORIGINAL
UMAT compiled into the same object as the reference): with zero strain seeds
the routine reproduces `UMAT_OTI_EVAL` bit for bit; every parameter direction
with random history seeds matches central differences of the ORIGINAL UMAT
(two steps, plateau) to at most 8.4e-10 relative for m3_j2, m6_fcc (at a
slip-hardening point) and a total-strain damage fixture that reads STRAN
(`tests/fixtures/provider_total_strain/`); DDSDDE and DSTATEV_DDSTRAN match
FD; a PNEWDT < 1 request is returned.

Note: the transform fingerprint (`umat_oti.store.transform_store`) covers
`src/umat_oti/provider/`, so adding this routine changed it (6aa20d22e37f14c9
-> d8a3d2445fda0b26); `schemas/transform_generation.json` has to follow at
the next re-freeze.
