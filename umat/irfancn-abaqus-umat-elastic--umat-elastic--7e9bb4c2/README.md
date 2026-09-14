# irfancn-abaqus-umat-elastic--umat-elastic--7e9bb4c2

`irfancn__Abaqus-UMAT-elastic/umat_elastic.for`

## What was established

Both builds ran in Abaqus on the same generated deck, under the same
physical conditions.

- **Original execution**: completed, 280 converged records.
- **Converted OTI execution**: completed, 280 converged records.
- **Stress and state history**: agreed to 0.000e+00 on stress and 0.000e+00 on state, over 1040 resolved components.
- **OTI tangent against a finite difference of the ORIGINAL**: agreed at 4 of 4 states along the loading path, worst 1.002e-14.

| state | increment | best relative | verdict |
| --- | --- | --- | --- |
| 0 | 1 | 9.433e-16 | agreed |
| 93 | 4 | 3.876e-15 | agreed |
| 186 | 2 | 1.002e-14 | agreed |
| 279 | 5 | 4.363e-15 | agreed |

## What was NOT established

- The loading is a **verification probe chosen by this pipeline** --
  prescribed extension, then shear, then a reversal. It is not the
  author's own example and a result here is not a reproduction of it.
- The **meaning** of the material constants is not certified. The deck
  gives values, not names.
- Passing the tangent check does **not** verify parameter
  sensitivities, higher orders, or loading regimes outside this probe.
- Physical correctness of the model itself is not in question here.
  What is established is that the conversion agrees with the original.

## Files

- `contract.json` — what was run, and where every input came from.
- `results.json` — what happened, per Abaqus execution and per state.
- `source.json` — upstream identity and the SHA-256 of the bytes verified.
- `verification/` — the generated deck and both probe histories.

The source itself is not committed here. See `umat/README.md`.
