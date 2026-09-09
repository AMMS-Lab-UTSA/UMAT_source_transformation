# jeff97-programming-plane-strain-plates-through-growth-under-body-forces--bodyforce-growth-2stages--d70f4ec3

`Jeff97__Programming-Plane-Strain-Plates-through-Growth-Under-Body-Forces/Examples-In-Section-3/ArcDown/Th001/BodyForce-Growth-2Stages.for`

## What was established

Both builds ran in Abaqus on the same generated deck, under the same
physical conditions.

- **Original execution**: completed, 30 converged records.
- **Converted OTI execution**: completed, 30 converged records.
- **Stress and state history**: agreed to 1.344e-11 on stress and 0.000e+00 on state, over 254 resolved components.
- **OTI tangent against a finite difference of the ORIGINAL**: agreed at 3 of 3 states along the loading path, worst 9.251e-07.

| state | increment | best relative | verdict |
| --- | --- | --- | --- |
| 0 | 1 | 5.034e-09 | agreed |
| 10 | 1 | 9.251e-07 | agreed |
| 21 | 2 | 1.694e-07 | agreed |

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

## Scope limit recorded during the run

both builds returned finite numbers for 22 increments and both went non-finite at increment 23, at the same increment and in the same components. The comparison covers the 22 increments in which the model produced numbers; nothing is claimed beyond them.

## Files

- `contract.json` — what was run, and where every input came from.
- `results.json` — what happened, per Abaqus execution and per state.
- `source.json` — upstream identity and the SHA-256 of the bytes verified.
- `verification/` — the generated deck and both probe histories.

The source itself is not committed here. See `umat/README.md`.
