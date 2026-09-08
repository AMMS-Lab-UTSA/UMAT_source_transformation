# mholla-growth--umat-fiber-morph--726933a8

`mholla__growth/umats/umat_fiber_morph.f`

## What was established

Both builds ran in Abaqus on the same generated deck, under the same
physical conditions.

- **Original execution**: completed, 30 converged records.
- **Converted OTI execution**: completed, 30 converged records.
- **Stress and state history**: agreed to 0.000e+00 on stress and 0.000e+00 on state, over 199 resolved components.
- **OTI tangent against a finite difference of the ORIGINAL**: agreed at 3 of 3 states along the loading path, worst 8.476e-08.

| state | increment | best relative | verdict |
| --- | --- | --- | --- |
| 0 | 1 | 2.215e-10 | agreed |
| 14 | 5 | 8.476e-08 | agreed |
| 29 | 10 | 1.962e-10 | agreed |

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
