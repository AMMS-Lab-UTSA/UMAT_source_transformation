# Re-freeze at transform fingerprint 16c9f305df378089 (2026-09-18)

The final integration branch changed transform code, so every stored
transform and every frozen artefact was evidence about code that no longer
existed. The changes were:

- the provider entry point `UMAT_OTI_EVAL_TOTAL`;
- fixes to labelled statements, predictor inputs, DATA constants and helper closure;
- the per-entry provider verifier;
- the continued-assignment fix;
- keeping integers out of the promotion and reading the lifted helpers' IMPLICIT types.

This records how the evidence was made current again, following the procedure in
`src/umat_oti/contract/schemas/transform_generation.json` (`how_to_update`).
The same file sits in both repositories.

The re-freeze was done twice on the same day. Pass14, at `da1f183708c19072`,
followed the continued-assignment fix. Pass15, at `16c9f305df378089`, followed
the fix for lifted-helper arguments (commit `5b97c2f`). The numbers below are
pass15's. Where pass14 differs, the difference is stated.

## What was run

| step | command (from the UMAT repository root) | result |
| --- | --- | --- |
| 1. re-transform all 391 acquired sources | `python tools/transform_all.py --all --jobs 8 --json <run>/transform_all_pass15.json` | 240 transformed, 151 refused; 214 compile cleanly (pass14: 244, 147, 218; the four differences are explained below) |
| 2. run every transformed entry in Abaqus 2021.HF5 | `python tools/verify_store_in_abaqus.py --work-dir <run>/pass15/work --results-dir <run>/pass15/results --jobs 6 --mode inventory --timeout 1800` | 240 of 240 entries attempted at fingerprint `16c9f305df378089` (19:09 to 19:55); 44 reach the verified stage |
| 3. rebuild the registry | `python tools/build_corpus_registry.py --transform <run>/transform_all_pass15.json --abaqus <run>/pass15/results/store_verification.jsonl --store-fingerprint 16c9f305df378089 --audit-refusals` | `paper_results/corpus/` rewritten. The refused set changed, so the offline `ifort -syntax-only` audit of every refused source was redone |
| 4. report against pass14 | `python tools/pass_report.py --registry paper_results/corpus/corpus_registry.json --previous <pass14 registry> --families <run>/material_families.json --label pass15` | 43 of 260 accepted, as in pass14; none gained, none lost |
| 5. generation and lock | fingerprint written to `transform_generation.json`, `umat_oti.contract.schema.write_lock()`, both copied byte for byte to Residual_Assembler `schemas/` | combined lock digest `036e7797d203d3adf2b1f492d41dc65a1d320197016e6d95cbabfa3b8415d789` |
| 6. Residual Assembler fixtures | Residual_Assembler [scripts/regenerate_recovery_fixture.py](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/blob/main/scripts/regenerate_recovery_fixture.py) for `isotropic-elasticity--f7eb90376a` and `j2_props--2feae9f158` (loading from the retained pass12 manifests, deck byte-identical) | four Abaqus jobs; both verified (tangent agreement 1.1e-14 and 8.3e-11 over a step-size plateau). Every number is identical to pass14; only the generation time and the fingerprint (`16c9f305df378089`) differ. `residual_core.core.fixture_residual_check`: elasticity 1 held / 2 not established, J2 32 held / 3 not established, the same pattern as before |

`<run>` is the corpus working directory outside the repositories
(`softwarex_work/corpus_run`; 12 GB per pass, not committed). The
acquisition cache is `softwarex_work/discovery_cache`.

## The census at this fingerprint

| population | verified | external | internal |
| --- | ---: | ---: | ---: |
| all 391 acquired sources | 44 | 119 | 228 |

Within the 260 adequately specified genuine UMATs, 43 clear all six
acceptance gates:

- Abaqus job completed;
- all requested outputs present;
- finite history;
- primal agreement;
- derivatives verified;
- mechanically informative.

The 217 not accepted are all internal, i.e. this project's to fix:

| reason | count |
| --- | ---: |
| transform refused | 102 |
| primal disagreed | 56 |
| primal mismatch explained | 16 |
| tangent not verified | 13 |
| original job failed | 8 |
| transformed job failed | 7 |
| unsupported formulation | 5 |
| experiment not informative | 4 |
| support build failed | 2 |
| arguments diverged before the routine | 2 |
| informativeness not established | 1 |
| derivative truncated | 1 |

Accepted by family:

| family | accepted of |
| --- | --- |
| growth | 35 of 132 |
| hyperelasticity | 3 of 19 |
| damage / phase field | 2 of 20 |
| elasticity | 2 of 10 |
| other | 1 of 15 |
| plasticity | 0 of 15 |
| crystal plasticity | 0 of 15 |
| viscoelasticity | 0 of 22 |
| geomaterials | 0 of 12 |

## What changed between pass14 and pass15

Exactly four sources changed terminal state. All four are crystal-plasticity
UMATs that share one LU-decomposition helper, and none was ever accepted.

- **Pass14:** three stopped at primal agreement (`primal_disagreed`) and one at
  `unsupported_formulation`.
- **What was wrong:** each passes a real work array to that helper. The lifted
  helper's IMPLICIT statement types the matching dummy as hypercomplex, and
  through the implicit interface of an external subprogram this compiled
  without a word. The helper then read each REAL as a whole hypercomplex
  element, so their stress was computed from reinterpreted memory.
- **Pass15:** the transform reads the lifted bodies' IMPLICIT rules and refuses
  such a call by name (`transform_refused`, internal). The same check covers
  the other direction: a hypercomplex shadow reaching a dummy the lifted body
  keeps real or integer.

The same commit keeps integer variables out of the promotion. The integer
flags of the benchmark `UMAT_HIN` had been promoted because they sit on the
stress path. After the fix, its transformed stress agrees with the original's
to 1.1e-9 of the stress scale; with the mismatched arguments it was off by
0.63 (`tests/test_lifted_helper_arguments_match_their_dummies.py`). No other
corpus source changed state.

At pass14 the continued-assignment fix had two effects:

- It restored the compile of `simplified_curing.for`, which compiled at pass13
  and stopped compiling after the predictor-input fix kept its modulus
  assignments live.
- It made `enhanced_curing.for` compile for the first time.

Neither changes acceptance: both stop at primal agreement (`primal_disagreed`,
internal). The fix leaves every other generated source it could touch
unchanged: the transformed sources of all 19 benchmark contracts (31 files) and
the generated sources of all 20 parameter-sensitivity providers (180 files) are
byte-identical at the commits before and after it.

## What stays history

The verified collection under `umat/` (44 material contracts, pass12,
`94a92c01814f107a`) and the ten Residual Assembler fixtures under
[tests/fixtures/historical/94a92c01814f107a](https://github.com/AMMS-Lab-UTSA/Residual_Assembler/tree/main/tests/fixtures/historical/94a92c01814f107a)
are not regenerated here.

- They keep their recorded generation and numbers.
- The tests keep refusing them as regression baselines.
- They are read only as history.

Re-promoting the collection from pass15 would make them current:

```sh
tools/promote_verified_umats.py --results <run>/pass15/results/store_verification.jsonl --work-dir <run>/pass15/work
```

That rewrites the collection, and it was not done in this step.
